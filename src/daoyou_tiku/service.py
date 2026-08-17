"""Service layer: source lifecycle and crawl orchestration.

A source lifecycle is: pending -> analyzing -> ready (questions stored)
or failed. `add_source_and_crawl` runs analyze + parse synchronously so the
API can return concrete results; per-source refresh re-crawls a stored
source and updates its question set.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import httpx

from . import adapters, crawler
from .db import connect, normalize_question_text

# National tour-guide exam subjects (导游资格考试科目):
#   1 政策与法律法规, 2 导游业务, 3 全国导游基础知识, 4 地方导游基础知识
# Examcoo subcategory id (in the source URL /paperlist/index/k/<kid>/) -> subject.
# NOTE: 413 "规范服务" is mostly tour-guide service content, i.e. 科目二,
# despite a few 科目一 legal questions inside; per-question keyword rules
# below reclassify those.
SUBJECT_BY_EXAMCOO_KID = {
    "408": 2,  # 导游业务
    "409": 3,  # 导游基础知识
    "413": 2,  # 规范服务 -> 导游业务（含少量法规题，题级规则修正）
}

import re

# Per-question keyword rules: legal (科目一) and basic-knowledge (科目三)
# markers override the source-level default. Keep compound words only so
# bare 法/方法/做法 do not misclassify tour-guide service questions.
_LEGAL_RE = re.compile(
    r"(旅游法|法规|条例|处罚|许可证|合同|投诉|赔偿|行政复议|行政诉讼|宪|规章|细则|"
    r"规定|办法|标准|检疫|签证|护照|边防|海关|民法|刑法|诉讼法|仲裁|罚款|拘留|吊销|责令|"
    r"立法|依法治国|法治|政权|人民代表大会|政府机关|国家机关|国家权力|国务院|全国人大|"
    r"总书记|党员|党组织|社会主义制度|国家制度|法律|行政法规|部门规章|规范性文件)"
)
_BASE_RE = re.compile(
    r"(文化|历史|地理|建筑|饮食|民俗|民族|石窟|园林|节日|特产|风景区|遗产|瓷|玉|茶|丝绸|"
    r"运河|长城|故宫|地貌|气候|方言|宗教|戏曲|菜系|小吃|工艺|史诗|朝代|皇帝|遗址)"
)

# Paper-title markers -> exam subject. Titles come from the source itself
# (e.g. 「导游综合知识导游业务试卷和试题：6.29导游业务第1至第3章单选题」), so
# they are the authoritative classification captured at crawl time.
#
# 科目四 = 地方导游基础知识. 其标题常无书名号且含「地方导游/地方基础/地方知识」
# (e.g. 「2012年重庆地方导游基础知识模拟题一」), 必须排在「导游基础知识/基础知识」
# 之前, 否则会被科目三规则抢先命中. 书名号规则同理: 《地方…》先于《导游基础知识…》.
_PAPER_TITLE_SUBJECTS: tuple[tuple[re.Pattern, int], ...] = (
    (re.compile(r"《([^》]*导游业务[^》]*)》"), 2),
    (re.compile(r"《([^》]*导游实务[^》]*)》"), 2),
    (re.compile(r"《([^》]*服务技能[^》]*)》"), 2),
    (re.compile(r"《([^》]*地方导游[^》]*)》"), 4),
    (re.compile(r"《([^》]*地方基础[^》]*)》"), 4),
    (re.compile(r"《([^》]*地方知识[^》]*)》"), 4),
    (re.compile(r"《([^》]*地方[^》]*)》"), 4),
    (re.compile(r"《([^》]*导游基础知识[^》]*)》"), 3),
    (re.compile(r"《([^》]*基础知识[^》]*)》"), 3),
    (re.compile(r"《([^》]*法规[^》]*)》"), 1),
    (re.compile(r"《([^》]*政策[^》]*)》"), 1),
    (re.compile(r"导游业务"), 2),
    (re.compile(r"导游实务"), 2),
    (re.compile(r"服务技能"), 2),
    (re.compile(r"规范服务"), 2),
    (re.compile(r"地方导游"), 4),
    (re.compile(r"地方基础"), 4),
    (re.compile(r"地方知识"), 4),
    (re.compile(r"导游文化基础知识"), 4),
    (re.compile(r"导游基础知识"), 3),
    (re.compile(r"基础知识"), 3),
    (re.compile(r"科目三"), 3),
    (re.compile(r"全导"), 3),
    (re.compile(r"规范服务能力"), 2),
)

# 34 省级行政区 (含港澳台). 从 paper_title 提取省份, 多省标题返回逗号分隔
# 字符串 (e.g. 「2010年导游资格证考试江西、浙江、上海旅游试题1」 -> "江西,浙江,上海").
# 与 subject 分类正交: 地方卷标题既可能属科目二/三(全国知识的地方考卷),
# 也可能是科目四(地方导游基础知识).
_PROVINCE_RE = re.compile(
    r"(北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|"
    r"河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|内蒙古|广西|西藏|宁夏|新疆|"
    r"香港|澳门|台湾)"
)

# 地方章节信号: 省名紧接地方章节词 (概况/历史/地理/民俗/风情/文化/特产/
# 风物/名胜/景观/旅游资源/风土人情), 说明该卷是「XX省地方导游知识」的章节卷,
# 而非「XX省考全国导游基础知识」(科目三). 与「全国/中国」等词互斥.
_LOCAL_SECTION_RE = re.compile(
    r"(?:北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|"
    r"河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|内蒙古|广西|西藏|宁夏|新疆|"
    r"香港|澳门|台湾)(?:概况|历史|地理|民俗|风情|文化|特产|风物|名胜|景观|旅游资源|风土人情)"
)

# 全国知识信号: 题干/标题含这些词时, 即使出现省名也属全国知识(科目三).
_NATIONAL_TERM_RE = re.compile(r"我国|中国|全国|中华|神州|华夏")

# 题干以省名开头(允许前导括号/引号/空格), 是「这道题考某省自身」的强信号.
_LEAD_PROV_RE = re.compile(
    r"^[（(【\"\'\s]*(北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|"
    r"河南|湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|内蒙古|广西|西藏|宁夏|新疆|"
    r"香港|澳门|台湾)"
)

# 「我省/本省/该省/全省/本地区」等指代本省的词, 也是地方知识信号.
_SELF_PROV_RE = re.compile(r"我省|本省|该省|全省|本地区")


def province_from_paper_title(title: str | None) -> str | None:
    """Province names found in a paper title, comma-separated (deduped,
    first-appearance order), or None."""
    if not title:
        return None
    seen: list[str] = []
    for m in _PROVINCE_RE.finditer(title):
        name = m.group(1)
        if name not in seen:
            seen.append(name)
    return ",".join(seen) if seen else None

_MIX_PAPER_RE = re.compile(r"科目一.*科目二|科目二.*科目一")

# Exam year embedded in a paper title, e.g. "2012年导游考试…真题".
_PAPER_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def _paper_year(title: str | None) -> str | None:
    """First 4-digit year found in a paper title, or None."""
    if not title:
        return None
    m = _PAPER_YEAR_RE.search(title)
    return m.group(0) if m else None


def _merge_years(existing: str | None, new: str | None) -> str | None:
    """Union of comma-separated year strings, sorted ascending and unique."""
    if not new:
        return existing
    seen = set()
    for y in ((existing or "").split(",") + new.split(",")):
        y = y.strip()
        if y:
            seen.add(y)
    return ",".join(sorted(seen)) if seen else None

# Tour-guide service (科目二) markers, used to split mixed 科目一+科目二
# papers per-question instead of guessing from the paper alone. Kept to
# concrete service-operation words; broad scene words (行程/游客/导游) also
# appear in legal/policy questions and would misclassify them.
_TOURGUIDE_RE = re.compile(
    r"(带团|讲解|接站|送站|地陪|全陪|领队|用餐|住宿|购物|退团|离团|散客|"
    r"游览路线|景点游览|导游服务|欢迎词|欢送词|途中讲解)"
)


def subject_from_paper_title(title: str, source_subject: int | None) -> int | None:
    """Exam subject signalled by a paper title (captured at crawl time).

    Priority: mixed papers (科目一+科目二) keep their per-question split
    (return None -> classify each question), then book-title markers,
    then title keywords, then the source-level mapping.

    科目四(地方导游基础知识)卷级信号: 标题含「地方」章节词, 或「省名+地方
    章节词(概况/历史/地理/… )」且不含全国词, 判为 4.
    """
    if not title:
        return source_subject
    if _MIX_PAPER_RE.search(title):
        return None
    for pat, subj in _PAPER_TITLE_SUBJECTS:
        if pat.search(title):
            # 命中科目三规则时, 若标题含「省名+地方章节词」且无全国词,
            # 说明是「XX省地方导游知识」章节卷, 改判科目四.
            if (
                subj == 3
                and _LOCAL_SECTION_RE.search(title)
                and not _NATIONAL_TERM_RE.search(title)
            ):
                return 4
            return subj
    # 无关键词命中: 仍由「省名+地方章节词」判定地方卷.
    if _LOCAL_SECTION_RE.search(title) and not _NATIONAL_TERM_RE.search(title):
        return 4
    return source_subject


def classify_question_subject(question_text: str, source_subject: int | None) -> int | None:
    """Classify a single question by content.

    Order: legal markers -> 科目一, then (for basic-knowledge papers) a
    local-knowledge signal -> 科目四, then basic markers -> 科目三,
    otherwise keep the source-level subject. Returns 1-4 or None.

    科目四(地方导游基础知识)的题干天然含历史/地理/文化词, 与科目三重叠;
    题级地方信号只识别「题干以省名开头」或「我省/本省/该省/全省」这类
    明确考某省自身的表述, 且排除全国词和多省列举, 避免误移业务/法规题.
    """
    if source_subject == 4:
        return 4
    if _LEGAL_RE.search(question_text):
        return 1
    # 题级地方信号仅在知识卷(3/None)生效: 明确考某省自身的题干改判科目四;
    # 业务/法规卷(1,2)不因省名词跨科目改判, 仍走下方 BASE/保留 source_subject.
    if source_subject in (3, None) and _is_local_question(question_text):
        return 4
    if _BASE_RE.search(question_text):
        return 3
    return source_subject


def _is_local_question(question_text: str) -> bool:
    """题级地方知识信号: 明确考某省自身, 且非全国知识."""
    if not question_text:
        return False
    if _NATIONAL_TERM_RE.search(question_text):
        return False
    # 多省列举(≥2个不同省名)说明是跨省/全国比较知识, 判科目三.
    if len(set(_PROVINCE_RE.findall(question_text))) >= 2:
        return False
    return bool(_LEAD_PROV_RE.match(question_text)) or bool(_SELF_PROV_RE.search(question_text))


def classify_question_subject_mixed(question_text: str) -> int:
    """Classify a question from a mixed 科目一+科目二 paper.

    The paper's title carries no single subject (it mixes both), so the
    per-question rules must decide: legal markers -> 科目一, basic
    markers -> 科目三, tour-guide service markers -> 科目二, otherwise
    default to 科目一 (the paper title lists 科目一 first and its content
    is predominantly legal/policy).
    """
    if _LEGAL_RE.search(question_text):
        return 1
    if _BASE_RE.search(question_text):
        return 3
    if _TOURGUIDE_RE.search(question_text):
        return 2
    return 1


def subject_for_source(url: str, kind: str) -> int | None:
    """Map a crawl source to a subject (1-4) or None when unclassified."""
    if kind == "examcoo":
        m = re.search(r"/k/(\d+)/", url)
        if m:
            return SUBJECT_BY_EXAMCOO_KID.get(m.group(1))
    return None


def _classify_row(
    question_text: str, url: str, kind: str, paper_title: str | None = None
) -> int | None:
    """Layered classification: paper title (crawl-time), then source default,
    then per-question keyword rules for mixed papers."""
    src_subject = subject_for_source(url, kind)
    paper_subject = subject_from_paper_title(paper_title or "", src_subject)
    if paper_subject is None and paper_title and _MIX_PAPER_RE.search(paper_title):
        return classify_question_subject_mixed(question_text)
    return classify_question_subject(question_text, paper_subject)


def backfill_subjects(conn=None) -> int:
    """Backfill the subject/paper_subject columns for existing rows.

    Layered: paper title (crawl-time signal), then source-level mapping
    (by kind+URL), then per-question keyword overrides. Re-runs update
    every row so changed rules propagate. Idempotent: rows already
    matching the computed class are untouched. Returns rows updated.
    """
    own = conn is None
    conn = conn or connect()
    rows = conn.execute(
        """SELECT q.id, q.question_text, q.paper_title, q.subject AS current,
                  q.paper_subject AS cur_paper,
                  cs.kind, cs.url
           FROM questions q JOIN crawl_sources cs ON cs.id = q.source_id"""
    ).fetchall()
    updated = 0
    for r in rows:
        src_subject = subject_for_source(r["url"], r["kind"])
        paper_subject = subject_from_paper_title(r["paper_title"] or "", src_subject)
        if paper_subject is None and r["paper_title"] and _MIX_PAPER_RE.search(r["paper_title"]):
            new = classify_question_subject_mixed(r["question_text"])
        else:
            new = classify_question_subject(r["question_text"], paper_subject)
        if new != r["current"] or paper_subject != r["cur_paper"]:
            conn.execute(
                "UPDATE questions SET subject = ?, paper_subject = ? WHERE id = ?",
                (new, paper_subject, r["id"]),
            )
            updated += 1
    if updated:
        conn.commit()
    if own:
        conn.close()
    return updated


def backfill_provinces(conn=None) -> int:
    """Backfill the province column from paper_title for existing rows.

    Province names are a per-title derived attribute (multi-province titles
    yield a comma-separated string), independent of the subject class.
    Re-runs recompute every row so rule changes propagate; rows already
    matching are untouched. Returns rows updated.
    """
    own = conn is None
    conn = conn or connect()
    rows = conn.execute(
        "SELECT id, paper_title, province AS current FROM questions"
    ).fetchall()
    updated = 0
    for r in rows:
        new = province_from_paper_title(r["paper_title"])
        if new != r["current"]:
            conn.execute(
                "UPDATE questions SET province = ? WHERE id = ?",
                (new, r["id"]),
            )
            updated += 1
    if updated:
        conn.commit()
    if own:
        conn.close()
    return updated


def backfill_question_types(conn=None) -> int:
    """Backfill q_type for rows crawled before the column existed.

    Inference from the stored answer shape: 1 letter -> single (1),
    multiple letters -> multiple (2), 正确/错误 -> true/false (3).
    Rows with a q_type already set are left untouched.
    """
    own = conn is None
    conn = conn or connect()
    rows = conn.execute(
        """SELECT id, answer, q_type FROM questions
           WHERE q_type IS NULL AND answer IS NOT NULL AND answer != ''"""
    ).fetchall()
    updated = 0
    for r in rows:
        ans = r["answer"]
        if ans in ("正确", "错误"):
            q_type = 3
        elif len(ans) == 1:
            q_type = 1
        elif len(ans) >= 2:
            q_type = 2
        else:
            continue
        conn.execute("UPDATE questions SET q_type = ? WHERE id = ?", (q_type, r["id"]))
        updated += 1
    if updated:
        conn.commit()
    if own:
        conn.close()
    return updated


def _upsert_source(
    conn: sqlite3.Connection, url: str, kind: str, config: dict, title: str, ok: bool, detail: str
) -> int:
    cur = conn.execute(
        """INSERT INTO crawl_sources (url, title, kind, status, detail, question_count, config)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(url) DO UPDATE SET
             title=excluded.title,
             kind=excluded.kind,
             status=excluded.status,
             detail=excluded.detail,
             config=excluded.config,
             updated_at=datetime('now')""",
        (
            url,
            title,
            kind,
            "ready" if ok else "failed",
            detail,
            0,
            json.dumps(config, ensure_ascii=False) if config else "",
        ),
    )
    conn.commit()
    return cur.lastrowid or conn.execute(
        "SELECT id FROM crawl_sources WHERE url = ?", (url,)
    ).fetchone()["id"]


def _store_questions(
    conn: sqlite3.Connection,
    source_id: int,
    url: str,
    questions,
    subject: int | None = None,
) -> int:
    """Sync pipeline: insert new questions, dedupe by question text.

    ``question_text`` is globally unique (schema UNIQUE constraint): the
    same question appearing in several papers/sources is stored once.
    Later crawls refresh the answer/options so the latest source data
    wins; ``source_url`` keeps the first origin link seen.

    ``q.source_url`` (when set) is the per-question origin link (e.g. the
    paper's public view page); it falls back to the crawl-source ``url``.
    Classification is layered: the paper title captured at crawl time is
    the authoritative signal (subject_from_paper_title), falling back to
    the source-level ``subject``, with per-question keyword overrides for
    mixed papers.
    """
    inserted = 0
    updated = 0
    deduped = 0
    for q in questions:
        q_url = q.source_url or url
        norm = normalize_question_text(q.question_text)
        province = province_from_paper_title(q.paper_title)
        paper_subject = subject_from_paper_title(q.paper_title or "", subject)
        if paper_subject is None and q.paper_title and _MIX_PAPER_RE.search(q.paper_title):
            # mixed 科目一+科目二 paper: per-question split
            q_subject = classify_question_subject_mixed(q.question_text)
        else:
            q_subject = classify_question_subject(q.question_text, paper_subject)
        cur = conn.execute(
            """INSERT OR IGNORE INTO questions
               (source_id, source_url, question_text, option_a, option_b,
                option_c, option_d, option_e, answer, explanation, subject,
                paper_title, paper_subject, province, years, q_type, norm_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (source_id, q_url, q.question_text, q.option_a, q.option_b,
             q.option_c, q.option_d, q.option_e, q.answer, q.explanation, q_subject,
             q.paper_title, paper_subject, province, _paper_year(q.paper_title),
             q.q_type, norm),
        )
        inserted += cur.rowcount
        if cur.rowcount == 0:
            # existing row: exact question_text match first, then
            # cross-platform normalized-text match
            existing = conn.execute(
                "SELECT id, years FROM questions WHERE question_text = ?",
                (q.question_text,),
            ).fetchone()
            if existing is None:
                existing = conn.execute(
                    "SELECT id, years FROM questions WHERE norm_text = ?",
                    (norm,),
                ).fetchone()
                if existing is not None:
                    deduped += 1
            if existing:
                # dedupe by question text: refresh when latest data differs —
                merged_years = _merge_years(existing["years"], _paper_year(q.paper_title))
                cur = conn.execute(
                    """UPDATE questions
                       SET answer = ?, explanation = ?,
                           option_a = ?, option_b = ?, option_c = ?, option_d = ?,
                           option_e = ?,
                           paper_title = COALESCE(paper_title, ?),
                           paper_subject = ?,
                           province = COALESCE(province, ?),
                           subject = ?,
                           years = ?,
                           q_type = ?
                       WHERE id = ?
                         AND (answer IS NOT ? OR explanation IS NOT ?
                              OR option_a IS NOT ? OR option_b IS NOT ?
                              OR option_c IS NOT ? OR option_d IS NOT ?
                              OR option_e IS NOT ?
                              OR paper_subject IS NOT ? OR province IS NOT ?
                              OR subject IS NOT ?
                              OR years IS NOT ? OR q_type IS NOT ?)""",
                    (q.answer, q.explanation, q.option_a, q.option_b,
                     q.option_c, q.option_d, q.option_e, q.paper_title, paper_subject,
                     province, q_subject, merged_years, q.q_type, existing["id"],
                     q.answer, q.explanation, q.option_a, q.option_b,
                     q.option_c, q.option_d, q.option_e, paper_subject, province,
                     q_subject, merged_years, q.q_type),
                )
                updated += cur.rowcount
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM questions WHERE source_id = ?", (source_id,)
    ).fetchone()["n"]
    conn.execute(
        """UPDATE crawl_sources
           SET question_count = ?, status = CASE WHEN ? > 0 THEN 'ready' ELSE status END,
               last_analyzed_at = datetime('now'), updated_at = datetime('now')
           WHERE id = ?""",
        (count, count, source_id),
    )
    conn.commit()
    return {"inserted": inserted, "updated": updated, "deduped": deduped, "total": count}


