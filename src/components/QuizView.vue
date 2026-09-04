<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { checkQuestion, loadSources, randomQuiz, recordAttempt } from "../dataStore";
import type { CheckResult, Question, Source } from "../types";
import { SUBJECTS, optionsOf, subjectLabel } from "../types";

const emit = defineEmits<{ done: [] }>();
const props = defineProps<{ subject?: number | null }>();

const size = ref(10);
const answeredOnly = ref(true);
const loading = ref(false);
const error = ref("");
const questions = ref<Question[]>([]);
const current = ref(0);
const picked = ref<Record<number, string>>({});
const results = ref<Record<number, CheckResult>>({});
const checking = ref(false);

// filters
const subjectFilter = ref<number | null>(props.subject ?? null);
const sourceFilter = ref<number | null>(null);
const yearFilter = ref<number | null>(null);
const realExamFilter = ref<boolean | null>(null);
const YEAR_OPTIONS = [2019, 2018, 2017, 2016, 2015, 2014, 2013, 2012, 2011, 2010];
const sources = ref<Source[]>([]);

watch(() => props.subject, (v) => {
  subjectFilter.value = v ?? null;
});

const total = () => questions.value.length;
const q = () => questions.value[current.value];

onMounted(async () => {
  try {
    sources.value = await loadSources();
  } catch {
    sources.value = [];
  }
});

