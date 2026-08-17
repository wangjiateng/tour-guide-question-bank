# 道游题库 · 导游证考题爬虫与答题平台

全国导游资格考试（导游证）考题的自动抓取与在线答题平台。后端全站爬取导游证考题、自动分析抓取源质量，通过 REST API + SQLite 存储；前端为 Vue 3 单页应用，支持在线答题、题目浏览、抓取源管理与答题统计。

## 功能特性

- **抓取源自动分析**：提交 URL 后自动抓取页面，按关键词、题目标记、试题表单等信号打分（`score`/`signals`），判定是否可作为题目来源
- **考题爬取**：内置 HTML / 试卷引擎 / JSON API 三种解析器，抽取题干、A-D 选项、答案与解析
- **抓取源管理**：每个源独立状态（`pending` / `analyzing` / `ready` / `failed`）、题目数、刷新调度（周期可配置，到期自动重抓、去重入库）
- **在线答题**：随机组卷、提交判分、答案与解析反馈、答题历史与正确率统计
- **错题本**：答错的题自动收录，错题列表 + 重练模式（逐题即时判定、科目过滤、分页），可反复刷错题
- **在线笔试模拟**：独立笔试页，按全国导游资格考试真实笔试组卷（科目一+二 合并卷 / 科目三+四 合并卷），单选 45 + 多选 35 + 判断 40，165 分钟倒计时，题号导航与已答标记；**每题选择答案后立即判定对错**并显示正确答案与解析，题号着色（对绿 / 错红），可随时改答重判，结束考试时汇总得分
- **科目分类**：题目按导游资格考试科目一至四分类（政策法规 / 导游业务 / 基础知识 / 地方知识），顶部大类导航 + 答题/浏览页按科目过滤
- **来源过滤**：答题与浏览页可按抓取源筛选题目
- **移动端适配**：响应式布局（导航横向滚动、筛选网格化、抓取源表格转卡片、触控尺寸 ≥44px），手机可直接刷题
- **SQLite 存储**：零配置单文件数据库，外键级联删除

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.11+ / FastAPI / uvicorn / httpx / BeautifulSoup4 + lxml |
| 存储 | SQLite |
| 前端 | Vue 3 / TypeScript / Vite / vue-tsc |
| 测试 | pytest（63 项） |
## 项目结构

```
├── src/daoyou_tiku/
│   ├── main.py       # FastAPI 应用：REST API + 静态前端挂载
│   ├── service.py    # 业务逻辑：抓取、分析、调度、统计
│   ├── crawler.py    # 页面抓取与三种解析器（HTML / 试卷引擎 / JSON API）
│   ├── analyzer.py   # 抓取源自动分析（打分与信号）
│   └── db.py         # SQLite 连接、建表与轻量迁移
├── frontend/
│   ├── src/
│   │   ├── App.vue              # 布局与导航（统计头部 / 6 个视图）
│   │   ├── components/
│   │   │   ├── QuizView.vue     # 在线答题
│   │   │   ├── BrowseView.vue   # 题目浏览
│   │   │   ├── SourcesView.vue  # 抓取源管理（刷新调度配置）
│   │   │   ├── HistoryView.vue  # 答题记录
│   │   │   ├── ExamView.vue     # 在线笔试模拟（题号导航 / 倒计时 / 逐题判定）
│   │   │   └── WrongView.vue    # 错题本（错题列表 / 重练逐题判定）
│   │   ├── api.ts               # REST 客户端
│   │   └── types.ts             # 类型定义
│   └── vite.config.ts           # base=/static/，/api 代理到 127.0.0.1:8000
├── tests/
│   ├── test_api.py              # API 集成测试（含错题本 /api/wrong）
│   ├── test_crawler.py          # 解析器单元测试
│   └── fixture_server.py        # 测试用本地抓取源
└── data/quiz.db                 # SQLite 数据库（运行时生成）
```

## 快速开始

### 环境要求

