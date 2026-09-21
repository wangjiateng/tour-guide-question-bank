package com.daoyou.tiku.data

import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonEncoder
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive

/** 题库 JSON 统一解析配置：忽略未知字段（历史数据字段演进），宽松容错。 */
val quizJson: Json = Json { ignoreUnknownKeys = true; isLenient = true }

/**
 * years 字段历史数据存在脏值（list 如 ['0','1','2023'] 或逗号串），统一归一化为
 * 逗号分隔的 4 位年份串（仅保留合法年份），保证下游 split(",") 安全。
 */
object FlexibleYearsSerializer : KSerializer<String?> {
    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("FlexibleYears", PrimitiveKind.STRING)

    override fun deserialize(decoder: Decoder): String? {
        val el: JsonElement = (decoder as JsonDecoder).decodeJsonElement()
        val parts: List<String> = when (el) {
            is JsonNull -> return null
            is JsonArray -> el.map { it.jsonPrimitive.content }
            else -> listOf(el.jsonPrimitive.content)
        }
        val valid = parts.map { it.trim() }.filter { Regex("^\\d{4}$").matches(it) }
        return valid.joinToString(",").ifEmpty { null }
    }

    override fun serialize(encoder: Encoder, value: String?) {
        (encoder as JsonEncoder).encodeJsonElement(if (value == null) JsonNull else JsonPrimitive(value))
    }
}

/**
 * 题目模型，字段与仓库根 data/ 目录的题库 JSON（唯一事实源）对齐。
 * answer 原样保留：判断题中文「正确/错误」、多选字母串——判分时归一化，勿在数据侧改动。
 */
@Serializable
data class Question(
    val id: Long,
    @SerialName("question_text") val questionText: String = "",
    @SerialName("option_a") val optionA: String? = null,
    @SerialName("option_b") val optionB: String? = null,
    @SerialName("option_c") val optionC: String? = null,
    @SerialName("option_d") val optionD: String? = null,
    @SerialName("option_e") val optionE: String? = null,
    val answer: String? = null,
    val explanation: String? = null,
    val subject: Int? = null,
    @SerialName("q_type") val qType: Int? = null,
    val province: String? = null,
    @Serializable(with = FlexibleYearsSerializer::class) val years: String? = null,
    @SerialName("is_real_exam") val isRealExam: Boolean? = null,
    @SerialName("source_id") val sourceId: Long? = null,
    @SerialName("paper_title") val paperTitle: String? = null,
    @SerialName("source_url") val sourceUrl: String? = null,
) {
    /** 选项列表：A-E 过滤空值与空串（历史数据存在 option_x="" 的脏值）。 */
    val options: List<String>
        get() = listOfNotNull(optionA, optionB, optionC, optionD, optionE)
            .filter { it.isNotBlank() }
}

/** manifest.json：统计信息 + generated_at 版本号。 */
@Serializable
data class Manifest(
    @SerialName("generated_at") val generatedAt: String = "",
    val total: Int = 0,
    val answered: Int = 0,
    val sources: Int = 0,
    @SerialName("per_subject") val perSubject: Map<String, Int> = emptyMap(),
)

/** 来源元数据（来源筛选用）。 */
@Serializable
data class Source(
    val id: Long,
    val url: String? = null,
    val title: String? = null,
    val kind: String? = null,
    val status: String? = null,
    @SerialName("question_count") val questionCount: Int? = null,
    @SerialName("last_refresh_at") val lastRefreshAt: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
)

@Serializable
data class SourcesFile(val generated_at: String = "", val sources: List<Source> = emptyList())

@Serializable
data class QuestionsFile(
    @SerialName("generated_at") val generatedAt: String = "",
    val subject: Int? = null,
    val questions: List<Question> = emptyList(),
)

/** map 的便捷序列化器。 */
object StringIntMapSerializer : KSerializer<Map<String, Int>> by MapSerializer(String.serializer(), Int.serializer())
