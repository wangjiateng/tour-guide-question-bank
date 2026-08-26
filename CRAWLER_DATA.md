---
name: 爬虫数据定义（CRAWLER-DATA）
description: 爬虫侧数据结构 / SQLite schema / 去重 / 分类规则的权威定义；仅在改动爬虫或数据相关代码时阅读
---

# 爬虫数据定义（CRAWLER-DATA）

面向 AI 编码代理：爬虫管线的**数据结构、SQLite schema、去重/分类规则、导出格式**的权威定义。
与 [AGENTS.md](./AGENTS.md) 配合使用——本文件聚焦 Python 爬虫侧；前端如何消费这些数据（判分规则/数据文件格式）见 AGENTS.md §4/§5。

> 何时读本文件：仅当改动**爬虫或数据相关代码**时阅读；日常前端开发只需 AGENTS.md。

> 改爬虫/数据相关代码前**必读**；触及「红线」的改动（§4 去重、§5 分类顺序）必须跑全量 pytest。

## 1. 数据流概览

```
scripts/crawl.py（CLI 入口，PYTHONPATH=scripts）
  → scripts/crawler/（爬虫包，import 名 crawler）
      adapters.build_adapter(kind) 选适配器（ADAPTERS 注册表）
      _crawl_all：逐页 adapter.fetch_page(page) → FetchResult(questions, has_more)
      _store_questions：ParsedQuestion → 去重入库（question_text + norm_text 双键）
  → data/quiz.db（爬虫工作存储，gitignore）
  → frontend/public/data/*.json（前端唯一数据源，由 AI 直接维护，格式见 §8）
```

- 生产者：适配器产出 `ParsedQuestion`；消费者：`_store_questions`（写库）
- `data/quiz.db` 不是分发物：前端只认 `frontend/public/data/` 下的静态 JSON（AI 直接编辑）

## 2. 核心数据结构

### ParsedQuestion（`scripts/crawler/crawler.py`）—— 适配器产出的单题

```python
@dataclass
class ParsedQuestion:
    question_text: str                       # 题干（必填）
    option_a..option_e: str | None = None    # 选项（A-E）
    answer: str | None = None                # 答案：判断题中文(正确/错误)，多选字母串(ABCD)
    explanation: str = ""                    # 解析
    source_url: str = ""                     # 题目原链接（无则回退到源 URL）
    paper_title: str | None = None           # 试卷标题（科目/省份/年份分类的权威依据）
    q_type: int | None = None                # 1=单选 2=多选 3=判断

    def is_valid(self) -> bool:
        # 题干非空 且 至少 2 个非空选项
```

- **answer 存储约定**（前端判分依赖，勿改）：判断题 `正确/错误`，多选 `ABCD` 字母串
- 入库前提：`is_valid()`；无答案也入库（`answer=None`，前端标记「未知」）

### FetchResult（`scripts/crawler/adapters.py`）—— 单页抓取结果

```python
@dataclass
class FetchResult:
    questions: list[ParsedQuestion]
    has_more: bool = False    # 是否还有下一页
```

### SourceAdapter 基类（`scripts/crawler/adapters.py`）

```python
@dataclass
class SourceAdapter(ABC):
    url: str
    config: dict            # 每源专属 JSON（存 crawl_sources.config）
    title: str = ""         # 抓取后回填（OK 时）

    @property
    @abstractmethod
    def kind(self) -> str: ...            # 注册键，存 crawl_sources.kind
    @abstractmethod
    def fetch_page(self, page: int) -> FetchResult: ...   # page 从 0 递增
    def total_estimate(self) -> int | None: ...           # 可选，进度用
```

注册表 `ADAPTERS: dict[str, type[SourceAdapter]]`（`adapters.py` 末尾）：

| kind | 适配器 | 适用 |
| --- | --- | --- |
| `static_page` | StaticPageAdapter | 单页静态 HTML 题目页 |
| `json_api` | JsonApiAdapter | 返回 JSON 题目数组的分页接口 |
| `fixture` | FixtureAdapter | 内置演示题库（离线） |
| `examcoo` | ExamcooAdapter | 考试酷逐试卷抓取 |

**新增源类型**：继承 `SourceAdapter` 实现 `fetch_page`，注册进 `ADAPTERS` 即可。

### ExamcooPaper（`scripts/crawler/examcoo.py`）—— 考试酷单卷

