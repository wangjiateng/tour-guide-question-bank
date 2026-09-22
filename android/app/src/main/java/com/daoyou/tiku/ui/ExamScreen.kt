package com.daoyou.tiku.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.daoyou.tiku.data.Question
import com.daoyou.tiku.data.RecordsStore
import com.daoyou.tiku.logic.ExamCheckResult
import com.daoyou.tiku.logic.ExamEngine
import com.daoyou.tiku.logic.ExamPaper
import com.daoyou.tiku.logic.ExamResult
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** 在线笔试模拟：两套卷（科目一+二 / 科目三+四），165 题 / 100 分 / 90 分钟。 */
@Composable
fun ExamScreen() {
    var paper by remember { mutableStateOf<ExamPaper?>(null) }
    var result by remember { mutableStateOf<ExamResult?>(null) }
    var loading by remember { mutableStateOf(false) }
    val scope = androidx.compose.runtime.rememberCoroutineScope()

    when {
        paper == null && result == null -> {
            Column(
                modifier = Modifier.fillMaxSize().padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text("在线笔试模拟", style = MaterialTheme.typography.titleLarge)
                Text(
                    "单选 90 × 0.5 分 + 多选 35 × 1 分 + 判断 40 × 0.5 分，满分 100，限时 90 分钟。每题选择答案后立即判定对错并显示正确答案与解析。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (loading) CircularProgressIndicator()
                listOf(1 to "科目一+科目二 合并卷", 2 to "科目三+科目四 合并卷").forEach { (type, label) ->
                    Button(onClick = {
                        loading = true
                        scope.launch {
                            try {
                                paper = ExamEngine.examPaper(type)
                            } finally {
                                loading = false
                            }
                        }
                    }) { Text(label) }
                }
            }
        }

        result != null -> {
            val r = result!!
            Column(
                modifier = Modifier.fillMaxSize().padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text("考试成绩", style = MaterialTheme.typography.titleLarge)
                Text(
                    text = "${r.totalScore} 分 / 满分 ${r.fullScore}",
                    style = MaterialTheme.typography.headlineLarge,
                    color = MaterialTheme.colorScheme.primary,
                    fontWeight = FontWeight.Bold,
                )
                r.typeStats.toSortedMap().forEach { (type, stat) ->
                    Text(
                        text = "${QTypes.label(type)}：答对 ${stat.correct} / ${stat.total}",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
                OutlinedButton(onClick = { result = null }) { Text("返回选题") }
            }
        }

        else -> ExamRunner(paper!!, onSubmitted = { r -> result = r; paper = null })
    }
}

/**
 * 答题执行器：逐题判定——
 * 单选/判断点选即判；多选勾选后点「确认答案」判定；已判题可改答案重判；
 * 翻页/跳题/交卷前自动补判未确认的多选；题号导航区分 当前/对/错/已答。
 */
@Composable
private fun ExamRunner(paper: ExamPaper, onSubmitted: (ExamResult) -> Unit) {
    var index by remember { mutableIntStateOf(0) }
    var answers by remember { mutableStateOf<Map<Long, String>>(emptyMap()) }
    var verdicts by remember { mutableStateOf<Map<Long, Boolean>>(emptyMap()) }
    var checkedMap by remember { mutableStateOf<Map<Long, ExamCheckResult>>(emptyMap()) }
    var showNav by remember { mutableStateOf(false) }
    var finished by remember { mutableStateOf(false) }
    var remaining by remember { mutableIntStateOf(paper.minutes * 60) }

    // 判定指定题（answer 返回原始存储答案：判断题「正确/错误」）
    fun judge(qid: Long) {
        val chosen = answers[qid] ?: return
        val r = ExamEngine.examCheck(paper.paperId, qid, chosen) ?: return
        verdicts = verdicts + (qid to r.correct)
        checkedMap = checkedMap + (qid to r)
        // 笔试错题收进错题本（普通题答对不写记录，避免整卷污染答题历史）
        if (!r.correct) {
            ExamEngine.examQuestionFull(paper.paperId, qid)?.let {
                RecordsStore.recordAttempt(it, chosen, false)
            }
        } else if (qid in RecordsStore.wrongIds()) {
            // 错题在笔试中答对也单独记录：推进「连续答对 5 次毕业」计数
            ExamEngine.examQuestionFull(paper.paperId, qid)?.let {
                RecordsStore.recordAttempt(it, chosen, true)
            }
        }
    }

    // 离开当前题/交卷前自动补判未确认的多选（保证题号导航与统计一致）
    fun commitCurrent() {
        val cur = paper.questions.getOrNull(index) ?: return
        if (cur.qType == 2 && cur.id !in verdicts && answers.containsKey(cur.id)) judge(cur.id)
    }

    LaunchedEffect(Unit) {
        while (remaining > 0) {
            delay(1000)
            remaining -= 1
        }
    }
    // 时间到自动交卷
    LaunchedEffect(remaining) {
        if (remaining == 0 && !finished) {
            finished = true
            val r = ExamEngine.examSubmit(paper.paperId, answers.map { it.key to it.value })
            if (r != null) onSubmitted(r)
        }
    }

    val cur = paper.questions[index]
    val mm = (remaining / 60).toString().padStart(2, '0')
    val ss = (remaining % 60).toString().padStart(2, '0')
    val answeredCount = answers.size
    val correctCount = verdicts.count { it.value }
    val wrongCount = verdicts.count { !it.value }
    val verdict = verdicts[cur.id]
    val checkedResult = checkedMap[cur.id]
    // 高亮用归一化字母（判断题「正确/错误」→ A/B），显示用原始存储答案
    val normRef = checkedResult?.answer?.uppercase()?.let { raw ->
        if (cur.qType == 3) (if (raw.contains("正确")) "A" else if (raw.contains("错误")) "B" else raw)
        else raw.replace(",", "")
    } ?: ""

    Column(
        modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "已答 $answeredCount/${paper.total} · 对 $correctCount 错 $wrongCount",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.outline,
            )
            Text(
                text = "$mm:$ss",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = if (remaining < 300) Color(0xFFD32F2F) else MaterialTheme.colorScheme.primary,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(onClick = { commitCurrent(); showNav = !showNav }) {
                Text(if (showNav) "收起题号" else "题号导航")
            }
            Button(enabled = !finished, onClick = {
                commitCurrent()
                finished = true
                val r = ExamEngine.examSubmit(paper.paperId, answers.map { it.key to it.value })
                if (r != null) onSubmitted(r)
            }) { Text("结束考试") }
        }
        if (showNav) {
            LazyVerticalGrid(
                columns = GridCells.Fixed(8),
                // 有界高度必需：垂直懒加载组件嵌在 verticalScroll 容器内时，
                // 无限高度约束会直接 IllegalStateException 崩溃（故用 heightIn 限高）
                modifier = Modifier.fillMaxWidth().heightIn(max = 320.dp).padding(vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(paper.questions.size) { i ->
                    val q = paper.questions[i]
                    val v = verdicts[q.id]
                    val bg = when {
                        i == index -> MaterialTheme.colorScheme.primary
                        v == true -> JudgeColors.correctBg
                        v == false -> JudgeColors.wrongBg
                        answers.containsKey(q.id) -> MaterialTheme.colorScheme.primaryContainer
                        else -> MaterialTheme.colorScheme.surfaceVariant
                    }
                    Box(
                        modifier = Modifier
                            .size(36.dp)
                            .background(bg, CircleShape)
                            .clickable { commitCurrent(); index = i },
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = "${i + 1}",
                            style = MaterialTheme.typography.labelSmall,
                            color = if (i == index) MaterialTheme.colorScheme.onPrimary
                            else MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
        QuestionCard(
            q = Question(
                id = cur.id, questionText = cur.questionText, optionA = cur.options.getOrNull(0),
                optionB = cur.options.getOrNull(1), optionC = cur.options.getOrNull(2),
                optionD = cur.options.getOrNull(3), optionE = cur.options.getOrNull(4),
                qType = cur.qType, subject = cur.subject, years = cur.years,
            ),
            selected = answers[cur.id]?.map { it.toString() }?.toSet() ?: emptySet(),
            revealed = verdict != null,
            correctRef = normRef,
            explanation = checkedResult?.explanation,
            answerDisplay = checkedResult?.answer,
            allowReanswer = !finished,
            onSelect = { letter ->
                if (finished) return@QuestionCard
                val qid = cur.id
                // 已判题改答案：清除判定，改完重判
                if (qid in verdicts) {
                    verdicts = verdicts - qid
                    checkedMap = checkedMap - qid
                }
                if (cur.qType == 2) {
                    val set = answers[qid]?.map { it.toString() }?.toSet() ?: emptySet()
                    val next = if (letter in set) set - letter else set + letter
                    answers = if (next.isEmpty()) answers - qid else answers + (qid to next.sorted().joinToString(""))
                    // 多选：勾选不自动判，选好后点「确认答案」
                } else {
                    answers = answers + (qid to letter)
                    judge(qid) // 单选/判断点选即判
                }
            },
        )
        // 多选确认按钮（未判定且有选择时）
        if (cur.qType == 2 && verdict == null && !finished) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    "多选题：勾选全部选项后点击「确认答案」判定。",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                )
                Button(
                    enabled = answers.containsKey(cur.id),
                    onClick = { judge(cur.id) },
                ) { Text("确认答案") }
            }
        }
        // 判定反馈（显示原始存储答案：判断题显示「正确答案：正确」）
        if (verdict != null && checkedResult != null) {
            Text(
                text = (if (verdict) "✓ 答对了" else "✗ 答错了") + " · 正确答案：${checkedResult.answer}",
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.SemiBold,
                color = if (verdict) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(enabled = index > 0, onClick = { commitCurrent(); index -= 1 }) { Text("上一题") }
            if (index + 1 < paper.total) {
                Button(onClick = { commitCurrent(); index += 1 }) { Text("下一题") }
            }
        }
    }
}
