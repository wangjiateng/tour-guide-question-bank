"""Examcoo (考试酷) crawler: fetch tour-guide question banks.

Examcoo hosts a public question bank for the tour-guide qualification
exam (导游资格考试) under 5 subcategories:

- 408 导游业务
- 409 导游基础知识
- 411 导游外语
- 413 导游规范服务能力
- 414 导游特殊问题处理及应变能力

Crawl flow (pure HTTP, no browser/session required):

1. List pages ``/paperlist/index/k/{kid}/p/{n}`` return paper rows with
   ``/editor/do/view/id/{pid}`` links -> paper ids.
2. Loading ``/editor/do/exercise/pid/{pid}`` embeds a per-paper
   ``leid`` + ``vp4tokenleid`` pair in inline JS.
3. ``/editor/rpc/getexercisecontent/leid/{leid}/tokenleid/{token}``
   returns the full paper as JSON including answers.

Question JSON (``b`` array):
- ``b[0]``: paper metadata
- ``b[1]``: group header (question-type intro)
- ``b[2:]``: questions with fields:
  - ``a``: question text
  - ``b``: JSON string of options ``[{"o": "..."}]`` (absent for 判断题)
  - ``c``: answer — single index (单选), decimal bitmask (多选),
    or 1=正确/2=错误 (判断)
  - ``d``: type — ``3`` single choice, ``4`` multiple choice,
    ``1.5`` true/false

Answers are stored as letters: 1->A, 2->B, 4->C, 8->D for the bitmask
multi-choice case (1+4 = "AD", etc.).

Each question's ``source_url`` is the paper's public view page so the
frontend can link back to the original questions.
"""
from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass, field

import httpx

from .analyzer import USER_AGENT
from .crawler import ParsedQuestion

LIST_BASE = "https://www.examcoo.com/paperlist/index/k/{kid}/p/{page}"
EXERCISE_BASE = "https://www.examcoo.com/editor/do/exercise/pid/{pid}"
VIEW_BASE = "https://www.examcoo.com/editor/do/view/id/{pid}"
RPC_BASE = (
    "https://www.examcoo.com/editor/rpc/getexercisecontent/"
    "leid/{leid}/tokenleid/{token}"
)

SUBCATEGORIES: dict[str, str] = {
    "408": "导游业务",
    "409": "导游基础知识",
    "411": "导游外语",  # excluded: English-only papers, not 普通话 questions
    "413": "导游规范服务能力",
    "414": "导游特殊问题处理及应变能力",
}

# Subcategory ids excluded from crawling: 外语 (411) is English-only
# content; the product requires 普通话 (Chinese) tour-guide questions.
EXCLUDED_SUBCATEGORIES = {"411"}

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "zh-CN,zh;q=0.9",
}

PAPER_ROW_RE = re.compile(r"/editor/do/view/id/(\d+)")
# list-page row: <tr>...<td title="<paper title>">...<a href="/editor/do/view/id/<pid>"
_PAPER_TITLE_RE = re.compile(
    r'<tr>.*?title="([^"]+)"[^>]*>\s*[^<]{2,60}.*?/editor/do/view/id/(\d+)',
    re.S,
)
LEID_RE = re.compile(r'var\s+leid\s*=\s*"(\d+)"')
TOKEN_RE = re.compile(r'var\s+vp4tokenleid\s*=\s*"([0-9a-f]+)"')
TOTAL_RE = re.compile(r"(\d+)\s*条记录")

# Foreign-language paper titles (English-only content) to skip: the
# product keeps 普通话 (Chinese) tour-guide questions only.
_FOREIGN_PAPER_RE = re.compile(r"英语|外语|英文|English")


@dataclass
class ExamcooPaper:
    """One paper plus its fetched questions (answers resolved)."""

    pid: str
    title: str = ""
    questions: list[ParsedQuestion] = field(default_factory=list)
    source_url: str = ""
    total_questions: int = 0


def _clean(text: str) -> str:
    """Decode HTML entities then collapse whitespace.

    examcoo embeds raw HTML (e.g. ``&nbsp;`` non-breaking spaces in question
    stems, ``&lt;``/``&gt;`` around book titles). ``html.unescape`` turns them
    into real characters so stored text is plain; trailing entity-only stems
    (a bare ``&nbsp;``) collapse to empty and are rejected by callers.
    """
    if not text:
        return text
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _get(url: str, timeout: float = 20.0) -> httpx.Response:
    resp = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return resp


def list_paper_ids(kid: str, max_pages: int = 100, timeout: float = 20.0) -> list[str]:
    """All paper ids in one subcategory by walking its list pages."""
    return [pid for pid, _ in list_papers(kid, max_pages, timeout)]


def list_papers(
    kid: str, max_pages: int = 100, timeout: float = 20.0
) -> list[tuple[str, str]]:
    """All (paper_id, paper_title) pairs in one subcategory.

    The list page exposes each paper's real title (e.g. 「导游综合知识
    导游业务试卷和试题：6.29导游业务第1至第3章单选题」) which carries the
    true exam-subject signal — captured at crawl time instead of guessing
    from question text afterwards.
    """
    papers: list[tuple[str, str]] = []
    for page in range(1, max_pages + 1):
        html = _get(LIST_BASE.format(kid=kid, page=page), timeout=timeout).text
        found = [
            (pid, _clean(title))
            for title, pid in _PAPER_TITLE_RE.findall(html)
            if pid not in {p for p, _ in papers}
        ]
        if not found:
            break
        papers.extend(found)
        if len(found) < 25:
            break
    return papers


