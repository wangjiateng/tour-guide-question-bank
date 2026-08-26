#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
题库精确去重流水线（三段式）

用法:
    python3 scripts/dedup/dedup_pipeline.py --dry-run   # 只出报告不修改
    python3 scripts/dedup/dedup_pipeline.py --apply     # 执行去重并写回

三段逻辑:
  Stage 1  三元组精确去重：题干+选项+答案 完全一致（含 OCR 词典归一）→ 保留质量最高版本，删除其余
  Stage 2  模糊自动合并：题干序列相似度 >= STAGE2_SIM 且 题型/选项集/答案 一致 → 合并（保留高质量版本，
           合并 years/解析）
  Stage 3  灰区复核：相似度在 [STAGE3_MIN, STAGE2_SIM) 且答案一致 → 输出复核清单，不自动处理

安全边界:
  - 判重单元是「题干+选项+答案」三元组：题干相同但选项/答案不同的题（如"西夏陵 59项/60项"）不会合并
  - 跨题型（同一句既是判断又是单选）不合并
  - questions_0.json（fixture/未分类）不参与去重
  - --dry-run 不写文件；--apply 前自动做 JSON 完整性校验，失败即中止不写盘
  - 数据文件在 git 中，可随时回滚
"""
import json
import os
import re
import sys
from collections import defaultdict
from difflib import SequenceMatcher

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO, 'public', 'data')
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = os.path.join(SCRIPT_DIR, 'reports')

FILES = ['questions_1.json', 'questions_2.json', 'questions_3.json', 'questions_4.json']
STAGE2_SIM = 0.92      # Stage2 自动合并阈值
STAGE3_MIN = 0.80      # Stage3 灰区下限
BUCKET_CAP = 300       # 每个前缀桶最多比较对数（防爆）
# Stage4 语义级（题意相同）阈值：
#   单选/多选：答案文本锚定（同题型+同答案选项内容）+ TF-IDF 余弦 >= CHOICE_SIM
#   判断：答案只有 正确/错误 锚点弱，需 TF-IDF >= JUDGE_SIM 且 字符相似度 >= JUDGE_CHAR 双条件
# 精准收紧带（低一档但需双信号 + 选项重叠，防"低山/高山""国外200/港澳100"类误并）：
#   单选/多选：TF-IDF >= CHOICE_SIM2 且 字符相似度 >= CHAR2 且 选项重叠 >= OPT_OVERLAP
#   判断：字符相似度 >= JUDGE_CHAR2（TF-IDF 仅作弱确认 >= 0.55）
STAGE4_CHOICE_SIM = 0.70
STAGE4_CHOICE_SIM2 = 0.65
STAGE4_CHAR2 = 0.65
STAGE4_OPT_OVERLAP = 0.5
STAGE4_JUDGE_SIM = 0.85
STAGE4_JUDGE_CHAR = 0.65
STAGE4_JUDGE_CHAR2 = 0.88
# 真题优先来源（合并时保留的优先级）
ZHENTI_SOURCES = {42, 43, 44, 50, 51, 52, 53, 54, 55, 56, 66}

PUNCT = re.compile(r'[\s\u3000，。、；：？！（）《》""''【】—…·\u00a0“”‘’]')


def norm(t):
    """保守归一化：去空白/标点/全半角统一。不改变任何实义字符。"""
    return PUNCT.sub('', t or '')


def load_ocr_fixes():
    path = os.path.join(SCRIPT_DIR, 'ocr_fixes.json')
    with open(path, encoding='utf-8') as f:
        return json.load(f)['fixes']


OCR_FIXES = load_ocr_fixes()


def strong_norm(t):
    """强归一化：norm 基础上应用 OCR 纠错词典（每条约可审计，见 ocr_fixes.json）。"""
    s = norm(t)
    for k, v in OCR_FIXES.items():
        s = s.replace(k, v)
    return s


def options_tuple(q):
    """选项集（强归一化、非空、去重排序）作为比较键的一部分。"""
    opts = []
    for key in ('option_a', 'option_b', 'option_c', 'option_d', 'option_e'):
        v = strong_norm(q.get(key))
        if v:
            opts.append(v)
    return tuple(sorted(set(opts)))


def key3(q):
    """Stage1 三元组键：题干+选项集+答案。"""
    return (strong_norm(q.get('question_text')), options_tuple(q), norm(q.get('answer')))


def quality(q):
    """合并时保留质量评分：真题源 +2 / 有解析 +1 / 题干污染 -2 / 疑似 OCR 错字 -1"""
    score = 0
    if q.get('source_id') in ZHENTI_SOURCES:
        score += 2
    if q.get('explanation'):
        score += 1
    t = norm(q.get('question_text')) or ''
    if any(x in t for x in ('正确答案', '解析', '本题说法')):
        score -= 2
    for bad in OCR_FIXES:
        if bad in t:
            score -= 1
            break
    return score


def merge_years(a, b):
    ys = set()
    for y in (a, b):
        if y:
            ys.update(x.strip() for x in y.split(',') if x.strip())
    return ','.join(sorted(ys)) if ys else None


def answer_text(q):
    """答案对应的选项内容（语义锚点）：单选取对应选项文本，多选取选项文本集，判断返回 正确/错误。"""
    if q.get('q_type') == 3:
        return q.get('answer')
    parts = [strong_norm(q.get('option_' + L.lower())) for L in (q.get('answer') or '') if q.get('option_' + L.lower())]
    return '|'.join(sorted(set(parts)))


def options_overlap(qa, qb):
    """两组选项文本（强归一、非空）的交集占比，用于收紧带的精度保护。"""
    oa = set(strong_norm(qa.get(k)) for k in ('option_a','option_b','option_c','option_d','option_e') if qa.get(k))
    ob = set(strong_norm(qb.get(k)) for k in ('option_a','option_b','option_c','option_d','option_e') if qb.get(k))
    if not oa or not ob:
        return 1.0
    return len(oa & ob) / max(len(oa), len(ob))


def merge_q(survivor, loser):
    """把 loser 并入 survivor：years 取并集；解析缺失时补。返回 survivor。"""
    survivor['years'] = merge_years(survivor.get('years'), loser.get('years'))
    if not survivor.get('explanation') and loser.get('explanation'):
        survivor['explanation'] = loser['explanation']
    return survivor


def load_all():
    questions = []
    for f in FILES:
        d = json.load(open(os.path.join(DATA, f), encoding='utf-8'))
        for q in d['questions']:
            q['_file'] = f
            questions.append(q)
    return questions


def save_all(questions):
    """写回 questions_1..4.json（json.dump indent=2，与既有格式一致）。先校验，失败不写盘。"""
    by_file = defaultdict(list)
    for q in questions:
        by_file[q['_file']].append(q)
    for f in FILES:
        qs = sorted(by_file[f], key=lambda q: q['id'])
        ids = [q['id'] for q in qs]
        assert ids == sorted(ids) and len(set(ids)) == len(ids), f'{f}: id 顺序/重复异常'
        obj = {'subject': int(f[len('questions_'):-5]), 'questions': qs}
        text = json.dumps(obj, ensure_ascii=False, indent=2) + '\n'
        json.loads(text)  # 写盘前校验
        with open(os.path.join(DATA, f), 'w', encoding='utf-8') as fh:
            fh.write(text)
        print(f'  written {f}: {len(qs)} questions')


def bucket_candidates(questions, stems):
    """首 N 字符前缀分桶生成候选对（同时用 norm 与 strong_norm 分桶，抗前缀 OCR 错字）。"""
    pairs = set()
    for stem_list in (stems, [strong_norm(q['question_text']) for q in questions]):
        buckets = defaultdict(list)
        for i, t in enumerate(stem_list):
            if len(t) >= 8:
                buckets[t[:8]].append(i)
        for idxs in buckets.values():
            if len(idxs) < 2:
                continue
            arr = idxs[:BUCKET_CAP]
            for a in range(len(arr)):
                for b in range(a + 1, len(arr)):
                    pairs.add(tuple(sorted((arr[a], arr[b]))))
    return pairs


def main():
    apply = '--apply' in sys.argv
    os.makedirs(REPORT_DIR, exist_ok=True)
    questions = load_all()
    total = len(questions)
    print(f'载入 {total} 题（{len(FILES)} 个文件） | 模式: {"APPLY 执行" if apply else "DRY-RUN 只报告"}')

    # ---------- Stage 1: 三元组精确去重 ----------
    groups = defaultdict(list)
    for q in questions:
        groups[key3(q)].append(q)
    stage1_remove = set()
    for k, g in groups.items():
        if len(g) > 1:
            g.sort(key=lambda q: (-quality(q), q['id']))
            survivor = g[0]
            for loser in g[1:]:
                stage1_remove.add(id(loser))
                merge_q(survivor, loser)
    print(f'Stage1 三元组精确重复: {len(groups)} 组中 {sum(1 for g in groups.values() if len(g)>1)} 组含重复，'
          f'待删除 {len(stage1_remove)} 题')

    # ---------- Stage 2: 模糊自动合并 ----------
    remain = [q for q in questions if id(q) not in stage1_remove]
    stems = [norm(q['question_text']) for q in remain]
    pairs = bucket_candidates(remain, stems)   # 元素为 remain 列表下标
    merged = set()      # 已并入的 loser（remain 下标）
    stage2_remove = set()
    stage2_merged_info = []
    for (i, j) in pairs:
        if i in merged or j in merged:
            continue
        qi, qj = remain[i], remain[j]
        if qi['q_type'] != qj['q_type']:
            continue
        if norm(qi['answer']) != norm(qj['answer']):
            continue
        if options_tuple(qi) != options_tuple(qj):
            continue
        r = SequenceMatcher(None, stems[i], stems[j]).ratio()
        if r >= STAGE2_SIM and r < 1.0:
            si, sj = qi, qj
            if quality(sj) > quality(si):
                si, sj = sj, si
            elif quality(sj) == quality(si) and sj['id'] < si['id']:
                si, sj = sj, si
            merge_q(si, sj)
            loser_idx = j if sj is qj else i
            stage2_remove.add(loser_idx)
            merged.update((i, j))
            stage2_merged_info.append((si['id'], sj['id'], round(r, 3)))
    print(f'Stage2 模糊自动合并: {len(stage2_merged_info)} 对（删除 {len(stage2_remove)} 题）')

    # ---------- Stage 4: 语义级去重（题意相同） ----------
    # 思路：同一道题的「答案内容」必然相同 → 先按(题型+答案文本)锚定分组；
    #       组内用 TF-IDF 词向量算题干语义相似度，识别措辞不同但题意相同的题。
    # 依赖：jieba + numpy（pip install jieba numpy）。缺失时跳过并提示。
    stage4_remove = set()
    stage4_merged_info = []
    try:
        import jieba
        import numpy as np
        from collections import Counter
        final = [q for idx, q in enumerate(remain) if idx not in stage2_remove]
        stems4 = [norm(q['question_text']) for q in final]
        corpus = [list(jieba.cut(s)) for s in stems4]
        df = Counter(w for toks in corpus for w in set(toks) if len(w) >= 2)
        N4 = len(corpus)
        logN = np.log((N4 + 1) / (np.array([df.get(w, 1) for w in sorted(df)]) + 1))

        def tfidf(toks):
            from collections import Counter as C
            c = C(w for w in toks if len(w) >= 2)
            n = sum(c.values()) or 1
            return {w: (cnt / n) * float(np.log((N4 + 1) / (df[w] + 1))) for w, cnt in c.items()}

        vecs = [tfidf(t) for t in corpus]

        def vcos(a, b):
            inter = set(a) & set(b)
            if not inter:
                return 0.0
            na = np.sqrt(sum(v * v for v in a.values())) or 1.0
            nb = np.sqrt(sum(v * v for v in b.values())) or 1.0
            return sum(a[w] * b[w] for w in inter) / (na * nb)

        groups4 = defaultdict(list)
        for i, q in enumerate(final):
            groups4[(q['q_type'], answer_text(q))].append(i)
        for g in groups4.values():
            if len(g) < 2:
                continue
            reps = []  # 已保留代表的 final 下标（贪心：每个成员只处理一次，无需 merged 集合）
            for idx in g:
                matched = None
                for r in reps:
                    s = vcos(vecs[idx], vecs[r])
                    r_charsim = SequenceMatcher(None, stems4[idx], stems4[r]).ratio()
                    if final[idx]['q_type'] == 3:
                        # 判断：主带（TF-IDF>=0.85 且 字符>=0.65）或 收紧带（字符>=0.88 且 TF-IDF>=0.55）
                        ok = (s >= STAGE4_JUDGE_SIM and r_charsim >= STAGE4_JUDGE_CHAR) or \
                             (r_charsim >= STAGE4_JUDGE_CHAR2 and s >= 0.55)
                    else:
                        # 单选/多选：主带（TF-IDF>=0.70）或 收紧带（TF-IDF>=0.65 且 字符>=0.65 且 选项重叠>=0.5）
                        ok = s >= STAGE4_CHOICE_SIM or \
                             (s >= STAGE4_CHOICE_SIM2 and r_charsim >= STAGE4_CHAR2 and
                              options_overlap(final[idx], final[r]) >= STAGE4_OPT_OVERLAP)
                    if ok:
                        matched = r
                        break
                if matched is None:
                    reps.append(idx)
                else:
                    si, sj = final[matched], final[idx]
                    if quality(sj) > quality(si):
                        si, sj = sj, si
                    elif quality(sj) == quality(si) and sj['id'] < si['id']:
                        si, sj = sj, si
                    merge_q(si, sj)
                    stage4_remove.add(id(sj))
                    stage4_merged_info.append((si['id'], sj['id'], round(vcos(vecs[matched], vecs[idx]), 3)))
        print(f'Stage4 语义级去重（题意相同，答案锚定+TF-IDF）: 合并 {len(stage4_merged_info)} 对（删除 {len(stage4_remove)} 题）')
    except ImportError as e:
        print(f'Stage4 跳过：缺少依赖 {e}（pip install jieba numpy 后重跑）')

    # ---------- Stage 3: 灰区复核清单 ----------
    gray = []
    gray_seen = set()
    for (i, j) in pairs:
        if i in stage2_remove or j in stage2_remove:
            continue
        qi, qj = remain[i], remain[j]
        if qi['q_type'] != qj['q_type']:
            continue
        if norm(qi['answer']) != norm(qj['answer']):
            continue
        r = SequenceMatcher(None, stems[i], stems[j]).ratio()
        if STAGE3_MIN <= r < STAGE2_SIM:
            key = tuple(sorted((min(qi['id'], qj['id']), max(qi['id'], qj['id']))))
            if key in gray_seen:
                continue
            gray_seen.add(key)
            gray.append({
                'sim': round(r, 3),
                'id_a': qi['id'], 'id_b': qj['id'],
                'qtype': qi['q_type'],
                'answer': qi['answer'],
                'text_a': qi['question_text'][:80],
                'text_b': qj['question_text'][:80],
                'file_a': qi['_file'], 'file_b': qj['_file'],
            })
    gray.sort(key=lambda x: -x['sim'])
    print(f'Stage3 灰区候选（{STAGE3_MIN}-{STAGE2_SIM}，需人工/AI复核）: {len(gray)} 对')

    # ---------- 报告 ----------
    report = {
        'mode': 'apply' if apply else 'dry-run',
        'total_before': total,
        'stage1_removed': len(stage1_remove),
        'stage2_removed': len(stage2_remove),
        'stage4_removed': len(stage4_remove),
        'stage2_merged_pairs': stage2_merged_info,
        'stage4_merged_pairs': stage4_merged_info,
        'stage3_gray_pairs': len(gray),
        'total_after': total - len(stage1_remove) - len(stage2_remove) - len(stage4_remove),
    }
    with open(os.path.join(REPORT_DIR, 'dedup_report.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(os.path.join(REPORT_DIR, 'gray_zone_review.json'), 'w', encoding='utf-8') as f:
        json.dump(gray, f, ensure_ascii=False, indent=2)
    print(f'\n报告: scripts/dedup/reports/dedup_report.json')
    print(f'灰区清单: scripts/dedup/reports/gray_zone_review.json')
    print(f'合计删除 {len(stage1_remove) + len(stage2_remove) + len(stage4_remove)} 题 → {report["total_after"]} 题')

    if apply:
        final = [q for idx, q in enumerate(remain) if idx not in stage2_remove and id(q) not in stage4_remove]
        assert len(final) == report['total_after']
        save_all(final)
        print('\n已写回数据文件。请更新 manifest.json 计数并 npm run build。')
    else:
        print('\nDRY-RUN 完成，未修改任何文件。确认后加 --apply 执行。')


if __name__ == '__main__':
    main()
