<script setup lang="ts">
import { onMounted, ref } from "vue";
import { stats as loadStatsData } from "./dataStore";
import type { Stats } from "./types";
import { SUBJECTS } from "./types";
import QuizView from "./components/QuizView.vue";
import BrowseView from "./components/BrowseView.vue";
import HistoryView from "./components/HistoryView.vue";
import ExamView from "./components/ExamView.vue";
import WrongView from "./components/WrongView.vue";

type ViewName = "quiz" | "browse" | "history" | "exam" | "wrong";

const VIEW_IDS = ["quiz", "browse", "history", "exam", "wrong"] as const;

function viewFromHash(): ViewName {
  const id = window.location.hash.replace(/^#\/?/, "");
  return (VIEW_IDS as readonly string[]).includes(id) ? (id as ViewName) : "quiz";
}

const current = ref<ViewName>(viewFromHash());
const activeSubject = ref<number | null>(null);
const stats = ref<Stats>({ questions: 0, answered: 0, sources: 0, attempts: 0, correct: 0, accuracy: null });

const views: { id: ViewName; label: string }[] = [
  { id: "exam", label: "在线笔试" },
  { id: "quiz", label: "在线答题" },
  { id: "browse", label: "题目浏览" },
  { id: "wrong", label: "错题本" },
  { id: "history", label: "答题记录" },
];

function selectView(id: ViewName) {
  current.value = id;
  const hash = `#/${id}`;
  if (window.location.hash !== hash) {
    window.location.hash = hash;
  }
}

function onHashChange() {
  current.value = viewFromHash();
}

async function loadStats() {
  try {
    stats.value = await loadStatsData();
  } catch {
    stats.value = { questions: 0, answered: 0, sources: 0, attempts: 0, correct: 0, accuracy: null };
  }
}

onMounted(() => {
  loadStats();
  window.addEventListener("hashchange", onHashChange);
});
</script>

<template>
  <header>
    <h1>导游证考题题库</h1>
    <nav class="views">
      <button
        v-for="v in views"
        :key="v.id"
        :class="{ active: current === v.id }"
        @click="selectView(v.id)"
      >
        {{ v.label }}
      </button>
    </nav>
    <span class="stats">
      题库 {{ stats.questions }} 题（有答案 {{ stats.answered }}）· 来源
      {{ stats.sources }} 个 · 答题
      {{ stats.attempts }} 次{{ stats.accuracy === null ? "" : `（正确率 ${Math.round(stats.accuracy * 100)}%）` }}
    </span>
  </header>

  <nav class="subjects">
    <button
      :class="{ active: activeSubject === null }"
      @click="activeSubject = null"
    >
      全部科目
    </button>
    <button
      v-for="s in SUBJECTS"
      :key="s.id"
      :class="{ active: activeSubject === s.id }"
      @click="activeSubject = s.id"
    >
      {{ s.label }}
    </button>
  </nav>

  <main>
    <ExamView v-if="current === 'exam'" />
    <QuizView v-else-if="current === 'quiz'" :subject="activeSubject" @done="loadStats" />
    <BrowseView v-else-if="current === 'browse'" :subject="activeSubject" />
    <WrongView v-else-if="current === 'wrong'" :subject="activeSubject" @done="loadStats" />
    <HistoryView v-else />
  </main>
</template>

<style scoped>
header {
  background: var(--panel);
  border-bottom: 1px solid var(--border);
  padding: 12px 24px;
  display: flex;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
  position: sticky;
  top: 0;
  z-index: 10;
}

h1 { font-size: 20px; margin: 0; flex: none; }

nav { display: flex; gap: 8px; }

nav.views {
  flex: 1 1 auto;
  min-width: 0;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}

nav.views::-webkit-scrollbar { display: none; }

nav.views button {
  flex: none;
  white-space: nowrap;
}

nav button {
  border: 1px solid var(--border);
  background: var(--panel);
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}

nav button.active {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

.subjects {
  background: var(--panel);
  border-bottom: 1px solid var(--border);
  padding: 8px 24px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  position: sticky;
  top: var(--header-height, 64px);
  z-index: 9;
}

.subjects button {
  border: 1px solid var(--border);
  background: transparent;
  padding: 4px 14px;
  border-radius: 14px;
  cursor: pointer;
  font-size: 13px;
  color: var(--muted);
}

.subjects button.active {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}

.stats {
  margin-left: auto;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.5;
}

main { max-width: 880px; margin: 24px auto; padding: 0 16px; }

/* 平板/小桌面 */
@media (max-width: 1024px) {
  main { max-width: 100%; }
}

/* 移动端主适配 */
@media (max-width: 768px) {
  header {
    padding: 8px 10px;
    gap: 8px;
    flex-direction: column;
    align-items: stretch;
  }
  h1 { font-size: 17px; width: 100%; }
  nav.views {
    width: 100%;
    padding-bottom: 4px;
  }
  nav.views button { min-height: 40px; padding: 6px 12px; }
  .subjects { padding: 6px 10px; top: 0; }
  .subjects button { min-height: 40px; padding: 4px 12px; }
  .stats {
    width: 100%;
    margin-left: 0;
    line-height: 1.5;
    font-size: 12px;
  }
  main { margin: 12px auto; padding: 0 10px; }
}

/* 小屏手机 */
@media (max-width: 480px) {
  header { padding: 6px 8px; }
  h1 { font-size: 16px; }
  .stats { font-size: 11px; }
  main { padding: 0 8px; }
}

/* 超窄屏 */
@media (max-width: 360px) {
  h1 { font-size: 15px; }
  nav.views button, .subjects button { font-size: 12px; padding: 4px 10px; }
}
</style>