def _paper_leid_token(pid: str, timeout: float = 20.0) -> tuple[str, str] | None:
    """Load the exercise page and extract its embedded leid/token pair."""
    html = _get(EXERCISE_BASE.format(pid=pid), timeout=timeout).text
    leid = LEID_RE.search(html)
    token = TOKEN_RE.search(html)
    if not leid or not token:
        return None
    return leid.group(1), token.group(1)


def _answer_letters(type_code: str, answer_code: str, option_count: int = 4) -> str:
    """Map an examcoo answer code to letters.

    All types use a decimal bitmask over option slots:
    - 1 = A, 2 = B, 4 = C, 8 = D, 16 = E, 32 = F, 64 = G, 128 = H,
      combined for multi-choice (e.g. 27 over 5 options = "ABDE").
    - 判断 (1.5) stores 1=正确 / 2=错误; the option labels are used as
      the answer for display consistency.
    ``option_count`` caps decoding to the question's actual options:
    a mask bit referencing an option beyond the list keeps the raw
    number instead of emitting phantom letters.
    """
    try:
        code = int(answer_code)
    except (TypeError, ValueError):
        return answer_code.upper()

    if type_code == "1.5":
        return "正确" if code == 1 else "错误"

    letters: list[str] = []
    for bit in (1, 2, 4, 8, 16, 32, 64, 128):
        if code & bit:
            letters.append(chr(ord("A") + (bit.bit_length() - 1)))
    if not letters:
        return str(code)
    if len(letters) > option_count or ord(letters[-1]) - ord("A") >= option_count:
        # mask references an option beyond the actual options -> keep raw
        return str(code)
    return "".join(letters)


def _parse_question(raw: dict, source_url: str = "") -> ParsedQuestion | None:
    q_text = _clean(str(raw.get("a") or ""))
    if not q_text:
        return None

    type_code = str(raw.get("d") or "")
    answer_code = str(raw.get("c") or "")
    answer = _answer_letters(type_code, answer_code) if answer_code else None
    # examcoo type codes: 3=single, 4=multiple, 1.5=true/false
    q_type = {"3": 1, "4": 2, "1.5": 3}.get(type_code)

    option_text = raw.get("b")
    options: list[str] = []
    if option_text:
        try:
            parsed = json.loads(option_text) if isinstance(option_text, str) else option_text
            options = [_clean(str(o.get("o") or "")) for o in parsed if isinstance(o, dict)]
        except (json.JSONDecodeError, TypeError):
            options = []
    if not options and type_code == "1.5":
        options = ["正确", "错误"]

    # keep the first five lettered options (A-E): the schema/frontend
    # expose five option columns, and multi-choice bitmask answers may
    # reference the 5th slot (16 = E). Any further options (F, G, …)
    # are appended to option_e so their text is not lost.
    option_count = len([o for o in options if o])
    while len(options) < 5:
        options.append("")
    extra = options[5:]
    options = options[:5]
    option_e = options[4] or None
    if extra:
        tail = " ".join(o for o in extra if o)
        option_e = (option_e + " " + tail).strip() if option_e else tail or None

    answer = _answer_letters(type_code, answer_code, option_count) if answer_code else None

    return ParsedQuestion(
        question_text=q_text,
        option_a=options[0] or None,
        option_b=options[1] or None,
        option_c=options[2] or None,
        option_d=options[3] or None,
        option_e=option_e,
        answer=answer,
        source_url=source_url,
        q_type=q_type,
    )


def fetch_paper(pid: str, timeout: float = 20.0) -> ExamcooPaper:
    """Fetch one paper end-to-end: exercise page -> leid/token -> RPC JSON."""
    paper = ExamcooPaper(pid=pid, source_url=VIEW_BASE.format(pid=pid))

    leid_token = _paper_leid_token(pid, timeout=timeout)
    if not leid_token:
        return paper
    leid, token = leid_token

    payload = _get(RPC_BASE.format(leid=leid, token=token), timeout=timeout).json()
    entries = payload.get("b") or []
    if not entries:
        return paper

    meta = entries[0] if isinstance(entries[0], dict) else {}
    paper.title = _clean(str(meta.get("a") or ""))
    try:
        paper.total_questions = int(meta.get("e") or 0)
    except (TypeError, ValueError):
        paper.total_questions = 0

    # entries[1] is the group header; questions start at entries[2].
    for entry in entries[2:]:
        if not isinstance(entry, dict):
            continue
        q = _parse_question(entry, source_url=paper.source_url)
        if q and q.is_valid():
            q.paper_title = paper.title
            paper.questions.append(q)
    return paper


def crawl_subcategory(
    kid: str,
    limit_papers: int | None = None,
    delay: float = 0.3,
    timeout: float = 20.0,
    progress=None,
) -> list[ExamcooPaper]:
    """Crawl every paper in one subcategory.

    ``progress`` is an optional callable(pid, title, n_questions).
    """
    pids = list_paper_ids(kid, timeout=timeout)
    if limit_papers:
        pids = pids[:limit_papers]
    papers: list[ExamcooPaper] = []
    for pid in pids:
        try:
            paper = fetch_paper(pid, timeout=timeout)
        except (httpx.HTTPError, json.JSONDecodeError):
            time.sleep(1.0)
            continue
        # skip foreign-language papers (English-only 英语/外语 content):
        # the product only keeps 普通话 (Chinese) questions
        if _FOREIGN_PAPER_RE.search(paper.title):
            continue
        papers.append(paper)
        if progress:
            progress(pid, paper.title, len(paper.questions))
        if delay:
            time.sleep(delay)
    return papers
