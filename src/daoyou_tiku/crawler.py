"""Question crawler: parse tour-guide questions from analyzed sources.

Parse strategies (chosen by source fingerprint):
- html:        pages with option markers / answer markers in text
- quiz_engine: pages with radio-input forms; answers may be embedded
               in page JS (window.answerKey) or absent
- json_api:    sources returning JSON arrays of questions

Parsed questions are normalized into (question_text, option_a..d,
answer, explanation). Only entries with a question and at least two
options are stored; quizzes without answers are still stored but with
answer=None so the frontend can mark them as "unknown".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from .analyzer import SourceVerdict, analyze_source

OPTION_PATTERN = re.compile(r"(?<![一-龥])[（(]?\s*([A-D])[.、．:：)]\s*")
ANSWER_PATTERN = re.compile(
    r"(?:参考答案|答案|正确答案)[:：]?\s*[（(]?\s*([A-D]{1,4})\s*[)）]?", re.I
)


@dataclass
class ParsedQuestion:
    question_text: str
    option_a: str | None = None
    option_b: str | None = None
    option_c: str | None = None
    option_d: str | None = None
    option_e: str | None = None
    answer: str | None = None
    explanation: str = ""
    source_url: str = ""
    paper_title: str | None = None
    q_type: int | None = None  # 1=single 2=multiple 3=true/false

    def is_valid(self) -> bool:
        options = [self.option_a, self.option_b, self.option_c, self.option_d, self.option_e]
        return bool(self.question_text.strip()) and sum(
            1 for o in options if o and o.strip()
        ) >= 2


def _extract_answer(text: str) -> str | None:
    m = ANSWER_PATTERN.search(text)
    if m:
        return m.group(1).upper()
    return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _split_option_block(block: str) -> list[tuple[str, str]]:
    """Split 'A. xxx B. yyy C. zzz D. www' into [(letter, text), ...]."""
    parts = OPTION_PATTERN.split(block)
    # parts looks like ['', 'A', 'xxx ', 'B', 'yyy ', ...]
    result = []
    for i in range(1, len(parts) - 1, 2):
        result.append((parts[i], _clean(parts[i + 1])))
    return result


def parse_html(html: str) -> list[ParsedQuestion]:
    """Parse a plain HTML page where each question is a <p>/<li> block.

    Question text, options and answers may be in the same block or split
    across consecutive blocks; units are assembled in document order:
    - a block with option markers extends the current unit's options
    - a block with an answer marker sets the current unit's answer
    - a block that looks like a question starts a new unit
    - other text extends the current unit's question text
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    units: list[dict] = []
    for node in soup.find_all(["p", "li", "div", "h1", "h2", "h3", "h4"]):
        text = node.get_text(" ", strip=True)
        if len(text) < 4:
            continue

        options = _split_option_block(text)
        answer = _extract_answer(text)

        if options:
            if not units:
                units.append({"q": "", "options": [], "answer": None, "expl": ""})
            units[-1]["options"].extend(options)
            if answer:
                units[-1]["answer"] = answer
            continue

        if answer and units:
            units[-1]["answer"] = answer
            expl = _extract_explanation(text)
            if expl:
                units[-1]["expl"] = expl
            continue

        if _looks_like_question(text):
            units.append({"q": text, "options": [], "answer": None, "expl": ""})
        elif units:
            units[-1]["q"] = (units[-1]["q"] + " " + text).strip()

    questions: list[ParsedQuestion] = []
    for unit in units:
        if not unit["options"]:
            continue
        opts = unit["options"]
        q = ParsedQuestion(
            question_text=_clean(unit["q"]),
            option_a=opts[0][1] if len(opts) > 0 else None,
            option_b=opts[1][1] if len(opts) > 1 else None,
            option_c=opts[2][1] if len(opts) > 2 else None,
            option_d=opts[3][1] if len(opts) > 3 else None,
            answer=unit["answer"],
            explanation=unit["expl"],
        )
        if q.is_valid():
            questions.append(q)
    return questions


