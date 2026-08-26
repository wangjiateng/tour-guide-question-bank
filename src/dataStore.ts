/**
 * 纯静态数据层：题库 JSON 文件加载 + 判分 + 浏览器 localStorage 答题记录。
 *
 * 无后端服务。题库来自 frontend/public/data/ 下的静态 JSON（由
 * scripts/export_static.py 从 data/quiz.db 导出）：
 *   - manifest.json / sources.json / questions_0.json..questions_4.json
 * 题目文件按科目懒加载（questions_0 = 未分类）。
 *
 * 答题记录（含错题本/历史/统计）保存在 localStorage，只存在于本机浏览器。
 * 判分逻辑与旧后端 /api/check、/api/exam/* 一致：
 *   判断题 answer 存中文（正确/错误）→ 归一化为 A/B 比较；
 *   多选题答案顺序无关（"AC" ≡ "CA"）。
 */
import type {
  Attempt,
  CheckResult,
  ExamCheckResult,
  ExamPaper,
  ExamQuestion,
  ExamResult,
  Question,
  Source,
  Stats,
} from "./types";

// ---------------------------------------------------------------------------
// 数据文件加载
// ---------------------------------------------------------------------------

const DATA_BASE = import.meta.env.BASE_URL + "data/";
const SUBJECT_KEYS = ["0", "1", "2", "3", "4"] as const;

interface Manifest {
  generated_at: string;
  total: number;
  answered: number;
  sources: number;
  per_subject: Record<string, number>;
}
interface SourcesFile {
  generated_at: string;
  sources: Source[];
}
interface QuestionsFile {
  generated_at: string;
  subject: number | null;
  questions: Question[];
}

let manifestCache: Manifest | null = null;
let sourcesCache: Source[] | null = null;
const loaded: Partial<Record<(typeof SUBJECT_KEYS)[number], Question[]>> = {};
const loading: Partial<Record<(typeof SUBJECT_KEYS)[number], Promise<Question[]>>> = {};

/** 主源（部署所在域名）单次超时：移动网络下易超时，短超时快速切换备用源。 */
const FETCH_TIMEOUT_MS = 8_000;
/** 备用源（jsDelivr CDN）退避重试次数：1s → 2s。 */
const FETCH_MAX_RETRIES = 2;
/** 备用数据源：github.io 在大陆移动网络不稳定，题库 JSON 经 jsDelivr CDN 镜像拉取。
 *  数据文件需随仓库提交到 master（public/data/），CDN 缓存约 12h 内更新。 */
const CDN_MIRROR_BASE = "https://cdn.jsdelivr.net/gh/wangjiateng/tour-guide-question-bank@master/public/data/";

