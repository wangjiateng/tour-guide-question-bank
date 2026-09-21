package com.daoyou.tiku.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.SnapshotStateList
import androidx.compose.runtime.snapshots.SnapshotStateMap
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.daoyou.tiku.data.Question
import com.daoyou.tiku.data.RecordsStore
import com.daoyou.tiku.logic.Grading
import kotlinx.coroutines.launch

/**
 * 错题本：错题列表 + 重练（HorizontalPager 左右滑动真实翻页，点选即判；错后答对仍在池）。
 * 性能要点与 QuizScreen 相同：状态读取下沉，拖动中外层作用域不重组。
 */
@Composable
fun WrongScreen(activeSubject: Int?) {
    var total by remember { mutableStateOf(0) }
    var questions by remember { mutableStateOf<List<Question>>(emptyList()) }
    var mode by remember { mutableStateOf("list") } // list | drill | done
    // per-index 作答/判定状态（翻页回看不重复计分）；selections 保存未确认的实时选择
    val answers = remember { mutableStateListOf<String?>() }
    val results = remember { mutableStateListOf<Boolean?>() }
    val selections = remember { mutableStateMapOf<Int, Set<String>>() }
    val marked = remember { mutableStateListOf<Int>() }
    var panelExpanded by remember { mutableStateOf(false) }
    val scope = androidx.compose.runtime.rememberCoroutineScope()

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
                    Button(onClick = {
                        mode = "drill"
                        answers.clear(); answers.addAll(List(questions.size) { null })
                        results.clear(); results.addAll(List(questions.size) { null })
                        selections.clear()
                        marked.clear()
                        panelExpanded = false
                    }) {
                        Text("重练")
                    }
                }
            }
            if (questions.isEmpty()) {
                Text("暂无错题，去答题练一练吧", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            questions.forEach { q -> BrowseQuestionCard(q) }
        }

        "done" -> Column(
            modifier = Modifier.fillMaxSize().padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("重练完成", style = MaterialTheme.typography.titleLarge)
            OutlinedButton(onClick = { mode = "list" }) { Text("返回错题本") }
        }

        else -> {
            val pagerState = rememberPagerState(pageCount = { questions.size })
            // 结构：顶部信息 + 翻页器撑满中间（全屏可滑）+ 底部按钮栏
            Column(
                modifier = Modifier.fillMaxSize().padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                DrillHeader(pagerState, results, questions.size)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text("试题列表", style = MaterialTheme.typography.labelMedium)
                    Text(
                        text = if (panelExpanded) "收起 ▲" else "展开 ▼",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.clickable { panelExpanded = !panelExpanded },
                    )
                }
                if (panelExpanded) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(max = 240.dp)
                            .verticalScroll(rememberScrollState()),
                    ) {
                        QuestionNumberPanel(
                            questions = questions,
                            results = results,
                            marked = marked.toSet(),
                            current = pagerState.currentPage,
                            onJump = { j -> scope.launch { pagerState.animateScrollToPage(j) } },
                        )
                    }
                }
                HorizontalPager(
                    state = pagerState,
                    pageSpacing = 12.dp,
                    beyondViewportPageCount = 1,
                    modifier = Modifier.fillMaxWidth().weight(1f),
                ) { p ->
                    QuestionPage(q = questions[p], page = p, selections = selections, answers = answers, results = results)
                }
                DrillBottomBar(
                    pagerState = pagerState,
                    marked = marked,
                    total = questions.size,
                    scope = scope,
                    onFinish = { mode = "done" },
                )
            }
        }
    }
}

/** 重练顶部进度：内部经 derivedStateOf 读取当前页。 */
@Composable
private fun DrillHeader(pagerState: PagerState, results: SnapshotStateList<Boolean?>, total: Int) {
    val page by remember(pagerState) { derivedStateOf { pagerState.currentPage } }
    Text(
        text = "重练 ${page + 1} / $total · 答对 ${results.count { it == true }}",
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.outline,
    )
}

/** 重练底部按钮栏：内部经 derivedStateOf 读取当前页。 */
@Composable
private fun DrillBottomBar(
    pagerState: PagerState,
    marked: SnapshotStateList<Int>,
    total: Int,
    scope: kotlinx.coroutines.CoroutineScope,
    onFinish: () -> Unit,
) {
    val page by remember(pagerState) { derivedStateOf { pagerState.currentPage } }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        OutlinedButton(
            onClick = { if (page in marked) marked.remove(page) else marked.add(page) },
        ) { Text(if (page in marked) "取消标记" else "标记本题") }
        Spacer(Modifier.weight(1f))
        OutlinedButton(
            enabled = page > 0,
            onClick = { scope.launch { pagerState.animateScrollToPage(page - 1) } },
        ) { Text("上一题") }
        Button(onClick = {
            if (page + 1 < total) {
                scope.launch { pagerState.animateScrollToPage(page + 1) }
            } else {
                onFinish()
            }
        }) { Text(if (page + 1 < total) "下一题" else "完成") }
    }
}
