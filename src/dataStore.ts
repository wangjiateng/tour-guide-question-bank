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

/** 主源（部署所在域名）单次超时：移动网络下易超时，短超时快速让位于备用源。 */
const PRIMARY_TIMEOUT_MS = 4_000;
/** 备用源（jsDelivr CDN）单次超时：CDN 是大陆主要可用路径，给足时间。 */
const FETCH_TIMEOUT_MS = 8_000;
/** 备用数据源：github.io 在大陆移动网络不稳定，题库 JSON 经 jsDelivr CDN 镜像拉取。
 *  数据文件需随仓库提交到 master（public/data/），CDN 缓存约 12h 内更新。 */
const CDN_MIRROR_BASE = "https://cdn.jsdelivr.net/gh/wangjiateng/tour-guide-question-bank@master/public/data/";

/** 题库数据持久缓存（Cache API）：全量题库约 14MB，刷新页面后命中缓存秒开，无需重新下载。
 *  键 = 文件绝对 URL + `?v=` + manifest.generated_at：题库更新（版本号变化）后自动失效重下。
 *  Cache API 仅在安全上下文（https / localhost）可用，不可用时静默降级为纯网络加载。 */
const DATA_CACHE_NAME = "daoyou-tiku-data-v1";
/** manifest 的 generated_at，作为题库版本号（持久缓存的失效依据）。 */
let dataVersion: string | null = null;

/** 打开持久缓存；环境不支持（file:// / 隐私模式等）时返回 null。 */
async function cacheStorage(): Promise<Cache | null> {
  try {
    if (typeof caches === "undefined") return null;
    return await caches.open(DATA_CACHE_NAME);
  } catch {
    return null;
  }
}

