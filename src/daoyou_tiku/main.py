"""FastAPI application: crawler backend + quiz API + static frontend."""
from __future__ import annotations

import random
import sqlite3
import uuid
from pathlib import Path

from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from . import service
from .db import connect

app = FastAPI(title="导游证考题爬虫与答题服务", version="0.2.0")

FRONTEND_DIST = "frontend/dist"


@app.on_event("startup")
def _backfill_subjects_on_startup() -> None:
    """Classify existing questions by source mapping on startup (idempotent)."""
    service.backfill_subjects()
    service.backfill_provinces()
    service.backfill_question_types()


class SourceIn(BaseModel):
    url: str
    kind: str = "static_page"
    config: dict = {}

    @field_validator("url")
    @classmethod
    def _url_scheme(cls, v: str) -> str:
        if v.startswith("fixture://"):
            return v
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("url must be http(s):// or fixture://")
        return v


class AnswerIn(BaseModel):
    answer: str


# ---- sources ---------------------------------------------------------

@app.get("/api/sources")
def list_sources():
    conn = connect()
    rows = conn.execute(
        """SELECT id, url, title, kind, status, detail, question_count,
                  last_analyzed_at, refresh_interval_seconds, last_refresh_at,
                  created_at
           FROM crawl_sources ORDER BY id DESC"""
    ).fetchall()
    conn.close()
    return {"sources": [dict(r) for r in rows]}


@app.post("/api/sources")
def add_source(payload: SourceIn):
    result = service.add_source_and_crawl(
        str(payload.url), kind=payload.kind, config=payload.config
    )
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result)
    return result


@app.post("/api/sources/{source_id}/refresh")
def refresh_source(source_id: int):
    result = service.refresh_source(source_id)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result)
    return result


@app.delete("/api/sources/{source_id}")
def delete_source(source_id: int):
    if not service.remove_source(source_id):
        raise HTTPException(status_code=404, detail={"reason": "source not found"})
    return {"ok": True}


class IntervalIn(BaseModel):
    interval_seconds: int


@app.put("/api/sources/{source_id}/interval")
def set_source_interval(source_id: int, payload: IntervalIn):
    result = service.set_refresh_interval(source_id, payload.interval_seconds)
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=result)
    return result


@app.get("/api/sources/due")
def list_due_sources():
    return {"sources": service.due_sources()}


@app.post("/api/sources/refresh-due")
def refresh_due_sources():
    return service.refresh_due_sources()


# ---- questions -------------------------------------------------------

