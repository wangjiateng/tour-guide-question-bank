export interface Source {
  id: number;
  url: string;
  title: string;
  kind: string;
  status: string;
  detail: string;
  question_count: number;
  last_analyzed_at: string | null;
  refresh_interval_seconds: number;
  last_refresh_at: string | null;
  created_at: string;
}

export interface Question {
  id: number;
  source_id: number | null;
  source_url: string;
  question_text: string;
  option_a: string | null;
  option_b: string | null;
  option_c: string | null;
  option_d: string | null;
  option_e: string | null;
  answer: string | null;
  explanation: string;
  subject: number | null;
  paper_title: string | null;
  province: string | null;
  years: string | null;
  q_type: number | null;
  created_at: string;
}

export interface CheckResult {
  question_id: number;
  correct: boolean;
  answer: string | null;
  explanation: string;
}

export interface Stats {
  questions: number;
  answered: number;
  sources: number;
  attempts: number;
  correct: number;
  accuracy: number | null;
}

export interface Attempt {
  id: number;
  question_id: number;
  selected: string;
  correct: boolean;
  created_at: string;
  /** 作答时的完整题目快照：历史展示与错题本重练都不依赖题库文件仍存在 */
  question: Question;
}

export interface ExamQuestion {
  id: number;
  question_text: string;
  options: string[];
  q_type: number; // 1 单选 / 2 多选 / 3 判断
  subject: number | null;
  province: string | null;
  years: string | null;
  source_url: string;
}

export interface ExamPaper {
  paper_id: string;
  paper_type: number;
  label: string;
  minutes: number;
  type_counts: Record<string, number>;
  total: number;
  questions: ExamQuestion[];
}

export interface ExamResultDetail {
  question_id: number;
  correct: boolean;
  given: string | null;
  answer: string | null;
  explanation: string;
  question_text: string;
  q_type: number;
}

export interface ExamResult {
  total_score: number;
  full_score: number;
  details: ExamResultDetail[];
  type_stats: Record<string, { total: number; correct: number }>;
}

export interface ExamCheckResult {
  question_id: number;
  correct: boolean;
  answer: string | null;
  explanation: string;
  question_text: string;
  q_type: number | null;
}

export const EXAM_PAPER_TYPES: { id: number; label: string }[] = [
  { id: 1, label: "科目一+二 合并卷" },
  { id: 2, label: "科目三+四 合并卷" },
];

export function qTypeLabel(q_type: number): string {
  return { 1: "单选", 2: "多选", 3: "判断" }[q_type] ?? "未知";
}

const OPTION_KEYS = ["option_a", "option_b", "option_c", "option_d", "option_e"] as const;
export const LETTERS = ["A", "B", "C", "D", "E"] as const;


/** 导游资格考试科目：1 政策与法律法规 / 2 导游业务 / 3 全国导游基础知识 / 4 地方导游基础知识 */
export const SUBJECTS: { id: number; label: string }[] = [
  { id: 1, label: "科目一·政策法规" },
  { id: 2, label: "科目二·导游业务" },
  { id: 3, label: "科目三·基础知识" },
  { id: 4, label: "科目四·地方知识" },
];

export function subjectLabel(subject: number | null): string {
  if (subject == null) return "未分类";
  return SUBJECTS.find((s) => s.id === subject)?.label ?? `科目${subject}`;
}

export function optionOf(q: Question, letter: (typeof LETTERS)[number]): string | null {
  return q[OPTION_KEYS[LETTERS.indexOf(letter)]] ?? null;
}

export function optionsOf(q: Question): { letter: string; text: string }[] {
  return LETTERS.map((l) => ({ letter: l, text: optionOf(q, l) ?? "" })).filter(
    (o) => o.text.trim() !== "",
  );
}