def _looks_like_question(text: str) -> bool:
    """A block starts a new question if it ends with a question mark or
    contains a question-number prefix and an answer slot."""
    if text.endswith(("？", "?")):
        return True
    if re.search(r"[（(]\s*[）)]", text):          # （ ） answer slot
        return True
    if re.match(r"^\d+[.、．]", text):               # "1. " numbering
        return True
    return False


def _extract_explanation(block: str) -> str:
    m = re.search(r"(?:解析|解释)[:：]\s*(.+)", block)
    return _clean(m.group(1)) if m else ""


def parse_quiz_engine(html: str) -> list[ParsedQuestion]:
    """Parse quiz-engine pages: <form> with radio inputs.

    Answers are read from an inline `window.answerKey` JS object when
    present; otherwise questions are stored with answer=None.
    """
    soup = BeautifulSoup(html, "lxml")
    answer_key: dict[str, str] = {}
    for script in soup.find_all("script"):
        text = script.string or ""
        if "answerKey" in text:
            m = re.search(r"answerKey\s*=\s*(\{.*?\})", text, re.S)
            if m:
                try:
                    answer_key = {
                        str(k): str(v).upper()
                        for k, v in json.loads(m.group(1)).items()
                    }
                except (json.JSONDecodeError, AttributeError):
                    answer_key = {}

    questions: list[ParsedQuestion] = []
    for form in soup.find_all("form") or [soup]:
        items = form.find_all("li") or form.find_all(
            "div", class_=re.compile("question|item", re.I)
        )
        for item in items:
            text = item.get_text(" ", strip=True)
            if not text or len(text) < 8:
                continue
            q_text, _, opt_text = text.partition("A.")
            if not opt_text:
                continue
            options = _split_option_block("A." + opt_text)
            if not options:
                continue
            qid = str(item.get("data-id") or item.get("id") or "")
            answer = answer_key.get(qid) or _extract_answer(text)
            q = ParsedQuestion(
                question_text=_clean(q_text),
                option_a=options[0][1] if len(options) > 0 else None,
                option_b=options[1][1] if len(options) > 1 else None,
                option_c=options[2][1] if len(options) > 2 else None,
                option_d=options[3][1] if len(options) > 3 else None,
                answer=answer,
            )
            if q.is_valid():
                questions.append(q)
    return questions


def parse_json_api(payload: dict | list) -> list[ParsedQuestion]:
    """Parse JSON question payloads with common field names."""
    raw = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(raw, dict):
        raw = raw.get("list") or raw.get("items") or raw.get("questions") or []
    if not isinstance(raw, list):
        return []

    questions: list[ParsedQuestion] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        options = entry.get("options") or entry.get("choices") or {}
        opts = options if isinstance(options, dict) else {}
        q = ParsedQuestion(
            question_text=_clean(str(entry.get("question") or entry.get("title") or "")),
            option_a=_clean(str(opts.get("A") or opts.get("a") or "")) or None,
            option_b=_clean(str(opts.get("B") or opts.get("b") or "")) or None,
            option_c=_clean(str(opts.get("C") or opts.get("c") or "")) or None,
            option_d=_clean(str(opts.get("D") or opts.get("d") or "")) or None,
            answer=(str(entry.get("answer") or "").upper() or None),
            explanation=_clean(str(entry.get("explanation") or "")),
        )
        if q.is_valid():
            questions.append(q)
    return questions


def crawl_source(url: str, timeout: float = 15.0) -> tuple[SourceVerdict, list[ParsedQuestion]]:
    """Analyze a source, then crawl questions from it. Returns (verdict, questions)."""
    verdict = analyze_source(url, timeout=timeout)
    if not verdict.ok or not verdict.html:
        return verdict, []

    if verdict.kind == "quiz_engine":
        questions = parse_quiz_engine(verdict.html)
    elif verdict.kind == "json_api":
        try:
            questions = parse_json_api(json.loads(verdict.html))
        except json.JSONDecodeError:
            questions = []
    else:
        questions = parse_html(verdict.html)
    return verdict, questions
