---
name: daoyou-tiku 仓库指南
description: 纯 Android 导游题库 App：构建命令、题库 JSON 格式、判分与组卷规则、数据维护、Git 约定、禁止事项；AI 编码代理必读
---

# AGENTS Guidelines for This Repository

道游题库（daoyou-tiku）：全国导游资格考试考题题库，**纯 Android 原生 App**（Kotlin + Compose，无后端、无网络请求）。
题库数据在 `data/*.json`（随仓库分发），**由 AI 直接维护**；构建时复制进 APK assets；
答题记录/错题本/历史/组卷计数存应用私有目录文件。唯一入库脚本是 `scripts/dedup/` 去重工具（数据质量维护，见 §10）。

> 原 Web 端（Vue SPA + dataStore.ts + GitHub Pages 部署）已于 2026-09-20 移除，本仓库现为纯 Android 工程。

## 1. Architecture（重要，先读）

```
data/*.json（题库 JSON 唯一事实源：AI 直接读取真实文件内容维护，格式见 §5）
  → copyQuizData（android/app/build.gradle.kts 的 Gradle 任务，构建时复制）
  → android/app/src/main/assets/data/（副本，不入 git；APK 离线内置，无网络请求）
  → data/QuestionRepository.kt（assets 懒加载 + 并发去重）
  → logic/（Grading 判分 / QuizBuilder 组卷 / ExamEngine 笔试）+ data/RecordsStore.kt（记录持久化）
  → ui/（五视图：答题 / 笔试 / 浏览 / 错题 / 历史 + 底部导航）
```

- **纯原生离线**：不依赖任何后端 / 网络；题库随 APK 分发，无请求
- 数据文件是**唯一事实源**：AI 增改题目时直接编辑 JSON（先读真实文件内容）
- 记录持久化：`RecordsStore` 写应用私有目录 `files/records.json`（答题历史 / 错题本）与 `appear.json`（组卷出现计数）——清应用数据即丢，无账号体系
- 判断题 answer 存中文（`正确/错误`），多选题存字母串（`ABCD`）；判分时归一化（见 §4）

## 2. Build & Run

前置：JDK 21 + 本地 Android SDK（`android/local.properties` 的 `sdk.dir` 指向 SDK 路径，该文件不入库）。

```bash
cd android
./gradlew assembleRelease
# 产物：android/app/build/outputs/apk/release/app-release.apk（约 18MB，minSdk 24 / targetSdk 36）

# 其他常用
./gradlew clean                      # 清理构建产物
./gradlew installRelease             # 连真机/模拟器直接安装（adb）
```

- **只打 release 包**：一律 `assembleRelease`。release 走 debug 签名（见 §3 `build.gradle.kts`），可直接安装分发、无调试开销
- **debug 变体已在构建配置层禁用**：`app/build.gradle.kts` 的 `androidComponents { beforeVariants { ... } }` 关掉了 debug，`assembleDebug`/`installDebug` 等 debug 任务根本不会生成（临时需要 debug 包时，注释掉该块即可）
- **任何改动：`assembleRelease` 编译通过才算通过**（Kotlin 编译 + 资源打包 + lintVital 全关卡）
- 本仓库**无单元测试框架**：验证关卡即编译通过 + 真机手动验证（改 UI 布局后必须真机实测）
- 构建时 `copyQuizData` 任务把仓库根 `data/` 复制进 `android/app/src/main/assets/data/`（该副本被 `android/.gitignore` 排除，不入库）

## 3. Project Structure

