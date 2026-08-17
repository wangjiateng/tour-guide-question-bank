"""Multi-source crawler adapters.

A source adapter encapsulates one stable way to obtain questions from a
source: how to fetch it, how to page through it, and how to normalize
entries into ParsedQuestion rows. Adapters are chosen by
``crawl_sources.kind``; ``config`` (JSON) holds per-source parameters.

Built-in adapters:
- ``static_page``: one HTML page parsed with the generic HTML parser
  (works for plain pages with A-D option blocks and answer markers).
- ``json_api``: a JSON endpoint returning question arrays; supports
  ``page_size``/``page_param``/``offset_param`` paging and a ``data_path``
  field path into the payload.
- ``fixture``: a built-in bundled question set (no network needed).
  Used as the vetted demo source and as a deterministic test source.

New sources: add a subclass and register it in ``ADAPTERS``; the rest of
the pipeline (sync, dedup, scheduling) is adapter-agnostic.
"""
from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from .analyzer import USER_AGENT
from .crawler import ParsedQuestion, parse_html, parse_json_api
from . import examcoo

MAX_FETCH_BYTES = 3 * 1024 * 1024


class AdapterError(Exception):
    """Raised when a source cannot be fetched or parsed."""


def _get_json(url: str, timeout: float = 15.0, **params) -> dict | list:
    resp = httpx.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
        params=params,
        timeout=timeout,
        follow_redirects=True,
    )
    resp.raise_for_status()
    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        raise AdapterError(f"not a JSON response: {exc}") from exc


def _get_text(url: str, timeout: float = 15.0) -> str:
    resp = httpx.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
        timeout=timeout,
        follow_redirects=True,
    )
    resp.raise_for_status()
    return resp.content[:MAX_FETCH_BYTES].decode("utf-8", errors="ignore")


def _dig(data, path: str):
    """Walk a dotted path through nested dict/list payloads."""
    cur = data
    for part in path.split(".") if path else []:
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)]
        else:
            return None
    return cur


@dataclass
class FetchResult:
    """One page of questions plus paging state."""

    questions: list[ParsedQuestion]
    has_more: bool = False


@dataclass
class SourceAdapter(ABC):
    """Base class for one crawl source.

    ``config`` is the per-source JSON config stored in
    ``crawl_sources.config``; it is adapter-specific.
    """

    url: str
    config: dict = field(default_factory=dict)
    title: str = ""

    @property
    @abstractmethod
    def kind(self) -> str:
        """Adapter kind stored in crawl_sources.kind."""

    @abstractmethod
    def fetch_page(self, page: int) -> FetchResult:
        """Fetch one page of questions (0-based)."""

    def total_estimate(self) -> int | None:
        """Optional total question count for progress reporting."""
        return None

    def describe(self) -> str:
        return f"{self.kind}:{self.url}"


class StaticPageAdapter(SourceAdapter):
    """One static HTML page of questions (A-D blocks + answer markers)."""

    kind = "static_page"

    def fetch_page(self, page: int) -> FetchResult:
        if page != 0:
            return FetchResult([], has_more=False)
        try:
            html = _get_text(self.url)
        except httpx.HTTPError as exc:
            raise AdapterError(f"fetch failed: {exc.__class__.__name__}") from exc
        if not self.title:
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
            if m:
                self.title = re.sub(r"\s+", " ", m.group(1)).strip()[:200]
        return FetchResult(parse_html(html), has_more=False)


class JsonApiAdapter(SourceAdapter):
    """A paged JSON question API.

    Config keys:
    - ``page_size``: questions per page (default 100)
    - ``page_param``: page-number query param name (default "page")
    - ``offset_param``: offset query param name; mutually exclusive with page_param
    - ``data_path``: dotted path to the question list inside the payload
      (default "" = payload itself is a list, or payload.data.list/items)
    - ``total_path``: dotted path to a total count field (optional)
    - ``has_more_path``: dotted path to a boolean has-more field (optional)
    """

    kind = "json_api"

    def fetch_page(self, page: int) -> FetchResult:
        params: dict = {}
        if self.config.get("offset_param"):
            params[self.config["offset_param"]] = page * self._page_size()
        else:
            params[self.config.get("page_param", "page")] = page + 1
        try:
            payload = _get_json(self.url, **params)
        except httpx.HTTPError as exc:
            raise AdapterError(f"fetch failed: {exc.__class__.__name__}") from exc
        raw = payload
        if self.config.get("data_path"):
            raw = {"data": _dig(payload, self.config["data_path"])}
        questions = parse_json_api(raw)
        return FetchResult(questions, has_more=self._has_more(payload, page, len(questions)))

    def _page_size(self) -> int:
        return int(self.config.get("page_size", 100))

    def _has_more(self, payload, page: int, got: int) -> bool:
        path = self.config.get("has_more_path")
        if path:
            return bool(_dig(payload, path))
        total_path = self.config.get("total_path")
        if total_path:
            total = _dig(payload, total_path)
            if isinstance(total, int):
                return (page + 1) * self._page_size() < total
        return got >= self._page_size()


