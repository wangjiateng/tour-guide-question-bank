package com.daoyou.tiku

import android.app.Application
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import com.daoyou.tiku.data.QuestionRepository
import com.daoyou.tiku.data.RecordsStore
import com.daoyou.tiku.ui.DaoyouApp

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
            MaterialTheme {
                DaoyouApp()
            }
        }
    }
}
