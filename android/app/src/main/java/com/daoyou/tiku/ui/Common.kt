package com.daoyou.tiku.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.daoyou.tiku.data.Question

/** 科目常量（与题库数据约定一致）。 */
object Subjects {
    val NAMES = mapOf(1 to "政策与法律法规", 2 to "导游业务", 3 to "全国导游基础知识", 4 to "地方导游基础知识")
    fun name(s: Int?): String = NAMES[s] ?: "未分类"
}

/** 题型常量：1 单选 / 2 多选 / 3 判断。 */
object QTypes {
    fun name(t: Int?): String = when (t) {
        1 -> "单选"
        2 -> "多选"
        3 -> "判断"
        else -> "单选"
    }

    fun label(t: Int?): String = when (t) {
        1 -> "单选题"
        2 -> "多选题"
        3 -> "判断题"
        else -> "单选题"
    }
}

/** 判断题选项字母 → 文案（归一化答案 A/B 对应 正确/错误）。 */
fun optionLabel(q: Question, letter: String): String = when (letter) {
    "A" -> if (q.qType == 3) "A 正确" else "A ${q.optionA.orEmpty()}"
    "B" -> if (q.qType == 3) "B 错误" else "B ${q.optionB.orEmpty()}"
    "C" -> "C ${q.optionC.orEmpty()}"
    "D" -> "D ${q.optionD.orEmpty()}"
    "E" -> "E ${q.optionE.orEmpty()}"
    else -> letter
}

/** 科目过滤条（全局 activeSubject 共用）。 */
@Composable
fun SubjectFilterBar(activeSubject: Int?, onChange: (Int?) -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        val items: List<Pair<Int?, String>> =
            listOf(null to "全部") + Subjects.NAMES.map { (k, v) -> k to v }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items.take(3).forEach { (k, label) ->
                FilterPill(label, activeSubject == k, Modifier.weight(1f)) { onChange(k) }
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items.drop(3).forEach { (k, label) ->
                FilterPill(label, activeSubject == k, Modifier.weight(1f)) { onChange(k) }
            }
        }
    }
}

/** 可点选的小药丸标签。 */
@Composable
fun FilterPill(label: String, selected: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Box(
        modifier = modifier
            .background(
                color = if (selected) MaterialTheme.colorScheme.primary
                else MaterialTheme.colorScheme.surfaceVariant,
                shape = RoundedCornerShape(16.dp),
            )
            .clickable { onClick() }
            .padding(horizontal = 10.dp, vertical = 8.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            color = if (selected) MaterialTheme.colorScheme.onPrimary
            else MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
        )
    }
}

/** 题目元信息行：科目 / 题型 / 年份 / 真题标记。 */
@Composable
fun QuestionMeta(q: Question) {
    val tags = buildList {
        add(Subjects.name(q.subject))
        add(QTypes.label(q.qType))
        q.years?.let { add("$it 年") }
        if (q.isRealExam == true) add("真题")
    }
    Text(
        text = tags.joinToString(" · "),
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.outline,
    )
}

/** 题型徽章配色与官方题型文案（对齐机考界面：单项选择题/多项选择题/判断题）。 */
private fun typeLabel(t: Int?): String = when (t) {
    2 -> "多项选择题"
    3 -> "判断题"
    else -> "单项选择题"
}

private fun typeColor(t: Int?): Color = when (t) {
    2 -> Color(0xFFEF6C00)
    3 -> Color(0xFF2E7D32)
    else -> Color(0xFF1976D2)
}

/** 题型徽章行：官方题型名 + 多选「可多选」提示。 */
@Composable
private fun TypeBadge(qType: Int?) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Box(
            modifier = Modifier
                .background(typeColor(qType), RoundedCornerShape(6.dp))
                .padding(horizontal = 8.dp, vertical = 3.dp),
        ) {
            Text(
                text = typeLabel(qType),
                style = MaterialTheme.typography.labelSmall,
                color = Color.White,
                fontWeight = FontWeight.Medium,
            )
        }
        if (qType == 2) {
            Text(
                text = "可多选",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.outline,
            )
        }
    }
}