class FixtureAdapter(SourceAdapter):
    """Bundled demo question set; no network access needed.

    Stable by construction: the same questions come back on every fetch,
    so it doubles as a deterministic sync/dedup test source.
    """

    kind = "fixture"

    FIXTURE = [
        ParsedQuestion(
            question_text="导游人员在带团过程中，遇有突发疾病游客，下列做法正确的是（ ）。",
            option_a="置之不理",
            option_b="立即联系医疗机构并协助救助",
            option_c="让游客自行处理",
            option_d="继续行程",
            answer="B",
            explanation="带团中游客突发疾病，导游应立即联系医疗机构并协助救助。",
        ),
        ParsedQuestion(
            question_text="中国旅游日的日期是（ ）。",
            option_a="5月1日",
            option_b="5月19日",
            option_c="6月1日",
            option_d="10月1日",
            answer="B",
            explanation="2011年国务院正式将5月19日确定为中国旅游日。",
        ),
        ParsedQuestion(
            question_text="导游证的有效期为（ ）年。",
            option_a="1",
            option_b="2",
            option_c="3",
            option_d="5",
            answer="C",
            explanation="导游证有效期为3年，届满前需要申请换发。",
        ),
        ParsedQuestion(
            question_text="我国旅游业的根本宗旨是（ ）。",
            option_a="安全第一",
            option_b="全心全意为旅游者服务",
            option_c="经济效益最大化",
            option_d="宣传当地文化",
            answer="B",
            explanation="旅游业以全心全意为旅游者服务为根本宗旨。",
        ),
        ParsedQuestion(
            question_text="导游员在讲解时发现游客走神，应采取的措施是（ ）。",
            option_a="提高音量吸引注意",
            option_b="立即停止讲解",
            option_c="调整讲解方式，增加互动",
            option_d="批评走神的游客",
            answer="C",
            explanation="发现游客走神时应调整讲解方式、增加互动以重新吸引注意力。",
        ),
        ParsedQuestion(
            question_text="《中华人民共和国旅游法》施行于（ ）年。",
            option_a="2010",
            option_b="2012",
            option_c="2013",
            option_d="2015",
            answer="C",
            explanation="《中华人民共和国旅游法》自2013年10月1日起施行。",
        ),
    ]

    def fetch_page(self, page: int) -> FetchResult:
        if page != 0:
            return FetchResult([], has_more=False)
        return FetchResult(list(self.FIXTURE), has_more=False)

    def total_estimate(self) -> int:
        return len(self.FIXTURE)


class ExamcooAdapter(SourceAdapter):
    """Tour-guide question bank on examcoo.com (考试酷).

    Config keys:
    - ``kid``: subcategory id (408 导游业务, 409 导游基础知识, 411 导游外语,
      413 导游规范服务能力, 414 导游特殊问题处理及应变能力). Default 408.
    - ``limit_papers``: cap on papers crawled (default unlimited).
    - ``delay``: seconds between paper fetches (default 0.3).

    Each page of the adapter maps to one list page (25 papers); questions
    from every paper on that list page are returned together. Answers are
    present for all question types (single, multiple, true/false).
    """

    kind = "examcoo"

    def __init__(self, url: str, config: dict | None = None):
        super().__init__(url=url, config=config or {})
        self._pid_cache: list[str] | None = None

    def _pids(self) -> list[str]:
        if self._pid_cache is None:
            kid = str(self.config.get("kid", "408"))
            if kid in examcoo.EXCLUDED_SUBCATEGORIES:
                # 外语子类目（411）为纯英语内容，按要求排除
                self._pid_cache = []
            else:
                try:
                    self._pid_cache = examcoo.list_paper_ids(kid)
                except httpx.HTTPError as exc:
                    raise AdapterError(f"list failed: {exc.__class__.__name__}") from exc
        return self._pid_cache

    def fetch_page(self, page: int) -> FetchResult:
        delay = float(self.config.get("delay", 0.3))
        pids = self._pids()
        if page * 25 >= len(pids):
            return FetchResult([], has_more=False)

        questions: list[ParsedQuestion] = []
        for pid in pids[page * 25 : (page + 1) * 25]:
            try:
                paper = examcoo.fetch_paper(pid, timeout=20.0)
            except (httpx.HTTPError, json.JSONDecodeError):
                continue
            if not self.title and paper.title:
                self.title = paper.title
            questions.extend(paper.questions)
            if delay:
                time.sleep(delay)
        has_more = (page + 1) * 25 < len(pids)
        return FetchResult(questions, has_more=has_more)

    def total_estimate(self) -> int | None:
        try:
            return len(self._pids())
        except AdapterError:
            return None


def build_adapter(kind: str, url: str, config: dict | None = None) -> SourceAdapter:
    """Instantiate the adapter registered for ``kind``."""
    if kind not in ADAPTERS:
        raise AdapterError(f"unknown source kind: {kind!r} (known: {sorted(ADAPTERS)})")
    return ADAPTERS[kind](url=url, config=config or {})


ADAPTERS: dict[str, type[SourceAdapter]] = {
    "static_page": StaticPageAdapter,
    "json_api": JsonApiAdapter,
    "fixture": FixtureAdapter,
    "examcoo": ExamcooAdapter,
}
