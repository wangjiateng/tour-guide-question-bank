package com.daoyou.tiku.logic

import com.daoyou.tiku.data.Question
import kotlinx.serialization.Serializable

/** 判分结果（对齐 web 端 CheckResult）。 */
@Serializable
data class CheckResult(
    @kotlinx.serialization.SerialName("question_id") val questionId: Long,
    val correct: Boolean,
    val answer: String,
    val explanation: String?,
)

/**
 * 判分逻辑，严格移植自 web 端 dataStore.ts（前端强耦合红线，勿混改）：
 * - 参考答案归一化：判断题中文「正确/错误」→ A/B，其余大写
 * - 多选答案顺序无关（"AC" ≡ "CA"）
 * - Quiz/错题本判分返回归一化字母；笔试判分返回原始存储答案（见 ExamEngine）
 */
object Grading {

    /** 归一化参考答案：判断题中文（正确/错误）→ A/B；其余大写。 */
    fun refAnswer(q: Question): String {
        val a = (q.answer ?: "").trim().uppercase()
        return if (q.qType == 3 && (a == "正确" || a == "错误")) {
            if (a == "正确") "A" else "B"
        } else a
    }

    /** 多选答案顺序无关比较："AC" ≡ "CA"。 */
    private fun sameMulti(given: String, ref: String): Boolean {
        if (ref.isEmpty()) return false
        val norm = { s: String -> s.replace(",", "").map { it }.sorted().joinToString("") }
        return norm(given) == norm(ref)
    }

    private fun isCorrect(q: Question, given: String, ref: String): Boolean {
        val chosen = given.trim().uppercase()
        return if (q.qType == 2) sameMulti(chosen, ref) else ref.isNotEmpty() && chosen == ref
    }

    /** 判分一题（quiz / 错题本共用），answer 返回归一化后的 A/B 字母。 */
    fun checkQuestion(q: Question, given: String): CheckResult {
        val ref = refAnswer(q)
        return CheckResult(q.id, isCorrect(q, given, ref), ref, q.explanation)
    }

    /** 笔试判分共用（answer 返回原始存储答案由调用方处理）。 */
    fun isCorrectRaw(q: Question, given: String): Boolean = isCorrect(q, given, refAnswer(q))
}
