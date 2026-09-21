# 道游题库 · 导游证考题题库（Android 客户端）

全国导游资格考试（导游证）考题刷题 App。**纯 Android 原生实现**：Kotlin 2.2 + Jetpack Compose + Material 3，题库离线内置在 APK 中（约 1.98 万题），完全无网络请求、无后端。

> 原 Web 端（Vue SPA）已于 2026-09-20 移除，本仓库收敛为纯 Android 工程。

## 功能特性

- **在线答题**：随机组卷（近三年真题 + 题引力新题补充）、提交判分、答案与解析反馈，科目/来源/年份/真题练习筛选
- **在线笔试模拟**：科目一+二 / 科目三+四 合并卷，单选 90 + 多选 35 + 判断 40（共 165 题，100 分），90 分钟倒计时，题号导航与对错着色，逐题即时判定，结束汇总得分；组卷为近三年真题 60% + 历史真题补齐 40%，避免反复刷到同一批题
- **题目浏览**：分页浏览，按科目/来源/省份/年份/是否有答案过滤，默认只看近三年
- **错题本**：答错的题自动收录，错题列表 + 重练逐题判定；连续答对 5 次自动「毕业」移出
- **答题记录与统计**：历史记录（最新优先，最近 500 条）、正确率统计
- **离线可用**：题库随 APK 分发，无任何网络依赖

## 技术栈

| 层 | 技术 |
| --- | --- |
| 客户端 | Kotlin 2.2 / Jetpack Compose / Material 3 |
| 序列化 | kotlinx.serialization（JSON） |
| 题库数据 | 静态 JSON 内置为 assets（源文件在仓库根 `data/`，AI 维护） |
| 答题记录 | 应用私有目录 `files/records.json` + `appear.json` |
| 构建 | Gradle（AGP）+ JDK 21 / Android SDK |

## 目录结构

```
├── android/                  # ★ Android 工程（Gradle 根，app 模块在其中）
│   └── app/src/main/java/com/daoyou/tiku/
│       ├── data/             # QuestionRepository（assets 加载）/ Models / RecordsStore（记录持久化）
│       ├── logic/            # Grading 判分 / QuizBuilder 组卷 / ExamEngine 笔试引擎
│       ├── ui/               # 五视图：答题 / 笔试 / 浏览 / 错题 / 历史 + 底部导航
│       └── MainActivity.kt
├── data/                     # ★ 题库 JSON（唯一事实源，AI 直接维护）：manifest / sources / questions_0..4.json
├── scripts/dedup/            # 题库去重管线（Python，数据质量维护，见 AGENTS.md §10）
├── CRAWLER_DATA.md           # 爬虫侧数据定义文档（数据结构 / SQLite schema / 去重 / 分类规则）
├── CRAWLER_PLAN.md           # 爬虫丰富题库的历史计划稿
└── AGENTS.md                 # 仓库指南（构建 / 数据格式 / 判分与组卷约定，AI 编码代理必读）
```

## 构建 APK

前置：JDK 21 + Android SDK（在 `android/local.properties` 写 `sdk.dir=/opt/android-sdk`）。

```bash
cd android
JAVA_HOME=/iCoding/java/jdk-21 ./gradlew assembleDebug
# 产物：android/app/build/outputs/apk/debug/app-debug.apk（约 18.5MB，minSdk 24 / targetSdk 36）
```

构建时 Gradle 任务 `copyQuizData` 会把仓库根 `data/` 的题库 JSON 复制进 `android/app/src/main/assets/data/`（该副本不入 git，唯一事实源始终是 `data/`）。本机构建环境注意事项见 [AGENTS.md](AGENTS.md) §11。

## 数据维护

题库数据文件 `data/*.json` 是唯一事实源，由 AI 直接读取真实文件内容维护（增改题目、修正答案）：

- 题目按科目分文件（`questions_0` = 未分类，`questions_1..4` = 科目一至四），按 `id` 升序
- `answer` 原样保留：判断题存中文（`正确`/`错误`）、多选题存字母串（`ABCD`）
- 加题前对照现有 `question_text` 查重；编辑后更新 `manifest.json` 的统计
- 详细字段规范见 [AGENTS.md](AGENTS.md) §5；多源采集后的去重见 [AGENTS.md](AGENTS.md) §10

## 已知限制

- 答题记录只在本机 App 私有目录：换设备/清除应用数据即丢失；无账号体系
- 题目与答案随 APK 一起分发，反编译可见（本就无脱敏）
- 笔试与随机答题均为本地判分，答案随 assets 内置
