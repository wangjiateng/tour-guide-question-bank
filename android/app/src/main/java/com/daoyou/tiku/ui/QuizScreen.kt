package com.daoyou.tiku.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshots.SnapshotStateList
import androidx.compose.runtime.snapshots.SnapshotStateMap
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.daoyou.tiku.data.Question
import com.daoyou.tiku.data.RecordsStore
import com.daoyou.tiku.logic.Grading
import com.daoyou.tiku.logic.QuizBuilder
import com.daoyou.tiku.logic.QuizOptions
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** 科目短名（答题页直选药丸）。 */
private val SUBJECT_SHORT = mapOf(1 to "科一", 2 to "科二", 3 to "科三", 4 to "科四")

/**
 * 在线答题：选科目后不限题量连续刷题；HorizontalPager 左右滑动真实翻页，点选即判。
 *
 * 全屏答题：刷题中通过 onFullScreen(true) 让 App 隐藏底部导航 → 无法误切页签；
 * 外层 when(tab) 分支不变、本组件不被销毁，故逐页作答状态天然保留（无需状态提升）。
 * 因不限题量，底部栏常驻「退出练习」按钮，任何时候都能退出，不会被困在全屏里；
 * 退出或翻到最后一题「完成本轮」时上报 false，导航栏恢复。
 *
 * 性能要点（滑动不掉帧的关键）：
 * - pagerState.currentPage 只在 Header/BottomBar 内部经 derivedStateOf 读取，
 *   拖动时外层组合作用域不重组 → Pager 的 content lambda 引用稳定 → 相邻页不会被中途重组
 * - 逐页状态（selections/answers/results）在 QuestionPage 内部读取，重组粒度=单页
 */
@Composable
fun QuizScreen(activeSubject: Int?, onFullScreen: (Boolean) -> Unit) {
    // 两态：选科目 → 连续刷题
    var questions by remember { mutableStateOf<List<Question>?>(null) }
    var loading by remember { mutableStateOf(false) }
    var loadError by remember { mutableStateOf(false) }
    var subject by rememberSaveable { mutableIntStateOf(activeSubject ?: 1) }
    // per-index 作答/判定状态（翻页回看不重复计分）；selections 保存未确认的实时选择
    val answers = remember { mutableStateListOf<String?>() }
    val results = remember { mutableStateListOf<Boolean?>() }
    val selections = remember { mutableStateMapOf<Int, Set<String>>() }
    val scope = androidx.compose.runtime.rememberCoroutineScope()

    // 刷题中 → 全屏（隐藏底部导航）；退出/完成回到选科目页自动复位
    LaunchedEffect(questions != null) { onFullScreen(questions != null) }

    val qs = questions
    if (qs == null) {
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
                text = "真题优先 · 不限题量 · ${Subjects.name(subject)}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                SUBJECT_SHORT.forEach { (s, label) ->
                    FilterPill(label, subject == s, Modifier.weight(1f)) { subject = s }
                }
            }
            if (loadError) {
                Text(
                    text = "该科目暂无可练习题目",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            Button(
                enabled = !loading,
                onClick = {
                    loading = true
                    loadError = false
                    scope.launch {
                        // 组卷（全库过滤+交错排序）为 CPU 密集，移出主线程
                        val loaded = withContext(Dispatchers.Default) {
                            try {
                                QuizBuilder.randomQuiz(
                                    QuizOptions(size = null, answeredOnly = true, subject = subject),
                                )
                            } catch (e: Exception) {
                                null
                            }
                        }
                        // 先清空旧状态再整体赋值，避免残留上一轮进度错位
                        answers.clear(); results.clear(); selections.clear()
                        if (loaded.isNullOrEmpty()) {
                            loadError = true
                        } else {
                            answers.addAll(List(loaded.size) { null })
                            results.addAll(List(loaded.size) { null })
                            questions = loaded
                        }
                        loading = false
                    }
                },
            ) { Text(if (loading) "组卷中…" else "开始答题") }
            if (loading) { CircularProgressIndicator() }
        }
    } else {
        val pagerState = rememberPagerState(pageCount = { qs.size })

        // 结构：顶部信息 + 翻页器撑满中间（全屏可滑，页内自行纵向滚动）+ 底部按钮栏
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            // 进度信息：内部读取 pager 状态，不触发外层重组
            PracticeHeader(pagerState, results, qs.size)
            // 左右滑动真实翻页：翻页器撑满剩余空间，全屏跟手；无 pageSpacing → 页面首尾相接无缝隙
            HorizontalPager(
                state = pagerState,
                beyondViewportPageCount = 1,
                modifier = Modifier.fillMaxWidth().weight(1f),
            ) { p ->
                QuestionPage(q = qs[p], page = p, selections = selections, answers = answers, results = results)
            }
            // 底部按钮栏（固定）：退出练习 / 上一题 / 下一题
            PracticeBottomBar(
                pagerState = pagerState,
                total = qs.size,
                scope = scope,
                onFinish = { questions = null },
            )
        }
    }
}