```python
@dataclass
class ExamcooPaper:
    pid: str                     # 试卷 id
    title: str = ""
    questions: list[ParsedQuestion] = ...
    source_url: str = ""
    total_questions: int = 0
```

## 3. SQLite Schema（`scripts/crawler/db.py`，`data/quiz.db`）

### crawl_sources

| 列 | 说明 |
| --- | --- |
| `id` / `url`（UNIQUE） | 主键 / 源地址 |
| `title` / `kind` / `status` | 标题 / 适配器类型 / `pending\|analyzing\|ready\|failed` |
| `detail` / `question_count` | 状态说明 / 题目数 |
| `refresh_interval_seconds` / `last_refresh_at` | 刷新周期 / 最近刷新（CLI 场景不再调度，字段保留） |
| `config` | 适配器专属 JSON 参数（TEXT） |
| `created_at` / `updated_at` | 时间戳 |

### questions

| 列 | 说明 |
| --- | --- |
| `id` / `source_id`（FK 级联）/ `source_url` | 主键 / 来源 / 原题链接 |
| `question_text`（UNIQUE） | 题干 |
| `option_a`–`option_e` / `answer` / `explanation` | 选项 / 答案 / 解析 |
| `subject` / `paper_subject` | 科目（1-4，逐题分类结果）/ 试卷标题信号科目 |
| `paper_title` / `province` / `years` | 试卷标题 / 省份 / 出现年份（`"2011,2012"`） |
| `q_type` | 1 单选 / 2 多选 / 3 判断 |
| `norm_text`（UNIQUE） | 规范化指纹，跨平台去重键 |

### answer_attempts（遗留表）

旧后端答题记录表，前端已改用 localStorage，**不再读写**；保留以备数据迁移。

### 迁移策略

`connect()` 内：建表（`CREATE TABLE IF NOT EXISTS`）→ `PRAGMA table_info` 差量 `ALTER TABLE ADD COLUMN` → 按最终列集建索引。**新增列只需在 `SCHEMA_TABLES` 与迁移段各加一处**，旧库自动补列；不手写一次性 DDL。

## 4. 去重机制（🔴 红线）

- **双 UNIQUE 键缺一不可**：`question_text` 精确唯一 + `norm_text` 规范化指纹唯一
- 入库路径（`_store_questions`）：`INSERT OR IGNORE` 命中任一键 → 走 UPDATE 刷新分支（答案/选项/年份合并等）
- **`normalize_question_text` 规则**（`db.py`，跨平台去重指纹）：
  1. 全角 → 半角（`_FULLWIDTH_MAP`）
  2. 标点族归一：`“”`→`"`、`（`→`(`、`。`→`.`、`，`/`、`→`,`、`：`→`:`、`！`→`!`、`？`→`?`、`％`→`%`、`×`→`x`、`—`→`-` 等
  3. 空白折叠为单空格（含全角空格 `\u3000`）
  4. 括号内空白折叠：`( )`→`()`、`[ ]`→`[]`
  5. 剥离题号前缀：`^\d+[.,、:：．]\s*`
  6. 去尾部空白与句点：`rstrip(" .")`
- **改动 `normalize_question_text` 必须先跑全量测试**（去重行为被大量测试覆盖）

## 5. 分类规则（`scripts/crawler/service.py`，分层，🔴 顺序不可颠倒）

> 科目定义：1 政策与法律法规 / 2 导游业务 / 3 全国导游基础知识 / 4 地方导游基础知识

分类分层（优先级从高到低）：

1. **试卷真实标题为权威依据**（`subject_from_paper_title`）：书名号/关键词规则 `_PAPER_TITLE_SUBJECTS`（元组有序，**「地方…」规则必须先于「导游基础知识/基础知识」**，否则科目四被科目三抢先命中）
2. **源级映射** `SUBJECT_BY_EXAMCOO_KID`：`408`→2（导游业务）、`409`→3（基础知识）、`413`→2（规范服务）
3. **混合卷逐题细分**：`_MIX_PAPER_RE = 科目一.*科目二|科目二.*科目一` → `classify_question_subject_mixed`（法规题→1、业务操作题→2，未命中默认 1）
4. **题级关键词覆盖**（`classify_question_subject`）：`_LEGAL_RE`（法规信号）、`_BASE_RE`（基础知识信号）覆盖源级默认；**只用复合词**（`法规`/`基础知识`），裸「法/方法/做法」不参与（会误分类业务题）