async function start() {
  loading.value = true;
  error.value = "";
  results.value = {};
  picked.value = {};
  current.value = 0;
  try {
    questions.value = await randomQuiz({
      size: size.value,
      answeredOnly: answeredOnly.value,
      subject: subjectFilter.value,
      sourceId: sourceFilter.value,
      year: yearFilter.value,
      isRealExam: realExamFilter.value,
    });
    if (questions.value.length === 0) {
      error.value = "没有符合筛选条件的题目";
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
    questions.value = [];
  } finally {
    loading.value = false;
  }
}

function isMulti() {
  return q()?.q_type === 2;
}

/** 单选/判断：点选即判分；多选：勾选多个选项后点「确认答案」判分。 */
async function check(letter: string) {
  const cur = q();
  if (!cur || checking.value) return;
  if (isMulti()) {
    if (results.value[cur.id]) return; // 已判定后锁定，不可再改
    const set = new Set((picked.value[cur.id] ?? "").split("").filter(Boolean));
    if (set.has(letter)) set.delete(letter);
    else set.add(letter);
    const joined = [...set].sort().join("");
    if (joined) picked.value[cur.id] = joined;
    else delete picked.value[cur.id];
    return;
  }
  if (picked.value[cur.id]) return;
  picked.value[cur.id] = letter;
  await judge(cur);
}

async function confirmMulti() {
  const cur = q();
  if (!cur || checking.value || !picked.value[cur.id]) return;
  await judge(cur);
}

async function judge(cur: Question) {
  checking.value = true;
  try {
    const r = checkQuestion(cur, picked.value[cur.id]);
    results.value[cur.id] = r;
    recordAttempt(cur, picked.value[cur.id], r.correct);
    emit("done");
  } catch (e) {
    delete picked.value[cur.id];
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    checking.value = false;
  }
}

function isPicked(letter: string): boolean {
  return (picked.value[q()?.id ?? -1] ?? "").includes(letter);
}

function isCorrectLetter(letter: string): boolean {
  const r = results.value[q()?.id ?? -1];
  if (!r) return false;
  return r.answer === letter || (isMulti() && (r.answer ?? "").includes(letter));
}

function next() {
  if (current.value < total() - 1) current.value += 1;
}

function prev() {
  if (current.value > 0) current.value -= 1;
}

function score() {
  return Object.values(results.value).filter((r) => r.correct).length;
}

function finished() {
  return total() > 0 && Object.keys(results.value).length === total();
}
</script>

<template>
  <section class="quiz">
    <div v-if="total() === 0" class="setup">
      <label>
        题目数
        <input v-model.number="size" type="number" min="1" max="100" />
      </label>
      <label>
        科目
        <select v-model="subjectFilter">
          <option :value="null">全部</option>
          <option v-for="s in SUBJECTS" :key="s.id" :value="s.id">
            {{ s.label }}
          </option>
        </select>
      </label>
      <label>
        来源
        <select v-model="sourceFilter">
          <option :value="null">全部来源</option>
          <option v-for="s in sources" :key="s.id" :value="s.id">
            {{ s.title || s.url || `来源 ${s.id}` }}
          </option>
        </select>
      </label>
      <label>
        年份
        <select v-model="yearFilter">
          <option :value="null">全部年份</option>
          <option v-for="y in YEAR_OPTIONS" :key="y" :value="y">{{ y }} 年</option>
        </select>
      </label>
      <label>
        类型
        <select v-model="realExamFilter">
          <option :value="null">真题与练习</option>
          <option :value="true">仅真题</option>
          <option :value="false">仅练习</option>
        </select>
      </label>
      <label>
        <input v-model="answeredOnly" type="checkbox" />
        仅做有答案的题
      </label>
      <button :disabled="loading" @click="start">
        {{ loading ? "加载题库中…" : "开始答题" }}
      </button>
      <p v-if="loading" class="hint">题库较大，首次加载需下载约十几 MB，请耐心等待；再次进入将秒开。</p>
      <p v-if="error" class="error">{{ error }}</p>
    </div>

    <div v-else class="session">
      <div class="progress">
        第 {{ current + 1 }} / {{ total() }} 题 · 答对 {{ score() }} 题
        <span v-if="q().subject != null" class="subject-tag">
          {{ subjectLabel(q().subject) }}
        </span>
        <span v-if="q()?.years" class="subject-tag">
          {{ q()!.years!.split(",").join(" / ") }} 年
        </span>
      </div>
      <p class="question">{{ q().question_text }}</p>
      <p v-if="q().source_url" class="origin">
        原题链接：
        <a :href="q().source_url" target="_blank" rel="noopener">{{
          q().source_url
        }}</a>
      </p>
      <ul class="options">
        <li
          v-for="opt in optionsOf(q())"
          :key="opt.letter"
          :class="{
            picked: isPicked(opt.letter),
            correct: results[q().id] && isCorrectLetter(opt.letter),
            wrong: results[q().id] && isPicked(opt.letter) && !isCorrectLetter(opt.letter) && !results[q().id].correct,
          }"
        >
          <button
            :disabled="!isMulti() ? !!picked[q().id] : !!results[q().id]"
            @click="check(opt.letter)"
          >
            {{ opt.letter }}. {{ opt.text }}
          </button>
        </li>
      </ul>
      <div v-if="isMulti() && !results[q().id]" class="multi-confirm">
        <p class="tip">多选题：勾选全部选项后点击「确认答案」判定。</p>
        <button :disabled="!picked[q().id] || checking" @click="confirmMulti">确认答案</button>
      </div>
      <p v-if="results[q().id]" class="feedback" :class="{ ok: results[q().id].correct }">
        参考答案：{{ results[q().id].answer }} ·
        {{ results[q().id].correct ? "回答正确" : "回答错误" }}
        <span v-if="results[q().id].explanation">—— {{ results[q().id].explanation }}</span>
      </p>
      <div class="nav">
        <button :disabled="current === 0" @click="prev">上一题</button>
        <button v-if="current < total() - 1" @click="next">下一题</button>
        <button v-else-if="finished()" @click="start">再来一组</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.setup {
  display: flex;
  gap: 16px;
  align-items: center;
  flex-wrap: wrap;
}
.setup > label { display: inline-flex; align-items: center; gap: 6px; }
.setup > button { margin-left: auto; }
.error { color: var(--bad); }
.hint { color: var(--muted); font-size: 13px; margin: 4px 0 0; grid-column: 1 / -1; }
.progress { color: var(--muted); margin-bottom: 8px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.subject-tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--accent, #2f6feb);
  color: #fff;
}
.question { font-size: 17px; line-height: 1.7; overflow-wrap: anywhere; }
.origin { font-size: 13px; color: var(--muted); margin-top: 4px; overflow-wrap: anywhere; }
.origin a { color: var(--accent, #2f6feb); word-break: break-all; }
.options { list-style: none; padding: 0; display: grid; gap: 8px; }
.options button {
  width: 100%;
  text-align: left;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel);
  cursor: pointer;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  line-height: 1.5;
}
.options li.correct button { border-color: #2e7d32; background: #e8f5e9; }
.options li.wrong button { border-color: var(--bad); background: #fdecea; }
.options li.picked:not(.correct):not(.wrong) button { border-color: var(--accent); }
.feedback { margin-top: 12px; color: var(--bad); overflow-wrap: anywhere; }
.feedback.ok { color: #2e7d32; }
.multi-confirm {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.multi-confirm .tip { margin: 0; color: var(--muted); font-size: 13px; }
.multi-confirm button {
  padding: 8px 18px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel);
  cursor: pointer;
  font: inherit;
}
.nav { display: flex; gap: 12px; margin-top: 16px; flex-wrap: wrap; }
.nav button { flex: 1; min-width: 0; }

/* 移动端主适配 */
@media (max-width: 768px) {
  .setup {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    align-items: stretch;
  }
  .setup > label {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 13px;
    color: var(--muted);
  }
  .setup > label > input,
  .setup > label > select {
    min-height: 44px;
    width: 100%;
    font-size: 15px;
  }
  .setup > label:has(input[type="checkbox"]) {
    flex-direction: row;
    align-items: center;
    font-size: 14px;
    color: var(--text);
    grid-column: 1 / -1;
  }
  .setup > button {
    margin-left: 0;
    min-height: 44px;
    grid-column: 1 / -1;
  }
  .setup > .error { grid-column: 1 / -1; }
  .question { font-size: 16px; }
  .nav button { min-height: 44px; padding: 4px 20px; }
  .multi-confirm button { min-height: 44px; }
}

/* 超窄屏：单列 */
@media (max-width: 360px) {
  .setup { grid-template-columns: 1fr; }
  .question { font-size: 15px; }
  .options button { padding: 10px 12px; font-size: 14px; }
}
</style>
