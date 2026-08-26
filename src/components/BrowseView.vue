<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { loadSources, queryQuestions } from "../dataStore";
import type { Question, Source } from "../types";
import { SUBJECTS, optionsOf, subjectLabel } from "../types";

const props = defineProps<{ subject?: number | null }>();

const questions = ref<Question[]>([]);
const total = ref(0);
const offset = ref(0);
const limit = 50;
const sourceFilter = ref<number | null>(null);
const subjectFilter = ref<number | null>(props.subject ?? null);
const provinceFilter = ref<string>("");
const answeredFilter = ref<"" | "true" | "false">("");
const yearFilter = ref<number | null>(null);
const PROVINCES = [
  "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
  "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
  "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "内蒙古",
  "广西", "西藏", "宁夏", "新疆", "香港", "澳门", "台湾",
];
const sources = ref<Source[]>([]);
const error = ref("");
const loading = ref(false);

watch(() => props.subject, (v) => {
  subjectFilter.value = v ?? null;
  offset.value = 0;
  load();
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const data = await queryQuestions({
      limit,
      offset: offset.value,
      subject: subjectFilter.value,
      sourceId: sourceFilter.value,
      province: provinceFilter.value || undefined,
      year: yearFilter.value,
      answered: answeredFilter.value,
    });
    questions.value = data.questions;
    total.value = data.total;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

function page(delta: number) {
  const nextOffset = offset.value + delta * limit;
  if (nextOffset < 0 || nextOffset >= total.value) return;
  offset.value = nextOffset;
  load();
}

onMounted(async () => {
  try {
    sources.value = await loadSources();
  } catch {
    sources.value = [];
  }
  load();
});
</script>

<template>
  <section class="browse">
    <div class="filters">
      <span class="count">共 {{ total }} 题</span>
      <select v-model="subjectFilter" @change="offset = 0; load()">
        <option :value="null">全部科目</option>
        <option v-for="s in SUBJECTS" :key="s.id" :value="s.id">
          {{ s.label }}
        </option>
      </select>
      <select v-model="provinceFilter" @change="offset = 0; load()">
        <option value="">全部省份</option>
        <option v-for="p in PROVINCES" :key="p" :value="p">{{ p }}</option>
      </select>
      <select v-model="sourceFilter" @change="offset = 0; load()">
        <option :value="null">全部来源</option>
        <option v-for="s in sources" :key="s.id" :value="s.id">
          {{ s.title || s.url || `来源 ${s.id}` }}
        </option>
      </select>
      <select v-model="answeredFilter" @change="offset = 0; load()">
        <option value="">全部答案</option>
        <option value="true">有答案</option>
        <option value="false">无答案</option>
      </select>
      <label class="year">
        年份
        <input
          type="number"
          v-model.number="yearFilter"
          placeholder="如 2019"
          min="2000"
          max="2100"
          @change="offset = 0; load()"
        />
      </label>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="loading">加载中…</p>

    <article v-for="q in questions" :key="q.id" class="card">
      <p class="qtext">
        <span v-if="q.subject != null" class="subject-chip">{{ subjectLabel(q.subject) }}</span>
        <span v-if="q.province" class="subject-chip">{{ q.province }}</span>
        <span v-if="q.years" class="subject-chip">{{ q.years.split(",").join(" / ") }} 年</span>
      </p>
      <ul class="opts">
        <li v-for="o in optionsOf(q)" :key="o.letter">
          <span class="letter" :class="{ right: q.answer === o.letter }">
            {{ o.letter }}
          </span>
          <span class="opt-text">{{ o.text }}</span>
        </li>
      </ul>
      <p v-if="q.answer" class="ans">答案：{{ q.answer }}</p>
      <p v-else class="ans muted">暂无答案</p>
      <p v-if="q.explanation" class="expl">解析：{{ q.explanation }}</p>
      <p class="src">来源：{{ q.source_url }}</p>
    </article>

    <div v-if="total > limit" class="pager">
      <button :disabled="offset === 0" @click="page(-1)">上一页</button>
      <span>第 {{ offset / limit + 1 }} / {{ Math.ceil(total / limit) }} 页</span>
      <button :disabled="offset + limit >= total" @click="page(1)">下一页</button>
    </div>
  </section>
</template>
<style scoped>
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  margin-bottom: 12px;
}
.filters .count { width: 100%; color: var(--muted); font-size: 13px; }
.filters select,
.filters .year { min-width: 140px; }
.filters .year {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--muted);
}
.filters .year input[type="number"] {
  width: 96px;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  min-height: 36px;
}
.error { color: var(--bad); }
.card {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 12px;
  background: var(--panel);
  overflow-wrap: anywhere;
}
.qtext { margin: 0 0 8px; line-height: 1.7; overflow-wrap: anywhere; }
.subject-chip {
  display: inline-block;
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 9px;
  background: var(--accent, #2f6feb);
  color: #fff;
  margin-right: 8px;
  vertical-align: middle;
}
.opts { list-style: none; padding: 0; margin: 0 0 8px; display: grid; gap: 6px; }
.opts li { display: flex; gap: 8px; align-items: flex-start; }
.letter {
  flex: none;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 1px solid var(--border);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}
.letter.right { background: #e8f5e9; border-color: #2e7d32; color: #2e7d32; }
.opt-text { flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; }
.ans { margin: 4px 0; font-weight: 600; }
.ans.muted { color: var(--muted); font-weight: 400; }
.expl { color: var(--muted); margin: 4px 0; overflow-wrap: anywhere; }
.src { color: var(--muted); font-size: 12px; margin: 6px 0 0; word-break: break-all; }
.pager { display: flex; gap: 16px; align-items: center; justify-content: center; flex-wrap: wrap; }

/* 平板/小桌面：筛选条更紧凑 */
@media (max-width: 1024px) {
  .filters select, .filters .year { min-width: 120px; }
}

/* 移动端主适配：5 控件两列网格，count 独占一行 */
@media (max-width: 768px) {
  .filters {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  .filters .count { grid-column: 1 / -1; }
  .filters select,
  .filters .year { width: 100%; min-width: 0; }
  .filters .year { flex-direction: column; align-items: stretch; }
  .filters .year input[type="number"] { width: 100%; }
  .card { padding: 12px 12px; }
  .qtext { font-size: 15px; }
  .pager button { min-height: 44px; padding: 6px 16px; flex: 1; }
}

/* 超窄屏：单列 */
@media (max-width: 360px) {
  .filters { grid-template-columns: 1fr; }
  .qtext { font-size: 14px; }
  .card { padding: 10px 10px; }
}
</style>
