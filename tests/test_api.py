"""API integration tests: source lifecycle + quiz flow against a temp DB."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from daoyou_tiku import main
from daoyou_tiku import db as db_module
from fixture_server import serve

TEST_DB = Path(__file__).resolve().parent / "test_quiz.db"


@pytest.fixture(autouse=True)
def isolate_db(monkeypatch: pytest.MonkeyPatch) -> None:
    TEST_DB.unlink(missing_ok=True)
    monkeypatch.setattr(db_module, "DEFAULT_DB", TEST_DB)
    # service and main bind `connect` at import time; patch every importer
    # so the whole stack writes to the temp DB.
    from daoyou_tiku import service as service_module

    patched = db_module.connect
    monkeypatch.setattr(db_module, "connect", patched)
    monkeypatch.setattr(service_module, "connect", patched)
    monkeypatch.setattr(main, "connect", patched)
    yield
    TEST_DB.unlink(missing_ok=True)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture(scope="module")
def source_url() -> str:
    server = serve(18933)
    yield f"http://127.0.0.1:18933/"
    server.shutdown()


def test_add_source_crawls_and_stores(client: TestClient, source_url: str) -> None:
    resp = client.post("/api/sources", json={"url": source_url})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["questions_found"] == 3

    stats = client.get("/api/stats").json()
    assert stats["questions"] == 3
    assert stats["answered"] == 3
    assert stats["sources"] == 1
    assert stats["sources_ready"] == 1


def test_add_source_rejects_non_question_url(client: TestClient) -> None:
    resp = client.post("/api/sources", json={"url": "http://127.0.0.1:1/"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["ok"] is False


def test_quiz_and_check_flow(client: TestClient, source_url: str) -> None:
    client.post("/api/sources", json={"url": source_url})
    quiz = client.get("/api/quiz?size=2&answered_only=true")
    assert quiz.status_code == 200
    ids = quiz.json()["question_ids"]
    assert len(ids) == 2

    # correct answer for q1 (fixture answer is B)
    first = client.get(f"/api/questions/{ids[0]}").json()
    right = client.post(f"/api/check?question_id={ids[0]}", json={"answer": first["answer"]})
    assert right.status_code == 200
    assert right.json()["correct"] is True

    wrong = client.post(f"/api/check?question_id={ids[0]}", json={"answer": "A"})
    assert wrong.json()["correct"] is (first["answer"] == "A")

    # attempts recorded for quiz statistics
    stats = client.get("/api/stats").json()
    assert stats["attempts"] == 2
    assert stats["accuracy"] is not None and 0 <= stats["accuracy"] <= 1
    history = client.get("/api/attempts").json()["attempts"]
    assert len(history) == 2
    assert {h["correct"] for h in history} == {True, False}
    assert history[0]["question_text"]


def test_list_questions_filters(client: TestClient, source_url: str) -> None:
    client.post("/api/sources", json={"url": source_url})
    answered = client.get("/api/questions?answered=true").json()
    assert answered["total"] == 3
    unanswered = client.get("/api/questions?answered=false").json()
    assert unanswered["total"] == 0


def test_delete_source_cascades(client: TestClient, source_url: str) -> None:
    client.post("/api/sources", json={"url": source_url})
    sources = client.get("/api/sources").json()["sources"]
    sid = sources[0]["id"]
    assert client.delete(f"/api/sources/{sid}").status_code == 200
    assert client.get("/api/stats").json()["questions"] == 0
    assert client.delete(f"/api/sources/{sid}").status_code == 404


def test_refresh_scheduling_flow(client: TestClient, source_url: str) -> None:
    """Interval 0 disables scheduling; due list honors interval + last refresh."""
    client.post("/api/sources", json={"url": source_url})
    sid = client.get("/api/sources").json()["sources"][0]["id"]

    # just crawled: not due with default 1-day interval
    assert client.get("/api/sources/due").json()["sources"] == []

    # backdate last_refresh_at -> due with default interval
    conn = db_module.connect()
    conn.execute(
        "UPDATE crawl_sources SET last_refresh_at = datetime('now', '-2 days') WHERE id = ?",
        (sid,),
    )
    conn.commit()
    conn.close()
    due = client.get("/api/sources/due").json()["sources"]
    assert [s["id"] for s in due] == [sid]

    # refresh-due re-crawls; dedup means no new rows; no longer due
    result = client.post("/api/sources/refresh-due").json()
    assert result["due"] == 1
    assert result["results"][0]["source_id"] == sid
    assert result["results"][0]["questions_inserted"] == 0
    assert client.get("/api/stats").json()["questions"] == 3
    assert client.get("/api/sources/due").json()["sources"] == []

    # interval 0 disables scheduling even with an old refresh stamp
    resp = client.put(
        f"/api/sources/{sid}/interval", json={"interval_seconds": 0}
    )
    assert resp.status_code == 200
    assert resp.json()["refresh_interval_seconds"] == 0
    conn = db_module.connect()
    conn.execute(
        "UPDATE crawl_sources SET last_refresh_at = datetime('now', '-2 days') WHERE id = ?",
        (sid,),
    )
    conn.commit()
    conn.close()
    assert client.get("/api/sources/due").json()["sources"] == []

    # negative interval rejected
    assert client.put(
        f"/api/sources/{sid}/interval", json={"interval_seconds": -1}
    ).status_code == 404
    # unknown source rejected
    assert client.put("/api/sources/9999/interval", json={"interval_seconds": 1}).status_code == 404


def test_exam_paper_and_scoring_flow(client: TestClient) -> None:
    """Real-exam paper: type counts, sanitized payload, score against the
    exact paper via paper_id, one-shot submit (404 on repeat)."""
    # seed the temp DB directly with enough 科目3/4 questions of each type
    conn = db_module.connect()
    conn.execute("INSERT INTO crawl_sources (url, title, kind, status) VALUES (?, 'exam', 'examcoo', 'ready')", ("http://exam.local/",))
    sid = conn.execute("SELECT id FROM crawl_sources ORDER BY id DESC LIMIT 1").fetchone()["id"]
    rows = []
    for q_type, label in ((1, "单选"), (2, "多选"), (3, "判断")):
        for i in range(60):
            rows.append(
                (sid, f"http://exam.local/q/{q_type}/{i}",
                 f"{label}题{i}：导游服务规范相关", "选项A", "选项B", "选项C", "选项D",
                 "A" if q_type != 3 else "正确", "", 3, None, None, None, q_type)
            )
    conn.executemany(
        """INSERT INTO questions
           (source_id, source_url, question_text, option_a, option_b,
            option_c, option_d, answer, explanation, subject, paper_title,
            paper_subject, years, q_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    # 前端提交字母：判断题中文答案映射为 A/B
    answers_by_id = {
        r["id"]: ("A" if r["answer"] == "正确" else r["answer"])
        for r in conn.execute("SELECT id, answer, q_type FROM questions")
    }
    conn.close()

    resp = client.get("/api/exam?paper_type=2")
    assert resp.status_code == 200
    paper = resp.json()
    assert paper["paper_id"]
    assert paper["total"] == 120
    assert {int(k): v for k, v in paper["type_counts"].items()} == {1: 45, 2: 35, 3: 40}
    # client payload must not leak answers
    q0 = paper["questions"][0]
    assert "answer" not in q0
    assert "explanation" not in q0

    # score every question correctly using the stored answers
    payload = [
        {"question_id": q["id"], "answer": answers_by_id[q["id"]]}
        for q in paper["questions"]
    ]
    scored = client.post(
        "/api/exam/submit", json={"paper_id": paper["paper_id"], "answers": payload}
    )
    assert scored.status_code == 200
    body = scored.json()
    assert body["total_score"] == 100.0
    assert body["full_score"] == 100.0
    assert len(body["details"]) == 120

    # one-shot: resubmitting the same paper_id is rejected
    again = client.post(
        "/api/exam/submit", json={"paper_id": paper["paper_id"], "answers": []}
    )
    assert again.status_code == 404

    # unknown paper_id rejected
    assert client.post(
        "/api/exam/submit", json={"paper_id": "deadbeef", "answers": []}
    ).status_code == 404


def test_exam_check_per_question(client: TestClient) -> None:
    """Per-question immediate scoring: correct/wrong verdict, paper stays
    alive for further checks and the final submit, 404 for unknown refs."""
    # seed the temp DB with 科目3 questions
    conn = db_module.connect()
    conn.execute("INSERT INTO crawl_sources (url, title, kind, status) VALUES (?, 'exam', 'examcoo', 'ready')", ("http://exam.local/check",))
    sid = conn.execute("SELECT id FROM crawl_sources ORDER BY id DESC LIMIT 1").fetchone()["id"]
    rows = [
        (sid, f"http://exam.local/q/{i}", f"判断题{i}：导游职责", "选项A", "选项B", "选项C", "选项D",
         "B", "", 3, None, None, None, 1)
        for i in range(60)
    ] + [
        (sid, f"http://exam.local/m{i}", f"多选题{i}：导游服务", "选项A", "选项B", "选项C", "选项D",
         "AC", "", 3, None, None, None, 2)
        for i in range(60)
    ] + [
        (sid, f"http://exam.local/j{i}", f"判断题{i}：导游行为", "正确", "错误", None, None,
         "正确", "", 3, None, None, None, 3)
        for i in range(60)
    ]
    conn.executemany(
        """INSERT INTO questions
           (source_id, source_url, question_text, option_a, option_b,
            option_c, option_d, answer, explanation, subject, paper_title,
            paper_subject, years, q_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    # 前端提交字母：判断题中文答案映射为 A/B
    answers_by_id = {
        r["id"]: ("A" if r["answer"] == "正确" else r["answer"])
        for r in conn.execute("SELECT id, answer, q_type FROM questions")
    }
    conn.close()

    paper = client.get("/api/exam?paper_type=2").json()
    pid = paper["paper_id"]
    q = paper["questions"][0]

    # correct answer -> correct verdict
    right = client.post(
        "/api/exam/check",
        json={"paper_id": pid, "question_id": q["id"], "answer": answers_by_id[q["id"]]},
    )
    assert right.status_code == 200
    body = right.json()
    assert body["correct"] is True
    assert body["answer"] == answers_by_id[q["id"]]
    assert "explanation" in body

    # wrong answer -> wrong verdict
    wrong = client.post(
        "/api/exam/check",
        json={"paper_id": pid, "question_id": q["id"], "answer": "ZZ"},
    )
    assert wrong.status_code == 200
    assert wrong.json()["correct"] is False

    # multi-choice order-insensitive
    m = next(x for x in paper["questions"] if x["q_type"] == 2)
    orderless = client.post(
        "/api/exam/check",
        json={"paper_id": pid, "question_id": m["id"], "answer": answers_by_id[m["id"]][::-1]},
    )
    assert orderless.json()["correct"] is True

    # paper stays alive after checks: full submit still scores
    all_answers = [
        {"question_id": x["id"], "answer": answers_by_id[x["id"]]}
        for x in paper["questions"]
    ]
    scored = client.post("/api/exam/submit", json={"paper_id": pid, "answers": all_answers})
    assert scored.status_code == 200
    assert scored.json()["total_score"] == 100.0

    # unknown paper / question -> 404
    assert client.post(
        "/api/exam/check", json={"paper_id": "nope", "question_id": 1, "answer": "A"}
    ).status_code == 404
    assert client.post(
        "/api/exam/check", json={"paper_id": pid, "question_id": 999999, "answer": "A"}
    ).status_code == 404


def test_exam_score_units() -> None:
    """Scoring edge cases: multi-choice order-insensitive, true/false,
    unknown questions skipped, empty answers never count as correct."""
    from daoyou_tiku.service import EXAM_TYPE_SCORES, exam_score

    questions = [
        {"id": 1, "q_type": 1, "answer": "A"},
        {"id": 2, "q_type": 2, "answer": "AC"},
        {"id": 3, "q_type": 3, "answer": "错误"},
    ]
    # 全对（多选乱序、判断题字母提交）
    r = exam_score(
        [
            {"question_id": 1, "answer": "A"},
            {"question_id": 2, "answer": "CA"},
            {"question_id": 3, "answer": "B"},
        ],
        questions,
    )
    assert r["total_score"] == sum(EXAM_TYPE_SCORES[t] for t in (1, 2, 3))
    assert all(d["correct"] for d in r["details"])

    # 多选缺项不算对
    r2 = exam_score([{"question_id": 2, "answer": "A"}], questions)
    assert not r2["details"][0]["correct"]

    # 空答案不算对
    r3 = exam_score([{"question_id": 1, "answer": ""}], questions)
    assert not r3["details"][0]["correct"]

    # 未知题号跳过，不计入
    r4 = exam_score([{"question_id": 999, "answer": "A"}], questions)
    assert r4["total_score"] == 0.0
    assert r4["details"] == []


def test_check_typed_scoring(client: TestClient) -> None:
    """/api/check scores by q_type: true/false (stored 中文, submitted
    letters) and multi-choice (submitted letters, order-insensitive)."""
    conn = db_module.connect()
    conn.execute("INSERT INTO crawl_sources (url, title, kind, status) VALUES (?, 't', 'static_page', 'ready')", ("http://check.local/",))
    sid = conn.execute("SELECT id FROM crawl_sources ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute(
        """INSERT INTO questions
           (source_id, source_url, question_text, option_a, option_b,
            option_c, option_d, answer, explanation, subject, paper_title,
            paper_subject, years, q_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (sid, "http://check.local/tf", "判断题：导游必须持证上岗", "正确", "错误", None, None,
         "正确", "依据《导游人员管理条例》", 1, None, None, None, 3),
    )
    conn.execute(
        """INSERT INTO questions
           (source_id, source_url, question_text, option_a, option_b,
            option_c, option_d, answer, explanation, subject, paper_title,
            paper_subject, years, q_type)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (sid, "http://check.local/multi", "多选题：导游服务的特点", "选项A", "选项B", "选项C", "选项D",
         "AD", "", 1, None, None, None, 2),
    )
    conn.commit()
    conn.close()

    tf = client.get("/api/questions?answered=true").json()["questions"]
    tf_id = next(q["id"] for q in tf if q["q_type"] == 3)
    multi_id = next(q["id"] for q in tf if q["q_type"] == 2)

    # 判断题：提交字母 A（=正确）判对；答案映射为 A 供前端高亮
    right = client.post(f"/api/check?question_id={tf_id}", json={"answer": "A"})
    assert right.status_code == 200
    assert right.json()["correct"] is True
    assert right.json()["answer"] == "A"
    wrong = client.post(f"/api/check?question_id={tf_id}", json={"answer": "B"})
    assert wrong.json()["correct"] is False

    # 多选题：顺序无关；缺项判错
    ok = client.post(f"/api/check?question_id={multi_id}", json={"answer": "DA"})
    assert ok.json()["correct"] is True
    partial = client.post(f"/api/check?question_id={multi_id}", json={"answer": "A"})
    assert partial.json()["correct"] is False
    over = client.post(f"/api/check?question_id={multi_id}", json={"answer": "ABCD"})
    assert over.json()["correct"] is False


def test_cross_platform_dedupe(client: TestClient, source_url: str) -> None:
    """跨平台去重: same questions with full-width punctuation/leading
    numbers from a second platform collapse onto the existing rows instead
    of duplicating; crawl reports deduped counts."""
    first = client.post("/api/sources", json={"url": source_url}).json()
    assert first["ok"] is True
    assert first["questions_inserted"] == 3

    # second platform serves the same 3 questions with full-width
    # punctuation, leading numbers, and full-width space brackets
    variant_url = "http://127.0.0.1:18933/api/variant"
    second = client.post("/api/sources", json={"url": variant_url, "kind": "json_api"}).json()
    assert second["ok"] is True
    assert second["questions_inserted"] == 0
    assert second["questions_deduped"] == 3

    # total question count did not double
    stats = client.get("/api/stats").json()
    assert stats["questions"] == 3

    # variant answer (B) refreshed the stored row; only 3 rows exist
    rows = db_module.connect().execute(
        "SELECT COUNT(*) AS n, SUM(CASE WHEN norm_text IS NOT NULL AND norm_text != '' THEN 1 ELSE 0 END) AS norm FROM questions"
    ).fetchone()
    assert rows["n"] == 3
    assert rows["norm"] == 3


def test_normalize_question_text() -> None:
    """规范化单元测试: full-width, punctuation families, whitespace,
    leading numbers collapse to one canonical form."""
    n = db_module.normalize_question_text
    assert n("１２．下列属于导游职责的是（　）") == "下列属于导游职责的是()"
    assert n("12、下列属于导游职责的是（　）") == "下列属于导游职责的是()"
    assert n("下列属于导游职责的是()") == "下列属于导游职责的是()"
    assert n("导游服务Ａ.正确　Ｂ.错误") == "导游服务A.正确 B.错误"
    assert n("") == ""


def test_legacy_db_dedupe_migration(tmp_path) -> None:
    """旧库迁移: pre-norm_text DB with cross-platform duplicates collapses
    on connect(); answer_attempts redirect to the kept row."""
    import sqlite3
    from daoyou_tiku import db as legacy_db

    p = tmp_path / "legacy.db"
    conn = sqlite3.connect(p)
    conn.executescript(
        """
        CREATE TABLE questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER, source_url TEXT NOT NULL,
            question_text TEXT NOT NULL,
            option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT,
            answer TEXT, explanation TEXT DEFAULT '', subject INTEGER,
            paper_title TEXT, paper_subject INTEGER, years TEXT, q_type INTEGER,
            created_at TEXT DEFAULT (datetime('now')), UNIQUE(question_text)
        );
        CREATE TABLE answer_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER, selected TEXT NOT NULL,
            correct INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        """
    )
    conn.execute(
        "INSERT INTO questions (source_url, question_text, answer) VALUES ('a','12. 下列属于导游职责的是（　）','B')"
    )
    conn.execute(
        "INSERT INTO questions (source_url, question_text, answer) VALUES ('b','下列属于导游职责的是()','B')"
    )
    conn.execute(
        "INSERT INTO questions (source_url, question_text, answer) VALUES ('c','导游证有效期（ ）年','C')"
    )
    conn.execute("INSERT INTO answer_attempts (question_id, selected, correct) VALUES (2, 'B', 1)")
    conn.commit()
    conn.close()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(legacy_db, "DEFAULT_DB", p)
    c = legacy_db.connect()
    assert c.execute("SELECT COUNT(*) n FROM questions").fetchone()["n"] == 2
    assert c.execute("SELECT question_id FROM answer_attempts").fetchone()["question_id"] == 1
    dup = c.execute("SELECT COUNT(*) c FROM questions GROUP BY norm_text HAVING COUNT(*) > 1").fetchall()
    assert len(dup) == 0
    c.close()
    monkeypatch.undo()


def test_wrong_questions_flow(client: TestClient, source_url: str) -> None:
    """错题本: wrong attempts dedupe per question, filters hold, answered
    questions only, newest wrong attempt sorts first."""
    client.post("/api/sources", json={"url": source_url})
    quiz = client.get("/api/quiz?size=3&answered_only=true").json()
    ids = quiz["question_ids"]
    assert len(ids) == 3

    # one question missed once, another missed twice, third never missed
    q1 = client.get(f"/api/questions/{ids[0]}").json()
    q2 = client.get(f"/api/questions/{ids[1]}").json()
    q3 = client.get(f"/api/questions/{ids[2]}").json()
    wrong_for_q1 = "A" if q1["answer"] != "A" else "B"
    wrong_for_q2 = "A" if q2["answer"] != "A" else "B"
    wrong_for_q3 = "A" if q3["answer"] != "A" else "B"

    assert client.post(f"/api/check?question_id={ids[0]}", json={"answer": wrong_for_q1}).json()["correct"] is False
    assert client.post(f"/api/check?question_id={ids[1]}", json={"answer": wrong_for_q2}).json()["correct"] is False
    assert client.post(f"/api/check?question_id={ids[1]}", json={"answer": wrong_for_q2}).json()["correct"] is False
    assert client.post(f"/api/check?question_id={ids[2]}", json={"answer": q3["answer"]}).json()["correct"] is True

    pool = client.get("/api/wrong").json()
    assert pool["total"] == 2
    assert {q["id"] for q in pool["questions"]} == {ids[0], ids[1]}
    # newest wrong attempt first: q2's second miss is the latest wrong attempt
    assert pool["questions"][0]["id"] == ids[1]
    assert pool["questions"][1]["id"] == ids[0]

    # subject filter: fixture questions carry NULL subject (source-level),
    # so a subject query must not crash and must return a valid envelope
    filtered = client.get("/api/wrong?subject=1").json()
    assert "total" in filtered and "questions" in filtered
    assert client.get("/api/wrong?subject=99").status_code == 422

    # pagination
    page = client.get("/api/wrong?limit=1&offset=1").json()
    assert page["total"] == 2
    assert len(page["questions"]) == 1
    assert page["questions"][0]["id"] == ids[0]

    # full question payload present for retraining
    first = pool["questions"][0]
    assert first["question_text"] and first["answer"] and first["option_a"]
    assert first["source_url"]