/**
 * 试题列表面板（对齐官方机考）：题号按题型分组（判断/单选/多选），四态着色，点击跳题。
 * results：各题判定结果（null=未作答）；marked：被标记的题目下标集合；current：当前题下标。
 */
@Composable
fun QuestionNumberPanel(
    questions: List<Question>,
    results: List<Boolean?>,
    marked: Set<Int>,
    current: Int,
    onJump: (Int) -> Unit,
) {
    @Composable
    fun cellColor(idx: Int): Color = when {
        idx == current -> MaterialTheme.colorScheme.primary
        idx in marked -> Color(0xFFE53935)
        results.getOrNull(idx) != null -> Color(0xFF43A047)
        else -> MaterialTheme.colorScheme.surfaceVariant
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        listOf(3 to "判断题", 1 to "单选题", 2 to "多选题").forEach { (type, label) ->
            val idxs = questions.withIndex().filter { it.value.qType == type }.map { it.index }
            if (idxs.isEmpty()) return@forEach
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            idxs.chunked(8).forEach { row ->
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    row.forEach { idx ->
                        Box(
                            modifier = Modifier
                                .size(32.dp)
                                .background(cellColor(idx), RoundedCornerShape(6.dp))
                                .clickable { onJump(idx) },
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                text = "${idx + 1}",
                                style = MaterialTheme.typography.labelSmall,
                                color = if (idx == current || idx in marked || results.getOrNull(idx) != null) {
                                    Color.White
                                } else {
                                    MaterialTheme.colorScheme.onSurfaceVariant
                                },
                            )
                        }
                    }
                }
            }
        }
        // 四态图例（当前/未完成/已完成/标记）
        Row(
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            listOf(
                MaterialTheme.colorScheme.primary to "当前",
                MaterialTheme.colorScheme.surfaceVariant to "未完成",
                Color(0xFF43A047) to "已完成",
                Color(0xFFE53935) to "标记",
            ).forEach { (color, label) ->
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    Box(modifier = Modifier.size(10.dp).background(color, RoundedCornerShape(3.dp)))
                    Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

/**
 * 选项行（对齐机考：前置小按钮 + 选项文本）。
 * 单选/判断为圆形（radio 视觉），多选为圆角方形（checkbox 视觉，选中打对勾）。
 */
@Composable
private fun OptionRow(
    letter: String,
    text: String,
    qType: Int?,
    isChosen: Boolean,
    revealed: Boolean,
    isRef: Boolean,
    enabled: Boolean,
    onSelect: () -> Unit,
) {
    val multi = qType == 2
    val rowBg = when {
        revealed && isRef -> JudgeColors.correctBg
        revealed && isChosen && !isRef -> JudgeColors.wrongBg
        isChosen -> MaterialTheme.colorScheme.primaryContainer
        else -> MaterialTheme.colorScheme.surfaceVariant
    }
    val markBg = when {
        revealed && isRef -> Color(0xFF2E7D32)
        revealed && isChosen && !isRef -> Color(0xFFC62828)
        isChosen -> MaterialTheme.colorScheme.primary
        else -> MaterialTheme.colorScheme.outline
    }
    val markFg = if (revealed && !isRef && isChosen) Color.White
    else if (revealed && isRef || isChosen) Color.White
    else MaterialTheme.colorScheme.onSurfaceVariant
    val textFg = when {
        revealed && (isRef || (isChosen && !isRef)) -> JudgeColors.revealText
        isChosen -> MaterialTheme.colorScheme.onPrimaryContainer
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(rowBg, RoundedCornerShape(10.dp))
            .clickable(enabled = enabled) { onSelect() }
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(26.dp)
                .background(
                    markBg,
                    shape = if (multi) RoundedCornerShape(7.dp) else RoundedCornerShape(50),
                ),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = if (multi && isChosen && !revealed) "✓" else letter,
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.SemiBold,
                color = markFg,
            )
        }
        Spacer(Modifier.width(10.dp))
        Text(text = text, style = MaterialTheme.typography.bodyMedium, color = textFg)
    }
}