/** 单次请求（带超时）。 */
async function fetchOnce<T>(url: string, timeoutMs: number): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const resp = await fetch(url, { signal: ctrl.signal });
    if (!resp.ok) {
      throw new Error(`加载题库文件失败：${url}（HTTP ${resp.status}）`);
    }
    return (await resp.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

/** 拉取题库 JSON：主源短超时，失败后自动切换到 jsDelivr CDN 备用源（带退避重试）。 */
async function fetchJson<T>(path: string): Promise<T> {
  const fileName = path.split("/").pop() ?? path;
  const mirror = CDN_MIRROR_BASE + fileName;
  let lastErr: unknown;
  // 主源：相对路径（github.io / 当前部署域名），数据最新
  try {
    return await fetchOnce<T>(path, 6_000);
  } catch (e) {
    lastErr = e;
  }
  // 备用源：jsDelivr CDN（国内可达），带退避重试
  for (let attempt = 0; attempt <= FETCH_MAX_RETRIES; attempt++) {
    try {
      return await fetchOnce<T>(mirror, FETCH_TIMEOUT_MS);
    } catch (e) {
      lastErr = e;
      if (attempt < FETCH_MAX_RETRIES) {
        await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
      }
    }
  }
  // 全部失败：给出可操作的中文提示
  if (lastErr instanceof Error && lastErr.name === "AbortError") {
    throw new Error(`题库文件下载超时（${path}），网络不稳定，请稍后重试`);
  }
  if (lastErr instanceof TypeError) {
    throw new Error(`无法连接题库服务器（${path}），请检查网络后重试`);
  }
  throw lastErr instanceof Error ? lastErr : new Error(String(lastErr));
}

/** 题目文件键：subject NULL → "0"，科目 1-4 → 字符串 */
function subjectKey(subject: number | null): (typeof SUBJECT_KEYS)[number] {
  return subject == null ? "0" : String(subject) as (typeof SUBJECT_KEYS)[number];
}

/** 加载 manifest（统计信息，App 头部与 stats 用）。 */
export async function loadManifest(): Promise<Manifest> {
  manifestCache ??= await fetchJson<Manifest>(DATA_BASE + "manifest.json");
  return manifestCache;
}

/** 加载来源元数据（Quiz/Browse 的「来源」筛选用）。 */
export async function loadSources(): Promise<Source[]> {
  if (sourcesCache == null) {
    const file = await fetchJson<SourcesFile>(DATA_BASE + "sources.json");
    sourcesCache = file.sources;
  }
  return sourcesCache;
}

/** 加载某科目题目文件（懒加载 + 并发去重）。subject null 表示未分类（0）。 */
export function loadSubjectQuestions(subject: number | null): Promise<Question[]> {
  const key = subjectKey(subject);
  if (loaded[key]) return Promise.resolve(loaded[key]!);
  if (!loading[key]) {
    loading[key] = fetchJson<QuestionsFile>(DATA_BASE + `questions_${key}.json`)
      .then((file) => {
        loaded[key] = file.questions;
        return file.questions;
      })
      .finally(() => {
        delete loading[key];
      });
  }
  return loading[key]!;
}

/** 加载多个科目（"全部科目" 时为 null 表示未分类）。 */
export async function loadSubjects(subjects: (number | null)[]): Promise<Question[]> {
  const lists = await Promise.all(subjects.map((s) => loadSubjectQuestions(s)));
  return lists.flat();
}

// ---------------------------------------------------------------------------
// 判分（移植自旧后端 /api/check 与 service.exam_score）
// ---------------------------------------------------------------------------

/** 归一化参考答案：判断题中文（正确/错误）→ A/B；其余大写。 */
export function refAnswer(q: Question): string {
  const a = (q.answer ?? "").trim().toUpperCase();
  if (q.q_type === 3 && (a === "正确" || a === "错误")) {
    return a === "正确" ? "A" : "B";
  }
  return a;
}

/** 多选答案顺序无关比较："AC" ≡ "CA"。 */
function sameMulti(given: string, ref: string): boolean {
  if (!ref) return false;
  const norm = (s: string) => [...s.replace(/,/g, "")].sort().join("");
  return norm(given) === norm(ref);
}

/** 判分一题（quiz / 错题本共用），answer 返回归一化后的 A/B 字母。 */
export function checkQuestion(q: Question, given: string): CheckResult {
  const chosen = given.trim().toUpperCase();
  const ref = refAnswer(q);
  const correct = q.q_type === 2 ? sameMulti(chosen, ref) : Boolean(ref) && chosen === ref;
  return { question_id: q.id, correct, answer: ref, explanation: q.explanation };
}

// ---------------------------------------------------------------------------
// 组卷（移植自旧后端 /api/quiz 与 service.build_exam_paper）
// ---------------------------------------------------------------------------

export interface QuizOptions {
  size: number;
  answeredOnly: boolean;
  subject?: number | null;
  sourceId?: number | null;
  year?: number | null;
}

function matchesYear(years: string | null, year: number): boolean {
  return years != null && years.split(",").map(Number).includes(year);
}

/** 近三年（2023-2025）真题：组卷/答题优先出题，其他年份真题与无年份练习作为补充。 */
const RECENT_YEARS = new Set(["2023", "2024", "2025"]);
/** 近三年题在组卷中的目标占比（其余由其他年份/无年份题补足）。 */
const RECENT_RATIO = 0.3;

function isRecent(q: Question): boolean {
  return (q.years ?? "").split(",").some((y) => RECENT_YEARS.has(y.trim()));
}

/** Fisher-Yates 洗牌（返回新数组）。 */
function shuffle<T>(arr: T[]): T[] {
  const out = [...arr];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j]!, out[i]!];
  }
  return out;
}

/** 近三年优先取题：先从近三年池抽（目标占比），不足用其他池补足。 */
function pickWeighted<T>(pool: T[], size: number, recent: (t: T) => boolean): T[] {
  const recentPool = shuffle(pool.filter(recent));
  const restPool = shuffle(pool.filter((t) => !recent(t)));
  const nRecent = Math.min(recentPool.length, Math.round(size * RECENT_RATIO));
  const out = recentPool.slice(0, nRecent);
  if (out.length < size) out.push(...restPool.slice(0, size - out.length));
  return out;
}

/** 随机抽题：近三年（2023-2025）真题优先（目标占比 70%），其余由其他年份/无年份题补足。 */
export async function randomQuiz(opts: QuizOptions): Promise<Question[]> {
  const { size, answeredOnly, subject, sourceId, year } = opts;
  const subjects = subject == null ? [null, 1, 2, 3, 4] : [subject];
  let pool = await loadSubjects(subjects);
  if (answeredOnly) pool = pool.filter((q) => q.answer);
  if (sourceId != null) pool = pool.filter((q) => q.source_id === sourceId);
  if (year != null) pool = pool.filter((q) => matchesYear(q.years, year));
  return pickWeighted(pool, Math.min(size, pool.length), isRecent);
}

