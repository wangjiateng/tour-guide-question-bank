<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { api } from "../api";
import type { CheckResult, Question, Source } from "../types";
import { LETTERS, SUBJECTS, optionOf, subjectLabel } from "../types";

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
const YEAR_OPTIONS = [2019, 2018, 2017, 2016, 2015, 2014, 2013, 2012, 2011, 2010];
const sources = ref<Source[]>([]);

watch(() => props.subject, (v) => {
  subjectFilter.value = v ?? null;
});

const total = () => questions.value.length;
const q = () => questions.value[current.value];

onMounted(async () => {
  try {
    sources.value = (await api.sources()).sources;
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
    const packet = await api.quiz(
      size.value,
      answeredOnly.value,
      subjectFilter.value,
      sourceFilter.value,
      yearFilter.value,
    );
    questions.value = await Promise.all(
      packet.question_ids.map((id) => api.question(id)),
    );
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

async function check(letter: string) {
  const cur = q();
  if (!cur || picked.value[cur.id] || checking.value) return;
  const chosen = isMulti()
    ? ((picked.value[cur.id] ?? "") + letter)
        .split("")
        .filter((c, idx, arr) => arr.indexOf(c) === idx)
        .sort()
        .join("")
    : letter;
  picked.value[cur.id] = chosen;
  checking.value = true;
  try {
    results.value[cur.id] = await api.check(cur.id, chosen);
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
        <input v-model="answeredOnly" type="checkbox" />
        仅做有答案的题
      </label>
      <button :disabled="loading" @click="start">
        {{ loading ? "加载中…" : "开始答题" }}
      </button>
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
          v-for="l in LETTERS"
          :key="l"
          :class="{
            picked: isPicked(l),
            correct: results[q().id] && isCorrectLetter(l),
            wrong: results[q().id] && isPicked(l) && !isCorrectLetter(l) && !results[q().id].correct,
          }"
        >
          <button
            :disabled="!isMulti() && !!picked[q().id]"
            @click="check(l)"
          >
            {{ l }}. {{ optionOf(q(), l) }}
          </button>
        </li>
      </ul>
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
.setup { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
.error { color: var(--bad); }
.progress { color: var(--muted); margin-bottom: 8px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.subject-tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--accent, #2f6feb);
  color: #fff;
}
.question { font-size: 17px; line-height: 1.7; overflow-wrap: anywhere; }
.origin { font-size: 13px; color: var(--muted); margin-top: 4px; }
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
}
.options li.correct button { border-color: #2e7d32; background: #e8f5e9; }
.options li.wrong button { border-color: var(--bad); background: #fdecea; }
.options li.picked:not(.correct):not(.wrong) button { border-color: var(--accent); }
.feedback { margin-top: 12px; color: var(--bad); }
.feedback.ok { color: #2e7d32; }
.nav { display: flex; gap: 12px; margin-top: 16px; }

@media (max-width: 640px) {
  .setup { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .setup label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--muted); }
  .setup input[type="number"],
  .setup select {
    min-height: 44px;
    width: 100%;
    font-size: 15px;
  }
  .setup label:has(input[type="checkbox"]) {
    flex-direction: row;
    align-items: center;
    font-size: 14px;
    color: var(--text);
  }
  .setup button { min-height: 44px; }
  .question { font-size: 16px; }
  .nav button { min-height: 44px; padding: 4px 20px; flex: 1; }
}
</style>