/** 顶部进度：内部经 derivedStateOf 读取当前页，拖动中仅本组件在跨页时重组。 */
@Composable
private fun PracticeHeader(pagerState: PagerState, results: SnapshotStateList<Boolean?>, total: Int) {
    val page by remember(pagerState) { derivedStateOf { pagerState.currentPage } }
    Text(
        text = "第 ${page + 1} / $total 题 · 本次答对 ${results.count { it == true }}",
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.outline,
    )
}

/** 单个题目页：自包含（读自身状态、判分、确认按钮），重组粒度=单页。 */
@Composable
internal fun QuestionPage(
    q: Question,
    page: Int,
    selections: SnapshotStateMap<Int, Set<String>>,
    answers: SnapshotStateList<String?>,
    results: SnapshotStateList<Boolean?>,
) {
    // 某页的实时选择：优先取未确认的实时值，其次取已提交答案
    val selected = selections[page]
        ?: answers[page]?.map { it.toString() }?.toSet()
        ?: emptySet()
    val revealed = results[page] != null
    Column(
        // 铺满页面底色：翻页时相邻页无缝隙、无露底黑框
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .verticalScroll(rememberScrollState()),
    ) {
        QuestionCard(
            q = q,
            selected = selected,
            revealed = revealed,
            correctRef = Grading.refAnswer(q),
            explanation = q.explanation,
            onSelect = { letter ->
                if (results[page] != null) return@QuestionCard
                when (q.qType) {
                    2 -> selections[page] = if (letter in selected) selected - letter else selected + letter
                    else -> {
                        selections[page] = setOf(letter)
                        commitQuestion(q, page, letter, answers, results)
                    }
                }
            },
        )
        // 多选确认按钮：紧跟题目卡下方（页面内），不占用底部栏
        if (q.qType == 2 && !revealed) {
            Spacer(Modifier.height(4.dp))
            Button(
                enabled = selected.isNotEmpty(),
                onClick = { commitQuestion(q, page, selected.sorted().joinToString(""), answers, results) },
                modifier = Modifier.fillMaxWidth(),
            ) { Text("确认答案") }
        }
    }
}

/**
 * 判定并记录某页（单选/判断点选即判；多选确认后判）。given 为显式传入的答案串，无任何时序依赖。
 * 记录策略与笔试页一致：只记答错（答对不写记录，避免污染答题历史）；
 * 例外是已在错题本中的题答对也记录一条，用于推进「连续答对 5 次毕业」计数。
 */
internal fun commitQuestion(
    q: Question,
    page: Int,
    given: String,
    answers: SnapshotStateList<String?>,
    results: SnapshotStateList<Boolean?>,
) {
    if (results[page] != null) return
    if (given.isEmpty()) return
    val r = Grading.checkQuestion(q, given)
    if (!r.correct) {
        RecordsStore.recordAttempt(q, given, false)
    } else if (q.id in RecordsStore.wrongIds()) {
        RecordsStore.recordAttempt(q, given, true)
    }
    answers[page] = given
    results[page] = r.correct
}

/** 底部按钮栏：内部经 derivedStateOf 读取当前页。左侧「退出练习」，右侧翻页按钮。 */
@Composable
private fun PracticeBottomBar(
    pagerState: PagerState,
    total: Int,
    scope: kotlinx.coroutines.CoroutineScope,
    onFinish: () -> Unit,
) {
    val page by remember(pagerState) { derivedStateOf { pagerState.currentPage } }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // 随时可退出本轮练习（不限题量，不能只靠翻到最后一题退出）
        OutlinedButton(onClick = onFinish) { Text("退出练习") }
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
        }) { Text(if (page + 1 < total) "下一题" else "完成本轮") }
    }
}
