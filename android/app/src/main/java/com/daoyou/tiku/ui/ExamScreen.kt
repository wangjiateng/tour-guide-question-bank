package com.daoyou.tiku.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.PagerState
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.daoyou.tiku.data.ExamProgress
import com.daoyou.tiku.data.Question
import com.daoyou.tiku.data.RecordsStore
import com.daoyou.tiku.data.SessionStore
import com.daoyou.tiku.logic.ExamCheckResult
import com.daoyou.tiku.logic.ExamEngine
import com.daoyou.tiku.logic.ExamPaper
import com.daoyou.tiku.logic.ExamResult
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** 在线笔试模拟：两套卷（科目一+二 / 科目三+四），165 题 / 100 分 / 90 分钟。 */
@Composable
fun ExamScreen(
    resumeRequest: ExamResumeRequest?,
    onResumeConsumed: () -> Unit,
    onFullScreen: (Boolean) -> Unit,
) {
    var paper by remember { mutableStateOf<ExamPaper?>(null) }
    var result by remember { mutableStateOf<ExamResult?>(null) }
    var loading by remember { mutableStateOf(false) }
    // 恢复后的初始作答状态（ExamRunner 的初值来源）
    var restored by remember { mutableStateOf<ExamProgress?>(null) }
    var loadError by remember { mutableStateOf(false) }
    val scope = androidx.compose.runtime.rememberCoroutineScope()

    // 考试进行中 → 全屏（App 隐藏底部导航，禁止切换页签）；交卷出结果后恢复
    LaunchedEffect(paper != null) { onFullScreen(paper != null) }

    // 恢复请求由 App 层全局弹窗下发（冷启动点「继续」）；key 为引用相等的请求对象。
    // 需依题号从内置题库重取题目并重新注入内存 session，否则判分链路（examCheck/examSubmit）返回 null。
    LaunchedEffect(resumeRequest) {
        val p = resumeRequest?.progress ?: return@LaunchedEffect
        if (paper != null || result != null) { onResumeConsumed(); return@LaunchedEffect }
        loading = true
        loadError = false
        val rebuilt = try {
            ExamEngine.restoreSession(p.paperId, p.paperType, p.questionIds)
        } catch (e: Exception) {
            null
        }
        if (rebuilt == null) {
            // 题库更新导致题号缺失：快照已失效，丢弃并提示重新组卷
            SessionStore.clearExam()
            loadError = true
        } else {
            // 续答：只打开写入口，不删磁盘快照（此刻它正是要续的内容）
            SessionStore.resumeExam()
            restored = p
            paper = rebuilt
        }
        loading = false
        onResumeConsumed()
    }

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
                if (loadError) {
                    Text(
                        text = "上次笔试已失效（题库已更新），请重新组卷",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
                if (loading) CircularProgressIndicator()
                listOf(1 to "科目一+科目二 合并卷", 2 to "科目三+科目四 合并卷").forEach { (type, label) ->
                    Button(onClick = {
                        loading = true
                        scope.launch {
                            try {
                                // 新一轮：先清残留快照再打开写入口
                                SessionStore.beginExam()
                                restored = null
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

        else -> ExamRunner(
            paper = paper!!,
            initial = restored,
            onSubmitted = { r -> result = r; paper = null; restored = null },
            // 判分链路失效（session 丢失）时的兜底：丢弃快照回选题页，避免卡在无法判分的试卷上
            onAborted = {
                SessionStore.clearExam()
                paper = null
                restored = null
                loadError = true
            },
        )
    }
}

/**
 * 答题执行器：逐题判定——
 * 单选/判断点选即判；多选勾选后点「确认答案」判定；已判题可改答案重判（改选自动清除旧判定）；
 * 多选未点确认的勾选也会计入交卷判分；题号导航区分 当前/对/错/已答。
 * 翻页用 HorizontalPager：左右滑动无缝切换（无 pageSpacing，页面首尾相接），
 * 上一题/下一题/题号导航均驱动同一个分页器并带过渡动画。
 *
 * 进度持久化：作答/翻页时把「题号序列 + 已选 + 已判定 + 绝对截止时间 + 当前题号」防抖落盘；
 * @param initial 非 null 表示由持久化快照恢复（答案/判定/当前页/截止时间取自快照）。
 * @param onAborted 判分链路不可用（内存 session 丢失，如进程重启后未经 restoreSession）时回调，
 *        由调用方丢弃快照回选题页——否则整卷判分恒为 0 分，结果不可信。
 */
@Composable
private fun ExamRunner(
    paper: ExamPaper,
    initial: ExamProgress? = null,
    onSubmitted: (ExamResult) -> Unit,
    onAborted: () -> Unit = {},
) {
    // 用 SnapshotStateMap 而非 Map 整体替换：`map[qid] = v` 只失效『读过该 key』的组合作用域，
    // 因此点选一题只重组那一页；整体替换会让整张卷子（含 Pager 各页）全部重组。
    val answers = remember { mutableStateMapOf<Long, String>().apply { putAll(initial?.answers ?: emptyMap()) } }
    val verdicts = remember { mutableStateMapOf<Long, Boolean>().apply { putAll(initial?.verdicts ?: emptyMap()) } }
    // 判定明细可由已选题号经 examCheck 重算，故不持久化；恢复时同步重建，避免首帧缺解析
    val checkedMap = remember {
        mutableStateMapOf<Long, ExamCheckResult>().apply {
            initial?.let { p ->
                for (qid in p.verdicts.keys) {
                    val a = p.answers[qid] ?: continue
                    ExamEngine.examCheck(paper.paperId, qid, a)?.let { put(qid, it) }
                }
            }
        }
    }
    var showNav by remember { mutableStateOf(false) }
    var finished by remember { mutableStateOf(false) }
    // 墙钟截止时间：恢复时沿用快照的绝对截止点，否则由当前时间 + 卷面时长推得
    val deadline = remember {
        initial?.deadlineEpochMs ?: (System.currentTimeMillis() + paper.minutes * 60_000L)
    }
    // 题号序列在会话内恒定，按 paperId（O(1) 比较）缓存一次供落盘复用；
    // 不用 paper 本身做 key——那是 data class，会在每次重组时逐题比较全部字段
    val questionIds = remember(paper.paperId) { paper.questions.map { it.id } }
    val pagerState = rememberPagerState(
        initialPage = (initial?.currentPage ?: 0).coerceIn(0, (paper.questions.size - 1).coerceAtLeast(0)),
        pageCount = { paper.questions.size },
    )
    val scope = androidx.compose.runtime.rememberCoroutineScope()

    /** 把当前进度写盘（SessionStore 内防抖合并）。 */
    fun persist(page: Int) {
        SessionStore.saveExam(
            ExamProgress(
                paperId = paper.paperId,
                paperType = paper.paperType,
                questionIds = questionIds,
                answers = answers.toMap(),
                verdicts = verdicts.toMap(),
                deadlineEpochMs = deadline,
                currentPage = page,
            ),
        )
    }

    // 翻页即落盘当前题号
    LaunchedEffect(pagerState) {
        snapshotFlow { pagerState.currentPage }.collect { persist(it) }
    }

    // 判定指定题（answer 返回原始存储答案：判断题「正确/错误」）
    fun judge(qid: Long) {
        val chosen = answers[qid] ?: return
        val r = ExamEngine.examCheck(paper.paperId, qid, chosen) ?: return
        verdicts[qid] = r.correct
        checkedMap[qid] = r
        persist(pagerState.currentPage)
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

    // 改答案：清除该题判定（多选回到可勾选态；单选/判断改选后立即重判）
    fun reopen(qid: Long) {
        verdicts.remove(qid)
        checkedMap.remove(qid)
    }

    // 交卷：answers 里所有选题（含未点确认的多选）都会计入判分
    fun submitNow() {
        finished = true
        val r = ExamEngine.examSubmit(paper.paperId, answers.map { it.key to it.value })
        if (r != null) {
            // 正常交卷：会话结束，清掉快照
            SessionStore.clearExam()
            onSubmitted(r)
        } else {
            // 判分链路不可用（session 丢失）：不产出错误成绩，交由上层丢弃本次考试
            finished = false
            onAborted()
        }
    }

    // 到期自动交卷：只依赖稳定的 deadline。
    // 不使用 `LaunchedEffect(remaining)`——把每秒变化的剩余秒数作为 key 会每秒失效整棵树
    // （含 HorizontalPager 的 content lambda），导致滑动中出现周期性卡顿。
    LaunchedEffect(deadline) {
        val waitMs = deadline - System.currentTimeMillis()
        if (waitMs > 0) delay(waitMs)
        if (!finished) submitNow()
    }

    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        ExamHeader(pagerState, paper, answers, verdicts, deadline)
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(onClick = { showNav = !showNav }) {
                Text(if (showNav) "收起题号" else "题号导航")
            }
            Button(enabled = !finished, onClick = { submitNow() }) { Text("结束考试") }
        }
        if (showNav) {
            LazyVerticalGrid(
                columns = GridCells.Fixed(8),
                // 有界高度必需：垂直懒加载组件嵌在普通 Column 内不会自动限高，故用 heightIn 限高
                modifier = Modifier.fillMaxWidth().heightIn(max = 320.dp).padding(vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(paper.questions.size) { i ->
                    val q = paper.questions[i]
                    val v = verdicts[q.id]
                    val isCurrent = pagerState.currentPage == i
                    val bg = when {
                        isCurrent -> MaterialTheme.colorScheme.primary
                        v == true -> JudgeColors.correctBg
                        v == false -> JudgeColors.wrongBg
                        answers.containsKey(q.id) -> MaterialTheme.colorScheme.primaryContainer
                        else -> MaterialTheme.colorScheme.surfaceVariant
                    }
                    Box(
                        modifier = Modifier
                            .size(36.dp)
                            .background(bg, CircleShape)
                            .clickable { scope.launch { pagerState.animateScrollToPage(i) } },
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = "${i + 1}",
                            style = MaterialTheme.typography.labelSmall,
                            color = if (isCurrent) MaterialTheme.colorScheme.onPrimary
                            else MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
        HorizontalPager(
            state = pagerState,
            beyondViewportPageCount = 1,
            modifier = Modifier.fillMaxWidth().weight(1f),
        ) { p ->
            ExamQuestionPage(
                paper = paper,
                index = p,
                answers = answers,
                verdicts = verdicts,
                checkedMap = checkedMap,
                finished = finished,
                onAnswered = { qid, value ->
                    if (value == null) answers.remove(qid) else answers[qid] = value
                    persist(pagerState.currentPage)
                },
                onJudge = { judge(it) },
                onReopen = { reopen(it) },
            )
        }
        ExamBottomBar(
            pagerState = pagerState,
            total = paper.total,
            scope = scope,
            onSubmit = { submitNow() },
        )
    }
}

/**
 * 顶部统计 + 倒计时。
 *
 * 剩余秒数在本组件内部维护（父作用域不读它）→ 每秒重组范围仅限本组件；
 * 否则父作用域被逐秒失效会连带重建 Pager 的 content lambda。
 * 墙钟计算而非逐秒自减，休眠/后台回归后误差可自愈。
 */
@Composable
private fun ExamHeader(
    pagerState: PagerState,
    paper: ExamPaper,
    answers: Map<Long, String>,
    verdicts: Map<Long, Boolean>,
    deadline: Long,
) {
    val page by remember(pagerState) { derivedStateOf { pagerState.currentPage } }
    var remaining by remember {
        mutableIntStateOf(((deadline - System.currentTimeMillis()) / 1000).coerceAtLeast(0).toInt())
    }
    LaunchedEffect(deadline) {
        while (true) {
            remaining = (((deadline - System.currentTimeMillis()) / 1000)).coerceAtLeast(0).toInt()
            if (remaining <= 0) break
            delay(1000)
        }
    }
    val mm = (remaining / 60).toString().padStart(2, '0')
    val ss = (remaining % 60).toString().padStart(2, '0')
    // 逐条读取（而非 remember(verdicts)）——SnapshotStateMap 实例不变，用实例做 key 永远不会刷新；
    // 直接 count 会按 key 追踪读取，仅在判定结果变化时重算（价格便宜：≤165 项）
    val rightCount = verdicts.count { it.value }
    val wrongCount = verdicts.size - rightCount
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "第 ${page + 1}/${paper.total} 题 · 已答 ${answers.size} · 对 $rightCount 错 $wrongCount",
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
        // 作答时视觉反馈当前进度（细进度条，不占高）
        LinearProgressIndicator(
            progress = { (page + 1f) / paper.total },
            modifier = Modifier.fillMaxWidth().height(4.dp),
        )
    }
}

/** 单个笔试题页：页内纵向滚动（题干 + 选项 + 解析都在页内），重组粒度=单页。 */
@Composable
private fun ExamQuestionPage(
    paper: ExamPaper,
    index: Int,
    answers: Map<Long, String>,
    verdicts: Map<Long, Boolean>,
    checkedMap: Map<Long, ExamCheckResult>,
    finished: Boolean,
    onAnswered: (Long, String?) -> Unit,
    onJudge: (Long) -> Unit,
    onReopen: (Long) -> Unit,
) {
    val cur = paper.questions[index]
    val chosenRaw = answers[cur.id]
    val verdict = verdicts[cur.id]
    val checkedResult = checkedMap[cur.id]
    // 高亮用归一化字母（判断题「正确/错误」→ A/B），显示用原始存储答案；按判定结果缓存
    val normRef = remember(checkedResult) {
        checkedResult?.answer?.uppercase()?.let { raw ->
            if (cur.qType == 3) (if (raw.contains("正确")) "A" else if (raw.contains("错误")) "B" else raw)
            else raw.replace(",", "")
        } ?: ""
    }
    // 已选字母集合（多选为未判定的临时勾选串，单选/判断为已提交答案）；按答案串缓存，
    // 否则每次重组（含每秒倒计时、滑动中的相邻页）都会重建 List 与 Set
    val selected = remember(chosenRaw) {
        chosenRaw?.map { it.toString() }?.toSet() ?: emptySet()
    }
    // 适配器 Question：ExamQuestion 与 Question 字段名不同，需转换以复用 QuestionCard。
    // 按题号缓存（题目在会话内不可变），否则每帧新建一个对象
    val cardQuestion = remember(cur.id) {
        Question(
            id = cur.id, questionText = cur.questionText, optionA = cur.options.getOrNull(0),
            optionB = cur.options.getOrNull(1), optionC = cur.options.getOrNull(2),
            optionD = cur.options.getOrNull(3), optionE = cur.options.getOrNull(4),
            qType = cur.qType, subject = cur.subject, years = cur.years,
        )
    }

    Column(
        // 铺满页面底色：翻页时相邻页无缝隙、无露底黑框
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        QuestionCard(
            q = cardQuestion,
            selected = selected,
            revealed = verdict != null,
            correctRef = normRef,
            explanation = checkedResult?.explanation,
            answerDisplay = checkedResult?.answer,
            allowReanswer = !finished,
            onSelect = { letter ->
                if (finished) return@QuestionCard
                val qid = cur.id
                if (cur.qType == 2) {
                    // 多选：勾选写入 answers（未确认），已判定则先清除判定再改
                    if (qid in verdicts) onReopen(qid)
                    val next = if (letter in selected) selected - letter else selected + letter
                    onAnswered(qid, if (next.isEmpty()) null else next.sorted().joinToString(""))
                    // 选好后点「确认答案」判定
                } else {
                    // 单选/判断点选即判；改选自动覆盖旧判定
                    onAnswered(qid, letter)
                    onJudge(qid)
                }
            },
        )
        // 多选确认按钮（未判定且有勾选时）
        if (cur.qType == 2 && verdict == null && !finished) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    "多选题：勾选全部选项后点击「确认答案」判定。",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.outline,
                )
                Button(
                    enabled = selected.isNotEmpty(),
                    onClick = { onJudge(cur.id) },
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
        Spacer(Modifier.height(4.dp))
    }
}

/** 笔试底部翻页栏：内部经 derivedStateOf 读取当前页。 */
@Composable
private fun ExamBottomBar(
    pagerState: PagerState,
    total: Int,
    scope: kotlinx.coroutines.CoroutineScope,
    onSubmit: () -> Unit,
) {
    val page by remember(pagerState) { derivedStateOf { pagerState.currentPage } }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        OutlinedButton(
            enabled = page > 0,
            onClick = { scope.launch { pagerState.animateScrollToPage(page - 1) } },
        ) { Text("上一题") }
        if (page + 1 < total) {
            Button(onClick = { scope.launch { pagerState.animateScrollToPage(page + 1) } }) { Text("下一题") }
        } else {
            Button(onClick = onSubmit) { Text("交卷") }
        }
        Spacer(Modifier.weight(1f))
    }
}
