package com.daoyou.tiku.data

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** 一次答题记录（含完整题目快照）。 */
@Serializable
data class Attempt(
    val id: Long,
    @SerialName("question_id") val questionId: Long,
    val selected: String,
    val correct: Boolean,
    @SerialName("created_at") val createdAt: String,
    val question: Question,
)

/**
 * 答题记录持久化：答题历史 / 错题本 / 统计 / 组卷出现计数，存应用私有目录
 * files/records.json（kotlinx.serialization）——换设备不丢，清应用数据才丢。
 */
object RecordsStore {

    private const val RECORDS_FILE = "records.json"
    private const val APPEAR_FILE = "appear.json"

    private var attempts: MutableList<Attempt> = mutableListOf()
    private var appear: MutableMap<Long, Int> = mutableMapOf()
    private var recordsFile: File? = null
    private var appearFile: File? = null

    // ---- 性能优化：写盘移出主线程 + 防抖合并（内存即时更新，功能与持久化语义不变） ----
    private val ioScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val writeMutex = Mutex()
    @Volatile private var recordsDirty = false
    @Volatile private var appearDirty = false

    fun init(context: Context) {
        val dir = context.applicationContext.filesDir
        recordsFile = File(dir, RECORDS_FILE)
        appearFile = File(dir, APPEAR_FILE)
        attempts = readList(recordsFile!!, ListSerializer(Attempt.serializer())).toMutableList()
        appear = readMap(appearFile!!).toMutableMap()
    }

    private fun readList(file: File, serializer: kotlinx.serialization.KSerializer<List<Attempt>>): List<Attempt> {
        return try {
            if (!file.exists()) emptyList()
            else quizJson.decodeFromString(serializer, file.readText())
        } catch (e: Exception) {
            emptyList()
        }
    }

    private fun readMap(file: File): Map<Long, Int> {
        return try {
            if (!file.exists()) emptyMap()
            else quizJson
                .decodeFromString(MapSerializer(String.serializer(), Int.serializer()), file.readText())
                .mapKeys { it.key.toLong() }
        } catch (e: Exception) {
            emptyMap()
        }
    }

    private fun fmtTime(): String =
        SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date())

    /** 记录一次答题（错题本数据源）。内存即时更新，写盘防抖后台执行。 */
    @Synchronized
    fun recordAttempt(q: Question, selected: String, correct: Boolean) {
        val nextId = (attempts.maxOfOrNull { it.id } ?: 0L) + 1L
        attempts.add(Attempt(nextId, q.id, selected, correct, fmtTime(), q))
        recordsDirty = true
        scheduleFlush()
    }

    /** 答题历史（最新优先）。 */
    @Synchronized
    fun attempts(limit: Int = 500): List<Attempt> =
        attempts.toList().takeLast(limit).asReversed()

    /** 错题池：答错过去重的题（最近答错优先），错后答对仍在池。 */
    @Synchronized
    fun wrongPool(subject: Int? = null, offset: Int = 0, limit: Int = 50): Pair<Int, List<Question>> {
        val byQuestion = linkedMapOf<Long, Attempt>()
        for (a in attempts) {
            if (!a.correct) {
                val prev = byQuestion[a.questionId]
                if (prev == null || a.id > prev.id) byQuestion[a.questionId] = a
            }
        }
        val graduated = graduatedIds()
        var entries = byQuestion.values
            .filter { it.question.id !in graduated && !it.question.answer.isNullOrEmpty() }
            .sortedByDescending { it.id }
        if (subject != null) entries = entries.filter { it.question.subject == subject }
        return entries.size.toLong().let { total ->
            total.toInt() to entries.drop(offset).take(limit).map { it.question }
        }
    }

    /** 毕业线：错题最后一次答错之后连续答对该次数，即移出错题本。 */
    const val GRADUATE_STREAK = 5

    /** 已「毕业」的错题 id：最后一次答错之后连续答对 >= GRADUATE_STREAK 次（从记录推导，无需额外存储）。 */
    @Synchronized
    private fun graduatedIds(): Set<Long> {
        val streak = mutableMapOf<Long, Int>()
        val wrongEver = mutableSetOf<Long>()
        for (a in attempts) {
            if (!a.correct) {
                streak[a.questionId] = 0 // 再答错则重新计数
                wrongEver.add(a.questionId)
            } else if (streak.containsKey(a.questionId)) {
                streak[a.questionId] = streak[a.questionId]!! + 1
            }
        }
        return wrongEver.filterTo(mutableSetOf()) { (streak[it] ?: 0) >= GRADUATE_STREAK }
    }

    /** 错题 id 集合：有答错记录且未毕业（与 wrongPool 口径一致）。 */
    @Synchronized
    fun wrongIds(): Set<Long> =
        attempts.filter { !it.correct }.map { it.questionId }.toSet() - graduatedIds()

    /** 某题历史被组卷抽中次数（平衡抽取用）。 */
    @Synchronized
    fun appearCount(id: Long): Int = appear[id] ?: 0

    /** 组卷抽取后计数 +1。内存即时更新，写盘防抖后台执行。 */
    @Synchronized
    fun bumpAppear(ids: Collection<Long>) {
        for (id in ids) appear[id] = (appear[id] ?: 0) + 1
        appearDirty = true
        scheduleFlush()
    }

    /** 脏标记时调度一次后台写盘；已有多笔未落盘改动会合并为一次文件写入。 */
    private fun scheduleFlush() {
        ioScope.launch { flushAsync() }
    }

    /** 后台写盘：快照+清脏+落盘在同一 writeMutex 临界区内串行执行，主线程零阻塞。 */
    suspend fun flushAsync() = writeMutex.withLock { doFlush() }

    /** 生命周期兜底（Activity.onStop 调用）：同步串行写盘，防止进程被杀丢最近几秒记录。 */
    fun flushSync() = runBlocking { writeMutex.withLock { doFlush() } }

    /** 实际写盘：快照在类监视器内完成（与写入方同一把锁，消除竞态）；写失败恢复脏标记等待重试。 */
    private fun doFlush() {
        val rec: List<Attempt>?
        val app: Map<Long, Int>?
        synchronized(this) {
            rec = if (recordsDirty) attempts.toList().also { recordsDirty = false } else null
            app = if (appearDirty) appear.toMap().also { appearDirty = false } else null
        }
        try {
            if (rec != null) { recordsFile?.let { f -> f.writeText(quizJson.encodeToString(ListSerializer(Attempt.serializer()), rec)) } }
            if (app != null) { appearFile?.let { f -> f.writeText(quizJson.encodeToString(MapSerializer(String.serializer(), Int.serializer()), app.mapKeys { it.key.toString() })) } }
        } catch (e: Exception) {
            // 写盘失败（存储满等）：恢复脏标记等待下次重试，静默同原实现
            synchronized(this) {
                if (rec != null) recordsDirty = true
                if (app != null) appearDirty = true
            }
        }
    }

    /** 统计：答题总数与正确数。 */
    @Synchronized
    fun attemptStats(): Pair<Int, Int> =
        attempts.size to attempts.count { it.correct }

    /** 清空记录（设置页预留）。 */
    @Synchronized
    fun clear() {
        attempts.clear()
        recordsDirty = true
        flushSync()
    }
}
