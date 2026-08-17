<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../api";
import type { Source, Stats } from "../types";

const emit = defineEmits<{ changed: [] }>();

const sources = ref<Source[]>([]);
const url = ref("");
const busy = ref(false);
const error = ref("");
const notice = ref("");
const stats = ref<Stats | null>(null);
const intervals = ref<Record<number, number>>({});

const STATUS_LABEL: Record<string, string> = {
  pending: "待分析",
  analyzing: "分析中",
  ready: "就绪",
  failed: "失败",
};

async function load() {
  try {
    const data = await api.sources();
    sources.value = data.sources;
    for (const s of data.sources) intervals.value[s.id] = s.refresh_interval_seconds;
    stats.value = await api.stats();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function add() {
  const target = url.value.trim();
  if (!target) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const result = await api.addSource(target);
    if (!result.ok) {
      error.value = `${result.reason}（信号：${result.signals.join("、") || "无"}）`;
    } else {
      notice.value = `抓取完成：发现 ${result.questions_found} 道题`;
    }
    url.value = "";
    await load();
    emit("changed");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

async function refresh(id: number) {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const result = await api.refreshSource(id);
    const parts = [`新收录 ${result.questions_inserted} 题`];
    if (result.questions_deduped > 0) {
      parts.push(`去重合并 ${result.questions_deduped} 题`);
    }
    if (result.questions_updated > 0) {
      parts.push(`更新 ${result.questions_updated} 题`);
    }
    notice.value = result.ok
      ? `刷新完成：${parts.join("，")}`
      : `刷新失败：${result.reason}`;
    await load();
    emit("changed");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

async function remove(id: number) {
  if (!window.confirm("确认删除该抓取源及其全部题目？")) return;
  busy.value = true;
  try {
    await api.deleteSource(id);
    await load();
    emit("changed");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

const INTERVAL_HOURS = [1, 6, 24, 168];

function fmtInterval(seconds: number): string {
  if (!seconds) return "不自动刷新";
  return seconds % 86400 === 0
    ? `${seconds / 86400} 天`
    : `${seconds / 3600} 小时`;
}

async function setInterval(id: number, seconds: number) {
  busy.value = true;
  error.value = "";
  try {
    await api.setSourceInterval(id, seconds);
    intervals.value[id] = seconds;
    notice.value = `刷新周期设为 ${fmtInterval(seconds)}`;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

async function refreshDue() {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const result = await api.refreshDue();
    notice.value =
      result.due === 0
        ? "没有到期需要刷新的抓取源"
        : `刷新了 ${result.due} 个到期源，新收录 ${result.results.reduce(
            (n, r) => n + r.questions_inserted,
            0,
          )} 题`;
    await load();
    emit("changed");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="sources">
    <div class="stats" v-if="stats">
      <span>题目 <b>{{ stats.questions }}</b></span>
      <span>有答案 <b>{{ stats.answered }}</b></span>
      <span>抓取源 <b>{{ stats.sources }}</b></span>
      <span>答题 <b>{{ stats.attempts }}</b> 次</span>
      <span>正确率 <b>{{ stats.accuracy === null ? "—" : Math.round(stats.accuracy * 100) + "%" }}</b></span>
    </div>
    <div class="add">
      <input
        v-model="url"
        type="url"
        placeholder="输入抓取源 URL，例如 https://example.com/kaoshi.html"
        @keyup.enter="add"
      />
      <button :disabled="busy || !url.trim()" @click="add">
        {{ busy ? "处理中…" : "添加并抓取" }}
      </button>
      <button :disabled="busy" @click="refreshDue">刷新到期源</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="notice" class="notice">{{ notice }}</p>

    <table v-if="sources.length">
      <thead>
        <tr>
          <th>URL</th>
          <th>状态</th>
          <th>题目数</th>
          <th>刷新周期</th>
          <th>最近刷新</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="s in sources" :key="s.id">
          <td class="url" data-label="来源">
            {{ s.title || s.url }}
            <small>{{ s.kind }} · {{ s.detail || s.url }}</small>
          </td>
          <td data-label="状态"><span class="badge" :class="s.status">{{ STATUS_LABEL[s.status] || s.status }}</span></td>
          <td data-label="题目数">{{ s.question_count }}</td>
          <td data-label="刷新周期">
            <select
              :value="intervals[s.id] ?? 0"
              :disabled="busy"
              @change="setInterval(s.id, Number(($event.target as HTMLSelectElement).value))"
            >
              <option :value="0">不自动刷新</option>
              <option v-for="h in INTERVAL_HOURS" :key="h" :value="h * 3600">
                {{ h >= 24 ? `${h / 24} 天` : `${h} 小时` }}
              </option>
            </select>
          </td>
          <td data-label="最近刷新">{{ s.last_refresh_at || s.last_analyzed_at || "—" }}</td>
          <td class="actions" data-label="操作">
            <button :disabled="busy" @click="refresh(s.id)">刷新</button>
            <button class="danger" :disabled="busy" @click="remove(s.id)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-else-if="!error && !busy" class="muted">还没有抓取源，先添加一个 URL 吧。</p>
  </section>
</template>

<style scoped>
.add { display: flex; gap: 10px; margin-bottom: 12px; }
.add input { flex: 1; padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px; }
.stats {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel);
  color: var(--muted);
  font-size: 13px;
}
.stats b { color: var(--text); }
.error { color: var(--bad); }
.notice { color: #2e7d32; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); }
.url small { display: block; color: var(--muted); word-break: break-all; }
.badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  background: var(--border);
  color: var(--muted);
}
.badge.ready { background: #e8f5e9; color: #2e7d32; }
.badge.failed { background: #fdecea; color: var(--bad); }
.actions { display: flex; gap: 8px; }
.actions button { padding: 4px 10px; border: 1px solid var(--border); border-radius: 6px; background: var(--panel); cursor: pointer; }
.actions button.danger { color: var(--bad); border-color: var(--bad); }
.muted { color: var(--muted); }

/* ---- 移动端：表格转卡片 ---- */
@media (max-width: 640px) {
  table, thead, tbody, tr, th, td { display: block; }
  thead { display: none; }
  table { font-size: 13px; }
  tr {
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    margin-bottom: 10px;
    background: var(--panel);
  }
  td {
    border-bottom: none;
    padding: 3px 0;
    display: flex;
    gap: 8px;
    align-items: baseline;
  }
  td::before {
    content: attr(data-label);
    flex: none;
    color: var(--muted);
    font-size: 12px;
    min-width: 58px;
  }
  td.actions::before { content: "操作"; }
  td.url::before { content: "来源"; }
  td.actions { flex-wrap: wrap; }
  .actions button { min-height: 38px; padding: 4px 14px; }
  .add { flex-wrap: wrap; }
  .add input { flex: 1 1 100%; min-height: 44px; }
  .add button { min-height: 44px; }
  select { max-width: 100%; }
}
</style>
