package com.daoyou.tiku.logic

import com.daoyou.tiku.data.Question
import com.daoyou.tiku.data.QuestionRepository
import com.daoyou.tiku.data.RecordsStore
import kotlinx.serialization.Serializable

/** 笔试单题（脱敏：不含答案）。 */
@Serializable
data class ExamQuestion(
    val id: Long,
    @kotlinx.serialization.SerialName("question_text") val questionText: String,
    val options: List<String>,
    @kotlinx.serialization.SerialName("q_type") val qType: Int,
    val subject: Int? = null,
    val province: String? = null,
    val years: String? = null,
)

/** 一套笔试卷。 */
@Serializable
data class ExamPaper(
    @kotlinx.serialization.SerialName("paper_id") val paperId: String,
    @kotlinx.serialization.SerialName("paper_type") val paperType: Int,
    val label: String,
    val minutes: Int,
    @kotlinx.serialization.SerialName("type_counts") val typeCounts: Map<Int, Int>,
    val total: Int,
    val questions: List<ExamQuestion>,
)

/** 逐题判定结果（笔试：answer 返回原始存储答案，勿混改）。 */
@Serializable
data class ExamCheckResult(
    @kotlinx.serialization.SerialName("question_id") val questionId: Long,
    val correct: Boolean,
    val answer: String,
    val explanation: String?,
    @kotlinx.serialization.SerialName("question_text") val questionText: String,
    @kotlinx.serialization.SerialName("q_type") val qType: Int,
)

/** 汇总判分结果。 */
@Serializable
data class ExamResult(
    @kotlinx.serialization.SerialName("total_score") val totalScore: Double,
    @kotlinx.serialization.SerialName("full_score") val fullScore: Double,
    @kotlinx.serialization.SerialName("type_stats") val typeStats: Map<Int, TypeStat>,
) {
    @Serializable
    data class TypeStat(val total: Int, val correct: Int)
}

/**
 * 笔试模拟引擎：
 * - paper_type=1 科目一+二、2 科目三+四
 * - 题型题量 单选90+多选35+判断40（2025 官方大纲），90 分钟
 * - 分值 单选0.5/多选1/判断0.5（满分 100）
 * - 近三年真题优先 60% + 历史真题补齐 40%（历史真题不足时从近三年补足）；组内按历史出现次数平衡抽取
 * - session 为内存态（组卷后判分针对当次精确题目）
 */
object ExamEngine {

    private val PAPERS = mapOf(
        1 to Pair(listOf(1, 2), "科目一+科目二 合并卷（政策法规+导游业务）"),
        2 to Pair(listOf(3, 4), "科目三+科目四 合并卷（全国基础+地方知识）"),
    )
    private val TYPE_COUNTS = listOf(1 to 90, 2 to 35, 3 to 40)
    private val TYPE_SCORES = mapOf(1 to 0.5, 2 to 1.0, 3 to 0.5)
    private const val EXAM_MINUTES = 90

    /**
     * 笔试近三年真题目标占比（0.6 = 近三年 60% + 历史真题补齐 40%）。
     * 原「只出近三年真题」池子仅 ~413/446 题，4 场考试即刷完导致反复重复（2026-09-20 修复）。
     */
    private const val EXAM_RECENT_RATIO = 0.6

    /** 各题型统计累加器。 */
    private class Acc { var total = 0; var correct = 0 }

    /** 内存试卷缓存：paperId -> 题目列表。 */
    private val sessions = mutableMapOf<String, List<Question>>()

    /** 组卷并缓存 session；返回脱敏题目（不含答案）。 */
    suspend fun examPaper(paperType: Int): ExamPaper {
        val (subjects, label) = PAPERS[paperType] ?: error("未知的试卷类型: $paperType")
        val pool = QuestionRepository.loadSubjects(subjects.map { it as Int? })
        val picked = mutableListOf<Question>()
        val typeCounts = mutableMapOf<Int, Int>()
        for ((qType, want) in TYPE_COUNTS) {
            val candidates = pool.filter {
                it.qType == qType && !it.answer.isNullOrEmpty() && subjects.contains(it.subject)
            }
            // 近三年真题优先（目标 60%）+ 历史真题补齐（is_real_exam=true 非近三年）；
            // 历史真题不足时从近三年补足，保证每卷题量完整；组内按出现次数平衡
            val recent = candidates.filter { QuizBuilder.isRecent(it) }
            val rest = candidates.filter { !QuizBuilder.isRecent(it) && it.isRealExam == true }
            val wantRecent = Math.round(want * EXAM_RECENT_RATIO).toInt()
            val fromRest = QuizBuilder.pickBalanced(rest, (want - minOf(wantRecent, recent.size)).coerceAtLeast(0))
            val fromRecent = QuizBuilder.pickBalanced(recent, (want - fromRest.size).coerceAtLeast(0))
            val chosen = fromRecent + fromRest
            picked.addAll(chosen)
            typeCounts[qType] = chosen.size
        }
        RecordsStore.bumpAppear(picked.map { it.id })
        val paperId = "p${System.currentTimeMillis()}${(0..999999).random()}"
        sessions[paperId] = picked
        val questions = picked.map { q ->
            ExamQuestion(
                id = q.id,
                questionText = q.questionText,
                options = q.options,
                qType = q.qType ?: 1,
                subject = q.subject,
                province = q.province,
                years = q.years,
            )
        }
        return ExamPaper(paperId, paperType, label, EXAM_MINUTES, typeCounts, questions.size, questions)
    }

    private fun sessionQuestion(paperId: String, questionId: Long): Question? =
        sessions[paperId]?.find { it.id == questionId }

    /** 会话内完整题目（含答案/解析，供笔试错题写入错题本）。 */
    fun examQuestionFull(paperId: String, questionId: Long): Question? =
        sessionQuestion(paperId, questionId)

    /** 单题即时判分；answer 返回原始存储答案（判断题「正确/错误」）。 */
    fun examCheck(paperId: String, questionId: Long, answer: String): ExamCheckResult? {
        val q = sessionQuestion(paperId, questionId) ?: return null
        val correct = Grading.isCorrectRaw(q, answer)
        return ExamCheckResult(q.id, correct, q.answer ?: "", q.explanation, q.questionText, q.qType ?: 1)
    }

    /** 汇总判分；同卷只可提交一次（提交后 session 移除，重交返回 null）。 */
    fun examSubmit(
        paperId: String,
        answers: List<Pair<Long, String>>,
    ): ExamResult? {
        val questions = sessions.remove(paperId) ?: return null
        val byId = questions.associateBy { it.id }
        val stats = mutableMapOf(1 to Acc(), 2 to Acc(), 3 to Acc())
        for ((qid, given) in answers) {
            val q = byId[qid] ?: continue
            val acc = stats[q.qType ?: 1] ?: continue
            acc.total += 1
            if (Grading.isCorrectRaw(q, given)) acc.correct += 1
        }
        val totalScore = listOf(1, 2, 3).sumOf { stats[it]!!.correct * TYPE_SCORES[it]!! }
        val fullScore = listOf(1, 2, 3).sumOf { stats[it]!!.total * TYPE_SCORES[it]!! }
        return ExamResult(
            totalScore = Math.round(totalScore * 10) / 10.0,
            fullScore = Math.round(fullScore * 10) / 10.0,
            typeStats = stats.mapValues { ExamResult.TypeStat(it.value.total, it.value.correct) },
        )
    }
}