```
├── android/                      # ★ Gradle 工程根（settings.gradle.kts / gradlew / gradle/ 均在此）
│   └── app/
│       ├── build.gradle.kts      # 含 copyQuizData 任务（data/ → assets）
│       └── src/main/
│           ├── AndroidManifest.xml
│           ├── res/              # strings.xml / themes.xml / drawable
│           └── java/com/daoyou/tiku/
│               ├── MainActivity.kt
│               ├── data/         # Models.kt / QuestionRepository.kt / RecordsStore.kt
│               ├── logic/        # Grading.kt / QuizBuilder.kt / ExamEngine.kt
│               └── ui/           # App.kt / QuizScreen / ExamScreen / BrowseScreen / WrongScreen / HistoryScreen / Common
├── data/                         # ★ 题库 JSON（唯一事实源，AI 维护）：manifest / sources / questions_0..4.json
├── scripts/dedup/                # 题库去重管线（唯一允许入库的脚本，见 §10）
├── CRAWLER_DATA.md               # 爬虫侧数据定义文档（数据结构 / SQLite schema / 去重 / 分类规则）
├── CRAWLER_PLAN.md               # 爬虫丰富题库的历史计划稿
└── AGENTS.md / README.md
```

## 4. 数据层与判分 / 组卷约定（改前先看）

### 数据层（data/）

- `QuestionRepository`：`loadManifest()` / `loadSources()` / `loadSubjectQuestions(subject)`（assets 懒加载 + 并发去重）；`loadSubjects([null,1..4])` 拼多科目
- `RecordsStore`：`recordAttempt` 存完整题目快照；`attempts()` 最新优先；`wrongPool()` 错题池（答错去重、最近答错优先）；`appearCounts()` 组卷出现计数快照 / `bumpAppear` 计数 +1；`wrongIds()` 错题集合（口径与 wrongPool 一致，含毕业判定，**结果按记录版本缓存，改记录时失效**）
- `SessionStore`：**进行中会话**持久化（`files/session_quiz.json` / `files/session_exam.json`），只存**题号序列 + 作答状态**（答题页出全池，存完整题目会每次写数 MB；题号按 id 从内置题库重取即可还原同一套题）。重启后由 `DaoyouApp` 冷启动探测一次并弹**全局**「继续 / 放弃」弹窗（不再依赖进入对应页签；点「继续」自动切到对应页签并下发恢复请求）；笔试倒计时存**绝对截止时间**（墙钟），进程被杀期间照常计时。恢复笔试必须走 `ExamEngine.restoreSession(paperId, paperType, ids)` 重新注入内存 session，否则判分链路（`examCheck`/`examSubmit`）返回 null
- **落盘策略（性能红线）**：活动期靠 **400ms 防抖**在 IO 线程持续写盘，`Activity.onStop` 只调 `requestFlush()`（**异步**，不阻塞主线程）——进程被杀最多丢最近 <0.5s 改动，换掉同步 `runBlocking` 是因为它会在主线程排队等待、代价更大。写盘一律走**临时文件 + 重命名**原子替换（`File.writeTextAtomic`），直接覆盖会在中途失败时留下截断 JSON，而读取侧的容错 `catch` 会**静默清空整个历史**
- **记录加载是异步的**：`RecordsStore.init` 只建文件句柄，历史在 IO 线程解码（记录内嵌完整题目，数千条即 MB 级，同步解码会拖慢冷启动首帧）。加载完成前 `loaded=false`，此时 `doFlush` 不写盘（否则会用残缺列表覆盖磁盘完整历史），`recordAttempt` 的新记录进 `pendingAttempts` 待合并重编号；`loaded` 前的窗口内 `wrongPool`/`wrongIds` 读不到新记录（冷启动瞬间，实际无影响）

### 判分规则（红线，勿混改）

- 参考答案归一化：判断题中文 `正确/错误` → `A/B`；其余大写
- 多选：答案顺序无关（`AC` ≡ `CA`），判分用排序后比较
- **返回口径两套且都已沿用，勿统一**：
  - **答题 / 错题本**（`Grading.checkQuestion` 路径）返回**归一化字母**（判断题显示「参考答案：A」）
  - **笔试单题判分**（`ExamEngine.examCheck`）返回**原始存储答案**（判断题显示「正确答案：正确」）

### 组卷规则

