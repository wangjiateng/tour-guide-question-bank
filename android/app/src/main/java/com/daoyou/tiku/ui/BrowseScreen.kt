package com.daoyou.tiku.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.daoyou.tiku.data.Question
import com.daoyou.tiku.data.Source
import com.daoyou.tiku.logic.QuizBuilder

/** 题目浏览：科目（全局）+ 年份/真题练习/已答过滤 + 分页列表，默认近三年（对齐 web 端浏览策略）。 */
@Composable
fun BrowseScreen(activeSubject: Int?) {
    var yearText by remember { mutableStateOf("") }
    var isRealExam by remember { mutableStateOf<Boolean?>(null) }
    var answered by remember { mutableStateOf<String?>(null) }
    var offset by remember { mutableStateOf(0) }
    var total by remember { mutableStateOf(0) }
    var list by remember { mutableStateOf<List<Question>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    var sources by remember { mutableStateOf<List<Source>>(emptyList()) }
    var sourceId by remember { mutableStateOf<Long?>(null) }

    val year: Int? = yearText.trim().toIntOrNull()

    suspend fun load(reset: Boolean) {
        loading = true
        try {
            val o = if (reset) 0 else offset
            val (t, page) = QuizBuilder.queryQuestions(
                subject = activeSubject,
                sourceId = sourceId,
                year = year,
                isRealExam = isRealExam,
                answered = answered,
                offset = o,
                limit = 50,
            )
            total = t
            list = if (reset) page else list + page
            if (reset) offset = 0
        } finally {
            loading = false
        }
    }

    // 筛选条件或科目变化时重置加载
    LaunchedEffect(activeSubject, yearText, isRealExam, answered, sourceId) {
        sources = runCatching { com.daoyou.tiku.data.QuestionRepository.loadSources() }.getOrDefault(emptyList())
        offset = 0
        load(reset = true)
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(horizontal = 12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = yearText,
                    onValueChange = { yearText = it },
                    label = { Text("年份（如 2025，空=近三年默认）") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterPill("真题与练习", isRealExam == null, Modifier.weight(1f)) { isRealExam = null }
                    FilterPill("仅真题", isRealExam == true, Modifier.weight(1f)) { isRealExam = true }
                    FilterPill("仅练习", isRealExam == false, Modifier.weight(1f)) { isRealExam = false }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterPill("全部", answered == null, Modifier.weight(1f)) { answered = null }
                    FilterPill("有答案", answered == "true", Modifier.weight(1f)) { answered = "true" }
                    FilterPill("无答案", answered == "false", Modifier.weight(1f)) { answered = "false" }
                }
                Text(
                    text = "共 $total 题",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.outline,
                )
            }
        }
        items(list, key = { "${it.id}" }) { q -> BrowseQuestionCard(q) }
        if (list.size < total) {
            item {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                    horizontalArrangement = Arrangement.Center,
                ) {
                    OutlinedButton(enabled = !loading, onClick = {
                        offset += 50
                    }) { Text(if (loading) "加载中…" else "加载更多") }
                }
            }
        }
    }
    // offset 变化触发追加
    LaunchedEffect(offset) { if (offset > 0) load(reset = false) }
}
