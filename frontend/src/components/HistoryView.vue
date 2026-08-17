<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "../api";
import type { Attempt } from "../types";

const attempts = ref<Attempt[]>([]);
const error = ref("");
const loading = ref(false);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const data = await api.attempts();
    attempts.value = data.attempts;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="history">
    <div class="head">
      <h2>答题记录</h2>
      <button :disabled="loading" @click="load">{{ loading ? "加载中…" : "刷新" }}</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="!loading && !error && attempts.length === 0" class="muted">
      还没有答题记录，去「在线答题」做几道题吧。
    </p>
    <ul v-else class="list">
      <li v-for="a in attempts" :key="a.id" :class="{ wrong: !a.correct }">
        <span class="verdict">{{ a.correct ? "✓" : "✗" }}</span>
        <div class="body">
          <p class="q">{{ a.question_text }}</p>
          <p class="meta">
            你的答案 {{ a.selected }} · 正确答案 {{ a.answer || "未收录" }} ·
            {{ a.created_at }}
          </p>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.head h2 { margin: 0; font-size: 16px; }
.head button { padding: 4px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--panel); cursor: pointer; }
.error { color: var(--bad); }
.muted { color: var(--muted); }
.list { list-style: none; padding: 0; display: grid; gap: 8px; }
.list li {
  display: flex;
  gap: 12px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel);
}
.list li.wrong { border-color: var(--bad); }
.verdict { font-weight: 700; color: #2e7d32; }
.list li.wrong .verdict { color: var(--bad); }
.body { min-width: 0; }
.q { margin: 0 0 4px; line-height: 1.6; overflow-wrap: anywhere; }
.meta { margin: 0; color: var(--muted); font-size: 12px; }

@media (max-width: 640px) {
  .head button { min-height: 40px; padding: 4px 16px; }
  .list li { padding: 10px 10px; }
}
</style>