- **随机答题**：近三年真题（2023-2025）50% + 题引力新题（`source_id=67`）等补充 50%（`QuizBuilder.RECENT_RATIO=0.5`）；未显式筛选来源/年份时排除历史老题
- **笔试组卷**：paper_type=1 科目一+二、2 科目三+四；题型题量 单选90+多选35+判断40（对齐 2025 官方大纲，两卷均完整 165 题）；90 分钟；分值 单选0.5/多选1/判断0.5（满分 100）
  - **近三年真题优先 60% + 历史真题补齐 40%**（`ExamEngine.EXAM_RECENT_RATIO=0.6`，补齐池限 `is_real_exam=true` 的非近三年真题；历史真题不足时从近三年补足，保证每卷 165 题完整）
  - 背景：原「只出近三年真题」池子仅 ~413/446 题，4 场考试即刷完导致反复刷到同一批题（2026-09-20 修复）
- **出现次数平衡**：答题与笔试均按历史出现次数平衡抽取（出现少的题优先、抽后计数 +1，`RecordsStore.appearCount` / `bumpAppear`）
- **错题加权（本端增强）**：`QuizBuilder.pickBalanced` 对错题按「出现次数等效 −1」加权，优先抽中重现
- **错题毕业**：最后一次答错后连续答对 `RecordsStore.GRADUATE_STREAK`（5）次即移出错题本与组卷加权
- **作答记录只记答错**（答题页与笔试页一致）：答对不写记录，避免污染答题历史；例外是已在错题本中的题答对也记录一条，用于推进「连续答对 5 次毕业」计数（`README` 口径：错题池 = 答错去重 + 毕业判定）
- **进行中进度持久化**（`SessionStore`）：答题/笔试作答与翻页即防抖落盘（400ms合并），`onStop` 兜底 `flushSync()`；退出练习/完成本轮/交卷/放弃均删快照。恢复时题目按 id 从内置题库重取，**任一题缺失即整体放弃恢复**（题库更新导致 id 变更时宁可重新组卷，避免题号错位判分错乱）
- **笔试错题收集**：笔试判错的题即收进错题本（答对不记）；错题在笔试中答对也单独记录以推进毕业计数
- 浏览未指定年份默认只显示近三年

## 5. 数据文件格式（data/*.json，AI 维护依据）

> 数据文件是**唯一事实源**。**新增或修改题目时，由 AI 直接读取真实文件内容后按本格式编辑**；
> 没有生成脚本（曾用于迁移的 export_static.py 已随后端一起移除）。
> 爬虫侧的数据定义（SQLite schema / 去重机制 / 分类规则）见 [CRAWLER_DATA.md](./CRAWLER_DATA.md)。

| 文件 | 内容 |
| --- | --- |
| `manifest.json` | `{generated_at, total, answered, sources, per_subject}`（App 头部统计 + 题库版本号） |
| `sources.json` | `{sources: [{id, url, title, kind, status, question_count, last_refresh_at, created_at}]}`（来源筛选） |
| `questions_0.json` | 未分类题（subject NULL，fixture） |
| `questions_1..4.json` | 按科目分文件（客户端按需懒加载）——**全量题库（2026-09-04 爬虫丰富后约 1.98 万题）** |

> **全量题库 + 爬虫丰富（2026-09-04）**：约 1.98 万题（历年真题 + 无年份练习 + 题引力 tiyinli 专题补充 1700+ 题，重点补强科目四地方知识）。答题默认近三年真题 50% + 题引力新题 50%；笔试近三年真题 60% + 历史真题补齐 40%；浏览未指定年份默认只显示近三年（手动输入年份可看历年/新题）。全库 19760 题全部有答案有解析。全量数据回滚点：git tag `backup_full_18044_20260904`。加新题：对照现有 `question_text` 查重、保持 id 升序、更新 manifest 即可。

