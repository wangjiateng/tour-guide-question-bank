# 道游题库 · 导游证考题题库

全国导游资格考试（导游证）考题在线刷题站。**纯静态前端 SPA**：Vue 3 + TypeScript + Vite，无后端服务；题目以静态 JSON 随仓库分发，答题记录存浏览器 localStorage。

## 功能特性

- **在线答题**：随机组卷、提交判分、答案与解析反馈、科目/来源/年份筛选
- **题目浏览**：分页浏览，按科目/来源/省份/年份/是否有答案过滤
- **错题本**：答错的题自动收录，错题列表 + 重练模式（逐题即时判定、科目过滤、分页）
- **在线笔试模拟**：按真实笔试组卷（科目一+二 / 科目三+四 合并卷），单选 45 + 多选 35 + 判断 40，165 分钟倒计时，题号导航与对错着色，结束汇总得分
- **答题记录与统计**：历史记录、正确率统计（localStorage）
- **移动端适配**：360/414/768 视口响应式

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Vue 3 / TypeScript / Vite / vue-tsc |
| 数据 | 静态 JSON（`public/data/`，AI 维护） |
| 答题记录 | 浏览器 localStorage |

## 目录结构

```
├── src/                  # Vue 源码（App.vue / dataStore.ts / components/）
├── public/data/          # ★ 题库数据（manifest / sources / questions_0..4.json）
├── index.html / package.json / tsconfig.json / vite.config.ts
└── .github/workflows/    # GitHub Pages 自动部署
```

## 本地运行

```bash
npm install
npm run dev        # 开发模式 http://127.0.0.1:5173
npm run build      # 构建到 dist/（vue-tsc 类型检查 + vite）
npm run preview    # 预览构建产物 http://127.0.0.1:4173
```

## 数据维护

题库数据文件 `public/data/*.json` 是唯一事实源，由 AI 直接读取真实文件内容维护（增改题目、修正答案）：
- 题目按科目分文件（`questions_0` = 未分类，`questions_1..4` = 科目一至四），按 `id` 升序
- `answer` 原样保留：判断题存中文（`正确/错误`）、多选题存字母串（`ABCD`）
- 加题前对照现有 `question_text` 查重；编辑后更新 `manifest.json` 的统计
- 详细字段规范见 [AGENTS.md](AGENTS.md) §5

## 部署

推送到 GitHub 后由 Actions 自动构建并发布到 GitHub Pages（`https://<user>.github.io/<repo>/`），或把 `dist/` 内容提交到 `gh-pages` 分支手动发布。任何静态服务器均可托管。

## 已知限制

- 答题记录只在本机浏览器（localStorage），换设备/清缓存会丢失
- 题目答案对前端可见（静态分发，无脱敏）
