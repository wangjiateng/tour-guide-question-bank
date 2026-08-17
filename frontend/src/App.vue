<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "./api";
import type { Stats } from "./types";
import { SUBJECTS } from "./types";
import QuizView from "./components/QuizView.vue";
import BrowseView from "./components/BrowseView.vue";
import SourcesView from "./components/SourcesView.vue";
import HistoryView from "./components/HistoryView.vue";
import ExamView from "./components/ExamView.vue";
import WrongView from "./components/WrongView.vue";

type ViewName = "quiz" | "browse" | "sources" | "history" | "exam" | "wrong";

const current = ref<ViewName>("quiz");
const activeSubject = ref<number | null>(null);
const stats = ref<Stats>({ questions: 0, answered: 0, sources: 0, sources_ready: 0, attempts: 0, correct: 0, accuracy: null });

const views: { id: ViewName; label: string }[] = [
  { id: "exam", label: "在线笔试" },
  { id: "quiz", label: "在线答题" },
  { id: "browse", label: "题目浏览" },
  { id: "wrong", label: "错题本" },
  { id: "sources", label: "抓取源管理" },
  { id: "history", label: "答题记录" },
];

async function loadStats() {
  try {
    stats.value = await api.stats();
  } catch {
    stats.value = { questions: 0, answered: 0, sources: 0, sources_ready: 0, attempts: 0, correct: 0, accuracy: null };
  }
}

onMounted(loadStats);
</script>

<template>
  <header>
    <h1>导游证考题题库</h1>
    <nav class="views">
      <button
        v-for="v in views"
        :key="v.id"
        :class="{ active: current === v.id }"
        @click="current = v.id"
      >
        {{ v.label }}
      </button>
    </nav>
    <span class="stats">
      题库 {{ stats.questions }} 题（有答案 {{ stats.answered }}）· 来源
      {{ stats.sources }} 个（可用 {{ stats.sources_ready }}）· 答题
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
    <SourcesView v-else-if="current === 'sources'" @changed="loadStats" />
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
}

h1 { font-size: 20px; margin: 0; }

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

.stats { margin-left: auto; color: var(--muted); font-size: 13px; }

main { max-width: 880px; margin: 24px auto; padding: 0 16px; }

@media (max-width: 640px) {
  header { padding: 10px 12px; gap: 12px; }
  h1 { font-size: 18px; width: 100%; }
  nav.views {
    width: 100%;
    padding-bottom: 4px;
  }
  nav.views button { min-height: 40px; }
  .stats {
    width: 100%;
    margin-left: 0;
    line-height: 1.6;
  }
  main { margin: 16px auto; padding: 0 12px; }
}
</style>
