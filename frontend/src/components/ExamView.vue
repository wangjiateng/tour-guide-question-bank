<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import { api } from "../api";
import { EXAM_PAPER_TYPES, qTypeLabel } from "../types";
import type { ExamCheckResult, ExamPaper, ExamResult } from "../types";

const paper = ref<ExamPaper | null>(null);
const loading = ref(false);
const error = ref("");
const currentIndex = ref(0);
const answers = ref<Record<number, string>>({});
const verdicts = ref<Record<number, boolean>>({});
const checked = ref<Record<number, ExamCheckResult>>({});
const checking = ref(false);
const secondsLeft = ref(0);
const finished = ref(false);
const result = ref<ExamResult | null>(null);
let timer: ReturnType<typeof setInterval> | null = null;

const qs = computed(() => paper.value?.questions ?? []);
const current = computed(() => qs.value[currentIndex.value]);
const answeredCount = computed(() => Object.keys(answers.value).length);
const correctCount = computed(() => Object.values(verdicts.value).filter(Boolean).length);
const wrongCount = computed(() => Object.values(verdicts.value).filter((v) => !v).length);
const unansweredCount = computed(() => qs.value.length - answeredCount.value);

function fmtTime(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

async function start(paperType: number) {
  loading.value = true;
  error.value = "";
  result.value = null;
  finished.value = false;
  answers.value = {};
  verdicts.value = {};
  checked.value = {};
  currentIndex.value = 0;
  try {
    paper.value = await api.exam(paperType);
    secondsLeft.value = paper.value.minutes * 60;
    if (timer) clearInterval(timer);
    timer = setInterval(() => {
      secondsLeft.value -= 1;
      if (secondsLeft.value <= 0) {
        secondsLeft.value = 0;
        finish();
      }
    }, 1000);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function toggleOption(letter: string) {
  if (finished.value || !current.value || checking.value) return;
  const id = current.value.id;
  // 已判过的题可以改答案重判
  delete verdicts.value[id];
  delete checked.value[id];
  if (current.value.q_type === 2) {
    const set = new Set((answers.value[id] ?? "").split("").filter(Boolean));
    if (set.has(letter)) set.delete(letter);
    else set.add(letter);
    answers.value = { ...answers.value, [id]: [...set].sort().join("") };
  } else {
    answers.value = { ...answers.value, [id]: letter };
  }
  const chosen = answers.value[id];
  if (chosen) {
    checking.value = true;
    try {
      const r = await api.examCheck(paper.value!.paper_id, id, chosen);
      verdicts.value = { ...verdicts.value, [id]: r.correct };
      checked.value = { ...checked.value, [id]: r };
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      checking.value = false;
    }
  }
}

function isSelected(letter: string): boolean {
  if (!current.value) return false;
  const a = answers.value[current.value.id] ?? "";
  return a.includes(letter);
}

function isChecked(qid: number): boolean {
  return qid in verdicts.value;
}

function isAnswered(qid: number): boolean {
  return Boolean(answers.value[qid]);
}

function LETTER(i: number): string {
  return "ABCDE"[i] ?? "";
}

/** 判分答案与选项字母比对：判断题 answer 为 A/B（服务端已映射中文），
    多选题逐字母包含判断。 */
function isAnswerLetter(letter: string): boolean {
  if (!current.value || !checked.value[current.value.id]) return false;
  const ans = checked.value[current.value.id]!.answer ?? "";
  if (current.value.q_type === 2) return ans.includes(letter);
  return ans === letter;
}

async function finish() {
  if (finished.value || !paper.value) return;
  finished.value = true;
  if (timer) clearInterval(timer);
  await doSubmit();
}

async function retrySubmit() {
  if (!paper.value) return;
  await doSubmit();
}

async function doSubmit() {
  if (!paper.value) return;
  try {
    const payload = Object.entries(answers.value).map(([id, answer]) => ({
      question_id: Number(id),
      answer,
    }));
    result.value = await api.examSubmit(paper.value.paper_id, payload);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
    result.value = null;
  }
}

function restart() {
  paper.value = null;
  finished.value = false;
  result.value = null;
  error.value = "";
  checking.value = false;
}

onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <section>
    <!-- 未开始：选卷 -->
    <div v-if="!paper" class="start">
      <h2>在线笔试模拟</h2>
      <p class="hint">
        按全国导游资格考试真实笔试组卷：单选 45 + 多选 35 + 判断 40（判断题量受题库库存限制），限时
        165 分钟。每题选择答案后<b>立即判定对错</b>并显示正确答案与解析。
      </p>
      <div class="paper-options">
        <button
          v-for="t in EXAM_PAPER_TYPES"
          :key="t.id"
          :disabled="loading"
          @click="start(t.id)"
        >
          {{ t.label }}
        </button>
      </div>
      <p v-if="loading" class="hint">正在组卷…</p>
      <p v-if="error" class="error">{{ error }}</p>
    </div>

    <!-- 作答中 / 已结束 -->
    <div v-else>
      <div class="toolbar">
        <span class="paper-label">{{ paper.label }}</span>
        <span class="count">
          已答 {{ answeredCount }} / {{ qs.length }}
          <template v-if="correctCount + wrongCount > 0">
            · 对 {{ correctCount }} 错 {{ wrongCount }}
          </template>
          <template v-if="unansweredCount > 0"> · 未答 {{ unansweredCount }}</template>
        </span>
        <span class="timer" :class="{ urgent: secondsLeft < 300 }">剩余 {{ fmtTime(secondsLeft) }}</span>
        <button :disabled="finished" @click="finish">结束考试</button>
      </div>

      <!-- 题号导航 -->
      <nav class="qnav">
        <button
          v-for="(q, i) in qs"
          :key="q.id"
          :class="{
            active: i === currentIndex,
            right: isChecked(q.id) && verdicts[q.id],
            wrong: isChecked(q.id) && !verdicts[q.id],
            answered: !isChecked(q.id) && isAnswered(q.id),
          }"
          @click="currentIndex = i"
        >
          {{ i + 1 }}
        </button>
      </nav>

      <!-- 当前题 -->
      <div v-if="current" class="question">
        <p class="qtype">
          {{ qTypeLabel(current.q_type) }}
          <span v-if="current.subject === 4" class="province">
            · {{ current.province || "未知省份" }}
          </span>
        </p>
        <p class="qtext">{{ current.question_text }}</p>
        <label
          v-for="(opt, i) in current.options"
          :key="i"
          class="option"
          :class="{
            selected: isSelected(LETTER(i)),
            correct: isChecked(current.id) && isAnswerLetter(LETTER(i)),
            wrong: isChecked(current.id) && isSelected(LETTER(i)) && !isAnswerLetter(LETTER(i)),
          }"
        >
          <input
            type="checkbox"
            :checked="isSelected(LETTER(i))"
            :disabled="finished || checking"
            @change="toggleOption(LETTER(i))"
          />
          <span class="letter">{{ LETTER(i) }}</span>
          <span>{{ opt }}</span>
        </label>
        <div v-if="isChecked(current.id) && checked[current.id]" class="feedback">
          <p :class="verdicts[current.id] ? 'ok' : 'bad'">
            {{ verdicts[current.id] ? "✓ 答对了" : "✗ 答错了" }}
            · 正确答案：{{ checked[current.id]!.answer }}
          </p>
          <p v-if="checked[current.id]!.explanation" class="explanation">
            {{ checked[current.id]!.explanation }}
          </p>
        </div>
        <p v-if="checking" class="hint">正在判定…</p>
      </div>

      <div class="pager">
        <button :disabled="currentIndex === 0" @click="currentIndex -= 1">上一题</button>
        <button v-if="currentIndex < qs.length - 1" @click="currentIndex += 1">下一题</button>
      </div>

      <!-- 结束考试汇总 -->
      <div v-if="finished" class="result">
        <template v-if="result">
          <h3>考试成绩</h3>
          <p class="score">{{ result.total_score }} / {{ result.full_score }} 分</p>
          <p class="hint">
            共 {{ result.details.length }} 题：答对
            {{ Object.values(verdicts).filter(Boolean).length }}，答错
            {{ Object.values(verdicts).filter((v) => !v).length }}，未答
            {{ unansweredCount }}。结束后不可再作答。
          </p>
        </template>
        <template v-else>
          <h3>交卷失败</h3>
          <p class="error">{{ error || "提交成绩时出错，请重试。" }}</p>
          <p class="hint">试卷已结束，不可再作答。可重新交卷或返回选题。</p>
        </template>
        <button v-if="!result" :disabled="checking" @click="retrySubmit">重新交卷</button>
        <button @click="restart">返回选题</button>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
    </div>
  </section>
</template>

<style scoped>
.start { text-align: center; padding: 40px 0; }
.hint { color: var(--muted, #666); font-size: 13px; }
.paper-options { display: flex; gap: 12px; justify-content: center; margin: 20px 0; }
.paper-options button, .toolbar button, .pager button, .result button {
  padding: 8px 18px; border-radius: 6px; border: 1px solid var(--border, #ccc);
  background: var(--panel, #fff); cursor: pointer;
}
.paper-options button:hover, .toolbar button:hover { background: var(--accent-soft, #eef); }
.toolbar {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  padding: 10px 0; border-bottom: 1px solid var(--border, #ddd); margin-bottom: 12px;
}
.paper-label { font-weight: 600; }
.timer { font-variant-numeric: tabular-nums; }
.timer.urgent { color: #c33; font-weight: 700; }
.qnav {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(34px, 1fr));
  gap: 4px; margin-bottom: 16px; max-height: 160px; overflow-y: auto;
}
.qnav button {
  padding: 4px 0; border: 1px solid var(--border, #ccc); border-radius: 4px;
  background: var(--panel, #fff); cursor: pointer; font-size: 12px;
}
.qtype { color: var(--muted, #666); font-size: 12px; margin: 0 0 6px; }
.qtype .province { color: var(--accent, #06c); font-weight: 600; }
.qnav button.active { outline: 2px solid #06c; }
.qnav button.wrong { background: #fcc; }
.qnav button.right { background: #cfc; }
.question { padding: 8px 0; }
.qtext { font-size: 15px; line-height: 1.6; margin: 0 0 12px; }

.option {
  display: flex; gap: 8px; align-items: flex-start; padding: 8px 10px;
  border: 1px solid var(--border, #ddd); border-radius: 6px; margin-bottom: 6px; cursor: pointer;
}
.option.selected { border-color: #06c; background: #eef6ff; }
.option.correct { border-color: #0a0; background: #eff; }
.option.wrong { border-color: #c00; background: #fee; }
.option .letter { font-weight: 700; }
.feedback { margin-top: 10px; padding: 8px 12px; border-radius: 6px; background: var(--panel-soft, #f6f6f6); }
.feedback .ok { color: #070; }
.feedback .bad { color: #b00; }
.explanation { color: #444; font-size: 13px; }
.pager { display: flex; gap: 10px; margin: 14px 0; }
.result { margin-top: 20px; padding: 16px; border: 1px solid var(--border, #ccc); border-radius: 8px; text-align: center; }
.score { font-size: 22px; font-weight: 700; }
.error { color: #b00; }

@media (max-width: 640px) {
  .paper-options { flex-direction: column; align-items: stretch; gap: 10px; margin: 16px 0; }
  .paper-options button, .toolbar button, .pager button, .result button { min-height: 44px; }
  .toolbar { gap: 10px; }
  .toolbar .count { order: 3; width: 100%; }
  .qnav {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(38px, 1fr));
    gap: 6px;
    max-height: none;
    overflow-y: visible;
  }
  .qnav button { min-height: 40px; font-size: 13px; }
  .option { padding: 12px 10px; }
  .option input[type="checkbox"] { width: 20px; height: 20px; flex: none; }
  .qtext { font-size: 16px; overflow-wrap: anywhere; }
  .pager { flex-wrap: wrap; }
  .pager button { flex: 1; }
  .explanation { overflow-wrap: anywhere; }
}
</style>
