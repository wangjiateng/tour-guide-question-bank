"""Iterative question deduplication (multi-pass, until fixpoint).

True-duplicate definition (conservative, no information loss):
  - normalized stem identical
  - normalized option set identical (order-insensitive)
  - answer identical
  - q_type identical

Two normalization levels, applied in passes until no new groups are found:
  - strict:  brackets dropped, CJK+ASCII letters kept (previous behaviour)
  - loose:   additionally strips fill-blank markers (＿ _), normalizes
             Chinese numerals to Arabic digits

Each group keeps the best row (explanation present > more options > more
years > smaller id); the others are deleted.  answer_attempts rows pointing
at a deleted question are re-pointed at the kept row.

Groups whose options, answers or q_type differ are NOT touched: they are
different exam versions of similar questions and are kept as-is.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

DB = Path("data/quiz.db")

_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "百": 100,
           "千": 1000, "万": 10000}


def _cn_num_to_arabic(m: re.Match) -> str:
    t = m.group(0)
    total = 0
    cur = 0
    for ch in t:
        if ch in "一二两三四五六七八九":
            cur = _CN_NUM[ch]
        elif ch == "十":
            total += (cur or 1) * 10
            cur = 0
        elif ch == "百":
            total += (cur or 1) * 100
            cur = 0
        elif ch == "千":
            total += (cur or 1) * 1000
            cur = 0
        elif ch == "万":
            total += (cur or 1) * 10000
            cur = 0
    total += cur
    return str(total)


def norm_text(s: str, loose: bool = False) -> str:
    if not s:
        return ""
    s = re.sub(r"[（(][^）)]*[)）]", "", s)  # drop bracket content
    if loose:
        s = re.sub(r"[＿_]+", "", s)  # drop fill-blank markers
        s = re.sub(r"[一二两三四五六七八九十百千万]+", _cn_num_to_arabic, s)
    s = re.sub(r"[^一-龥A-Za-z0-9]", "", s)  # keep CJK + ASCII letters + digits
    return s


def option_fingerprint(r: sqlite3.Row, loose: bool = False) -> frozenset:
    opts = [r["option_a"], r["option_b"], r["option_c"], r["option_d"], r["option_e"]]
    return frozenset(norm_text(o, loose) for o in opts if o)


def row_score(r: sqlite3.Row) -> tuple:
    n_opts = sum(1 for o in (r["option_a"], r["option_b"], r["option_c"], r["option_d"], r["option_e"]) if o)
    n_years = len((r["years"] or "").split(",")) if r["years"] else 0
    return (1 if r["explanation"] else 0, n_opts, n_years, -r["id"])


def levenshtein(a: str, b: str, max_d: int = 2) -> int:
    """Levenshtein distance, early-exit above max_d."""
    if abs(len(a) - len(b)) > max_d:
        return max_d + 1
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev = dp[0]
        dp[0] = i
        row_min = dp[0]
        for j, cb in enumerate(b, 1):
            cur = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (ca != cb))
            prev = cur
            row_min = min(row_min, dp[j])
        if row_min > max_d:
            return max_d + 1
    return dp[-1]


def find_edit_dupes(rows: list[sqlite3.Row], max_d: int = 2) -> tuple[list[tuple[sqlite3.Row, list[sqlite3.Row]]], int]:
    """Find near-duplicates by stem edit distance (loose normalization).

    Only pairs whose normalized option set, answer and q_type are identical
    are merged; anything else stays untouched.
    """
    items: list[tuple[sqlite3.Row, str]] = []
    for r in rows:
        n = norm_text(r["question_text"], loose=True)
        if len(n) >= 10:
            items.append((r, n))

    by_pre: dict[str, list[tuple[sqlite3.Row, str]]] = defaultdict(list)
    for r, n in items:
        by_pre[n[:12]].append((r, n))

    # union-find over matched pairs
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    pairs = 0
    for pre, lst in by_pre.items():
        if len(lst) < 2:
            continue
        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                ri, ni = lst[i]
                rj, nj = lst[j]
                if levenshtein(ni, nj, max_d) > max_d:
                    continue
                if option_fingerprint(ri, loose=True) != option_fingerprint(rj, loose=True):
                    continue
                if ri["answer"] != rj["answer"] or ri["q_type"] != rj["q_type"]:
                    continue
                union(ri["id"], rj["id"])
                pairs += 1

    # group members by root
    root_members: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for r, _n in items:
        root_members[find(r["id"])].append(r)

    found: list[tuple[sqlite3.Row, list[sqlite3.Row]]] = []
    n_groups = 0
    for root, mems in root_members.items():
        if len(mems) < 2:
            continue
        if root not in parent and all(m["id"] not in parent for m in mems):
            continue
        keeper = max(mems, key=row_score)
        dup_members = [r for r in mems if r["id"] != keeper["id"]]
        n_groups += 1
        found.append((keeper, dup_members))
    return found, n_groups


def find_dupes(rows: list[sqlite3.Row], loose: bool) -> tuple[list[tuple[sqlite3.Row, list[sqlite3.Row]]], int]:
    """Return (keeper, dup-members) groups found in this pass."""
    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        key = norm_text(r["question_text"], loose)
        if len(key) >= 8:  # skip degenerate stems
            groups[key].append(r)

    found: list[tuple[sqlite3.Row, list[sqlite3.Row]]] = []
    n_groups = 0
    for key, members in groups.items():
        if len(members) < 2:
            continue
        # cluster members by fingerprint: same options + q_type may still
        # split into sub-groups (e.g. 太长公主 vs 大长公主) that must not
        # be merged across each other.
        by_fp: dict[tuple[frozenset, int], list[sqlite3.Row]] = defaultdict(list)
        for r in members:
            by_fp[(option_fingerprint(r, loose), r["q_type"])].append(r)
        for fp, sub in by_fp.items():
            if len(sub) < 2:
                continue
            answers = {r["answer"] for r in sub}
            if len(answers) != 1:
                continue
            keeper = max(sub, key=row_score)
            dup_members = [r for r in sub if r["id"] != keeper["id"]]
            n_groups += 1
            found.append((keeper, dup_members))
    return found, n_groups


def main() -> int:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT id, question_text, q_type, answer, option_a, option_b,
                  option_c, option_d, option_e, explanation, years
           FROM questions"""
    ).fetchall()

    delete_ids: list[int] = []
    delete_to_keep: dict[int, int] = {}
    total_groups = 0

    for pass_name, loose in (("strict", False), ("loose", True)):
        found, n_groups = find_dupes(rows, loose)
        pass_deletes: list[int] = []
        for keeper, mems in found:
            for r in mems:
                if r["id"] not in delete_ids and r["id"] not in pass_deletes:
                    pass_deletes.append(r["id"])
                    delete_to_keep[r["id"]] = keeper["id"]
        total_groups += n_groups
        delete_ids += pass_deletes
        print(f"pass[{pass_name}]: 重复组 {n_groups}, 新增待删 {len(pass_deletes)}")

    # edit-distance pass (near-duplicate stems, e.g. 讲清/讲清楚, 导游人员/导游员)
    found, n_groups = find_edit_dupes(rows, max_d=2)
    pass_deletes: list[int] = []
    for keeper, mems in found:
        for r in mems:
            if r["id"] not in delete_ids and r["id"] not in pass_deletes:
                pass_deletes.append(r["id"])
                delete_to_keep[r["id"]] = keeper["id"]
    total_groups += n_groups
    delete_ids += pass_deletes
    print(f"pass[edit]: 重复组 {n_groups}, 新增待删 {len(pass_deletes)}")

    print(f"\n重复组总计: {total_groups}")
    print(f"待删 id: {len(delete_ids)}")

    if not delete_ids:
        print("无待删记录")
        conn.close()
        return 0

    # re-point answer_attempts before deleting
    attempts = conn.execute(
        f"SELECT id, question_id FROM answer_attempts WHERE question_id IN ({','.join('?' * len(delete_ids))})",
        delete_ids,
    ).fetchall()
    n_moved = 0
    for a in attempts:
        new_qid = delete_to_keep.get(a["question_id"])
        if new_qid:
            conn.execute(
                "UPDATE answer_attempts SET question_id = ? WHERE id = ?",
                (new_qid, a["id"]),
            )
            n_moved += 1
    print(f"answer_attempts 引用迁移: {n_moved}")

    # delete
    placeholders = ",".join("?" * len(delete_ids))
    cur = conn.execute(f"DELETE FROM questions WHERE id IN ({placeholders})", delete_ids)
    print(f"删除行: {cur.rowcount}")

    # refresh crawl_sources.question_count
    conn.execute(
        """UPDATE crawl_sources
           SET question_count = (SELECT COUNT(*) FROM questions q WHERE q.source_id = crawl_sources.id)"""
    )
    conn.commit()

    n_after = conn.execute("SELECT COUNT(*) c FROM questions").fetchone()["c"]
    print(f"删除后总题数: {n_after}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