题目字段（与 `android/app/src/main/java/com/daoyou/tiku/data/Models.kt` 的 `Question` 对齐）：
`id / question_text / option_a..e / answer / explanation / subject / q_type / province / years / is_real_exam / source_id / paper_title / source_url`

- **is_real_exam**：是否真题（true=官方历年真题：daoyouhome/hqwx/101贝考 真题源 42-44/50-56/66 + 考试酷历年卷 60-64；false=练习/模拟/章节/题引力专题 19/21/23/57/58/59/67）。客户端答题/浏览可按「真题与练习 / 仅真题 / 仅练习」筛选
- **answer 原样保留**：判断题 `正确/错误`、多选字母串 `ABCD`——判分时映射，勿在数据侧归一化
- **科目定义**：1 政策与法律法规 / 2 导游业务 / 3 全国导游基础知识 / 4 地方导游基础知识；`q_type`：1 单选 / 2 多选 / 3 判断
- `years` 兼容字符串与数组两种写法（`FlexibleYearsSerializer` 归一为逗号分隔串）
- 维护约定：题目按 id 升序、时间戳只写 manifest（`generated_at`）；**加题前对照现有 JSON 的 `question_text` 查重**（JSON 无数据库级 UNIQUE 约束，靠 AI 把关）；编辑后更新 manifest 的 total/per_subject

## 6. Coding Conventions

- 任何改动：`cd android && ./gradlew assembleRelease` 编译通过才算通过（**只保留 release 变体，debug 变体已禁用**）；改 UI 布局后**必须真机实测**（无自动化 UI 测试）
- **主线程红线**：题库过滤/打乱/组卷等 CPU 密集工作必须包 `withContext(Dispatchers.Default)`（`randomQuiz` / `ExamEngine.examPaper` / `ExamEngine.restoreSession` 均已包）；`RecordsStore`/`SessionStore` 的写盘不得同步阻塞主线程
- **组合性能红线**：`pagerState.currentPage` 只能在**叶子组件**内用 `derivedStateOf` 读取，且**不得作为 `LaunchedEffect` 的 key**（`remaining` 曾因作 key 导致每秒失效整棵树含 `HorizontalPager` 的 content lambda）；大 List 不得作为 `remember` 的 key（key 比较会退化成逐元素 `equals`，用 `paperId` 等标量代替）；可滚动的 `LazyColumn` 外层不得再套 `verticalScroll`（嵌套纵向滚动直接抛异常）
- Kotlin + Jetpack Compose（Material 3）；类型集中 `data/Models.kt`，数据访问走 `QuestionRepository`（不裸读 assets）
- 领域词汇固定：`subject`（科目 1-4）、`qType`（1 单选 / 2 多选 / 3 判断，JSON 侧为 `q_type`）
- 数据文件用 UTF-8 无 BOM、`ensure_ascii=False` 风格（中文可读），编辑时保持
- **Kotlin 注释嵌套陷阱**：Kotlin 块注释支持嵌套，注释里写 `data/*.json` 这类含 `/*` 序列的文本会导致「Unclosed comment」编译错，注释中避免 `/*` 字符序列（写 `data/` 或 `assets/data` 代替）

## 7. Git Workflow

- 提交信息参照现有风格：`<范围> [类型] 摘要`，类型标签用 `[Feature]` / `[Fix]` / `[Docs]` 等（历史示例：`E2E-Efficiency [Feature] 导游题库全栈实现：…（CR P0）`、`Android [Feature] 原生安卓客户端：Kotlin + Compose 全量实现`）
- 未提交的文档/题库改动（如 `CRAWLER_DATA.md`、`data/*.json`）随功能一并提交，避免长期遗留工作区
- 无 CI / 无自动部署：APK 由本地 `assembleRelease` 构建后手动分发

## 8. Boundaries（禁止事项与安全）

