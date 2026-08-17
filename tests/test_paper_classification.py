"""Tests for the crawl-time paper classification and exam-year capture.

Covers:
- subject_from_paper_title: 书名号 titles, keywords, mixed papers -> None,
  foreign-language exclusion, fallback to source subject
- _paper_year / _merge_years: year extraction and multi-year union
- paper_title/paper_subject/years persisted on insert, years merged on re-crawl
- foreign-language paper exclusion at crawl time
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from daoyou_tiku.db import connect
from daoyou_tiku.examcoo import (
    EXCLUDED_SUBCATEGORIES,
    _FOREIGN_PAPER_RE,
)
from daoyou_tiku.service import (
    _MIX_PAPER_RE,
    _merge_years,
    _paper_year,
    classify_question_subject,
    classify_question_subject_mixed,
    province_from_paper_title,
    subject_from_paper_title,
)


# ---------------------------------------------------------------- title mapping

def test_subject_from_paper_title_book_titles():
    assert subject_from_paper_title("2012年《导游业务》真题", 4) == 2
    assert subject_from_paper_title("2011年《全国导游基础知识》真题", 2) == 3
    assert subject_from_paper_title("《旅游政策与法规》模拟试卷", 2) == 1
    assert subject_from_paper_title("2014年《地方导游基础知识》真题", 3) == 4


def test_subject_from_paper_title_keywords():
    assert subject_from_paper_title("导游业务第1至第3章单选题", 4) == 2
    assert subject_from_paper_title("导游服务技能真题", 4) == 2
    assert subject_from_paper_title("基础知识综合练习", 2) == 3


def test_subject_from_paper_title_mixed_returns_none():
    # mixed 科目一+科目二 papers carry no single subject; per-question split
    assert subject_from_paper_title("科目一+科目二模拟试卷第一套", 1) is None
    assert _MIX_PAPER_RE.search("科目一+科目二模拟试卷第一套")


def test_subject_from_paper_title_fallback_source():
    # no title signal -> source-level subject wins
    assert subject_from_paper_title("", 2) == 2
    assert subject_from_paper_title("", None) is None


def test_subject_from_paper_title_foreign_language():
    # foreign-language papers are excluded at crawl time; the title mapper
    # should not silently classify them
    assert _FOREIGN_PAPER_RE.search("2011年英语真题")
    assert not _FOREIGN_PAPER_RE.search("导游业务第1至第3章单选题")


# ---------------------------------------------------------------- province

def test_province_from_paper_title():
    assert province_from_paper_title("2012年重庆地方导游基础知识模拟题一") == "重庆"
    assert province_from_paper_title("2010年云南导游考试导游基础知识考前压题试卷一") == "云南"
    assert province_from_paper_title("2010年导游资格证考试江西、浙江、上海旅游试题1") == "江西,浙江,上海"
    assert province_from_paper_title("导游业务第1至第3章单选题") is None
    assert province_from_paper_title(None) is None
    assert province_from_paper_title("") is None


def test_province_dedupes_and_keeps_order():
    # repeated province names collapse; first-appearance order preserved
    assert province_from_paper_title("重庆与四川联合出题，四川卷") == "重庆,四川"


def test_subject_four_kept_against_legal_and_base_overrides():
    # 科目四题干天然含历史/地理/文化词, 必须信任 paper 级信号 4 不覆盖
    assert classify_question_subject("胡锦涛总书记为重庆新阶段发展提出了314总体部署", 4) == 4
    assert classify_question_subject("重庆大足石刻属于世界文化遗产", 4) == 4
    # 题干以省名开头(地方知识信号)时, 知识卷(3)改判科目四
    assert classify_question_subject("重庆大足石刻属于世界文化遗产", 3) == 4


def test_local_signal_reclassifies_to_four():
    # 题级地方信号: 题干以省名开头且非全国知识 -> 科目四
    assert classify_question_subject("浙江三雕是指（ ）。", 3) == 4
    assert classify_question_subject("我省积极开展各种专项旅游。", 3) == 4
    # 含全国词 -> 保持科目三
    assert classify_question_subject("我国浙江省的省会城市是（ ）。", 3) == 3
    # 多省列举 -> 全国比较知识, 保持科目三
    assert classify_question_subject("山东、江苏、福建、安徽菜的主要代表菜品依次是（ ）。", 3) == 3

def test_service_paper_not_reclassified_to_four():
    # 业务/法规卷(1,2)不因题干含省名词被跨科目改判为地方知识
    assert classify_question_subject("北京时间为12时时，下列哪些城市的地方时间为5时。", 2) == 2
    assert classify_question_subject("香港旅行社已为游客上了200万元的保险，导游员要协助办理的索赔证明是。", 2) == 2
    assert classify_question_subject("《云南省旅游条例》规定的原则是", 2) == 1


def test_paper_title_local_section_reclassifies_to_four():
    # 卷级地方章节信号: 「省名+地方章节词」且无全国词 -> 科目四
    assert subject_from_paper_title("2012年安徽省导游考试基础知识章节练习试题：第二章安徽历史", 3) == 4
    assert subject_from_paper_title("2010年北京市导游资格证考试导游基础知识试题--第一章 北京地理概况", 3) == 4
    # 「XX省考《导游基础知识》」无章节词 -> 保持科目三
    assert subject_from_paper_title("2003年河北省导游考试《导游基础知识》试题", 3) == 3

def test_excluded_subcategories_contains_411():
    assert "411" in EXCLUDED_SUBCATEGORIES


# ---------------------------------------------------------------- year helpers

@pytest.mark.parametrize(
    "title,want",
    [
        ("江苏2011年导游考试《导游服务技能》真题", "2011"),
        ("2019年全国导游资格考试", "2019"),
        ("导游综合知识导游业务试卷和试题：6.29导游业务第1至第3章单选题", None),
        (None, None),
        ("", None),
    ],
)
def test_paper_year(title, want):
    assert _paper_year(title) == want


@pytest.mark.parametrize(
    "existing,new,want",
    [
        (None, "2012", "2012"),
        ("2012", None, "2012"),
        ("2011,2012", "2012,2014", "2011,2012,2014"),
        ("2014,2012", "2010", "2010,2012,2014"),
        (None, None, None),
        ("2011,2012", "2012", "2011,2012"),
    ],
)
def test_merge_years(existing, new, want):
    assert _merge_years(existing, new) == want


# ---------------------------------------------------------- per-question split

def test_classify_mixed_legal_question():
    # legal/policy questions in a mixed paper -> 科目一
    assert classify_question_subject_mixed("全面推进依法治国的总目标是（ ）。") == 1
    assert classify_question_subject_mixed("《宪法》规定，法律和其他议案由全国人民代表大会以（ ）通过。") == 1
    assert classify_question_subject_mixed("下列不属于重点领域立法的是（）。") == 1


def test_classify_mixed_service_question():
    # concrete tour-guide service operation -> 科目二
    assert classify_question_subject_mixed("在景点的示意图前，地陪应讲明游览路线，并对景点做（ ）") == 2
    assert classify_question_subject_mixed("景区导游服务的核心工作是（ ）") == 2


def test_classify_mixed_default_legal():
    # mixed papers default to 科目一 when no marker matches
    assert classify_question_subject_mixed("下列关于饲养动物致人损害责任说法错误的是（ ）") == 1


def test_classify_single_keeps_source_subject():
    # non-mixed path keeps the paper/source subject when no marker matches
    assert classify_question_subject("带团时应注意的事项", 2) == 2
    assert classify_question_subject("旅游法关于投诉的规定", 2) == 1


# ------------------------------------------------------- persistence end-to-end

def test_paper_fields_persisted_and_years_merged(tmp_path):
    from daoyou_tiku.crawler import ParsedQuestion
    from daoyou_tiku import service

    def q(paper_title: str) -> list[ParsedQuestion]:
        return [
            ParsedQuestion(
                question_text="地陪服务的第一项工作是（ ）。",
                option_a="接站",
                option_b="送站",
                option_c="讲解",
                option_d="购物",
                answer="A",
                source_url="/editor/do/view/id/1",
                paper_title=paper_title,
            )
        ]

    db_path = tmp_path / "quiz.db"
    db = connect(db_path)
    db.execute(
        """INSERT INTO crawl_sources (id, url, title, kind, status)
           VALUES (1, 'examcoo://k/408/', '408', 'examcoo', 'ready')"""
    )
    db.commit()

    # first crawl from a 2011 paper
    service._store_questions(db, 1, "examcoo://k/408/", q("2011年导游资格考试《导游业务》真题"), subject=2)
    db.commit()
    row = db.execute("SELECT * FROM questions WHERE question_text LIKE '地陪服务的第一项工作%'").fetchone()
    assert row["paper_title"] == "2011年导游资格考试《导游业务》真题"
    assert row["paper_subject"] == 2
    assert row["years"] == "2011"
    assert row["subject"] == 2

    # same question reappears in a 2012 paper: years merge, one row kept
    service._store_questions(db, 1, "examcoo://k/408/", q("2012年导游资格考试《导游业务》真题"), subject=2)
    db.commit()
    rows = db.execute("SELECT * FROM questions WHERE question_text LIKE '地陪服务的第一项工作%'").fetchall()
    assert len(rows) == 1  # still deduplicated
    assert rows[0]["years"] == "2011,2012"
    assert rows[0]["paper_title"] == "2011年导游资格考试《导游业务》真题"  # first-seen title kept
    db.close()


def test_paper_title_stored_from_list_papers():
    # list page rows carry (pid, title); the title regex anchors on the row
    from daoyou_tiku import examcoo

    html = """
    <tr>
      <td title="2011年导游资格考试《导游业务》真题">
        <a href="/editor/do/view/id/12345">2011年导游资格考试《导游业务》真题</a>
      </td>
    </tr>
    <tr>
      <td title="科目一+科目二模拟试卷第一套">
        <a href="/editor/do/view/id/1559923">科目一+科目二模拟试卷第一套</a>
      </td>
    </tr>
    """
    pairs = examcoo._PAPER_TITLE_RE.findall(html)
    assert pairs == [
        ("2011年导游资格考试《导游业务》真题", "12345"),
        ("科目一+科目二模拟试卷第一套", "1559923"),
    ]