@app.get("/api/questions")
def list_questions(
    source_id: int | None = Query(None),
    answered: bool | None = Query(None, description="filter by known answer"),
    subject: int | None = Query(None, ge=1, le=4, description="filter by exam subject (1-4)"),
    province: str | None = Query(None, description="filter by province name"),
    year: int | None = Query(None, ge=1990, le=2100, description="filter by exam year"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    conn = connect()
    where, params = [], []
    if source_id is not None:
        where.append("source_id = ?")
        params.append(source_id)
    if subject is not None:
        where.append("subject = ?")
        params.append(subject)
    if province is not None:
        # province holds a comma-separated list for multi-province titles
        where.append("(',' || province || ',') LIKE ?")
        params.append(f"%,{province},%")
    if year is not None:
        # year appears as a standalone token inside the comma-separated years column
        where.append("(',' || years || ',') LIKE ?")
        params.append(f"%,{year},%")
    if answered is True:
        where.append("answer IS NOT NULL AND answer != ''")
    elif answered is False:
        where.append("answer IS NULL OR answer = ''")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM questions {clause}", params
    ).fetchone()["n"]
    rows = conn.execute(
        f"""SELECT id, source_id, source_url, question_text, option_a, option_b,
                   option_c, option_d, option_e, answer, explanation, subject,
                   paper_title, province, years, q_type, created_at
            FROM questions {clause}
            ORDER BY years DESC, id DESC LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    return {"total": total, "limit": limit, "offset": offset, "questions": [dict(r) for r in rows]}


@app.get("/api/questions/{question_id}")
def get_question(question_id: int):
    conn = connect()
    row = conn.execute(
        """SELECT id, source_id, source_url, question_text, option_a, option_b,
                  option_c, option_d, option_e, answer, explanation, subject,
                  paper_title, province, years, q_type, created_at
           FROM questions WHERE id = ?""",
        (question_id,),
    ).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail={"reason": "question not found"})
    return dict(row)


@app.get("/api/quiz")
def create_quiz(
    size: int = Query(10, ge=1, le=100),
    answered_only: bool = Query(True, description="only questions with known answers"),
    subject: int | None = Query(None, ge=1, le=4, description="only questions of this subject (1-4)"),
    source_id: int | None = Query(None, description="only questions from this source"),
    year: int | None = Query(None, ge=1990, le=2100, description="only questions from this exam year"),
):
    conn = connect()
    where, params = [], []
    if answered_only:
        where.append("answer IS NOT NULL AND answer != ''")
    if subject is not None:
        where.append("subject = ?")
        params.append(subject)
    if source_id is not None:
        where.append("source_id = ?")
        params.append(source_id)
    if year is not None:
        where.append("(',' || years || ',') LIKE ?")
        params.append(f"%,{year},%")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    ids = conn.execute(
        f"SELECT id FROM questions {clause} ORDER BY years DESC, id DESC", params
    ).fetchall()
    conn.close()
    if not ids:
        raise HTTPException(status_code=404, detail={"reason": "no questions available"})
    picked = random.sample([r["id"] for r in ids], k=min(size, len(ids)))
    return {"quiz_id": "-".join(map(str, picked)), "question_ids": picked}


@app.post("/api/check")
def check_answer(payload: AnswerIn, question_id: int = Query(...)):
    conn = connect()
    row = conn.execute(
        "SELECT answer, explanation, q_type FROM questions WHERE id = ?", (question_id,)
    ).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail={"reason": "question not found"})
    given = payload.answer.strip().upper()
    # 判断题答案存中文（正确/错误），多选题存拼接串（ABCD）：
    # 前端统一提交字母，此处按 q_type 归一化后判分（顺序无关）。
    q_type = row["q_type"]
    answer = str(row["answer"] or "")
    if q_type == 3 and answer in ("正确", "错误"):
        ref = "A" if answer == "正确" else "B"
    else:
        ref = answer.upper()
    if q_type == 2:
        norm = lambda s: sorted(s.replace(",", ""))
        correct = bool(ref) and norm(given) == norm(ref)
    else:
        correct = bool(ref) and given == ref
    conn.execute(
        "INSERT INTO answer_attempts (question_id, selected, correct) VALUES (?, ?, ?)",
        (question_id, given, 1 if correct else 0),
    )
    conn.commit()
    conn.close()
    return {
        "question_id": question_id,
        "correct": correct,
        "answer": ref,
        "explanation": row["explanation"],
    }


@app.get("/api/stats")
def stats():
    conn = connect()
    questions = conn.execute("SELECT COUNT(*) AS n FROM questions").fetchone()["n"]
    answered = conn.execute(
        "SELECT COUNT(*) AS n FROM questions WHERE answer IS NOT NULL AND answer != ''"
    ).fetchone()["n"]
    sources = conn.execute("SELECT COUNT(*) AS n FROM crawl_sources").fetchone()["n"]
    sources_ready = conn.execute(
        "SELECT COUNT(*) AS n FROM crawl_sources WHERE status = 'ready'"
    ).fetchone()["n"]
    attempts = conn.execute("SELECT COUNT(*) AS n FROM answer_attempts").fetchone()["n"]
    correct = conn.execute(
        "SELECT COUNT(*) AS n FROM answer_attempts WHERE correct = 1"
    ).fetchone()["n"]
    conn.close()
    return {
        "questions": questions,
        "answered": answered,
        "sources": sources,
        "sources_ready": sources_ready,
        "attempts": attempts,
        "correct": correct,
        "accuracy": round(correct / attempts, 3) if attempts else None,
    }


@app.get("/api/attempts")
def list_attempts(limit: int = Query(50, ge=1, le=500)):
    conn = connect()
    rows = conn.execute(
        """SELECT a.id, a.question_id, a.selected, a.correct, a.created_at,
                  q.question_text, q.answer
           FROM answer_attempts a
           JOIN questions q ON q.id = a.question_id
           ORDER BY a.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return {"attempts": [dict(r) for r in rows]}


# ---- 错题本（重练） ---------------------------------------------------

@app.get("/api/wrong")
def list_wrong_questions(
    subject: int | None = Query(None, ge=1, le=4, description="filter by exam subject (1-4)"),
    source_id: int | None = Query(None, description="filter by question source"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """错题本：答错过的题（去重，最新作答优先），支持科目/来源过滤。"""
    return service.wrong_questions(subject=subject, source_id=source_id, limit=limit, offset=offset)


# ---- 真实笔试模拟 ------------------------------------------------------

class ExamSubmitIn(BaseModel):
    paper_id: str
    answers: list[dict]  # [{question_id, answer}]


class ExamCheckIn(BaseModel):
    paper_id: str
    question_id: int
    answer: str


# In-memory paper cache: paper_id -> list of question dicts.
# A finished paper is scored against the exact questions it was built from.
_EXAM_PAPERS: dict[str, list[dict]] = {}


@app.get("/api/exam")
def get_exam(
    paper_type: int = Query(1, ge=1, le=2),
):
    """Build a real-exam-style paper: 科目一+二 (1) or 科目三+四 (2),
    单选45/多选35/判断40 capped at bank supply, 165 minutes."""
    conn = connect()
    paper = service.build_exam_paper(conn, paper_type)
    conn.close()
    paper_id = uuid.uuid4().hex
    # keep the full rows (including answer) for later scoring; the client
    # only ever sees the sanitized question payload below.
    _EXAM_PAPERS[paper_id] = [dict(q) for q in paper["questions"]]
    questions = [
        {
            "id": q["id"],
            "question_text": q["question_text"],
            "options": [
                o
                for o in (q["option_a"], q["option_b"], q["option_c"], q["option_d"], q["option_e"])
                if o
            ],
            "q_type": q["q_type"],
            "subject": q["subject"],
            "province": q["province"],
            "years": q["years"],
            "source_url": q["source_url"],
        }
        for q in paper["questions"]
    ]
    return {
        "paper_id": paper_id,
        "paper_type": paper["paper_type"],
        "label": paper["label"],
        "minutes": paper["minutes"],
        "type_counts": paper["type_counts"],
        "total": len(questions),
        "questions": questions,
    }


@app.post("/api/exam/check")
def check_exam_question(body: ExamCheckIn):
    """Score one question of a live paper immediately (per-question mode).
    Unlike submit, the paper stays in the cache for further checks and the
    final submit. Multi-choice is order-insensitive."""
    questions = _EXAM_PAPERS.get(body.paper_id)
    if questions is None:
        return JSONResponse(status_code=404, content={"detail": "paper not found"})
    q = next((x for x in questions if x["id"] == body.question_id), None)
    if q is None:
        return JSONResponse(status_code=404, content={"detail": "question not in paper"})
    scored = service.exam_score(
        [{"question_id": q["id"], "answer": body.answer}], [q]
    )
    d = scored["details"][0]
    return {
        "question_id": q["id"],
        "correct": d["correct"],
        "answer": q.get("answer"),
        "explanation": q.get("explanation") or "",
        "question_text": q.get("question_text", ""),
        "q_type": q.get("q_type"),
    }


@app.post("/api/exam/submit")
def submit_exam(body: ExamSubmitIn):
    """Score a finished paper against the exact paper it was built from
    (matched by paper_id). Results never persist; paper is stateless."""
    questions = _EXAM_PAPERS.pop(body.paper_id, None)
    if questions is None:
        return JSONResponse(status_code=404, content={"detail": "paper not found or already submitted"})
    return service.exam_score(body.answers, questions)


# ---- static frontend (Vite build output) -----------------------------

Path(FRONTEND_DIST).mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=FRONTEND_DIST), name="static")


@app.get("/")
def index():
    return FileResponse(f"{FRONTEND_DIST}/index.html")