### 省份与年份

- 省份：`_PROVINCE_RE`（34 省级行政区含港澳台），从 `paper_title` 提取，多省逗号分隔
- 年份：`_PAPER_YEAR_RE = (?:19|20)\d{2}` 取标题首个 4 位年份；同题多卷合并 `_merge_years`（升序去重）
- 地方信号：省名 + 地方章节词 → 科目四；题干以省名开头 / 含「我省/本省/该省/全省」→ 地方知识强信号

### 外语排除（`scripts/crawler/examcoo.py`）

- `EXCLUDED_SUBCATEGORIES = {"411"}`（导游外语纯英语子类目）
- `_FOREIGN_PAPER_RE = 英语|外语|英文|English` 标题双保险；中文题含英文缩写（VIP、F.I.T.）正常保留

## 6. 适配器 config 关键参数

| kind | config 参数 |
| --- | --- |
| `static_page` | 无 |
| `json_api` | `page_size`（默认 100）、`page_param`/`offset_param`、`data_path`（如 `data.list`）、`total_path`/`has_more_path` |
| `fixture` | 无 |
| `examcoo` | `subcategory_id`、`subcategory_name` |

- 单源抓取页数上限 100 页；单页正文上限 3 MiB（`MAX_FETCH_BYTES`）
- `json_api` 分页：`page` 从 1 递增（或 `offset` 按 `page_size` 步进），直到 `has_more=false`/达到 `total`/返回不足一页

## 7. 入库与刷新

- `_upsert_source(conn, url, kind, config, title, ok, detail) -> int`：`ON CONFLICT(url) DO UPDATE`，返回源 id
- `_store_questions(conn, source_id, url, questions, subject=None) -> {inserted, updated, deduped, total}`：逐题 `q_url = q.source_url or url` → 分类 → 双键去重入库/更新；同题跨源只存一行，后抓的答案刷新，`source_url` 保留首次来源
- `add_source_and_crawl(url, kind, config)` / `refresh_source(source_id)`：抓取 → 入库 → 回写 `question_count`/状态，返回 `{ok, url, source_id, kind, reason, questions_found, questions_inserted, questions_updated, questions_deduped, pages_fetched}`
- **`questions_deduped` 是跨平台规范化命中数，不是失败**；`ok=false` 时看 `reason`

## 8. 数据文件格式（`frontend/public/data/*.json`，AI 维护依据）

> 采集脚本不生成/覆盖这些文件；新增或修改题目时，由 AI **直接读取真实文件内容**后按本格式编辑。
> （`scripts/export_static.py` 曾是从旧库导出的迁移脚本，迁移完成后已删除。）

| 文件 | 内容 |
| --- | --- |
| `manifest.json` | `{generated_at, total, answered, sources, per_subject}` |
| `sources.json` | `{sources: [{id, url, title, kind, status, question_count, last_refresh_at, created_at}]}` |
| `questions_0.json` | 未分类题（subject NULL） |
| `questions_1..4.json` | 按科目分文件 |

题目字段（与前端 `types.ts` 的 `Question` 对齐）：`id / question_text / option_a..e / answer / explanation / subject / q_type / province / years / source_id / paper_title / source_url`。

- **answer 原样保留**：判断题 `正确/错误`、多选字母串 `ABCD`——前端判分时映射，勿在数据侧归一化
- 维护约定：题目按 id 升序、时间戳只写 manifest（`generated_at`），编辑时保持，避免无谓 diff

## 9. 数据红线速查（改代码前必看）

1. `question_text` 与 `norm_text` 双 UNIQUE 不可破坏 → 改 `normalize_question_text` 必跑全量测试
2. `_PAPER_TITLE_SUBJECTS` 中「地方…」必须先于「基础知识…」→ 改规则用真实试卷标题验证
3. 题级关键词只用复合词，裸「法/方法/做法」会误分类业务题
4. answer 存储/导出格式（判断题中文、多选字母串）不可改——前端判分与其强耦合
5. 改任何数据定义后：`cd frontend && npm run build` + `PYTHONPATH=scripts .venv/bin/python -m pytest`（49 项全绿）；若改了数据文件，直接编辑 `frontend/public/data/*.json` 后重新构建