- **不重新引入 Web/前端**：本仓库定位纯 Android App，不得添加 Vue/React/Node/服务端依赖
- **不引入后端**：无网络请求、无 API、无账号体系
- **数据文件是唯一事实源**：不创建/保留采集/生成类脚本覆盖 `data/*.json`；增改题目直接编辑 JSON（先读真实文件内容，见 §5）。**唯一例外**：`scripts/dedup/` 题库去重工具（运行方式见 §10），禁止在其外新增任何触碰数据文件的脚本
- **不整文件覆盖数据**：编辑前读真实内容，answer 原样保留（判断题中文、多选字母串）
- **删除未提交的文档/数据文件前先确认**（CRAWLER_DATA.md 曾因清理被误删）
- 判分与组卷约定（§4）是强耦合红线，改动前必读
- 安全：题目与答案随 APK 公开分发（本就无脱敏，反编译可见）；答题记录仅存应用私有目录

## 9. Known Limitations（改代码前先看）

- 答题记录只存本机应用私有目录：清应用数据/换设备即丢失；无账号体系
- 题目与答案随 APK 内置分发，反编译可见（本就无脱敏）；题库更新 = 编辑 `data/` JSON → 重新构建 APK
- 年份覆盖 2003-2025，但**近三年（2023-2025）真题池偏小**：卷1 约 413 题 / 卷2 约 446 题；全量真题池 卷1 5272 题 / 卷2 2595 题（笔试 60/40 混合后分别可撑 30+/15+ 场不重复）。卷2 单选/多选的历史真题尤其薄（77/8 题），新题主要靠判断题提供
- 笔试 session 为内存态（`ExamEngine.sessions` Map）：刷新/退出页面即失效，需重新组卷
- 无单元测试与 UI 自动化测试，回归靠手工验证

## 10. Common Operations

```bash
# 构建 / 安装（统一 release 包，不要打 debug）
cd android && ./gradlew assembleRelease   # APK → app/build/outputs/apk/release/
cd android && ./gradlew installRelease    # 直接装到已连接设备

# 更新题库（AI 维护）
# 1. 读取 data/questions_X.json 真实内容
# 2. 增改题目（对照现有 question_text 查重，保持 id 升序）
# 3. 更新 manifest.json 的 total/per_subject/generated_at
# 4. cd android && ./gradlew assembleRelease → 产物分发

# 题库去重（多源采集后必跑；四段式，精确优先；数据目录 = 仓库根 data/）
python3 scripts/dedup/dedup_pipeline.py --dry-run   # 出报告不修改（推荐先跑）
python3 scripts/dedup/dedup_pipeline.py --apply     # 执行并写回
# 四段逻辑：
#   Stage1 三元组精确去重（题干+选项+答案完全一致，含 ocr_fixes.json 词典归一）→ 保留质量最高版本
#   Stage2 模糊自动合并（题干相似度≥0.92 且 选项集/答案一致）→ 合并 years/解析
#   Stage4 语义级去重（题意相同）：先按(题型+答案内容)锚定分组，组内用 TF-IDF 词向量比题干语义。
#          单选/多选 TF-IDF 余弦≥0.70；判断（答案锚点弱）需 TF-IDF≥0.85 且字符相似度≥0.65。
#          精准收紧带（低一档但双信号+选项重叠防误并）：单选/多选 TF-IDF≥0.65 且 字符≥0.65 且 选项重叠≥0.5；
#          判断 字符相似度≥0.88 且 TF-IDF≥0.55。依赖 jieba + numpy（缺失时该阶段自动跳过）
#   Stage3 灰区复核（0.80-0.92）→ reports/gray_zone_review.json；语义漏网候选 → reports/semantic_leak_review.json
# 安全边界：跨题型不合并；questions_0.json（fixture）不参与；数据在 git 可回滚；写盘前自动校验 JSON/id 升序
# 注意：ocr_fixes.json 是去重专用 OCR 错字词典，添加映射会让更多文本判为相同，务必高置信度才加
# 去重率口径：原始采集量（各源抓取原始题量之和）→ 最终题库，整体去重率约 50%
```
