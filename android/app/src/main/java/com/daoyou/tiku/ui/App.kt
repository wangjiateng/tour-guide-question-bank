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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector

/** 底部导航三个视图。 */
enum class Tab(val label: String, val icon: ImageVector) {
    QUIZ("答题", Icons.Filled.Edit),
    EXAM("笔试", Icons.Filled.Home),
    WRONG("错题", Icons.Filled.Warning),
}

@Composable
fun DaoyouApp() {
    var tab by remember { mutableStateOf(Tab.QUIZ) }
    // 科目过滤为全局状态，答题/错题共用
    var activeSubject by remember { mutableStateOf<Int?>(null) }
    // 全屏态：练习/笔试答题中为 true（隐藏底部导航，避免误切页签丢进度）
    var fullScreen by remember { mutableStateOf(false) }

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
                Tab.QUIZ -> QuizScreen(activeSubject = activeSubject, onFullScreen = { fullScreen = it })
                Tab.EXAM -> ExamScreen(onFullScreen = { fullScreen = it })
                Tab.WRONG -> WrongScreen(activeSubject)
            }
        }
    }
}