def _crawl_all(adapter) -> tuple[list, int]:
    """Fetch every page of an adapter; returns (questions, pages_fetched)."""
    questions: list = []
    page = 0
    while True:
        result = adapter.fetch_page(page)
        questions.extend(result.questions)
        if not result.has_more:
            break
        page += 1
        if page > 100:  # safety cap against infinite paging
            break
    return questions, page + 1


def add_source_and_crawl(url: str, kind: str = "static_page", config: dict | None = None) -> dict:
    """Add a source and crawl it synchronously via its adapter."""
    config = config or {}
    try:
        adapter = adapters.build_adapter(kind, url, config)
        questions, pages = _crawl_all(adapter)
        ok = True
        detail = f"crawled {len(questions)} questions across {pages} page(s)"
    except (adapters.AdapterError, httpx.HTTPError) as exc:
        ok = False
        questions = []
        pages = 0
        detail = str(exc)
    conn = connect()
    source_id = _upsert_source(
        conn, url, kind, config, adapter.title if ok else "", ok, detail
    )
    stored = _store_questions(
        conn, source_id, url, questions, subject_for_source(url, kind)
    ) if questions else {
        "inserted": 0, "updated": 0, "deduped": 0, "total": 0
    }
    # the initial crawl is the first refresh: mark it so scheduling counts
    # from now, not from a NULL "never refreshed" state
    conn.execute(
        """UPDATE crawl_sources SET last_refresh_at = datetime('now'),
               updated_at = datetime('now')
           WHERE id = ?""",
        (source_id,),
    )
    conn.commit()
    conn.close()
    return {
        "url": url,
        "source_id": source_id,
        "ok": ok,
        "kind": kind,
        "reason": detail,
        "questions_found": len(questions),
        "questions_inserted": stored["inserted"],
        "questions_updated": stored["updated"],
        "questions_deduped": stored["deduped"],
        "pages_fetched": pages,
    }


