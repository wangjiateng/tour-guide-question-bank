import type {
  Attempt,
  CheckResult,
  ExamCheckResult,
  ExamPaper,
  ExamResult,
  Question,
  QuizPacket,
  Source,
  SourceAddResult,
  Stats,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const data: unknown = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    let detail = resp.statusText;
    if (data && typeof data === "object" && "detail" in data) {
      const d = data.detail;
      detail = typeof d === "string" ? d : JSON.stringify(d);
    }
    throw new Error(detail);
  }
  return data as T;
}

export const api = {
  stats: () => request<Stats>("/api/stats"),
  sources: () => request<{ sources: Source[] }>("/api/sources"),
  addSource: (url: string) =>
    request<SourceAddResult>("/api/sources", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  refreshSource: (id: number) =>
    request<{ ok: boolean; reason: string; questions_found: number; questions_inserted: number; questions_updated: number; questions_deduped: number }>(
      `/api/sources/${id}/refresh`,
      { method: "POST" },
    ),
  deleteSource: (id: number) =>
    request<{ ok: boolean }>(`/api/sources/${id}`, { method: "DELETE" }),
  setSourceInterval: (id: number, intervalSeconds: number) =>
    request<{ ok: boolean; refresh_interval_seconds: number }>(
      `/api/sources/${id}/interval`,
      { method: "PUT", body: JSON.stringify({ interval_seconds: intervalSeconds }) },
    ),
  refreshDue: () =>
    request<{ due: number; results: { source_id: number; ok: boolean; questions_inserted: number }[] }>(
      "/api/sources/refresh-due",
      { method: "POST" },
    ),
  attempts: () => request<{ attempts: Attempt[] }>("/api/attempts"),
  wrong: (params?: URLSearchParams) =>
    request<{ total: number; limit: number; offset: number; questions: Question[] }>(
      `/api/wrong?${params ?? ""}`,
    ),
  questions: (params: URLSearchParams) =>
    request<{ total: number; questions: Question[] }>(`/api/questions?${params}`),
  question: (id: number) => request<Question>(`/api/questions/${id}`),
  quiz: (size: number, answeredOnly: boolean, subject?: number | null, sourceId?: number | null, year?: number | null) => {
    const params = new URLSearchParams({
      size: String(size),
      answered_only: String(answeredOnly),
    });
    if (subject != null) params.set("subject", String(subject));
    if (sourceId != null) params.set("source_id", String(sourceId));
    if (year != null) params.set("year", String(year));
    return request<QuizPacket>(`/api/quiz?${params}`);
  },
  check: (questionId: number, answer: string) =>
    request<CheckResult>(`/api/check?question_id=${questionId}`, {
      method: "POST",
      body: JSON.stringify({ answer }),
    }),
  exam: (paperType: number) => request<ExamPaper>(`/api/exam?paper_type=${paperType}`),
  examCheck: (paperId: string, questionId: number, answer: string) =>
    request<ExamCheckResult>("/api/exam/check", {
      method: "POST",
      body: JSON.stringify({ paper_id: paperId, question_id: questionId, answer }),
    }),
  examSubmit: (paperId: string, answers: { question_id: number; answer: string }[]) =>
    request<ExamResult>("/api/exam/submit", {
      method: "POST",
      body: JSON.stringify({ paper_id: paperId, answers }),
    }),
};