/**
 * 题目卡：题型徽章 + 题干 + 选项 + （揭示后）答案与解析。
 * selected：当前所选（多选为字母集合拼接）；revealed：是否已判分。
 * 多选/判断判分由调用方完成，这里只负责展示。
 */
@Composable
fun QuestionCard(
    q: Question,
    selected: Set<String>,
    revealed: Boolean,
    correctRef: String,
    explanation: String?,
    onSelect: (String) -> Unit,
    /** 判定后展示的答案文本（笔试传原始存储答案：判断题「正确/错误」）；null 时按归一化字母推导。 */
    answerDisplay: String? = null,
    /** 已判定后是否允许改选（笔试可改答案重判）。 */
    allowReanswer: Boolean = false,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            TypeBadge(q.qType)
            if (q.qType == 3) {
                // 官方机考判断题说明文案
                Text(
                    text = "（请对下列各题表述的正确与否作出判断，\"A\"表示正确，\"B\"表示错误。）",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                )
            }
            QuestionMeta(q)
            Text(
                text = q.questionText,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.Medium,
            )
            val letters = listOf("A", "B", "C", "D", "E").filter { letter ->
                // 空串/纯空白的选项一律不展示（历史数据存在 option_x="" 的脏值）
                when (letter) {
                    "A" -> !q.optionA.isNullOrBlank() || q.qType == 3
                    "B" -> !q.optionB.isNullOrBlank() || q.qType == 3
                    "C" -> !q.optionC.isNullOrBlank()
                    "D" -> !q.optionD.isNullOrBlank()
                    "E" -> !q.optionE.isNullOrBlank()
                    else -> false
                }
            }
            letters.forEach { letter ->
                OptionRow(
                    letter = letter,
                    text = optionLabel(q, letter),
                    qType = q.qType,
                    isChosen = letter in selected,
                    revealed = revealed,
                    isRef = correctRef.contains(letter),
                    enabled = !revealed || allowReanswer,
                    onSelect = { onSelect(letter) },
                )
            }
            if (revealed) {
                Spacer(Modifier.height(2.dp))
                Text(
                    text = "参考答案：${answerDisplay ?: (if (q.qType == 3) (if (correctRef == "A") "正确" else "错误") else correctRef)}",
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.primary,
                )
                if (!explanation.isNullOrEmpty()) {
                    Text(
                        text = "解析：$explanation",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

/** 可展开的浏览题卡（默认收起，点开展开选项/答案/解析）。 */
@Composable
fun BrowseQuestionCard(q: Question) {
    var expanded by remember { mutableStateOf(false) }
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { expanded = !expanded },
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            QuestionMeta(q)
            Text(q.questionText, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
            if (expanded) {
                val ref = com.daoyou.tiku.logic.Grading.refAnswer(q)
                q.options.forEachIndexed { idx, opt ->
                    val letter = ('A' + idx).toString()
                    val isRef = ref.contains(letter)
                    Text(
                        text = optionLabel(q, letter).ifEmpty { opt },
                        style = MaterialTheme.typography.bodySmall,
                        color = if (isRef) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                        fontWeight = if (isRef) FontWeight.SemiBold else FontWeight.Normal,
                    )
                }
                Text(
                    text = "参考答案：${if (q.qType == 3) (if (ref == "A") "正确" else "错误") else ref}",
                    style = MaterialTheme.typography.bodySmall,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.primary,
                )
                if (!q.explanation.isNullOrEmpty()) {
                    Text(
                        text = "解析：${q.explanation}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            } else {
                Text(
                    text = "点击展开选项与答案",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                )
            }
        }
    }
}
