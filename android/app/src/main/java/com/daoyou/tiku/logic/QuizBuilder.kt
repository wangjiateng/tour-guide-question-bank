package com.daoyou.tiku.logic

import com.daoyou.tiku.data.Question
import com.daoyou.tiku.data.QuestionRepository
import com.daoyou.tiku.data.RecordsStore
import kotlin.random.Random

/** 组卷选项（对齐 web 端 QuizOptions）。 */
data class QuizOptions(
    val size: Int,
    val answeredOnly: Boolean,
    val subject: Int? = null,
    val sourceId: Long? = null,
    val year: Int? = null,
    /** true=仅真题，false=仅练习，null=全部 */
    val isRealExam: Boolean? = null,
)

/**
 * 组卷逻辑，严格移植自 web 端 dataStore.ts：
 * - 近三年（2023-2025）真题 50% + 题引力新题（source_id=67）等补充 50%（原生端 55 开；web 端仍 70/30，两侧差异见 AGENTS.md）
 * - 未显式筛选来源/年份时排除历史老题与旧练习
 * - 按历史出现次数平衡抽取（出现少的题优先，抽后计数 +1）
 */
object QuizBuilder {

    private val RECENT_YEARS = setOf("2023", "2024", "2025")
    private const val RECENT_RATIO = 0.5

    fun isRecent(q: Question): Boolean =
        (q.years ?: "").split(",").any { it.trim() in RECENT_YEARS }

    /** 题引力（tiyinli）专题题：近三年之外的高质量补充。 */
    private fun isSupplement(q: Question): Boolean = q.sourceId == 67L

    private fun matchesYear(years: String?, year: Int): Boolean =
        years != null && years.split(",").mapNotNull { it.trim().toIntOrNull() }.contains(year)

    private fun <T> shuffle(arr: List<T>): List<T> = arr.shuffled(Random.Default)

    /** 按历史出现次数平衡取题：出现次数少的优先（组内随机）。 */
    fun <T : Question> pickBalanced(pool: List<T>, size: Int): List<T> {
        if (size <= 0) return emptyList()
        val wrong = RecordsStore.wrongIds()
        val byCount = sortedMapOf<Int, MutableList<T>>()
        for (t in pool) {
            // 错题加权：出现次数等效减一，排序上优先被抽中重现（对齐用户要求，原生端增强）
            val c = RecordsStore.appearCount(t.id) - (if (t.id in wrong) 1 else 0)
            byCount.getOrPut(c) { mutableListOf() }.add(t)
        }
        val out = mutableListOf<T>()
        for ((_, group) in byCount) {
            if (out.size >= size) break
            out.addAll(shuffle(group).take(size - out.size))
        }
        return out
    }

    /** 随机抽题（在线答题）。 */
    suspend fun randomQuiz(opts: QuizOptions): List<Question> {
        val subjects = if (opts.subject == null) listOf<Int?>(null, 1, 2, 3, 4) else listOf<Int?>(opts.subject)
        var pool = QuestionRepository.loadSubjects(subjects)
        if (opts.answeredOnly) pool = pool.filter { !it.answer.isNullOrEmpty() }
        if (opts.sourceId != null) pool = pool.filter { it.sourceId == opts.sourceId }
        if (opts.year != null) pool = pool.filter { matchesYear(it.years, opts.year) }
        if (opts.isRealExam != null) pool = pool.filter { it.isRealExam == opts.isRealExam }
        // 未显式筛选来源/年份：只从「近三年真题 + 题引力新题」出题
        if (opts.sourceId == null && opts.year == null) {
            pool = pool.filter { isRecent(it) || isSupplement(it) }
        }
        val n = minOf(opts.size, pool.size)
        val recent = pool.filter { isRecent(it) }
        val rest = pool.filter { !isRecent(it) }
        val nRecent = minOf(recent.size, Math.round(n * RECENT_RATIO).toInt())
        val out = pickBalanced(recent, nRecent) + pickBalanced(rest, n - nRecent)
        RecordsStore.bumpAppear(out.map { it.id })
        return out
    }

    /** 浏览：过滤 + 分页，按年份降序（对齐 web 端 queryQuestions）。 */
    suspend fun queryQuestions(
        subject: Int? = null,
        sourceId: Long? = null,
        province: String? = null,
        year: Int? = null,
        isRealExam: Boolean? = null,
        answered: String? = null,
        offset: Int = 0,
        limit: Int = 50,
    ): Pair<Int, List<Question>> {
        var pool = QuestionRepository.loadSubjects(
            if (subject == null) listOf(null, 1, 2, 3, 4) else listOf(subject),
        )
        if (sourceId != null) pool = pool.filter { it.sourceId == sourceId }
        if (!province.isNullOrEmpty()) pool = pool.filter { it.province?.contains(province) == true }
        if (year != null) pool = pool.filter { matchesYear(it.years, year) }
        if (isRealExam != null) pool = pool.filter { it.isRealExam == isRealExam }
        if (answered == "true") pool = pool.filter { !it.answer.isNullOrEmpty() }
        if (answered == "false") pool = pool.filter { it.answer.isNullOrEmpty() }
        pool = pool.sortedWith(
            compareByDescending<Question> { it.years ?: "" }.thenByDescending { it.id },
        )
        return pool.size to pool.drop(offset).take(limit)
    }
}