def refresh_source(source_id: int) -> dict:
    conn = connect()
    row = conn.execute(
        "SELECT id, url, kind, config FROM crawl_sources WHERE id = ?", (source_id,)
    ).fetchone()
    if row is None:
        conn.close()
        return {"ok": False, "reason": "source not found"}
    conn.execute(
        """UPDATE crawl_sources SET status='analyzing', updated_at=datetime('now')
           WHERE id = ?""",
        (source_id,),
    )
    conn.commit()
    kind = row["kind"] or "static_page"
    config = json.loads(row["config"]) if row["config"] else {}
    try:
        adapter = adapters.build_adapter(kind, row["url"], config)
        questions, pages = _crawl_all(adapter)
        ok = True
        detail = f"crawled {len(questions)} questions across {pages} page(s)"
    except (adapters.AdapterError, httpx.HTTPError) as exc:
        ok = False
        questions = []
        pages = 0
        detail = str(exc)
    _upsert_source(
        conn, row["url"], kind, config, adapter.title if ok else "", ok, detail
    )
    stored = _store_questions(
        conn, source_id, row["url"], questions, subject_for_source(row["url"], kind)
    ) if questions else {
        "inserted": 0, "updated": 0, "deduped": 0, "total": 0
    }
    conn.execute(
        """UPDATE crawl_sources SET last_refresh_at = datetime('now'),
               updated_at = datetime('now')
           WHERE id = ?""",
        (source_id,),
    )
    conn.commit()
    conn.close()
    return {
        "ok": ok,
        "url": row["url"],
        "kind": kind,
        "reason": detail,
        "questions_found": len(questions),
        "questions_inserted": stored["inserted"],
        "questions_updated": stored["updated"],
        "questions_deduped": stored["deduped"],
        "pages_fetched": pages,
    }


