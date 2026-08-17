"""Crawl-source auto-analysis.

Given a URL, this module fetches the page, fingerprints its structure,
and decides whether it can yield tour-guide (导游证) questions.

Detection signals:
1. title/heading contains tour-guide keywords (导游, 导考, 导游证, 笔试, 试题)
2. page contains question-shaped HTML: option markers (A./B./C./D.),
   question blocks, or answer markers
3. HTML form tags (quiz engines like <form> + radio inputs)

Fingerprint scoring returns a structured verdict used by the crawler
to pick a parse strategy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup

GUIDE_KEYWORDS = [
    "导游", "导考", "导游证", "导游资格", "笔试", "科目一", "科目二",
    "导游考试", "全国导游", "基础知识", "政策法规", "试题", "题库",
]

QUESTION_MARKERS = [
    re.compile(r"^[（(]?\s*[A-D][.、．:：)]\s*", re.M),
    re.compile(r"^(?:单选|多选|判断)[题：:]", re.M),
    re.compile(r"参考答案[:：]?\s*[A-D]+", re.M),
    re.compile(r"答案[:：]?\s*[A-D]+", re.M),
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

MAX_FETCH_BYTES = 3 * 1024 * 1024


@dataclass
class SourceVerdict:
    url: str
    title: str = ""
    ok: bool = False
    kind: str = "web"          # web | json_api | quiz_engine | unknown
    score: int = 0
    signals: list[str] = field(default_factory=list)
    reason: str = ""
    html: str = ""             # parsed html text kept for the crawler

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "ok": self.ok,
            "kind": self.kind,
            "score": self.score,
            "signals": self.signals,
            "reason": self.reason,
        }


def _title_of(soup: BeautifulSoup) -> str:
    t = soup.title.string if soup.title else ""
    return (t or "").strip()[:200]


def _score_text(text: str, verdict: SourceVerdict) -> None:
    lowered = text.lower()
    for kw in GUIDE_KEYWORDS:
        if kw in lowered:
            verdict.score += 2
            verdict.signals.append(f"keyword:{kw}")
    for marker in QUESTION_MARKERS:
        if marker.search(text):
            verdict.score += 3
            verdict.signals.append("question-marker")
            break
    if re.search(r"<form[^>]*>.*?<input[^>]*type=[\"']radio", text, re.S | re.I):
        verdict.score += 4
        verdict.signals.append("quiz-form")
        verdict.kind = "quiz_engine"


def analyze_source(url: str, timeout: float = 15.0) -> SourceVerdict:
    """Fetch and fingerprint one candidate source URL."""
    verdict = SourceVerdict(url=url)
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
            timeout=timeout,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        verdict.reason = f"fetch failed: {exc.__class__.__name__}"
        return verdict

    if resp.status_code != 200:
        verdict.reason = f"http {resp.status_code}"
        return verdict

    body = resp.content[:MAX_FETCH_BYTES].decode("utf-8", errors="ignore")
    soup = BeautifulSoup(body, "lxml")
    verdict.title = _title_of(soup)
    _score_text(body, verdict)
    if not verdict.signals:
        verdict.reason = "no tour-guide question signals found"
        return verdict

    # A page with >=1 strong signal is considered a usable source.
    verdict.ok = verdict.score >= 3
    verdict.reason = "usable source" if verdict.ok else "weak signals only"
    if verdict.ok:
        verdict.html = body
    return verdict
