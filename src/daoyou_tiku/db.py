"""Database layer: SQLite schema and row helpers for the quiz store.

Schema invariants:
- questions are deduplicated by (source_url, question_text) via UNIQUE index
- crawl_sources keeps one row per discovered source with its own status
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent.parent / "data" / "quiz.db"

# Cross-platform normalization for dedupe. Same question text differs
# across platforms by punctuation, whitespace, full/half-width chars, or a
# leading question number; normalize so those variants collapse onto one
# stored question.
_FULLWIDTH_MAP = str.maketrans(
    "０１２３４５６７８９ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ：；，。！？（）［］｛｝＂＇～"
    "％×÷＝＋－",
    "0123456789abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ:;,。!?()[]{}\"'~"
    "%x÷=+-",
)


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


def normalize_question_text(text: str) -> str:
    """Normalize question text for cross-platform dedupe.

    Full-width -> half-width, punctuation families collapse onto one
    canonical form, whitespace collapses, a leading question number
    (``12.`` / ``12、`` / ``12．``) is stripped, and trailing dots are
    trimmed. Returns the normalized text ('' for blank input).
    """
    if not text:
        return ""
    t = text.translate(_FULLWIDTH_MAP)
    # punctuation families -> single canonical form
    for src, dst in (
        ("“”", '"'), ("‘’", "'"), ("（", "("), ("）", ")"),
        ("【", "["), ("】", "]"), ("｛", "{"), ("｝", "}"),
        ("。", "."), ("，", ","), ("、", ","), ("：", ":"), ("；", ";"),
        ("！", "!"), ("？", "?"), ("％", "%"), ("×", "x"), ("—", "-"),
    ):
        for ch in src:
            t = t.replace(ch, dst)
    # collapse all whitespace (incl. full-width space \u3000) to one space
    t = " ".join(t.split())
    # collapse whitespace inside brackets: "( )" -> "()", "[ ]" -> "[]"
    t = re.sub(r"\(\s+\)", "()", t)
    t = re.sub(r"\[\s+\]", "[]", t)
    t = re.sub(r"\{\s+\}", "{}", t)
    # strip a leading question number like "12." / "12、" / "12．"
    t = re.sub(r"^\d+[.,、:：．]\s*", "", t)
    # trim trailing whitespace/dots
    return t.rstrip(" .")

SCHEMA_TABLES = """
CREATE TABLE IF NOT EXISTS crawl_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    title TEXT DEFAULT '',
    kind TEXT DEFAULT 'web',
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|analyzing|ready|failed
    detail TEXT DEFAULT '',
    last_analyzed_at TEXT,
    question_count INTEGER DEFAULT 0,
    refresh_interval_seconds INTEGER DEFAULT 86400,
    last_refresh_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES crawl_sources(id) ON DELETE CASCADE,
    source_url TEXT NOT NULL,
    question_text TEXT NOT NULL,
    option_a TEXT,
    option_b TEXT,
    option_c TEXT,
    option_d TEXT,
    option_e TEXT,
    answer TEXT,
    explanation TEXT,          -- 答案解析
    subject INTEGER,             -- 1=政策法规 2=导游业务 3=基础知识 4=地方知识
    paper_title TEXT,            -- source paper title captured at crawl time
    paper_subject INTEGER,       -- exam subject signalled by the paper title
    province TEXT,               -- 省份, 从 paper_title 提取 (多省逗号分隔)
    years TEXT,                  -- comma-separated exam years this question appeared in (e.g. "2011,2012")
    q_type INTEGER,              -- 1=single 2=multiple 3=true/false
    norm_text TEXT,              -- normalized question text for cross-platform dedupe
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(question_text),
    UNIQUE(norm_text)
);

CREATE TABLE IF NOT EXISTS answer_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
    selected TEXT NOT NULL,
    correct INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

