"""One-shot importer: parse daoyouhome static 真题 text and upsert into quiz.db.

Source data: /tmp/daoyouhome_raw.json (already-fetched raw text, keyed by
article title).  No crawler/adapter — daoyouhome 真题 is static content; the
raw dump is re-fetched by an AI agent when updates are needed.

Only 初级/全国导游资格考试 真题 (2023/2024/2025) are imported.  中级/高级
等级考试 真题 are deliberately skipped (user: 重要! 我是初级考试).

Paper-title classification reuses service.subject_from_paper_title so the
layered subject rules stay the single source of truth.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from daoyou_tiku.crawler import ParsedQuestion
from daoyou_tiku.db import connect
from daoyou_tiku.service import _store_questions, _upsert_source

RAW_PATH = Path("/tmp/daoyouhome_raw.json")

# Article URLs (公开页面, 见 zghelp 列表页).
URLS = {
    "2023": "https://www.daoyouhome.com/zghelp/2065.html",
    "2024": "https://www.daoyouhome.com/zghelp/2514.html",
    "2025": "https://www.daoyouhome.com/zghelp/2831.html",
}

# paper_title: 2023/2024 are single 科目三 papers; 2025 splits into two
# segments.  Titles are crafted to hit the existing classification rules:
#   - 2023/2024 「导游基础知识」 -> paper_subject=3, per-question 省名开头 -> 4
#   - 2025 法规+业务 「科目一…+科目二…」 -> _MIX_PAPER_RE -> per-question 1/2
#   - 2025 全导+地导 「科目三…+科目四…」 -> paper_subject=None -> per-question 3/4
PAPER_TITLES = {
    "2023": "《2023年全国导游资格考试真题（导游基础知识）》",
    "2024": "《2024年全国导游资格考试真题（导游基础知识）》",
    "2025_legal": "《2025年全国导游资格考试真题（科目一政策与法律法规+科目二导游业务）》",
    "2025_base": "《2025年全国导游资格考试真题（科目三全导+科目四地导）》",
}

SEC_RE = re.compile(r"^[ \t]*[一二三四五六七八九十0-9]+[、.．]\s*(判断题|单选题|多选题)\s*$", re.M)


def split_sections(text: str) -> list[tuple[str, str]]:
    """Split raw text into [(题型, content), ...] by 小节 heading lines."""
    positions = [(m.start(), m.end(), m.group(1)) for m in SEC_RE.finditer(text)]
    out = []
    for i, (s, e, typ) in enumerate(positions):
        content = text[e: positions[i + 1][0] if i + 1 < len(positions) else len(text)]
        out.append((typ, content))
    return out


def preprocess(text: str) -> str:
    """Repair OCR damage in the 2025 multi-choice options."""
    text = text.replace("[日】", "【B】").replace("【日】", "【B】")
    text = text.replace("【0】", "【C】").replace("【O】", "【C】")
    text = text.replace("[0】", "【C】")
    # 「【\nD】」 — bracket split across a line break
    text = re.sub(r"【\s*\n\s*([A-E])\s*】", r"【\1】", text)
    text = re.sub(r"\[\s*\n\s*([A-E])\s*】", r"【\1】", text)
    # 「30“地坑院”」 — question number glued to opening quote
    text = re.sub(r"^(\d{1,2})(?=[“”\"'])", r"\1、", text, flags=re.M)
    return text


def parse_judge(content: str) -> list[ParsedQuestion]:
    """判断题: 「N.题干(对/错)」 or 「N.题干答案：正确/错误」."""
    lines = content.split("\n")
    cur: dict | None = None
    blocks: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)[、.．]\s*(.*)$", line)
        if m:
            if cur:
                blocks.append(cur)
            cur = {"num": m.group(1), "text": m.group(2)}
        elif cur is not None:
            cur["text"] += line
    if cur:
        blocks.append(cur)

    out: list[ParsedQuestion] = []
    for q in blocks:
        text = q["text"]
        answer: str | None = None
        explanation = ""
        m = re.search(r"[（(]\s*(对|错|正确|错误)\s*[)）]", text)
        if m:
            answer = "正确" if m.group(1) in ("对", "正确") else "错误"
            stem = text[: m.start()]
            tail = text[m.end():]
            if tail.strip():
                explanation = tail.strip()
        else:
            m2 = re.search(r"答案[:：]\s*(正确|错误|对|错)", text)
            if m2:
                answer = "正确" if m2.group(1) in ("对", "正确") else "错误"
                stem = text[: m2.start()]
                tail = text[m2.end():]
                if tail.strip():
                    explanation = tail.strip()
            else:
                stem = text
        stem = re.sub(r"[（(]\s*[)）]\s*$", "", stem).strip()
        out.append(ParsedQuestion(
            question_text=stem,
            option_a="正确",
            option_b="错误",
            answer=answer,
            explanation=explanation,
            q_type=3,
        ))
    return out


def parse_single(content: str) -> list[ParsedQuestion]:
    """单选题 (2024): 「N.题干\nA.xB.xC.xD.x\n答案：X」."""
    blocks = re.split(r"\n(?=\d{1,3}[、.．,]\s*\S)", content)
    out: list[ParsedQuestion] = []
    for block in blocks:
        block = block.strip()
        m = re.match(r"^(\d{1,3})[、.．,]\s*(.*)$", block, re.S)
        if not m:
            continue
        body = re.sub(r"篇幅有限.*$", "", m.group(2), flags=re.S).strip()
        lines = body.split("\n")
        stem = lines[0].strip()
        options: dict[str, str] = {}
        answer = ""
        option_txt = ""
        for line in lines[1:]:
            s = line.strip()
            if s.startswith("答案"):
                am = re.search(r"答案[:：]\s*([A-E])", s)
                if am:
                    answer = am.group(1)
            elif re.match(r"^[A-E][.、．:：)]", s):
                option_txt = s
        if option_txt:
            for om in re.finditer(r"([A-E])[.、．:：)]\s*([^A-E]*(?=[A-E][.、．:：)]|$))", option_txt):
                options[om.group(1)] = om.group(2).strip()
        stem = re.sub(r"[（(]\s*[)）]\s*$", "", stem).strip()
        out.append(ParsedQuestion(
            question_text=stem,
            option_a=options.get("A"),
            option_b=options.get("B"),
            option_c=options.get("C"),
            option_d=options.get("D"),
            option_e=options.get("E"),
            answer=answer or None,
            q_type=1,
        ))
    return out


def parse_multi(content: str) -> list[ParsedQuestion]:
    """多选题 (2025): 「N.题干()。ABCDE\n【A】…【B】…」."""
    blocks = re.split(r"\n(?=\d{1,3}[、.．,]\s*\S)", content)
    out: list[ParsedQuestion] = []
    for block in blocks:
        block = block.strip()
        m = re.match(r"^(\d{1,3})[、.．,]\s*(.*)$", block, re.S)
        if not m:
            continue
        body = m.group(2)
        options: dict[str, str] = {}
        for om in re.finditer(r"[【\[]\s*([A-E])\s*[】\]]\s*([^【\[]*)", body):
            options[om.group(1)] = om.group(2).strip()
        answer = ""
        # 标点后裸字母序列（后跟选项占位或行尾）
        for mm in re.finditer(r"[）)。．]\s*([A-E]{1,5})\s*(?=[【\[]|$)", body):
            answer = mm.group(1)
            break
        if not answer:
            # fallback: 第一个选项占位前, 末尾裸字母序列 (如「…之家ABC」)
            first_opt = re.search(r"[【\[]\s*[A-E]\s*[】\]]", body)
            prefix = body[: first_opt.start()] if first_opt else body
            mm = re.search(r"([A-E]{2,5})\s*$", prefix)
            if mm:
                answer = mm.group(1)
        stem_end = None
        mm = re.search(r"[）)]", body)
        if mm:
            stem_end = mm.end()
        else:
            mm = re.search(r"[。．]", body)
            if mm:
                stem_end = mm.end()
        stem = body[:stem_end] if stem_end else body
        stem = re.sub(r"[（(]\s*[)）]\s*[。．]?\s*$", "", stem).strip()
        stem = re.sub(r"[。．]\s*$", "", stem).strip()
        stem = re.sub(r"[）)]\s*[。．]?\s*$", "", stem).strip()
        out.append(ParsedQuestion(
            question_text=stem,
            option_a=options.get("A"),
            option_b=options.get("B"),
            option_c=options.get("C"),
            option_d=options.get("D"),
            option_e=options.get("E"),
            answer=answer or None,
            q_type=2,
        ))
    return out


def build_questions() -> dict[str, dict]:
    """Parse all three 初级 papers into {source_key: {url, title, questions}}."""
    raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))

    t2023 = raw["2023全国导游资格真题"]
    t2024 = raw["2024全国导游资格真题"]
    t2025 = raw["2025全国导游资格真题"]

    q2023 = []
    for typ, content in split_sections(t2023):
        if typ == "判断题":
            q2023 += parse_judge(content)

    q2024 = []
    for typ, content in split_sections(t2024):
        if typ == "判断题":
            q2024 += parse_judge(content)
        elif typ == "单选题":
            q2024 += parse_single(content)

    i = t2025.find("《全导+地导》")
    seg_legal = preprocess(t2025[:i])
    seg_base = preprocess(t2025[i:])

    q2025_legal = []
    for typ, content in split_sections(seg_legal):
        if typ == "判断题":
            q2025_legal += parse_judge(content)
        elif typ == "多选题":
            q2025_legal += parse_multi(content)
        # 单选题 (回忆版填空式, 无 A-D) 跳过

    q2025_base = []
    for typ, content in split_sections(seg_base):
        if typ == "判断题":
            q2025_base += parse_judge(content)
        elif typ == "多选题":
            q2025_base += parse_multi(content)

    result = {
        "2023": {"url": URLS["2023"], "title": "2023年全国导游资格考试真题", "paper": PAPER_TITLES["2023"], "questions": q2023},
        "2024": {"url": URLS["2024"], "title": "2024年全国导游资格考试真题", "paper": PAPER_TITLES["2024"], "questions": q2024},
        "2025": {"url": URLS["2025"], "title": "2025年全国导游资格考试真题", "paper": PAPER_TITLES["2025_legal"], "questions": q2025_legal},
        "2025_2": {"url": URLS["2025"], "title": "2025年全国导游资格考试真题", "paper": PAPER_TITLES["2025_base"], "questions": q2025_base},
    }
    return result


def main() -> int:
    groups = build_questions()
    conn = connect()

    total_inserted = total_updated = total_deduped = 0
    # The two 2025 segments share one crawl_sources row (same URL).
    source_ids: dict[str, int] = {}

    for key, g in groups.items():
        url = g["url"]
        # upsert source once per URL
        if url not in source_ids:
            source_ids[url] = _upsert_source(
                conn, url, "static_page", {}, g["title"], True,
                f"daoyouhome 静态真题一次性导入 (2023/2024/2025 初级)",
            )
        source_id = source_ids[url]
        # attach paper_title to every question of this segment
        for q in g["questions"]:
            q.paper_title = g["paper"]
            q.source_url = url
        stored = _store_questions(conn, source_id, url, g["questions"], subject=None)
        total_inserted += stored["inserted"]
        total_updated += stored["updated"]
        total_deduped += stored["deduped"]
        print(f"[{key}] {g['title']} | {g['paper']} | "
              f"n={len(g['questions'])} insert={stored['inserted']} "
              f"update={stored['updated']} dedupe={stored['deduped']} "
              f"src_total={stored['total']}")

    conn.close()
    print(f"\nTOTAL inserted={total_inserted} updated={total_updated} deduped={total_deduped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
