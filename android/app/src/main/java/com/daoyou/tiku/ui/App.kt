package com.daoyou.tiku.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import com.daoyou.tiku.data.ExamProgress
import com.daoyou.tiku.data.QuizProgress
import com.daoyou.tiku.data.SessionStore

/** 底部导航三个视图。 */
enum class Tab(val label: String, val icon: ImageVector) {
    QUIZ("答题", Icons.Filled.Edit),
    EXAM("笔试", Icons.Filled.Home),
    WRONG("错题", Icons.Filled.Warning),
}

/**
 * 恢复请求载体：**普通 class**（非 data class）→ `equals` 为引用比较。
 * 用作子页面 `LaunchedEffect` 的 key 时，避免 `questionIds`（最大 8000+ 元素）逐元素比较（组合性能红线）。
 */
class QuizResumeRequest(val progress: QuizProgress)
class ExamResumeRequest(val progress: ExamProgress)

/** 冷启动探测到的待提示会话。 */
private sealed interface ResumePrompt {
    data class Quiz(val progress: QuizProgress) : ResumePrompt
    data class Exam(val progress: ExamProgress) : ResumePrompt
}

@Composable
fun DaoyouApp() {
    var tab by remember { mutableStateOf(Tab.QUIZ) }
    // 科目过滤为全局状态，答题/错题共用
    var activeSubject by remember { mutableStateOf<Int?>(null) }
    // 全屏态：练习/笔试答题中为 true（隐藏底部导航，避免误切页签丢进度）
    var fullScreen by remember { mutableStateOf(false) }

    // 冷启动探测到的未完成会话（笔试优先，依次提示）；「继续」时下发给对应页签执行恢复
    var resumeQueue by remember { mutableStateOf<List<ResumePrompt>>(emptyList()) }
    var quizResume by remember { mutableStateOf<QuizResumeRequest?>(null) }
    var examResume by remember { mutableStateOf<ExamResumeRequest?>(null) }

    // 全局续答探测：进程被杀重启后在此弹出，不再依赖进入对应页签。
    // 校验口径与原页内逻辑一致：空题号序列丢弃；一题未答丢弃；笔试过截止时间丢弃。
    // 笔试优先（有时限更紧急）；两者共存时依次提示。
    LaunchedEffect(Unit) {
        val prompts = mutableListOf<ResumePrompt>()
        SessionStore.loadExam()?.let { e ->
            when {
                e.questionIds.isEmpty() -> {}
                e.answeredCount == 0 || e.deadlineEpochMs <= System.currentTimeMillis() -> SessionStore.clearExam()
                else -> prompts += ResumePrompt.Exam(e)
            }
        }
        SessionStore.loadQuiz()?.let { p ->
            when {
                p.questionIds.isEmpty() -> {}
                p.answeredCount == 0 -> SessionStore.clearQuiz()
                else -> prompts += ResumePrompt.Quiz(p)
            }
        }
        resumeQueue = prompts
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        bottomBar = {
            // 全屏作答时整条导航栏隐藏（带收拢动画）；练习页底部栏常驻「退出练习」可随时退出
            AnimatedVisibility(
                visible = !fullScreen,
                enter = fadeIn() + expandVertically(),
                exit = fadeOut() + shrinkVertically(),
            ) {
                NavigationBar {
                    Tab.entries.forEach { t ->
                        NavigationBarItem(
                            selected = tab == t,
                            onClick = { tab = t },
                            icon = { Icon(t.icon, contentDescription = t.label) },
                            label = { Text(t.label) },
                        )
                    }
                }
            }
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            // 错题页有全局科目条；答题/笔试全屏作答时不显示
            if (tab == Tab.WRONG && !fullScreen) {
                SubjectFilterBar(
                    activeSubject = activeSubject,
                    onChange = { activeSubject = it },
                )
            }
            when (tab) {
                Tab.QUIZ -> QuizScreen(
                    activeSubject = activeSubject,
                    resumeRequest = quizResume,
                    onResumeConsumed = { quizResume = null },
                    onFullScreen = { fullScreen = it },
                )
                Tab.EXAM -> ExamScreen(
                    resumeRequest = examResume,
                    onResumeConsumed = { examResume = null },
                    onFullScreen = { fullScreen = it },
                )
                Tab.WRONG -> WrongScreen(activeSubject)
            }
        }
    }

    // 全局续答弹窗：强制「继续 / 放弃」，点外部/返回键不可关闭。
    // 「继续」切到对应页签并下发恢复请求（不删快照，由页面内 resumeQuiz/resumeExam 打开写入口）。
    resumeQueue.firstOrNull()?.let { prompt ->
        ResumeDialog(
            title = when (prompt) {
                is ResumePrompt.Quiz -> "未完成的练习"
                is ResumePrompt.Exam -> "未完成的笔试"
            },
            detail = when (prompt) {
                is ResumePrompt.Quiz -> {
                    val p = prompt.progress
                    "${Subjects.name(p.subject)} · 第 ${p.currentPage + 1}/${p.questionIds.size} 题 · 已答 ${p.answeredCount} 题 · 上次保存 ${p.savedAt}"
                }
                is ResumePrompt.Exam -> {
                    val p = prompt.progress
                    val left = ((p.deadlineEpochMs - System.currentTimeMillis()) / 1000).coerceAtLeast(0).toInt()
                    "第 ${p.currentPage + 1}/${p.questionIds.size} 题 · 已答 ${p.answeredCount} 题 · 剩余 ${left / 60}分${left % 60}秒 · 上次保存 ${p.savedAt}"
                }
            },
            onResume = {
                when (prompt) {
                    is ResumePrompt.Quiz -> {
                        tab = Tab.QUIZ
                        quizResume = QuizResumeRequest(prompt.progress)
                    }
                    is ResumePrompt.Exam -> {
                        tab = Tab.EXAM
                        examResume = ExamResumeRequest(prompt.progress)
                    }
                }
                resumeQueue = resumeQueue.drop(1)
            },
            onDiscard = {
                when (prompt) {
                    is ResumePrompt.Quiz -> SessionStore.clearQuiz()
                    is ResumePrompt.Exam -> SessionStore.clearExam()
                }
                resumeQueue = resumeQueue.drop(1)
            },
        )
    }
}
