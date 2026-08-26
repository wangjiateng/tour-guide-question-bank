<script setup lang="ts">
import { onMounted, ref } from "vue";
import { checkQuestion, recordAttempt, wrongPool } from "../dataStore";
import type { CheckResult, Question } from "../types";
import { SUBJECTS, optionsOf, subjectLabel } from "../types";

const emit = defineEmits<{ done: [] }>();
const props = defineProps<{ subject?: number | null }>();

const loading = ref(false);
const error = ref("");
const questions = ref<Question[]>([]);
const total = ref(0);
const offset = ref(0);
const pageSize = 50;
const subjectFilter = ref<number | null>(props.subject ?? null);
const current = ref(0);
const picked = ref<Record<number, string>>({});
const results = ref<Record<number, CheckResult>>({});
const checking = ref(false);

function q() {
  return questions.value[current.value];
}

async function load() {
  loading.value = true;
  error.value = "";
  picked.value = {};
  results.value = {};
  current.value = 0;
  try {
    const data = wrongPool({
      subject: subjectFilter.value,
      offset: offset.value,
      limit: pageSize,
    });
    questions.value = data.questions;
    total.value = data.total;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
    questions.value = [];
    total.value = 0;
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
  if (current.value < questions.value.length - 1) current.value += 1;
}

function prev() {
  if (current.value > 0) current.value -= 1;
}

function finished() {
  return questions.value.length > 0 && Object.keys(results.value).length === questions.value.length;
}

onMounted(load);
</script>

<template>
  <section class="wrong">
    <div class="bar">
      <span class="count">错题 {{ total }} 道</span>
      <select v-model="subjectFilter" @change="offset = 0; load()">
        <option :value="null">全部科目</option>
        <option v-for="s in SUBJECTS" :key="s.id" :value="s.id">
          {{ s.label }}
        </option>
      </select>
    </div>

    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="loading" class="hint">加载中…</div>
    <div v-else-if="total === 0" class="hint">暂无错题，继续答题吧</div>

    <div v-else class="session">
      <div class="progress">
        第 {{ current + 1 }} / {{ questions.length }} 题（剩余错题 {{ total }}）
        <span v-if="q().subject != null" class="subject-tag">
          {{ subjectLabel(q().subject) }}
        </span>
      </div>
      <p class="question">{{ q().question_text }}</p>
      <p v-if="q().source_url" class="origin">
        原题链接：
        <a :href="q().source_url" target="_blank" rel="noopener">{{ q().source_url }}</a>
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
        <button v-if="current < questions.length - 1" @click="next">下一题</button>
        <button v-else-if="finished()" @click="offset = 0; load()">再来一组</button>
      </div>
      <div class="pager">
        <button :disabled="offset === 0" @click="offset -= pageSize; load()">上一页</button>
        <span>{{ offset / pageSize + 1 }} / {{ Math.max(1, Math.ceil(total / pageSize)) }} 页</span>
        <button :disabled="offset + pageSize >= total" @click="offset += pageSize; load()">下一页</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.bar select { min-height: 36px; }
.count { color: var(--muted); }
.error { color: var(--bad); }
.hint { color: var(--muted); padding: 24px 0; text-align: center; }
.progress {
  color: var(--muted);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
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
.pager { display: flex; gap: 12px; margin-top: 12px; align-items: center; color: var(--muted); flex-wrap: wrap; }
.pager button { flex: 1; min-width: 0; }

@media (max-width: 768px) {
  .bar select { min-height: 44px; }
  .question { font-size: 16px; }
  .nav button, .pager button { min-height: 44px; padding: 4px 18px; }
  .options button { min-height: 48px; padding: 12px 14px; font-size: 15px; }
  .multi-confirm button { min-height: 44px; }
}

@media (max-width: 360px) {
  .question { font-size: 15px; }
  .options button { padding: 10px 12px; font-size: 14px; }
}
</style>
