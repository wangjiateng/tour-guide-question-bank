package com.daoyou.tiku

import android.app.Application
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.daoyou.tiku.data.QuestionRepository
import com.daoyou.tiku.data.RecordsStore
import com.daoyou.tiku.data.SessionStore
import com.daoyou.tiku.ui.DaoyouApp
import com.daoyou.tiku.ui.DaoyouTheme

class MainApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        QuestionRepository.init(this)
        RecordsStore.init(this)
        SessionStore.init(this)
    }
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            // 跟随系统深浅色切换主题
            DaoyouTheme {
                DaoyouApp()
            }
        }
    }

    override fun onStop() {
        super.onStop()
        // 生命周期兜底：请求后台写盘（不阻塞主线程）。
        // 活动期已有 400ms 防抖持续落盘，故这里用异步即可——进程被杀最多丢最近 <0.5s 改动，
        // 而同步 runBlocking 会在主线程排队等待（可能排在一次在途的大写入之后），代价更大。
        RecordsStore.requestFlush()
        SessionStore.requestFlush()
    }
}