def remove_source(source_id: int) -> bool:
    conn = connect()
    cur = conn.execute("DELETE FROM crawl_sources WHERE id = ?", (source_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# Real 全国导游资格考试 written-exam structure: each paper mixes two
# 科目s, 165 minutes, 单选45 + 多选35 + 判断40 = 120 题.
EXAM_PAPERS = {
    # paper_type -> (subjects, display label)
    1: ([1, 2], "科目一+科目二 合并卷（政策法规+导游业务）"),
    2: ([3, 4], "科目三+科目四 合并卷（全国基础+地方知识）"),
}
EXAM_TYPE_COUNTS = ((1, 45), (2, 35), (3, 40))  # q_type -> 题量
EXAM_TYPE_SCORES = {1: 1.0, 2: 1.0, 3: 0.5}      # 每题型每题分值（满分 100）
EXAM_MINUTES = 165


def build_exam_paper(conn, paper_type: int) -> dict:
    """Randomly assemble a real-exam-style paper from the question bank.

    Structure mirrors the 全国导游资格考试 written exam: 单选45 + 多选35 +
    判断40 (each type capped at what the bank actually holds), subjects per
    paper type, 165-minute duration. Returns paper + per-question rows.
    """
    subjects = EXAM_PAPERS[paper_type][0]
    picked: list[sqlite3.Row] = []
    type_counts: dict[int, int] = {}
    for q_type, want in EXAM_TYPE_COUNTS:
        rows = conn.execute(
            """SELECT id, source_id, source_url, question_text, option_a,
                      option_b, option_c, option_d, option_e, answer, explanation,
                      subject, province, years, q_type
               FROM questions
               WHERE q_type = ? AND subject IN (?, ?)
                 AND answer IS NOT NULL AND answer != ''
               ORDER BY RANDOM() LIMIT ?""",
            (q_type, subjects[0], subjects[1], want),
        ).fetchall()
        picked.extend(rows)
        type_counts[q_type] = len(rows)
    return {
        "paper_type": paper_type,
        "label": EXAM_PAPERS[paper_type][1],
        "minutes": EXAM_MINUTES,
        "type_counts": type_counts,
        "questions": picked,
    }


def exam_score(answers: list[dict], questions: list[dict]) -> dict:
    """Score an exam submission: per-question correctness, per-type and
    total scores. Multi-choice matches order-insensitively; true/false
    answers map between stored 中文 (正确/错误) and submitted letters."""
    type_stats = {1: {"total": 0, "correct": 0}, 2: {"total": 0, "correct": 0}, 3: {"total": 0, "correct": 0}}
    details = []
    by_id = {q["id"]: q for q in questions}
    for a in answers:
        q = by_id.get(a["question_id"])
        if not q:
            continue
        q_type = q.get("q_type") or 1
        type_stats[q_type]["total"] += 1
        given = (a.get("answer") or "").strip().upper()
        ref = (q.get("answer") or "").strip().upper()
        if q_type == 3 and ref in ("正确", "错误"):
            ref = "A" if ref == "正确" else "B"
        correct = False
        if q_type == 2:
            norm = lambda s: sorted(s.replace(",", ""))
            correct = bool(ref) and norm(given) == norm(ref)
        else:
            correct = bool(ref) and given == ref
        if correct:
            type_stats[q_type]["correct"] += 1
        details.append(
            {
                "question_id": q["id"],
                "correct": correct,
                "given": a.get("answer"),
                "answer": ref,
                "explanation": q.get("explanation") or "",
                "question_text": q.get("question_text", ""),
                "q_type": q_type,
            }
        )
    total = sum(type_stats[t]["correct"] * EXAM_TYPE_SCORES[t] for t in (1, 2, 3))
    full = sum(type_stats[t]["total"] * EXAM_TYPE_SCORES[t] for t in (1, 2, 3))
    return {
        "total_score": round(total, 1),
        "full_score": round(full, 1),
        "details": details,
        "type_stats": type_stats,
    }


def set_refresh_interval(source_id: int, interval_seconds: int) -> dict:
    """Set a source's refresh interval; 0 disables scheduled refresh."""
    if interval_seconds < 0:
        return {"ok": False, "reason": "interval must be >= 0"}
    conn = connect()
    cur = conn.execute(
        """UPDATE crawl_sources
           SET refresh_interval_seconds = ?, updated_at = datetime('now')
           WHERE id = ?""",
        (interval_seconds, source_id),
    )
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return {"ok": False, "reason": "source not found"}
    return {"ok": True, "source_id": source_id, "refresh_interval_seconds": interval_seconds}


def due_sources(now_utc: str | None = None) -> list[dict]:
    """Sources whose scheduled refresh is due: refresh_interval > 0 and
    last_refresh_at older than the interval (or never refreshed).
    `now_utc` overrides the clock for deterministic tests.
    """
    conn = connect()
    if now_utc is None:
        now_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """SELECT id, url, title, kind, status, question_count,
                  refresh_interval_seconds, last_refresh_at, last_analyzed_at
           FROM crawl_sources
           WHERE refresh_interval_seconds > 0
             AND status IN ('ready', 'failed')
             AND (last_refresh_at IS NULL
                  OR last_refresh_at <= datetime(?, '-' || refresh_interval_seconds || ' seconds'))""",
        (now_utc,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def refresh_due_sources(now_utc: str | None = None) -> dict:
    """Re-crawl every due source; returns per-source results."""
    due = due_sources(now_utc)
    results = []
    for src in due:
        results.append({"source_id": src["id"], **refresh_source(src["id"])})
    return {"due": len(due), "results": results}


def wrong_questions(
    subject: int | None = None,
    source_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Distinct questions answered wrong at least once, newest attempt first.

    The wrong-question pool (错题本) is derived from answer_attempts: a
    question counts once even if missed multiple times, and a question
    answered wrong but later answered correctly stays in the pool (real
    exams repeat; retraining stale misses is the point). Optional
    subject/source filters mirror /api/quiz. Unanswered rows are excluded.
    """
    conn = connect()
    where, params = [], []
    if subject is not None:
        where.append("q.subject = ?")
        params.append(subject)
    if source_id is not None:
        where.append("q.source_id = ?")
        params.append(source_id)
    extra = (" AND " + " AND ".join(where)) if where else ""
    total = conn.execute(
        f"""SELECT COUNT(*) AS n FROM (
                SELECT q.id FROM answer_attempts a
                JOIN questions q ON q.id = a.question_id
                WHERE a.correct = 0
                  AND q.answer IS NOT NULL AND q.answer != ''
                  {extra}
                GROUP BY q.id
            ) sub""",
        params,
    ).fetchone()["n"]
    rows = conn.execute(
        f"""SELECT q.id, q.source_id, q.source_url, q.question_text,
                   q.option_a, q.option_b, q.option_c, q.option_d, q.option_e,
                   q.answer, q.explanation, q.subject, q.paper_title,
                   q.years, q.q_type, MAX(a.id) AS last_attempt_id
            FROM answer_attempts a
            JOIN questions q ON q.id = a.question_id
            WHERE a.correct = 0
              AND q.answer IS NOT NULL AND q.answer != ''
              {extra}
            GROUP BY q.id
            ORDER BY last_attempt_id DESC
            LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "questions": [dict(r) for r in rows],
    }
