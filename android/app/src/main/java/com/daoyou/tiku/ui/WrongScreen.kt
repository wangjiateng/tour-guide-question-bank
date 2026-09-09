package com.daoyou.tiku.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.daoyou.tiku.data.Question
import com.daoyou.tiku.data.RecordsStore
import com.daoyou.tiku.logic.Grading

/** 错题本：错题列表 + 重练（逐题判定，与 web 端 WrongView 一致；错后答对仍在池）。 */
@Composable
fun WrongScreen(activeSubject: Int?) {
    var total by remember { mutableStateOf(0) }
    var questions by remember { mutableStateOf<List<Question>>(emptyList()) }
    var mode by remember { mutableStateOf("list") } // list | drill
    var drillIndex by remember { mutableStateOf(0) }
    var selected by remember { mutableStateOf(setOf<String>()) }
    var revealed by remember { mutableStateOf(false) }

    LaunchedEffect(activeSubject) {
        val (t, list) = RecordsStore.wrongPool(subject = activeSubject, offset = 0, limit = 100)
        total = t
        questions = list
    }

    when (mode) {
        "list" -> Column(
            modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("错题 $total 道", style = MaterialTheme.typography.titleMedium)
                Text(
                    text = "连续答对 ${RecordsStore.GRADUATE_STREAK} 次自动毕业",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                )
                if (questions.isNotEmpty()) {
                    Button(onClick = { mode = "drill"; drillIndex = 0; selected = emptySet(); revealed = false }) {
                        Text("重练")
                    }
                }
            }
            if (questions.isEmpty()) {
                Text("暂无错题，去答题练一练吧", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            questions.forEach { q -> BrowseQuestionCard(q) }
        }

        else -> {
            if (drillIndex >= questions.size) {
                Column(
                    modifier = Modifier.fillMaxSize().padding(16.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Text("重练完成", style = MaterialTheme.typography.titleLarge)
                    OutlinedButton(onClick = { mode = "list" }) { Text("返回错题本") }
                }
            } else {
                val q = questions[drillIndex]
                Column(
                    modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Text(
                        text = "重练 ${drillIndex + 1} / ${questions.size}",
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
                                val r = Grading.checkQuestion(q, given)
                                RecordsStore.recordAttempt(q, given, r.correct)
                                revealed = true
                            },
                        ) { Text("提交答案") }
                        if (revealed) {
                            Button(onClick = {
                                drillIndex += 1; selected = emptySet(); revealed = false
                            }) { Text(if (drillIndex + 1 < questions.size) "下一题" else "完成") }
                        }
                    }
                }
            }
        }
    }
}
