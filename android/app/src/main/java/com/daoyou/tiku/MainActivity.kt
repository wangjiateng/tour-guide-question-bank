package com.daoyou.tiku

import android.app.Application
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.daoyou.tiku.data.QuestionRepository
import com.daoyou.tiku.data.RecordsStore
import com.daoyou.tiku.ui.DaoyouApp
import com.daoyou.tiku.ui.DaoyouTheme

class MainApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        QuestionRepository.init(this)
        RecordsStore.init(this)
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
}
