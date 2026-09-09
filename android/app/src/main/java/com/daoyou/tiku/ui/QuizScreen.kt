package com.daoyou.tiku.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
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
import androidx.compose.ui.unit.dp
import com.daoyou.tiku.data.Question
import com.daoyou.tiku.data.RecordsStore
import com.daoyou.tiku.logic.Grading
import com.daoyou.tiku.logic.QuizBuilder
import com.daoyou.tiku.logic.QuizOptions
import kotlinx.coroutines.launch

/** 在线答题：近三年真题 70% + 题引力补充，判分对齐 web 端 checkQuestion。 */
@Composable
fun QuizScreen(activeSubject: Int?) {
    // 阶段：idle 选参数 → loading → running 答题 → done 结果
    var stage by remember { mutableStateOf("idle") }
    var questions by remember { mutableStateOf<List<Question>>(emptyList()) }
    var index by remember { mutableIntStateOf(0) }
    var selected by remember { mutableStateOf(setOf<String>()) }
    var revealed by remember { mutableStateOf(false) }
    var correctCount by remember { mutableIntStateOf(0) }
    var size by remember { mutableIntStateOf(10) }
    val scope = androidx.compose.runtime.rememberCoroutineScope()

    when (stage) {
        "idle" -> {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text("在线随机练习", style = MaterialTheme.typography.titleLarge)
                Text(
                    text = "版本 ${com.daoyou.tiku.BuildConfig.VERSION_NAME}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                )
                Text(
                    text = "默认近三年真题 70% + 题引力新题 30%${activeSubject?.let { " · ${Subjects.name(it)}" } ?: " · 全部科目"}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(10, 20, 30, 50).forEach { n ->
                        FilterPill("$n 题", size == n) { size = n }
                    }
                }
                Button(onClick = {
                    stage = "loading"
                    scope.launch {
                        try {
                            questions = QuizBuilder.randomQuiz(
                                QuizOptions(size = size, answeredOnly = true, subject = activeSubject),
                            )
                            index = 0; correctCount = 0; revealed = false; selected = emptySet()
                            stage = if (questions.isEmpty()) "idle" else "running"
                        } catch (e: Exception) {
                            stage = "idle"
                        }
                    }
                }) { Text("开始答题") }
            }
        }

        "loading" -> Column(
            modifier = Modifier.fillMaxSize().padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) { CircularProgressIndicator() }

        "running" -> {
            val q = questions[index]
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(
                    text = "第 ${index + 1} / ${questions.size} 题 · 本次答对 $correctCount",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.outline,
                )
                QuestionCard(
                    q = q,
                    selected = selected,
                    revealed = revealed,
                    correctRef = Grading.refAnswer(q),
                    explanation = q.explanation,
                    onSelect = { letter ->
                        selected = when (q.qType) {
                            2 -> if (letter in selected) selected - letter else selected + letter
                            else -> setOf(letter)
                        }
                    },
                )
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Button(
                        enabled = selected.isNotEmpty() && !revealed,
                        onClick = {
                            val given = selected.sorted().joinToString("")
                            val result = Grading.checkQuestion(q, given)
                            RecordsStore.recordAttempt(q, given, result.correct)
                            if (result.correct) correctCount += 1
                            revealed = true
                        },
                    ) { Text("提交答案") }
                    if (revealed) {
                        Button(onClick = {
                            if (index + 1 < questions.size) {
                                index += 1; revealed = false; selected = emptySet()
                            } else {
                                stage = "done"
                            }
                        }) { Text(if (index + 1 < questions.size) "下一题" else "查看结果") }
                    }
                }
                Spacer(Modifier.height(24.dp))
            }
        }

        "done" -> Column(
            modifier = Modifier.fillMaxSize().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("本组完成", style = MaterialTheme.typography.titleLarge)
            Text(
                text = "答对 $correctCount / ${questions.size} 题",
                style = MaterialTheme.typography.headlineMedium,
                color = MaterialTheme.colorScheme.primary,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(onClick = { stage = "idle" }) { Text("再来一组") }
            }
        }
    }
}
