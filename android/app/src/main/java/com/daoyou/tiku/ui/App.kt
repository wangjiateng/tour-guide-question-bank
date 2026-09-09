package com.daoyou.tiku.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector

/** 底部导航五个视图，与 web 端 App.vue 的 5 视图对齐。 */
enum class Tab(val label: String, val icon: ImageVector) {
    QUIZ("答题", Icons.Filled.Edit),
    EXAM("笔试", Icons.Filled.Home),
    BROWSE("浏览", Icons.Filled.Search),
    WRONG("错题", Icons.Filled.Warning),
    HISTORY("历史", Icons.Filled.List),
}

@Composable
fun DaoyouApp() {
    var tab by remember { mutableStateOf(Tab.QUIZ) }
    // 科目过滤为全局状态（对齐 web 端 App.vue 层 activeSubject），答题/浏览/错题共用
    var activeSubject by remember { mutableStateOf<Int?>(null) }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        bottomBar = {
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
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            // 笔试模拟有自己的卷型选择，不需要全局科目条
            if (tab != Tab.EXAM) {
                SubjectFilterBar(
                    activeSubject = activeSubject,
                    onChange = { activeSubject = it },
                )
            }
            when (tab) {
                Tab.QUIZ -> QuizScreen(activeSubject)
                Tab.EXAM -> ExamScreen()
                Tab.BROWSE -> BrowseScreen(activeSubject)
                Tab.WRONG -> WrongScreen(activeSubject)
                Tab.HISTORY -> HistoryScreen()
            }
        }
    }
}