# backward-compatible alias for tests/imports that reference SCHEMA
SCHEMA = SCHEMA_TABLES


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    if db_path is None:
        db_path = DEFAULT_DB
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # 1) create tables if missing (fresh DBs get the subject column)
    conn.executescript(SCHEMA_TABLES)
    # 2) lightweight migrations: add columns missing on older DBs, so the
    #    index statements below can reference them
    qcols = {r[1] for r in conn.execute("PRAGMA table_info(questions)")}
    if "subject" not in qcols:
        conn.execute("ALTER TABLE questions ADD COLUMN subject INTEGER")
    if "explanation" not in qcols:
        conn.execute("ALTER TABLE questions ADD COLUMN explanation TEXT")
    if "paper_title" not in qcols:
        conn.execute("ALTER TABLE questions ADD COLUMN paper_title TEXT")
    if "paper_subject" not in qcols:
        conn.execute("ALTER TABLE questions ADD COLUMN paper_subject INTEGER")
    if "province" not in qcols:
        conn.execute("ALTER TABLE questions ADD COLUMN province TEXT")
    if "years" not in qcols:
        conn.execute("ALTER TABLE questions ADD COLUMN years TEXT")
    if "q_type" not in qcols:
        conn.execute("ALTER TABLE questions ADD COLUMN q_type INTEGER")
    if "norm_text" not in qcols:
        conn.execute("ALTER TABLE questions ADD COLUMN norm_text TEXT")
    if "option_e" not in qcols:
        conn.execute("ALTER TABLE questions ADD COLUMN option_e TEXT")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(crawl_sources)")}
    if "refresh_interval_seconds" not in cols:
        conn.execute(
            "ALTER TABLE crawl_sources ADD COLUMN refresh_interval_seconds INTEGER DEFAULT 86400"
        )
    if "last_refresh_at" not in cols:
        conn.execute("ALTER TABLE crawl_sources ADD COLUMN last_refresh_at TEXT")
    if "config" not in cols:
        conn.execute("ALTER TABLE crawl_sources ADD COLUMN config TEXT DEFAULT ''")
    # 3) indexes on the final column set (skip any whose column is missing
    #    on a legacy table so connect() never fails on partial schemas)
    qcols = {r[1] for r in conn.execute("PRAGMA table_info(questions)")}
    if "source_id" in qcols:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_questions_source ON questions(source_id)")
    if "answer" in qcols:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_questions_answer ON questions(answer)")
    if "subject" in qcols:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_questions_subject ON questions(subject)")
    # backfill norm_text for rows stored before the column existed (NULLs
    # would bypass the unique index and let cross-platform variants duplicate)
    if "norm_text" in qcols:
        missing_norm = conn.execute(
            "SELECT id, question_text FROM questions WHERE norm_text IS NULL OR norm_text = ''"
        ).fetchall()
        for row in missing_norm:
            conn.execute(
                "UPDATE questions SET norm_text = ? WHERE id = ?",
                (normalize_question_text(row["question_text"]), row["id"]),
            )
        # merge pre-existing normalized duplicates (stored before norm_text
        # existed): same normalized text from different platforms/papers may
        # have been inserted as separate rows. Keep the earliest row,
        # redirect answer_attempts to it, merge years, then delete the
        # duplicates. Only runs when duplicates actually exist (idempotent).
        dup_groups = conn.execute(
            """SELECT norm_text, COUNT(*) AS n
               FROM questions
               GROUP BY norm_text HAVING n > 1"""
        ).fetchall()
        for group in dup_groups:
            norm = group["norm_text"]
            rows = conn.execute(
                "SELECT id, years FROM questions WHERE norm_text = ? ORDER BY id",
                (norm,),
            ).fetchall()
            keep_id = rows[0]["id"]
            drop_ids = [r["id"] for r in rows[1:]]
            merged_years = rows[0]["years"]
            for r in rows[1:]:
                merged_years = _merge_years(merged_years, r["years"])
            conn.execute(
                "UPDATE answer_attempts SET question_id = ? WHERE question_id IN (%s)"
                % ",".join("?" * len(drop_ids)),
                [keep_id, *drop_ids],
            )
            conn.execute(
                "UPDATE questions SET years = ? WHERE id = ?",
                (merged_years, keep_id),
            )
            conn.execute(
                "DELETE FROM questions WHERE id IN (%s)" % ",".join("?" * len(drop_ids)),
                drop_ids,
            )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_questions_norm ON questions(norm_text)"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_attempts_question ON answer_attempts(question_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_attempts_created ON answer_attempts(created_at)"
    )
    conn.commit()
    return conn
