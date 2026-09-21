package com.daoyou.tiku.data

import android.content.Context
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * 题库仓库：从 APK 内置 assets/data 目录 JSON 加载题库（16MB 全量离线）。
 * manifest 先行（版本源），科目文件懒加载 + 并发去重。
 * 数据文件由构建任务从仓库根 data/（唯一事实源）复制进 assets，不做网络请求。
 */
object QuestionRepository {

    private var context: Context? = null
    private var manifestCache: Manifest? = null
    private var sourcesCache: List<Source>? = null
    private val subjectCache = mutableMapOf<Int, List<Question>>()
    private val mutex = Mutex()

    fun init(context: Context) {
        this.context = context.applicationContext
    }

    private val assets get() = context!!.assets

    /** 加载 manifest（统计头部 + 题库版本号）。 */
    suspend fun loadManifest(): Manifest {
        manifestCache?.let { return it }
        mutex.withLock {
            manifestCache?.let { return it }
            val text = assets.open("data/manifest.json").bufferedReader().use { it.readText() }
            val m = quizJson.decodeFromString(Manifest.serializer(), text)
            manifestCache = m
            return m
        }
    }

    /** 加载来源元数据（来源筛选用）。 */
    suspend fun loadSources(): List<Source> {
        sourcesCache?.let { return it }
        loadManifest()
        mutex.withLock {
            sourcesCache?.let { return it }
            val text = assets.open("data/sources.json").bufferedReader().use { it.readText() }
            val s = quizJson.decodeFromString(SourcesFile.serializer(), text)
            sourcesCache = s.sources
            return s.sources
        }
    }

    private fun subjectKey(subject: Int?): Int = subject ?: 0

    /** 加载某科目题目文件（懒加载 + 并发去重）。subject null 表示未分类（0）与全部科目兜底。 */
    suspend fun loadSubjectQuestions(subject: Int?): List<Question> {
        val key = subjectKey(subject)
        subjectCache[key]?.let { return it }
        loadManifest() // 先确保版本源就绪
        mutex.withLock {
            subjectCache[key]?.let { return it }
            val text = assets.open("data/questions_$key.json").bufferedReader().use { it.readText() }
            val f = quizJson.decodeFromString(QuestionsFile.serializer(), text)
            // years 归一化已在反序列化时由 FlexibleYearsSerializer 完成
            subjectCache[key] = f.questions
            return f.questions
        }
    }

    /** 加载多个科目并拼接（"全部科目"时传 listOf(null, 1, 2, 3, 4)）。 */
    suspend fun loadSubjects(subjects: List<Int?>): List<Question> =
        subjects.flatMap { loadSubjectQuestions(it) }

    /** 全部科目。 */
    suspend fun loadAll(): List<Question> = loadSubjects(listOf(null, 1, 2, 3, 4))
}