/** 浏览：过滤 + 分页，按年份降序（移植自 /api/questions）。 */
export async function queryQuestions(opts: {
  limit: number;
  offset: number;
  subject?: number | null;
  sourceId?: number | null;
  province?: string;
  year?: number | null;
  answered?: "" | "true" | "false";
}): Promise<{ total: number; questions: Question[] }> {
  const { limit, offset, sourceId, province, year, answered } = opts;
  const subjects = opts.subject == null ? [null, 1, 2, 3, 4] : [opts.subject];
  let pool = await loadSubjects(subjects);
  if (sourceId != null) pool = pool.filter((q) => q.source_id === sourceId);
  if (province) pool = pool.filter((q) => q.province?.includes(province));
  if (year != null) pool = pool.filter((q) => matchesYear(q.years, year));
  if (answered === "true") pool = pool.filter((q) => q.answer);
  if (answered === "false") pool = pool.filter((q) => !q.answer);
  pool = pool.sort((a, b) => (b.years ?? "").localeCompare(a.years ?? "") || b.id - a.id);
  return { total: pool.length, questions: pool.slice(offset, offset + limit) };
}

// ---------------------------------------------------------------------------
// 答题记录（localStorage）——答题历史 / 错题本 / 统计的唯一数据源
// ---------------------------------------------------------------------------

const LS_KEY = "daoyou_tiku_attempts_v1";

function readAttempts(): Attempt[] {
  try {
    const raw = localStorage.getItem(LS_KEY);
    return raw ? (JSON.parse(raw) as Attempt[]) : [];
  } catch {
    return [];
  }
}

function writeAttempts(list: Attempt[]): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(list));
  } catch {
    // 存储满/隐私模式：静默失败，仅本次会话内不持久化
  }
}

