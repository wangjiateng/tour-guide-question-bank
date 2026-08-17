"""Adapter-layer tests: multi-source crawling and the sync pipeline.

Covers the new observable contracts:
- fixture adapter yields deterministic questions without network
- json_api adapter pages through an endpoint and normalizes entries
- refresh updates changed answers (latest source data wins) and skips
  unchanged rows (incremental sync)
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from daoyou_tiku import db as db_module
from daoyou_tiku.adapters import (
    FetchResult,
    FixtureAdapter,
    JsonApiAdapter,
    SourceAdapter,
    build_adapter,
)
from daoyou_tiku.crawler import ParsedQuestion
from daoyou_tiku.db import connect
from daoyou_tiku.service import (
    add_source_and_crawl,
    backfill_subjects,
    classify_question_subject,
    refresh_source,
    subject_for_source,
)

TEST_DB = Path(__file__).resolve().parent / "test_adapters.db"


@pytest.fixture(autouse=True)
def isolate_db(monkeypatch: pytest.MonkeyPatch) -> None:
    TEST_DB.unlink(missing_ok=True)
    monkeypatch.setattr(db_module, "DEFAULT_DB", TEST_DB)
    from daoyou_tiku import service as service_module

    patched = db_module.connect
    monkeypatch.setattr(db_module, "connect", patched)
    monkeypatch.setattr(service_module, "connect", patched)
    yield
    TEST_DB.unlink(missing_ok=True)


# ---------------------------------------------------------------- adapters

FIXTURE = FixtureAdapter("https://demo.local/fixture", {})


def test_fixture_adapter_deterministic():
    page = FIXTURE.fetch_page(0)
    assert len(page.questions) == 6
    assert all(q.answer for q in page.questions)
    assert page.has_more is False
    again = FIXTURE.fetch_page(0)
    assert [q.question_text for q in again.questions] == [
        q.question_text for q in page.questions
    ]


def test_build_adapter_unknown_kind_raises():
    with pytest.raises(Exception):
        build_adapter("bogus", "https://x.local/", {})


def test_json_api_adapter_pages_and_normalizes():
    pages = [
        [
            {"question": f"q{i}", "options": {"A": "a", "B": "b", "C": "c", "D": "d"}, "answer": "A"}
            for i in range(3)
        ],
        [
            {"question": f"q{i}", "options": {"A": "a", "B": "b", "C": "c", "D": "d"}, "answer": "B"}
            for i in range(3, 5)
        ],
        [],
    ]

    app = FastAPI()

    @app.get("/api/questions")
    def questions(page: int = 1):
        return {"data": pages[page - 1], "has_more": page < len(pages)}

    server = threading.Thread(
        target=uvicorn.run,
        args=(app,),
        kwargs={"host": "127.0.0.1", "port": 8765, "log_level": "warning"},
        daemon=True,
    )
    server.start()
    try:
        adapter = JsonApiAdapter(
            "http://127.0.0.1:8765/api/questions",
            {"page_size": 3, "data_path": "data", "has_more_path": "has_more"},
        )
        out = adapter.fetch_page(0)
        assert len(out.questions) == 3 and out.has_more
        out = adapter.fetch_page(1)
        assert len(out.questions) == 2 and out.has_more
        out = adapter.fetch_page(2)
        assert len(out.questions) == 0 and not out.has_more
    finally:
        server.join(timeout=2)


# ---------------------------------------------------------------- sync pipeline

def test_fixture_source_add_and_refresh():
    """Adding a fixture source stores its questions; refresh is incremental
    (0 inserted again) and answer updates land."""
    url = "fixture://tour-guide-demo"
    first = add_source_and_crawl(url, kind="fixture", config={})
    assert first["ok"]
    assert first["questions_found"] == 6
    assert first["questions_inserted"] == 6
    assert first["source_id"] > 0

    second = refresh_source(first["source_id"])
    assert second["ok"]
    assert second["questions_inserted"] == 0, "incremental sync must not duplicate"

    # answer change on the same question must propagate
    conn = connect()
    conn.execute(
        """UPDATE questions SET answer='A'
           WHERE question_text LIKE '%旅游日%'"""
    )
    conn.commit()
    conn.close()

    refreshed = refresh_source(first["source_id"])
    assert refreshed["questions_inserted"] == 0
    conn = connect()
    row = conn.execute(
        """SELECT answer FROM questions WHERE question_text LIKE '%旅游日%'"""
    ).fetchone()
    conn.close()
    assert row["answer"] == "B", "refresh must restore latest source answer"


def test_json_api_source_end_to_end():
    """A real HTTP paged JSON endpoint is fully drained into the DB
    (3 pages -> 7 questions), and a re-crawl inserts nothing (dedup)."""
    from fixture_server import serve

    server = serve(18926)
    try:
        url = "http://127.0.0.1:18926/api/questions"
        first = add_source_and_crawl(
            url,
            kind="json_api",
            config={"page_size": 3, "data_path": "data", "has_more_path": "has_more"},
        )
        assert first["ok"]
        assert first["questions_found"] == 7
        assert first["questions_inserted"] == 7
        assert first["pages_fetched"] == 3

        again = refresh_source(first["source_id"])
        assert again["questions_inserted"] == 0
        assert again["questions_updated"] == 0

        conn = connect()
        total = conn.execute("SELECT COUNT(*) AS n FROM questions").fetchone()["n"]
        conn.close()
        assert total == 7, "HTTP source must land exactly its 7 questions"
    finally:
        server.shutdown()


# ---------------------------------------------------------------- examcoo answers

def test_examcoo_answer_bitmask_mapping():
    """Examcoo answer codes are decimal bitmasks over A-D slots:
    1=A, 2=B, 4=C, 8=D; 判断 uses 1=正确/2=错误."""
    from daoyou_tiku.examcoo import _answer_letters

    assert _answer_letters("3", "1") == "A"
    assert _answer_letters("3", "2") == "B"
    assert _answer_letters("3", "8") == "D"
    assert _answer_letters("4", "5") == "AC"      # 1 + 4
    assert _answer_letters("4", "15") == "ABCD"   # 1+2+4+8
    assert _answer_letters("4", "7") == "ABC"
    assert _answer_letters("4", "10") == "BD"
    assert _answer_letters("1.5", "1") == "正确"
    assert _answer_letters("1.5", "2") == "错误"


def test_examcoo_answer_bitmask_beyond_four_options():
    """5+ option questions: bitmask slots 16/32/64 map to E/F/G when the
    question has that many options; bits beyond the actual options keep
    the raw number instead of phantom letters."""
    from daoyou_tiku.examcoo import _answer_letters

    assert _answer_letters("4", "16", 5) == "E"        # 5th option
    assert _answer_letters("4", "27", 5) == "ABDE"     # 1+2+8+16
    assert _answer_letters("4", "48", 6) == "EF"       # 16+32
    assert _answer_letters("4", "127", 7) == "ABCDEFG"  # all 7 slots
    # mask references an option the question does not have -> raw number
    assert _answer_letters("4", "16", 4) == "16"
    assert _answer_letters("4", "32", 5) == "32"


def test_examcoo_parse_five_plus_options():
    """5+ option payloads: option_e holds the 5th option (and any further
    ones appended), and the bitmask answer decodes against the real
    option count."""
    from daoyou_tiku.examcoo import _parse_question

    five = {
        "id": "s6_five",
        "a": "下列属于导游服务特点的有（ ）。",
        "b": '[{"o":"甲"},{"o":"乙"},{"o":"丙"},{"o":"丁"},{"o":"戊"}]',
        "c": "27",  # 1+2+8+16 -> A B D E
        "d": "4",
    }
    q = _parse_question(five)
    assert q is not None
    assert q.option_e == "戊"
    assert q.answer == "ABDE"

    # single-choice referencing the 5th option
    single = {
        "id": "s7_five_single",
        "a": "导游证的有效期是（ ）。",
        "b": '[{"o":"1年"},{"o":"2年"},{"o":"3年"},{"o":"4年"},{"o":"5年"}]',
        "c": "16",
        "d": "3",
    }
    qs = _parse_question(single)
    assert qs is not None and qs.answer == "E"
    assert qs.option_e == "5年"

    # six options: 6th option text survives in option_e, mask decodes F
    six = {
        "id": "s8_six",
        "a": "下列属于六选项题（ ）。",
        "b": '[{"o":"A1"},{"o":"B1"},{"o":"C1"},{"o":"D1"},{"o":"E1"},{"o":"F1"}]',
        "c": "32",
        "d": "4",
    }
    q6 = _parse_question(six)
    assert q6 is not None
    assert q6.option_e == "E1 F1"
    assert q6.answer == "F"

    # four options unchanged: no option_e, mask stays A-D
    four = {
        "id": "s9_four",
        "a": "常规四选项（ ）。",
        "b": '[{"o":"A1"},{"o":"B1"},{"o":"C1"},{"o":"D1"}]',
        "c": "15",
        "d": "4",
    }
    q4 = _parse_question(four)
    assert q4 is not None
    assert q4.option_e is None
    assert q4.answer == "ABCD"


def test_examcoo_parse_question_shapes():
    """Full question payload shapes parse into ParsedQuestion with letters
    and the paper view URL as source_url."""
    from daoyou_tiku.examcoo import _parse_question

    single = {
        "id": "s1_x",
        "a": "导游证的有效期为（ ）年。",
        "b": '[{"o":"1"},{"o":"2"},{"o":"3"},{"o":"5"}]',
        "c": "4",
        "d": "3",
    }
    q = _parse_question(single, source_url="https://www.examcoo.com/editor/do/view/id/1")
    assert q is not None
    assert q.question_text == "导游证的有效期为（ ）年。"
    assert q.option_c == "3"
    assert q.answer == "C"
    assert q.source_url == "https://www.examcoo.com/editor/do/view/id/1"

    # 判断: no options field -> 正确/错误 options, answer is the label
    judge = {"id": "s3_y", "a": "导游证有效期三年。（ ）", "c": "1", "d": "1.5"}
    qj = _parse_question(judge)
    assert qj is not None and qj.answer == "正确"
    assert qj.option_a == "正确" and qj.option_b == "错误"

    # 多选: bitmask answer -> concatenated letters
    multi = {
        "id": "s2_z",
        "a": "下列属于导游职责的有（ ）。",
        "b": '[{"o":"a"},{"o":"b"},{"o":"c"},{"o":"d"}]',
        "c": "13",
        "d": "4",
    }
    qm = _parse_question(multi)
    assert qm is not None and qm.answer == "ACD"

    # HTML entities in stems/options are decoded to plain text
    nbsp = {
        "id": "s4_n",
        "a": "下列选项中属于意外受伤的情况是&nbsp; &nbsp; &nbsp; 。",
        "b": '[{"o":"跌倒"},{"o":"摔伤"},{"o":"中暑"},{"o":"晕车"}]',
        "c": "7",
        "d": "3",
    }
    qn = _parse_question(nbsp)
    assert qn is not None
    assert "&nbsp;" not in qn.question_text
    assert qn.question_text == "下列选项中属于意外受伤的情况是 。"
    assert qn.answer == "ABC"

    # entity-only stem (a bare &nbsp;) is rejected as empty
    empty = {"id": "s5_e", "a": "&nbsp;", "b": '[{"o":"a"},{"o":"b"},{"o":"c"},{"o":"d"}]', "c": "1", "d": "3"}
    assert _parse_question(empty) is None


# ---------------------------------------------------------------- global dedup

def test_question_text_global_dedup_across_sources():
    """The same question text from two different sources is stored once:
    the DB schema unique index is on question_text, not source_url."""
    url_a = "https://example.org/source-a"
    url_b = "https://example.org/source-b"
    first = add_source_and_crawl(url_a, kind="fixture", config={})
    assert first["ok"]
    assert first["questions_inserted"] == 6

    # a second source sharing the same question text must not duplicate it
    class OverlapFixture(SourceAdapter):
        kind = "overlap_fixture"

        def fetch_page(self, page: int) -> FetchResult:
            if page != 0:
                return FetchResult([], has_more=False)
            return FetchResult(
                [
                    ParsedQuestion(
                        question_text="中国旅游日的日期是（ ）。",
                        option_a="5月1日",
                        option_b="5月19日",
                        option_c="6月1日",
                        option_d="10月1日",
                        answer="B",
                    )
                ],
                has_more=False,
            )

    from daoyou_tiku.adapters import ADAPTERS

    ADAPTERS["overlap_fixture"] = OverlapFixture
    try:
        second = add_source_and_crawl(url_b, kind="overlap_fixture", config={})
    finally:
        ADAPTERS.pop("overlap_fixture", None)
    assert second["ok"]
    assert second["questions_inserted"] == 0, "overlap must not insert a duplicate"
    assert second["questions_updated"] == 1, "overlap refreshes the existing row"

    conn = connect()
    total = conn.execute("SELECT COUNT(*) AS n FROM questions").fetchone()["n"]
    dup = conn.execute(
        """SELECT COUNT(*) AS n FROM (SELECT question_text FROM questions
           GROUP BY question_text HAVING COUNT(*) > 1)"""
    ).fetchone()["n"]
    conn.close()
    assert total == 6, "no duplicate rows after overlapping sources"
    assert dup == 0


# ---------------------------------------------------------------- subject classification

def test_subject_for_source_maps_examcoo_kids():
    """Examcoo subcategory ids in the source URL map to exam subjects 1-4."""
    assert subject_for_source("https://www.examcoo.com/paperlist/index/k/408/p/1", "examcoo") == 2
    assert subject_for_source("https://www.examcoo.com/paperlist/index/k/409/p/1", "examcoo") == 3
    # 413 规范服务 = 导游业务（科目二），少量法规题由题级规则修正为科目一
    assert subject_for_source("https://www.examcoo.com/paperlist/index/k/413/p/1", "examcoo") == 2
    # 411(外语)/414(应变能力)不再是地方导游知识, 不映射到科目四
    assert subject_for_source("https://www.examcoo.com/paperlist/index/k/411/p/1", "examcoo") is None
    assert subject_for_source("https://www.examcoo.com/paperlist/index/k/414/p/1", "examcoo") is None
    # non-examcoo kinds and unlisted kids stay unclassified
    assert subject_for_source("fixture://demo", "fixture") is None
    assert subject_for_source("https://www.examcoo.com/paperlist/index/k/999/p/1", "examcoo") is None


def test_classify_question_subject_keyword_overrides():
    """Per-question keyword rules override the source-level subject:
    legal markers -> 科目一, basic-knowledge markers -> 科目三."""
    # legal markers win even from a 科目二 source
    assert classify_question_subject("《云南省旅游条例》规定的原则是", 2) == 1
    assert classify_question_subject("解决合同争议的方法主要有", 2) == 1
    # basic-knowledge markers -> 科目三
    assert classify_question_subject("中国三大古瓷都是指", 2) == 3
    assert classify_question_subject("故宫的建筑特点", 3) == 3
    # plain tour-guide service questions keep the source subject
    assert classify_question_subject("导游人员身心健康的内涵包括身体健康及", 2) == 2
    assert classify_question_subject("地陪办理国内航班手续的做法", 2) == 2
    # bare 法 in 方法/做法 must not trigger legal
    assert classify_question_subject("游客患病，下面导游做法不正确的是", 2) == 2
    # unclassified source stays None
    assert classify_question_subject("导游证的有效期为", None) is None


def test_subject_column_stored_on_crawl_and_backfilled():
    """Inserted questions carry the source's subject; legacy rows without it
    are backfilled idempotently by backfill_subjects."""
    conn = connect()
    conn.execute(
        """INSERT INTO crawl_sources (id, url, kind, status, question_count)
           VALUES (1, 'https://www.examcoo.com/paperlist/index/k/409/p/1', 'examcoo',
                   'ready', 0)"""
    )
    # legacy rows created without a subject value
    conn.execute(
        """INSERT INTO questions (source_id, source_url, question_text)
           VALUES (1, 'https://www.examcoo.com/editor/do/view/id/1', '旧题一')"""
    )
    conn.execute(
        """INSERT INTO questions (source_id, source_url, question_text)
           VALUES (1, 'https://www.examcoo.com/editor/do/view/id/2', '旧题二')"""
    )
    conn.execute(
        """INSERT INTO crawl_sources (id, url, kind, status, question_count)
           VALUES (2, 'fixture://demo', 'fixture', 'ready', 0)"""
    )
    conn.execute(
        """INSERT INTO questions (source_id, source_url, question_text)
           VALUES (2, 'fixture://demo', 'fixture 题')"""
    )
    conn.commit()
    conn.close()

    updated = backfill_subjects()
    assert updated == 2, "only examcoo rows get a subject; fixture stays NULL"

    conn = connect()
    rows = conn.execute("SELECT question_text, subject FROM questions ORDER BY id").fetchall()
    conn.close()
    by_text = {r["question_text"]: r["subject"] for r in rows}
    assert by_text["旧题一"] == 3
    assert by_text["旧题二"] == 3
    assert by_text["fixture 题"] is None

    # idempotent: no further updates once classified
    assert backfill_subjects() == 0
