---
name: daoyou-tiku 仓库指南
description: 纯静态 Vue 3 导游题库 SPA：构建命令、数据 JSON 格式、判分规则、Git 约定、禁止事项与部署；AI 编码代理必读
---

# AGENTS Guidelines for This Repository

道游题库（daoyou-tiku）：全国导游资格考试考题题库，**纯静态前端 SPA**（无后端、无爬虫脚本）。
Vue 3 + TypeScript + Vite，题目数据在 `public/data/*.json`（随仓库分发），由 **AI 直接维护**；
答题记录/错题本/历史存浏览器 localStorage。唯一入库脚本是 `scripts/dedup/` 去重工具（数据质量维护，见 §11）。

## 1. Architecture（重要，先读）

```
public/data/*.json（题库 JSON：AI 直接读取真实文件内容维护，格式见 §5）
  → src/dataStore.ts（懒加载 JSON + localStorage 答题记录 + 本地判分）
  → Vue 组件（5 视图）
  → npm run build → dist/（任意静态服务器 / GitHub Pages 部署）
```

- **无后端服务**：不依赖任何 Python / 服务端代码；`vite base: "./"` 相对路径 + hash 路由，任意子路径可部署
- 数据文件是**唯一事实源**：AI 增改题目时直接编辑 JSON（先读真实文件内容），采集脚本已全部移除
- 答题记录/错题本/历史/统计存 `localStorage`（键 `daoyou_tiku_attempts_v1`）：**只在本机浏览器**，换设备/清缓存会丢
- 判断题 answer 存中文（`正确/错误`），多选题存字母串（`ABCD`）；判分时前端映射（见 §4 判分规则）

## 2. Build & Run

环境：Node.js >= 18。技术栈：Vue ^3.5 / Vite ^6 / TypeScript ~5.7 / vue-tsc ^2.2（见 package.json）。

```bash
npm install
npm run build           # vue-tsc 类型检查 + vite 构建到 dist/
npm run dev             # 开发模式 http://127.0.0.1:5173
npm run preview         # 预览构建产物 http://127.0.0.1:4173
```

- **前端任何改动**：`npm run build` 全绿才算通过（vue-tsc + vite 双关卡）
- `public/data/` 由 vite 原样复制进 `dist/data/`
- 无前端测试框架：验证关卡即 `npm run build`（vue-tsc 类型检查 + vite 构建）

## 3. Project Structure

```
├── src/
│   ├── App.vue              # 布局与导航（hash 路由 + 统计头部），5 视图
│   ├── dataStore.ts         # ★ 数据层：JSON 懒加载 / 判分 / 组卷 / localStorage
│   ├── types.ts             # 类型定义 + 科目/题型常量与工具函数
│   ├── style.css            # 全局样式（含移动端 360/414/768 断点）
│   └── components/
│       ├── QuizView.vue     # 在线答题
│       ├── BrowseView.vue   # 题目浏览（分页 + 科目/来源/省份/年份/已答过滤）
│       ├── HistoryView.vue  # 答题记录（localStorage）
│       ├── ExamView.vue     # 在线笔试模拟（题号导航 / 倒计时 / 逐题判定）
│       └── WrongView.vue    # 错题本（错题列表 / 重练逐题判定）
├── public/data/             # ★ 静态题库（入库，AI 维护）：manifest / sources / questions_0..4.json
├── CRAWLER_DATA.md          # 爬虫侧数据定义文档（数据结构 / SQLite schema / 去重 / 分类规则）
├── index.html / package.json / tsconfig.json / vite.config.ts
└── .github/workflows/deploy-pages.yml   # GitHub Pages 部署
```

## 4. 前端数据层（dataStore.ts）

- 加载：`loadManifest()` / `loadSources()` / `loadSubjectQuestions(subject)`（懒加载+并发去重）；`loadSubjects([null,1..4])` 拼多科目
- **持久缓存（组卷慢的解法）**：题目 JSON（全量约 15MB）经 Cache API 持久缓存，键含 `manifest.generated_at` 版本号，题库更新自动失效重下；刷新页面命中缓存秒开，环境不支持时静默降级纯网络。manifest 是版本源必须实时拉取（`cache:false`）；sources/questions 加载前先确保版本号就绪。主源与 jsDelivr CDN 并行竞速取最快，不再串行等超时
- 组卷：`randomQuiz({size, answeredOnly, subject, sourceId, year})`；`queryQuestions({limit, offset, ...filters})`（浏览分页，年份降序）
- 判分：`checkQuestion(q, given)` → `{question_id, correct, answer, explanation}`
- 答题记录：`recordAttempt(q, selected, correct)` 存完整题目快照；`attempts()` 最新优先；`wrongPool({subject, offset, limit})` 错题池（答错去重、最近答错优先，错后答对仍在池）；`stats()` = manifest 静态数 + localStorage 动态数
- 笔试：`examPaper(paperType)`（组卷+内存 session 缓存）→ `examCheck(paperId, qid, answer)` / `examSubmit(paperId, answers)`（同卷只可交一次，提交后 session 移除）