/** 按版本化键读持久缓存；未命中 / 损坏时返回 null（走网络）。 */
async function cacheRead<T>(key: string): Promise<T | null> {
  const cache = await cacheStorage();
  if (!cache) return null;
  try {
    const res = await cache.match(key);
    if (!res || !res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/** 写持久缓存；写失败（配额/隐私）不影响主流程。写入前清理同文件其他版本的旧条目，防累积。 */
async function cacheWrite<T>(key: string, data: T): Promise<void> {
  const cache = await cacheStorage();
  if (!cache) return;
  try {
    const base = key.split("?")[0]!;
    const keys = await cache.keys();
    for (const k of keys) {
      if (k.url.split("?")[0] === base && k.url !== key) await cache.delete(k);
    }
    await cache.put(
      key,
      new Response(JSON.stringify(data), { headers: { "Content-Type": "application/json" } }),
    );
  } catch {
    // 静默：缓存写失败不影响组卷
  }
}

/** 多个请求并发竞速，先成功者胜（其余请求由其自身超时 abort，无泄漏）。 */
function firstFulfilled<T>(promises: Promise<T>[]): Promise<T> {
  return new Promise((resolve, reject) => {
    let pending = promises.length;
    let lastErr: unknown;
    for (const p of promises) {
      p.then(resolve, (e) => {
        lastErr = e;
        if (--pending === 0) reject(lastErr);
      });
    }
  });
}

/** 版本化缓存键：同一文件不同版本独立缓存，写新键时旧键自动清理。 */
function cacheKey(path: string): string {
  const abs = new URL(path, document.baseURI).href;
  return dataVersion ? `${abs}?v=${encodeURIComponent(dataVersion)}` : abs;
}

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

/** 纯网络拉取题库 JSON（无缓存）：主源与 CDN 并行竞速，先成功者胜，避免主源超时的串行等待。 */
async function fetchJsonNetwork<T>(path: string): Promise<T> {
  const fileName = path.split("/").pop() ?? path;
  const mirror = CDN_MIRROR_BASE + fileName;
  let lastErr: unknown;
  // 主源 + 备用源（CDN）同时发起：谁先返回用谁。移动网络下 github.io 常慢，CDN 通常更快。
  try {
    return await firstFulfilled<T>([
      fetchOnce<T>(path, PRIMARY_TIMEOUT_MS),
      fetchOnce<T>(mirror, FETCH_TIMEOUT_MS),
    ]);
  } catch (e) {
    lastErr = e;
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

/** 拉取题库 JSON（默认带持久缓存）：命中缓存秒开；未命中走网络并写入缓存。
 *  manifest.json 是版本源，必须实时拉取（cache=false）。 */
async function fetchJson<T>(path: string, opts?: { cache?: boolean }): Promise<T> {
  const useCache = opts?.cache ?? true;
  const key = cacheKey(path);
  if (useCache) {
    const cached = await cacheRead<T>(key);
    if (cached != null) return cached;
  }
  const data = await fetchJsonNetwork<T>(path);
  if (useCache) await cacheWrite(key, data);
  return data;
}

/** 题目文件键：subject NULL → "0"，科目 1-4 → 字符串 */
function subjectKey(subject: number | null): (typeof SUBJECT_KEYS)[number] {
  return subject == null ? "0" : String(subject) as (typeof SUBJECT_KEYS)[number];
}

/** years 字段归一化：历史数据存在 list 脏值（如 ['0','1','2','4']），统一转成逗号分隔字符串或 null。
 *  仅保留 4 位数字年份（如 2012），脏值/空串一律归 null，保证下游 .split(",") 安全。 */
function normalizeYears(years: unknown): string | null {
  if (years == null) return null;
  const parts = Array.isArray(years) ? years : String(years).split(",");
  const valid = parts
    .map((p) => String(p).trim())
    .filter((p) => /^\d{4}$/.test(p));
  return valid.length ? valid.join(",") : null;
}

/** 加载 manifest（统计信息 + 题库版本号，App 头部与 stats 用）。
 *  manifest 是版本源，始终实时拉取（不持久缓存），成功后记录 generated_at 作为题库版本。 */
export async function loadManifest(): Promise<Manifest> {
  if (!manifestCache) {
    manifestCache = await fetchJson<Manifest>(DATA_BASE + "manifest.json", { cache: false });
    dataVersion = manifestCache.generated_at;
  }
  return manifestCache;
}

/** 加载来源元数据（Quiz/Browse 的「来源」筛选用）。加载前先确保版本号就绪，持久缓存才能正确失效。 */
export async function loadSources(): Promise<Source[]> {
  if (sourcesCache == null) {
    await loadManifest(); // 版本号就绪（内存缓存，开销可忽略）
    const file = await fetchJson<SourcesFile>(DATA_BASE + "sources.json");
    sourcesCache = file.sources;
  }
  return sourcesCache;
}

/** 加载某科目题目文件（懒加载 + 并发去重 + 持久缓存）。subject null 表示未分类（0）。 */
export function loadSubjectQuestions(subject: number | null): Promise<Question[]> {
  const key = subjectKey(subject);
  if (loaded[key]) return Promise.resolve(loaded[key]!);
  if (!loading[key]) {
    loading[key] = (async () => {
      await loadManifest(); // 版本号就绪后，题目文件的持久缓存键才能区分新旧题库
      const file = await fetchJson<QuestionsFile>(DATA_BASE + `questions_${key}.json`);
      // years 存在 list 脏值的历史数据，加载时统一归一化，保证组卷/排序/展示不崩
      for (const q of file.questions) q.years = normalizeYears(q.years);
      loaded[key] = file.questions;
      return file.questions;
    })().finally(() => {
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
  /** true=仅真题，false=仅练习，null=全部 */
  isRealExam?: boolean | null;
}

function matchesYear(years: string | null, year: number): boolean {
  return years != null && years.split(",").map(Number).includes(year);
}

/** 近三年（2023-2025）真题：在线答题优先出题。 */
const RECENT_YEARS = new Set(["2023", "2024", "2025"]);
/** 在线答题中近三年真题的目标占比（0.7 = 近三年 70% + 题引力新题等补充 30%）。 */
const RECENT_RATIO = 0.7;

function isRecent(q: Question): boolean {
  return (q.years ?? "").split(",").some((y) => RECENT_YEARS.has(y.trim()));
}

/** 题引力（tiyinli）专题题：作为近三年之外的高质量补充练习（带答案解析，与历史老题不同）。 */
function isSupplement(q: Question): boolean {
  return q.source_id === 67;
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

// ---------------------------------------------------------------------------
// 组卷出现次数平衡：localStorage 记录每题被组卷抽中的次数，抽题时出现少的优先
// ---------------------------------------------------------------------------

const APPEAR_KEY = "daoyou_tiku_exam_appear_v1";

function readAppear(): Map<number, number> {
  try {
    const raw = localStorage.getItem(APPEAR_KEY);
    if (!raw) return new Map();
    const obj = JSON.parse(raw) as Record<string, number>;
    const m = new Map<number, number>();
    for (const [k, v] of Object.entries(obj)) {
      if (typeof v === "number") m.set(Number(k), v);
    }
    return m;
  } catch {
    return new Map();
  }
}

function writeAppear(m: Map<number, number>): void {
  try {
    const obj: Record<string, number> = {};
    for (const [k, v] of m) obj[String(k)] = v;
    localStorage.setItem(APPEAR_KEY, JSON.stringify(obj));
  } catch {
    // 存储满/隐私模式：静默失败，仅本次组卷不持久化
  }
}

/** 按历史出现次数平衡取题：出现次数少的优先（组内随机），使每题被抽中频率趋于均衡。 */
function pickBalanced<T extends { id: number }>(
  pool: T[],
  size: number,
  appear: Map<number, number>,
): T[] {
  const byCount = new Map<number, T[]>();
  for (const t of pool) {
    const c = appear.get(t.id) ?? 0;
    const arr = byCount.get(c);
    if (arr) arr.push(t);
    else byCount.set(c, [t]);
  }
  const out: T[] = [];
  for (const c of [...byCount.keys()].sort((a, b) => a - b)) {
    if (out.length >= size) break;
    out.push(...shuffle(byCount.get(c)!).slice(0, size - out.length));
  }
  return out;
}

/** 随机抽题：近三年（2023-2025）真题优先（默认 70%），其余由题引力新题等补充；未显式筛选来源/年份时排除历史老题与旧练习。 */
export async function randomQuiz(opts: QuizOptions): Promise<Question[]> {
  const { size, answeredOnly, subject, sourceId, year, isRealExam } = opts;
  const subjects = subject == null ? [null, 1, 2, 3, 4] : [subject];
  let pool = await loadSubjects(subjects);
  if (answeredOnly) pool = pool.filter((q) => q.answer);
  if (sourceId != null) pool = pool.filter((q) => q.source_id === sourceId);
  if (year != null) pool = pool.filter((q) => matchesYear(q.years, year));
  if (isRealExam != null) pool = pool.filter((q) => q.is_real_exam === isRealExam);
  // 未显式筛选来源/年份：只从"近三年真题 + 题引力新题"出题，避免历史老题与旧无年份练习
  if (sourceId == null && year == null) pool = pool.filter((q) => isRecent(q) || isSupplement(q));
  const appear = readAppear();
  const n = Math.min(size, pool.length);
  const recent = pool.filter(isRecent);
  const rest = pool.filter((q) => !isRecent(q));
  const nRecent = Math.min(recent.length, Math.round(n * RECENT_RATIO));
  const out = [
    ...pickBalanced(recent, nRecent, appear),
    ...pickBalanced(rest, n - nRecent, appear),
  ];
  for (const q of out) appear.set(q.id, (appear.get(q.id) ?? 0) + 1);
  writeAppear(appear);
  return out;
}

/** 浏览：过滤 + 分页，按年份降序（移植自 /api/questions）。 */
export async function queryQuestions(opts: {
  limit: number;
  offset: number;
  subject?: number | null;
  sourceId?: number | null;
  province?: string;
  year?: number | null;
  isRealExam?: boolean | null;
  answered?: "" | "true" | "false";
}): Promise<{ total: number; questions: Question[] }> {
  const { limit, offset, sourceId, province, year, isRealExam, answered } = opts;
  const subjects = opts.subject == null ? [null, 1, 2, 3, 4] : [opts.subject];
  let pool = await loadSubjects(subjects);
  if (sourceId != null) pool = pool.filter((q) => q.source_id === sourceId);
  if (province) pool = pool.filter((q) => q.province?.includes(province));
  if (year != null) pool = pool.filter((q) => matchesYear(q.years, year));
  if (isRealExam != null) pool = pool.filter((q) => q.is_real_exam === isRealExam);
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
    if (!raw) return [];
    const list = JSON.parse(raw) as Attempt[];
    // 历史快照的 years 可能存过 list 脏值，读取时统一归一化防崩
    for (const a of list) {
      if (a.question) a.question.years = normalizeYears(a.question.years);
    }
    return list;
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
  const appear = readAppear();
  const picked: Question[] = [];
  const typeCounts: Record<string, number> = {};
  for (const [qType, want] of EXAM_TYPE_COUNTS) {
    const candidates = pool.filter(
      (q) => q.q_type === qType && q.answer && paper.subjects.includes(q.subject ?? -1),
    );
    // 笔试保持只出近三年真题（不足才补），模拟真实考试；组内按历史出现次数平衡抽取
    const recent = candidates.filter(isRecent);
    const rest = candidates.filter((q) => !isRecent(q));
    const chosen = [
      ...pickBalanced(recent, Math.min(want, recent.length), appear),
      ...pickBalanced(rest, want - Math.min(want, recent.length), appear),
    ];
    picked.push(...chosen);
    typeCounts[qType] = chosen.length;
  }
  // 记录本次组卷各题出现次数，用于平衡后续组卷
  for (const q of picked) appear.set(q.id, (appear.get(q.id) ?? 0) + 1);
  writeAppear(appear);
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
