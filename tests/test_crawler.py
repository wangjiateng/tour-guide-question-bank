"""Analyzer + crawler parse tests: fingerprint scoring and HTML parsing.

Uses the local fixture server (no external network).
"""
from __future__ import annotations

import pytest

from daoyou_tiku.analyzer import analyze_source
from daoyou_tiku.crawler import parse_html, parse_quiz_engine, parse_json_api, crawl_source

from fixture_server import serve


@pytest.fixture(scope="module")
def fixture_server() -> str:
    server = serve(18931)
    yield f"http://127.0.0.1:18931/"
    server.shutdown()


def test_analyze_fixture_page_is_usable(fixture_server: str) -> None:
    verdict = analyze_source(fixture_server)
    assert verdict.ok is True
    assert verdict.kind == "web"
    assert verdict.score >= 3
    assert "question-marker" in verdict.signals
    assert verdict.title  # non-empty
    assert verdict.html  # raw html retained for the crawler


def test_analyze_unreachable_host_fails() -> None:
    verdict = analyze_source("http://127.0.0.1:1/", timeout=1.0)
    assert verdict.ok is False
    assert verdict.reason.startswith("fetch failed")
    assert verdict.html == ""


def test_crawl_source_extracts_three_questions(fixture_server: str) -> None:
    verdict, questions = crawl_source(fixture_server)
    assert verdict.ok is True
    assert len(questions) == 3
    for q in questions:
        assert q.is_valid()
        assert q.answer in {"A", "B", "C", "D"}
        assert q.option_b  # every question has options


def test_parse_html_option_and_answer_blocks() -> None:
    html = """
    <html><body>
    <p>1. 导游证的有效期为（ ）年。</p>
    <p>A. 1 B. 2 C. 3 D. 5</p>
    <p>参考答案：C</p>
    </body></html>
    """
    questions = parse_html(html)
    assert len(questions) == 1
    q = questions[0]
    assert q.question_text.startswith("1.")
    assert q.option_c == "3"
    assert q.answer == "C"


def test_parse_quiz_engine_reads_answer_key() -> None:
    html = """
    <html><body>
    <script>window.answerKey = {"q1": "B", "q2": "A"};</script>
    <form>
      <li data-id="q1">带团遇突发疾病游客应（ ）。A. 置之不理 B. 立即联系医疗机构 C. 继续行程 D. 自行处理</li>
      <li data-id="q2">中国旅游日是（ ）。A. 5月1日 B. 5月19日 C. 6月1日 D. 10月1日</li>
    </form>
    </body></html>
    """
    questions = parse_quiz_engine(html)
    assert len(questions) == 2
    assert questions[0].answer == "B"
    assert questions[1].answer == "A"


def test_parse_json_api_common_fields() -> None:
    payload = {
        "data": {
            "list": [
                {
                    "question": "导游人员必须持证上岗。",
                    "options": {"A": "正确", "B": "错误"},
                    "answer": "A",
                    "explanation": "依据导游人员管理条例。",
                }
            ]
        }
    }
    questions = parse_json_api(payload)
    assert len(questions) == 1
    q = questions[0]
    assert q.answer == "A"
    assert q.explanation.startswith("依据")


def test_parse_json_api_rejects_invalid_entries() -> None:
    payload = {"data": [{"question": "缺选项的题"}]}
    assert parse_json_api(payload) == []