### 判分规则（改前先看）

- 参考答案归一化：判断题中文 `正确/错误` → `A/B`；其余大写
- 多选：答案顺序无关（`AC` ≡ `CA`），判分用排序后比较
- 笔试组卷：paper_type=1 科目一+二、2 科目三+四；题型题量 单选90+多选35+判断40（对齐 2025 官方大纲，库存充足，两卷均完整 165 题）；90 分钟；分值 单选0.5/多选1/判断0.5（满分 100）；**答题默认近三年真题 70% + 题引力新题 30%（`RECENT_RATIO=0.7`，未显式筛选时排除历史老题）；笔试保持只出近三年真题；笔试与随机答题组卷均按历史出现次数平衡（localStorage `daoyou_tiku_exam_appear_v1`，出现少的题优先、抽后计数+1）；浏览未指定年份默认只显示近三年**
- Quiz/错题本判分返回**归一化字母**（判断题显示「参考答案：A」）；笔试单题判分返回**原始存储答案**（判断题显示「正确答案：正确」）——两者行为一致沿用，勿混改

### 前端路由（App.vue）

- hash 路由（`#/exam` 等），非 vue-router；5 视图：`exam / quiz / browse / wrong / history`
- 科目过滤为全局 `activeSubject`（App.vue 层），答题/浏览/错题视图共用

## 5. 数据文件格式（public/data/*.json，AI 维护依据）

> 数据文件是前端唯一事实源。**新增或修改题目时，由 AI 直接读取真实文件内容后按本格式编辑**；
> 没有生成脚本（曾用于迁移的 export_static.py 已随后端一起移除）。
> 爬虫侧的数据定义（SQLite schema / 去重机制 / 分类规则）见 [CRAWLER_DATA.md](./CRAWLER_DATA.md)。

| 文件 | 内容 |
| --- | --- |
| `manifest.json` | `{generated_at, total, answered, sources, per_subject}`（App 头部统计） |
| `sources.json` | `{sources: [{id, url, title, kind, status, question_count, last_refresh_at, created_at}]}`（Quiz/Browse「来源」筛选） |
| `questions_0.json` | 未分类题（subject NULL，fixture） |
| `questions_1..4.json` | 按科目分文件（前端按需懒加载）——**全量题库（2026-09-04 爬虫丰富后约 1.98 万题）** |

> **全量题库 + 爬虫丰富（2026-09-04）**：约 1.98 万题（历年真题 + 无年份练习 + 题引力 tiyinli 专题补充 1700+ 题，重点补强科目四地方知识）。答题默认近三年真题 70% + 题引力新题 30%（`RECENT_RATIO=0.7`），笔试只出近三年真题；浏览未指定年份默认只显示近三年（手动输入年份可看历年/新题）。全库 19760 题全部有答案有解析。全量数据回滚点：git tag `backup_full_18044_20260904`。加新题：对照现有 `question_text` 查重、保持 id 升序、更新 manifest 即可。

题目字段（与 `src/types.ts` 的 `Question` 对齐）：
`id / question_text / option_a..e / answer / explanation / subject / q_type / province / years / is_real_exam / source_id / paper_title / source_url`

- **is_real_exam**：是否真题（true=官方历年真题：daoyouhome/hqwx/101贝考 真题源 42-44/50-56/66 + 考试酷历年卷 60-64；false=练习/模拟/章节/题引力专题 19/21/23/57/58/59/67）。前端答题/浏览可按下拉筛选「真题与练习/仅真题/仅练习」
- **answer 原样保留**：判断题 `正确/错误`、多选字母串 `ABCD`——前端判分时映射，勿在数据侧归一化
- **科目定义**：1 政策与法律法规 / 2 导游业务 / 3 全国导游基础知识 / 4 地方导游基础知识；`q_type`：1 单选 / 2 多选 / 3 判断
- 维护约定：题目按 id 升序、时间戳只写 manifest（`generated_at`）；**加题前对照现有 JSON 的 `question_text` 查重**（JSON 无数据库级 UNIQUE 约束，靠 AI 把关）；编辑后更新 manifest 的 total/per_subject