- Python >= 3.11（建议 [uv](https://docs.astral.sh/uv/) 管理）
- Node.js >= 18

### 1. 启动后端

```bash
uv sync                 # 安装依赖（含 dev 组 pytest）
PYTHONPATH=src .venv/bin/python -m uvicorn daoyou_tiku.main:app \
  --host 0.0.0.0 --port 8000
```

> 注意：项目 `[tool.uv] package = false`，须用 `PYTHONPATH=src` 运行，`.venv/bin/uvicorn` 直启会报 `ModuleNotFoundError`。

首次启动自动创建 `data/quiz.db`（含 `crawl_sources`、`questions`、`answer_attempts` 三张表，旧库自动执行 ALTER 迁移补充调度字段）。

### 2. 构建并访问前端

```bash
cd frontend
npm install
npm run build           # vue-tsc 类型检查 + vite 构建到 frontend/dist
```

构建产物由后端在 `/static` 挂载，浏览器打开 <http://127.0.0.1:8000/> 即可使用。

开发模式（前端热更新，`/api` 代理到后端 8000 端口）：

```bash
cd frontend
npm run dev             # http://127.0.0.1:5173
```

### 3. 运行测试

```bash
.venv/bin/python -m pytest          # 63 passed
```

## REST API

### 抓取源

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/sources` | 列出所有抓取源（含状态、题目数、调度字段） |
| POST | `/api/sources` | 添加源并抓取，body `{"url": "...", "kind": "static_page", "config": {}}`（`kind` 见「多源适配器」） |
| POST | `/api/sources/{id}/refresh` | 立即重新抓取该源（按 URL 去重） |
| DELETE | `/api/sources/{id}` | 删除源及其题目（级联） |
| PUT | `/api/sources/{id}/interval` | 设置刷新周期，body `{"interval_seconds": 3600}`，`0` = 禁用 |
| GET | `/api/sources/due` | 列出到期需刷新的源 |
| POST | `/api/sources/refresh-due` | 批量刷新所有到期源 |

### 题目与答题

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/questions` | 分页浏览题目，支持 `?limit=&offset=&source_id=&subject=&answered=&year=`（`subject` 1-4 按科目过滤；`answered=true/false` 过滤有无答案；`year=2012` 只返回该年份的题）；默认按年份降序（最新优先） |
| GET | `/api/questions/{id}` | 单题详情（`question_text` / `option_a`-`option_d` / `answer` / `explanation` / `subject` / `paper_title` / `years`） |
| GET | `/api/quiz` | 随机组卷，`?size=N` 题目数（默认 10）、`?answered_only=true` 仅抽有答案的题（默认开启）、`?subject=1-4` 按科目、`?source_id=N` 按来源、`?year=2012` 按年份；返回 `{"quiz_id": "...", "question_ids": [...]}` |
| POST | `/api/check?question_id=N` | 判分，body `{"answer": "B"}`；每次答题记录到 `answer_attempts` |
| GET | `/api/stats` | 统计：`questions` 题目总数、`answered` 有答案数、`sources` / `sources_ready` 源总数 / 就绪数、`attempts` / `correct` / `accuracy` 答题次数 / 正确数 / 正确率 |
| GET | `/api/attempts?limit=50` | 答题历史（题目、你的答案、正确答案、时间） |
| GET | `/api/wrong` | 错题本：从 `answer_attempts` 答错记录取题（同题去重，最新答错优先），支持 `?limit=&offset=&subject=&source_id=` 过滤，返回 `{"questions": [...], "total": N}` |

### 笔试模拟

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/exam?paper_type=1|2` | 组卷：`paper_type=1` 科目一+二 合并卷、`2` 科目三+四 合并卷；单选 45 + 多选 35 + 判断 40（判断题量受题库库存上限约束），限时 165 分钟；返回 `paper_id` 与脱敏题目（不含答案） |
| POST | `/api/exam/check` | 单题即时判分，body `{"paper_id": "...", "question_id": N, "answer": "B"}`；返回该题 `correct` 对错、`answer` 正确答案与 `explanation` 解析（多选答案顺序无关）；不消耗试卷，可反复判与改答重判 |
| POST | `/api/exam/submit` | 结束考试汇总判分，body `{"paper_id": "...", "answers": [{"question_id": N, "answer": "B"}]}`；按 `paper_id` 对同一张卷判分，返回总分 `total_score` / 满分 `full_score`、各题型得分 `type_stats` 与逐题 `details`（对错/正确答案/解析）；同一 `paper_id` 只可提交一次（重复提交 404） |

分值：单选 1 分、多选 1 分、判断 0.5 分（满分配比卷为 100 分；科目一+二卷因判断题库存仅 21 道，实际满分 90.5）。判分多选答案顺序无关（`AC` 与 `CA` 等价）。逐题判定模式（`/api/exam/check`）选题即判、可改答重判，结束考试（`/api/exam/submit`）按当前已答汇总计分，未答题按 0 分。

## 抓取源用法示例

### 1. 添加抓取源并抓取

```bash
curl -X POST http://127.0.0.1:8000/api/sources \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/daoyou/shiti.html", "kind": "static_page", "config": {}}'
```

响应示例：

```json
{
  "url": "https://example.com/daoyou/shiti.html",
  "source_id": 7,
  "ok": true,
  "kind": "static_page",
  "reason": "crawled 25 questions across 1 page(s)",
  "questions_found": 25,
  "questions_inserted": 25,
  "questions_updated": 0,
  "pages_fetched": 1
}
```

- `ok=false`：抓取失败（网络/HTTP 状态非 2xx、JSON 解析失败或未知 `kind`），`reason` 说明原因
- `ok=true`：题目入库；`questions_inserted` 新增数、`questions_updated` 答案/解析变更数、`pages_fetched` 抓取页数
- `url` 支持 `http(s)://` 与内置 `fixture://` 源

### 2. 立即刷新某个源

```bash
curl -X POST http://127.0.0.1:8000/api/sources/1/refresh
# {"ok": true, "url": "...", "questions_found": 25, "questions_inserted": 0, "questions_updated": 1}
```

按双路径去重入库：先按 `question_text` 精确匹配（同一道题在多份试卷/多个来源出现时只存一条），未命中再按 `norm_text` 规范化指纹匹配——`normalize_question_text` 统一全角/半角、标点族（`（）`→`()`、`。`→`.`、`、`→`,`、`：`→`:` 等）、空白（含全角空格）与题号前缀，跨平台相似题目（全角/半角差异、题号差异、括号空格差异）合并为一条。响应 `questions_inserted` 为新增题数；`questions_updated` 为精确文本命中且源侧答案/解析/选项有变的更新数；`questions_deduped` 为跨平台规范化命中、合并到已有行的数量（答案/选项以最新抓取为准，`source_url` 保留首见链接）。

### 3. 设置刷新周期（0 = 禁用）

```bash
curl -X PUT http://127.0.0.1:8000/api/sources/1/interval \
  -H 'Content-Type: application/json' \
  -d '{"interval_seconds": 21600}'
```

### 4. 查看到期源并批量刷新

```bash
curl http://127.0.0.1:8000/api/sources/due
curl -X POST http://127.0.0.1:8000/api/sources/refresh-due
```

### 5. 删除源（级联删除其题目）

```bash
curl -X DELETE http://127.0.0.1:8000/api/sources/1
```

前端「抓取源管理」页（`SourcesView.vue`）封装了以上全部操作：添加、立即刷新、周期下拉（不自动 / 1h / 6h / 24h / 7d）与「刷新到期源」。

### 6. 全量抓取考试酷导游资格题库

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
from daoyou_tiku import examcoo

SUBCATEGORIES = {  # 子类目 ID → 名称
    "408": "导游业务", "409": "导游基础知识", "411": "外语",
    "413": "规范服务", "414": "应变能力",
}
for kid, name in SUBCATEGORIES.items():
    papers = examcoo.crawl_subcategory(kid)   # 逐卷抓取（每试卷 0.3s 延迟）
    print(name, kid, "试卷", len(papers), "道题",
          sum(len(p.questions) for p in papers))
PY
```

- 子类目：408 导游业务、409 导游基础知识、411 外语、413 规范服务、414 应变能力（共 236 份试卷，去重后入库 11,311 题）- 每题 `source_url` 指向考试酷原题查看页 `/editor/do/view/id/{pid}`，前端答题页可直接跳转核对原卷
- 去重按双路径：`question_text` 精确唯一 + `norm_text` 规范化指纹唯一（全角/半角、标点族、题号前缀、括号空格差异跨源合并）；重复试卷题目只保留一条（答案/选项以最新为准，链接保留首见，`years` 合并多个出现年份）

## 多源适配器

抓取逻辑按「适配器」组织（`src/daoyou_tiku/adapters.py`）：每个适配器封装一种稳定的取题方式（如何抓取、如何分页、如何归一化题目），由 `crawl_sources.kind` 选择，`config`（JSON，存于 `crawl_sources.config`）保存该源专属参数。同步管线（增量、去重、答案更新）与调度对适配器透明。

| kind | 适配器 | 适用 | config 关键参数 |
| --- | --- | --- | --- |
| `static_page` | `StaticPageAdapter` | 单页静态 HTML 题目页（A-D 选项 + 答案标记） | 无 |
| `json_api` | `JsonApiAdapter` | 返回 JSON 题目数组的分页接口 | `page_size`（默认 100）、`page_param`/`offset_param`（分页参数名，二选一）、`data_path`（题目列表的字段路径，如 `data.list`）、`total_path`/`has_more_path`（续页判定） |
| `fixture` | `FixtureAdapter` | 内置演示题库（6 道导游基础题，离线可用） | 无 |
| `examcoo` | `ExamcooAdapter` | 考试酷（examcoo.com）逐试卷抓取：列子类目试卷列表 → 逐卷解析题目（`source_url` 指向原题查看页） | `subcategory_id`（考试酷子类目 ID）、`subcategory_name` |

- 新增源类型：继承 `SourceAdapter` 实现 `fetch_page(page) -> FetchResult`，注册进 `ADAPTERS` 即可；其余管线零改动
- `json_api` 每页请求：`page` 从 1 递增（或 `offset` 按 `page_size` 步进），直到 `has_more=false`/达到 `total`/返回不足一页；单源抓取页数上限 100 页防失控
- 分页用 `httpx` 流式请求，单页正文上限 3 MiB

## 解析器选择与判定

解析器是适配器的底层组件（`crawler.py`）：`StaticPageAdapter`/`JsonApiAdapter` 抓回正文后，按页面指纹选择解析策略归一化题目；`analyzer.py` 的 `analyze_source` 仍可用于人工审核候选源（信号打分）。

| 判定 | 条件 | 结果 |
| --- | --- | --- |
| 关键词命中 | 标题/正文含「导游」「导游证」「试题」等（`GUIDE_KEYWORDS`） | +2 / 个 |
| 题目标记 | 行首 `A.`-`D.` 选项、`单选/多选/判断`、`参考答案/答案:` 等（`QUESTION_MARKERS`） | +3（只计一次） |
| 试卷表单 | 页面含 `<form>` + `radio` 输入 | +4，解析器选 `quiz_engine` |
| 可用性 | `score >= 3` | 源判定 `ready`，进入解析 |

解析策略（由源指纹选择）：

| 策略 | 适用页面 | 说明 |
| --- | --- | --- |
| `html` | 纯文本/静态页面，题干与 `A.`-`D.` 选项同块或相邻块 | 文档序组装题目单元；答案标记（`参考答案/答案/正确答案`）与解析（`解析/解释`）可选 |
| `quiz_engine` | `<form>` + radio 试卷引擎页 | 答案可能内嵌页面 JS（`window.answerKey`）或缺失 |
| `json_api` | 返回 JSON 题目数组的接口 | 识别常见字段名 |

入库前提：题目非空且至少两个选项；无答案的题仍入库（`answer=None`，前端标记「未知」）。

## 抓取源调度

调度是**拉取式**的：系统不常驻后台定时器，到期与否由查询判定，刷新由外部调用触发（API 或前端按钮）。

- 添加源时首次抓取即记为一次刷新（`last_refresh_at`）
- 周期 `0` 表示禁用自动刷新
- `GET /api/sources/due` 判定条件：`refresh_interval_seconds > 0` 且状态为 `ready` / `failed`，且 `last_refresh_at` 距今超过周期（`last_refresh_at <= now - interval`；从未刷新过也视为到期）
- 周期单位统一为秒，前端下拉（不自动 / 1h / 6h / 24h / 7d）映射为 `0 / 3600 / 21600 / 86400 / 604800`

需要无人值守定时刷新时，由外部调度器（cron / systemd timer）周期调用 `POST /api/sources/refresh-due` 即可，例如每小时一次：

```cron
0 * * * * curl -s -X POST http://127.0.0.1:8000/api/sources/refresh-due
```

## 数据库

| 表 | 说明 |
| --- | --- |
| `crawl_sources` | 抓取源：URL、标题、类型、状态、题目数、刷新周期、最近刷新时间 |
| `questions` | 题目：题干、A-D 选项、答案、解析、来源、科目（1-4）、`paper_title`（抓取时记录的试卷标题）、`paper_subject`（试卷标题解析的科目）、`years`（该题出现过的考试年份，同题多卷合并如 `"2011,2012"`）、`q_type`（1 单选 / 2 多选 / 3 判断，抓取时按源题型字段写入，存量按答案特征回填）、`norm_text`（规范化指纹，跨平台去重键：全角/半角、标点族、题号前缀、括号空格归一，`UNIQUE` 约束） |
| `answer_attempts` | 答题记录：题目、所选答案、是否正确、时间（答错记录即错题本数据源） |

## 已知边界

- 抓取仅面向公开静态页面与可解析的 JSON API；需要登录或反爬的站点不在支持范围
- 题目去重基于双唯一约束：`question_text` 精确 + `norm_text` 规范化指纹（`normalize_question_text` 统一全角/半角、标点族 `（）`→`()`、`。`→`.`、`、`→`,`、`：`→`:`、`【】`→`[]`、空白含全角空格、题号前缀、括号内空白；同一题干跨源只存一条，答案/选项以最新抓取为准，`source_url` 与 `paper_title` 保留首见，`years` 合并多个出现年份；存量库迁移时自动合并历史跨平台变体并重定向 `answer_attempts`）
- 答题统计（正确率）来自真实答题历史，尚无答题时为 `null`
- 已接入考试酷导游资格题库 4 个子类目（408 导游业务 / 409 导游基础知识 / 413 规范服务 / 414 应变能力），全量抓取后入库 **11,311 题**（跨平台去重合并 537 条历史变体后；100% 有答案，`source_url` 指向考试酷原题查看页）；抓取依赖考试酷 `getexercisecontent` 接口（页面内嵌 `leid`+`vp4tokenleid`），纯 HTTP 无需浏览器
- **科目分类来自抓取时的试卷真实标题**（列表页 `<td title>` 与 RPC 试卷元信息），不再事后关键词猜题：书名号内科目（《导游业务》→科目二、《基础知识》→科目三、《地方…》→科目四、《…法规/政策》→科目一）→ 标题关键词 → 源级映射；科目一+科目二混合卷按题目内容逐题细分（法规题→科目一、业务操作题→科目二，未命中默认科目一）
- **外语内容整体排除**：411 子类目（导游外语）为纯英文题，抓取层 `EXCLUDED_SUBCATEGORIES={"411"}` 直接跳过 + 标题含 `英语/外语/英文/English` 的试卷跳过（双保险），已从库中删除 15 题英文题；中文题含英文缩写（VIP、F.I.T. 等）不属于外语，正常保留
- 年份：题目从试卷标题提取考试年份存入 `years`，同一题出现在多份不同年份试卷时年份合并（11,338 题有年份，840 题多年份）；API 默认按年份降序（最新优先）并支持 `?year=` 过滤；考试酷源真题集中在 2003-2014，最新为 2019 年 3 卷（409 源）
- **题干 HTML 实体清洗**：抓取时 `_clean` 用 `html.unescape` 解码题干/选项/解析中的 `&nbsp;`、`&lt;`/`&gt;`、`&quot;` 等实体为普通文本；存量库同步清洗并合并了 `&nbsp;` 掩盖的跨试卷重复题（276 条合并 years 后删除）、剔除 1 条题干仅实体无可恢复内容的脏题
- **笔试模拟的判断题库存受限**：科目一+二（法规+业务）判断题仅 21 道，该卷实际 101 题（单选 45 + 多选 35 + 判断 21），满分 90.5；科目三+四卷为完整 120 题 / 100 分。题库判断题总量 138 道，如需补足卷一并开放判断题源可补充
- **题干以普通文本存储**：考试酷源文本中的 `&nbsp;` 等 HTML 实体已在入库与存量清洗时解码，前端渲染与 API 返回均为干净文本
- `crawl_sources` 增列 `config` 由启动时轻量迁移补上（`ALTER TABLE ... ADD COLUMN`），旧库无需重建