function fmtTime(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** 记录一次答题（错题本数据源）。 */
export function recordAttempt(q: Question, selected: string, correct: boolean): void {
  const list = readAttempts();
  const nextId = list.length ? Math.max(...list.map((a) => a.id)) + 1 : 1;
  list.push({
    id: nextId,
    question_id: q.id,
    selected,
    correct,
    created_at: fmtTime(new Date()),
    question: { ...q },
  });
  writeAttempts(list);
}

/** 答题历史（最新优先）。 */
export function attempts(limit = 500): Attempt[] {
  return readAttempts().slice(-limit).reverse();
}

/** 错题池：答错过的题去重、按最近一次答错排序（最新优先）。
 *  错后答对仍在池中（与旧后端 wrong_questions 一致：只要有答错记录）。 */
export function wrongPool(opts: {
  subject?: number | null;
  offset?: number;
  limit?: number;
}): { total: number; questions: Question[] } {
  const { offset = 0, limit = 50 } = opts;
  const all = readAttempts().filter((a) => !a.correct);
  const byQuestion = new Map<number, Attempt>();
  for (const a of all) {
    const prev = byQuestion.get(a.question_id);
    if (!prev || a.id > prev.id) byQuestion.set(a.question_id, a);
  }
  let entries = [...byQuestion.values()]
    .filter((a) => a.question.answer) // 排除无答案题
    .sort((a, b) => b.id - a.id); // 最近答错优先
  if (opts.subject != null) {
    entries = entries.filter((a) => a.question.subject === opts.subject);
  }
  const questions = entries.slice(offset, offset + limit).map((a) => a.question);
  return { total: entries.length, questions };
}

// ---------------------------------------------------------------------------
// 统计（manifest 静态数据 + localStorage 答题记录）
// ---------------------------------------------------------------------------

export async function stats(): Promise<Stats> {
  const manifest = await loadManifest();
  const list = readAttempts();
  const correct = list.filter((a) => a.correct).length;
  return {
    questions: manifest.total,
    answered: manifest.answered,
    sources: manifest.sources,
    attempts: list.length,
    correct,
    accuracy: list.length ? Math.round((correct / list.length) * 1000) / 1000 : null,
  };
}

// ---------------------------------------------------------------------------
// 笔试模拟（移植自旧后端 /api/exam*，内存 session 缓存）
// ---------------------------------------------------------------------------

const EXAM_PAPERS: Record<number, { subjects: number[]; label: string }> = {
  1: { subjects: [1, 2], label: "科目一+科目二 合并卷（政策法规+导游业务）" },
  2: { subjects: [3, 4], label: "科目三+科目四 合并卷（全国基础+地方知识）" },
};
const EXAM_TYPE_COUNTS: [number, number][] = [[1, 90], [2, 35], [3, 40]]; // 官方大纲：单选90+多选35+判断40
const EXAM_TYPE_SCORES: Record<number, number> = { 1: 0.5, 2: 1, 3: 0.5 }; // 官方分值：单选0.5/多选1/判断0.5
const EXAM_MINUTES = 90; // 官方每卷 90 分钟

interface ExamSession {
  questions: Question[];
}

/** 内存试卷缓存：paper_id -> session（判分针对组卷当时的精确题目）。 */
const examSessions = new Map<string, ExamSession>();

/** 组卷并缓存 session；返回脱敏题目（不含答案），与旧 /api/exam 一致。 */
export async function examPaper(paperType: number): Promise<ExamPaper> {
  const paper = EXAM_PAPERS[paperType];
  const pool = await loadSubjects(paper.subjects);
  const picked: Question[] = [];
  const typeCounts: Record<string, number> = {};
  for (const [qType, want] of EXAM_TYPE_COUNTS) {
    const candidates = pool.filter(
      (q) => q.q_type === qType && q.answer && paper.subjects.includes(q.subject ?? -1),
    );
    // 近三年真题优先取 want 道（不足用其他年份/无年份题补足，受库存上限）
    const chosen = pickWeighted(candidates, want, isRecent);
    picked.push(...chosen);
    typeCounts[qType] = chosen.length;
  }
  const paperId = `p${Date.now()}${Math.random().toString(36).slice(2, 8)}`;
  examSessions.set(paperId, { questions: picked });
  const questions: ExamQuestion[] = picked.map((q) => ({
    id: q.id,
    question_text: q.question_text,
    options: [q.option_a, q.option_b, q.option_c, q.option_d, q.option_e].filter(
      (o): o is string => Boolean(o),
    ),
    q_type: q.q_type ?? 1,
    subject: q.subject,
    province: q.province,
    years: q.years,
    source_url: q.source_url,
  }));
  return {
    paper_id: paperId,
    paper_type: paperType,
    label: paper.label,
    minutes: EXAM_MINUTES,
    type_counts: typeCounts,
    total: questions.length,
    questions,
  };
}

/** 单题即时判分；answer 返回原始存储答案（判断题「正确/错误」），与旧接口一致。 */
export function examCheck(paperId: string, questionId: number, answer: string): ExamCheckResult | null {
  const session = examSessions.get(paperId);
  const q = session?.questions.find((x) => x.id === questionId);
  if (!q) return null;
  const given = (answer || "").trim().toUpperCase();
  const ref = refAnswer(q);
  const correct = q.q_type === 2 ? sameMulti(given, ref) : Boolean(ref) && given === ref;
  return {
    question_id: q.id,
    correct,
    answer: q.answer ?? "",
    explanation: q.explanation ?? "",
    question_text: q.question_text,
    q_type: q.q_type,
  };
}

/** 汇总判分；同卷只可提交一次（提交后 session 移除，重交返回 null）。 */
export function examSubmit(
  paperId: string,
  answers: { question_id: number; answer: string }[],
): ExamResult | null {
  const session = examSessions.get(paperId);
  if (!session) return null;
  examSessions.delete(paperId);
  const questions = session.questions;
  const typeStats: Record<number, { total: number; correct: number }> = {
    1: { total: 0, correct: 0 },
    2: { total: 0, correct: 0 },
    3: { total: 0, correct: 0 },
  };
  const byId = new Map(questions.map((q) => [q.id, q]));
  const details: ExamResult["details"] = [];
  for (const a of answers) {
    const q = byId.get(a.question_id);
    if (!q) continue;
    const qType = q.q_type ?? 1;
    typeStats[qType]!.total += 1;
    const given = (a.answer || "").trim().toUpperCase();
    const ref = refAnswer(q);
    const correct = qType === 2 ? sameMulti(given, ref) : Boolean(ref) && given === ref;
    if (correct) typeStats[qType]!.correct += 1;
    details.push({
      question_id: q.id,
      correct,
      given: a.answer,
      answer: ref,
      explanation: q.explanation ?? "",
      question_text: q.question_text,
      q_type: qType,
    });
  }
  const total = (t: number) => typeStats[t]!.correct * EXAM_TYPE_SCORES[t]!;
  const full = (t: number) => typeStats[t]!.total * EXAM_TYPE_SCORES[t]!;
  return {
    total_score: Math.round((total(1) + total(2) + total(3)) * 10) / 10,
    full_score: Math.round((full(1) + full(2) + full(3)) * 10) / 10,
    details,
    type_stats: typeStats,
  };
}