## 6. Coding Conventions

- 任何改动：`npm run build` 全绿才算通过（vue-tsc 类型检查 + vite 构建）
- Vue 3 `<script setup lang="ts">`，类型集中在 `types.ts`，数据访问走 `dataStore.ts`（不裸 `fetch` 题目文件）
- 领域词汇固定：`subject`（科目 1-4）、`q_type`（1 单选 / 2 多选 / 3 判断）
- 数据文件用 UTF-8 无 BOM、`ensure_ascii=False` 风格（中文可读），编辑时保持

### 移动端适配（历史经验）

- 响应式布局已适配 360/414/768 视口：导航横向滚动、筛选网格化、触控尺寸 ≥44px
- `ExamView.vue` 的 `.qnav` 题号区固定列数 + `max-height` 滚动、`overscroll-behavior:contain` 防链式滚动；`count` 默认收起为「已答 X/N」点击展开
- 改布局后**必须浏览器实测三个视口**（360/414/768），不能只看代码

## 7. Git Workflow（提交与合入）

- 提交信息参照现有风格：`<范围> [类型] 摘要`，类型标签用 `[Feature]` / `[Fix]` / `[Docs]` 等（历史示例：`E2E-Efficiency [Feature] 导游题库全栈实现：…（CR P0）`）
- 未提交的文档/题库改动（如 `CRAWLER_DATA.md`、`public/data/*.json`）随功能一并提交，避免长期遗留工作区
- 部署只在 push `master` 时自动触发（`.github/workflows/deploy-pages.yml`），`develop` 分支不发布

## 8. Boundaries（禁止事项与安全）

- **不引入后端**：仓库定位纯静态 SPA，任何改动不得添加 Python / API / Web 框架等服务端依赖
- **数据文件是唯一事实源**：不创建/保留采集/生成类脚本覆盖 `public/data/*.json`；增改题目直接编辑 JSON（先读真实文件内容，见 §5）。**唯一例外**：`scripts/dedup/` 题库去重工具（数据质量维护，运行方式见 §11），禁止在其外新增任何触碰数据文件的脚本
- **不整文件覆盖数据**：编辑前读真实内容，answer 原样保留（判断题中文、多选字母串）
- **删除未提交的文档/数据文件前先确认**（CRAWLER_DATA.md 曾因清理被误删）
- 判分与 answer 存储约定（§4）是前端强耦合红线，改动前必读
- 安全：题目与答案随静态 JSON 公开分发（本就无脱敏）；答题记录仅存浏览器 localStorage，无账号体系

## 9. Known Limitations（改代码前先看）

- 答题记录只存本机浏览器 localStorage：换设备/清缓存即丢失；无账号体系
- 题目静态 JSON 随前端分发，答案对前端可见（本就无脱敏）；题库更新 = AI 直接编辑数据 JSON → 构建 → 部署
- 年份覆盖 2003-2025（最新为 daoyouhome 真题 2023 40 题 / 2024 80 题 / 2025 138 题）；浏览默认按年份降序
- 笔试两套卷判断题库存均充足（科目一+二 2487 道、科目三+四 2443 道），组卷完整 165 题 / 100 分
- **全量题库 + 爬虫丰富（2026-09-04）**：约 1.98 万题（2026-09-04 从题引力 tiyinli 全站 192 个真题专题抓取解析，新增约 1700 题，重点补强科目四地方知识）；答题默认近三年 70% + 题引力新题 30%（`RECENT_RATIO=0.7`），笔试只出近三年；浏览未指定年份默认只显示近三年；全库全部有答案有解析；全量回滚点 git tag `backup_full_18044_20260904`
- 笔试 session 为内存态（`examSessions` Map）：刷新页面即失效，需重新组卷
- 爬虫代码已全部移除；根目录 `CRAWLER_DATA.md` 保留爬虫侧数据定义作参考（其路径引用 `scripts/`、`frontend/` 为迁移中间态，与当前工作区不一致；若重建采集需同步更新）

## 10. GitHub Pages 部署（静态站点）

- 已配置 `.github/workflows/deploy-pages.yml`：push 到 `master` 或手动触发时，自动 `npm run build` 并把 `dist/` 发布到 GitHub Pages
- **一次性启用**：仓库 Settings → Pages → Source 选 **GitHub Actions**
- 站点地址：`https://<user>.github.io/<repo>/`（vite `base: "./"` 相对路径，子路径部署无需改配置；hash 路由无需服务端回退）
- 也可手动发布：把 `dist/` 内容提交到 `gh-pages` 分支（Pages Source 选 Deploy from a branch）

## 11. Common Operations

```bash
# 本地开发 / 构建 / 预览
npm run dev            # http://127.0.0.1:5173
npm run build          # vue-tsc + vite → dist/
npm run preview        # http://127.0.0.1:4173

# 更新题库（AI 维护）
# 1. 读取 public/data/questions_X.json 真实内容
# 2. 增改题目（对照现有 question_text 查重，保持 id 升序）
# 3. 更新 manifest.json 的 total/per_subject/generated_at
# 4. npm run build → 部署

# 题库去重（多源采集后必跑；四段式，精确优先）
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


## 12. APK 安卓客户端（原生 Kotlin + Compose）

- **纯原生实现**：Kotlin 2.2 + Jetpack Compose + Material 3，工程在 `android/` 目录（2026-09-09 曾短暂使用 Capacitor 壳方案，真机体验不佳，已整体替换为原生）
- **数据离线内置**：Gradle 任务 `copyQuizData` 构建时把 `public/data/`（唯一事实源，AI 直接维护）复制进 assets；副本不入 git（`android/.gitignore` 已排除）；APK 完全离线可用，无网络请求
- **逻辑移植**：`android/app/src/main/java/com/daoyou/tiku/logic/` 判分/组卷严格对齐 web 端 dataStore.ts——判断题中文归一化 A/B、多选无序比较、近三年 70% + 题引力(source_id=67)补充、笔试 90+35+40 题型分值 0.5/1/0.5、组卷出现次数平衡；**判分约定是前后端强耦合红线，两侧改必须同步**
- **原生端增强（web 端无此行为）**：笔试判错的题即收进错题本（答对不记，避免整卷污染答题历史）；组卷 `pickBalanced` 对错题加权（出现次数等效减一，优先抽中重现）；错题毕业机制：最后一次答错后连续答对 5 次（`RecordsStore.GRADUATE_STREAK`）即移出错题本与组卷加权，错题在笔试中答对也单独记录以推进计数；随机答题近三年占比原生端为 50/50（`QuizBuilder.RECENT_RATIO=0.5`），web 端仍 70/30
- **记录持久化**：`data/RecordsStore.kt` 存应用私有 `files/records.json`（答题历史/错题本）与 `appear.json`（组卷计数），替代 web 的 localStorage
- **UI**：`ui/` 五视图（答题/笔试/浏览/错题/历史）+ 底部导航，科目过滤为全局状态
- 一键构建：`npm run apk`（= `cd android && JAVA_HOME=/iCoding/java/jdk-21 ./gradlew assembleDebug`），产物 `android/app/build/outputs/apk/debug/app-debug.apk`（约 18.5MB，minSdk 24 / targetSdk 36）
- 前置：JDK 21（`/iCoding/java/jdk-21`）+ Android SDK（`/opt/android-sdk`，写 `android/local.properties`）；web 版构建 `npm run build` 与原生构建互不影响
- 本机构建环境要点：
  - `JAVA_HOME` 默认指向 Java 8（/iCoding/java/jdk8u242-b08）会弄挂 gradle/sdkmanager，构建前切 JDK 21；sdkmanager 用 JDK 17 且需 `--sdk_root=/opt/android-sdk`
  - Gradle 发行版官方源跳 GitHub 资产超时，wrapper 已改腾讯镜像（`android/gradle/wrapper/gradle-wrapper.properties`）
  - 全局 `~/.gradle/init.gradle` 预设百度内网 Maven 镜像（HTTP 明文，已加 `allowInsecureProtocol = true` 放行）
- **Kotlin 注释嵌套陷阱**：Kotlin 块注释支持嵌套，注释里写 `data/*.json` 这类含 `/*` 序列的文本会导致「Unclosed comment」编译错，注释中避免 `/*` 字符序列
