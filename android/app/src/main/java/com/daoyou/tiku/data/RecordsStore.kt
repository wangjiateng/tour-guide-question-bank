package com.daoyou.tiku.data

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
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

    /** 防抖合并窗口：连续作答/组卷的多次改动合并为一次文件写入。 */
    private const val FLUSH_DEBOUNCE_MS = 400L

    private var attempts: MutableList<Attempt> = mutableListOf()

    /** 递增 id 游标：避免每次记录都 `maxOfOrNull` 全表扫描。 */
    private var nextAttemptId: Long = 1L

    private var appear: MutableMap<Long, Int> = mutableMapOf()
    private var recordsFile: File? = null
    private var appearFile: File? = null

    /**
     * 加载完成标记。`false` 期间：
     * - [recordAttempt] 的新记录先进 [pendingAttempts]，避免被加载结果覆盖；
     * - [doFlush] 不写盘，否则会用「只含 pending 的残缺列表」覆盖掉磁盘上的完整历史。
     */
    private var loaded = false

    /** 加载期间到达的新记录（正常为空白，仅冷启动瞬间可能命中）。 */
    private var pendingAttempts: MutableList<Attempt> = mutableListOf()

    /** 错题 id 缓存：`wrongIds()` 每次调用要全表两遍，而它在每次答对时都会命中。 */
    private var wrongIdsCache: Set<Long>? = null

    /** 时间格式化复用（SimpleDateFormat 非线程安全，故用 ThreadLocal）。 */
    private val timeFormat = ThreadLocal.withInitial { SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US) }

    // ---- 性能优化：写盘移出主线程 + 防抖合并（内存即时更新，功能与持久化语义不变） ----
    private val ioScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val writeMutex = Mutex()
    @Volatile private var recordsDirty = false
    @Volatile private var appearDirty = false
    @Volatile private var flushScheduled = false

    /**
     * 初始化：只建立文件句柄，**异步**读取历史。
     *
     * 记录里内嵌完整题目快照，`records.json` 随使用量增长（数千条即 MB 级），
     * 若在 `Application.onCreate` 主线程同步解码会拖慢冷启动首帧，且随使用量线性恶化。
     * 所有读取 API 在加载完成后返回完整数据；加载期间的写入进 [pendingAttempts] 于合并时补上。
     */
    fun init(context: Context) {
        val dir = context.applicationContext.filesDir
        recordsFile = File(dir, RECORDS_FILE)
        appearFile = File(dir, APPEAR_FILE)
        ioScope.launch {
            // 文件 IO 在锁外完成，避免加载期间阻塞作答（点击回调）进入监视器
            val loadedAttempts = readList(recordsFile!!, ListSerializer(Attempt.serializer()))
            val loadedAppear = readMap(appearFile!!)
            val needFlush = synchronized(this@RecordsStore) {
                // loaded 已为 true 说明期间被 clear() 接管，直接放弃本次加载
                if (loaded) return@synchronized false
                val maxId = loadedAttempts.maxOfOrNull { it.id } ?: 0L
                // pending 记录的 id 是在加载前分配的（可能与文件里的 id 撞车），合并时重新编号
                val renumbered = pendingAttempts.mapIndexed { i, p -> p.copy(id = maxId + 1L + i) }
                attempts = (loadedAttempts + renumbered).toMutableList()
                pendingAttempts = mutableListOf()
                appear = loadedAppear.toMutableMap()
                nextAttemptId = (attempts.maxOfOrNull { it.id } ?: 0L) + 1L
                wrongIdsCache = null
                loaded = true
                // 加载期间若已有变更（脏标记已置），其防抖调度可能已空跑过（那时 loaded 还是 false），需补一次
                recordsDirty || appearDirty
            }
            if (needFlush) scheduleFlush()
        }
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
        timeFormat.get()!!.format(Date())

    /**
     * 记录一次答题（错题本数据源）。内存即时更新，写盘防抖后台执行。
     *
     * 注意：初始化（[init] 的异步读取）完成前写入的记录进入 `pendingAttempts`，
     * 此刻 [attempts] / [wrongPool] / [wrongIds] 等读取 API **看不到它**（冷启动瞬间的窗口，
     * 用户尚无机会作答，实际不会发生）。合并时会重新编号后并入，不丢数据。
     */
    @Synchronized
    fun recordAttempt(q: Question, selected: String, correct: Boolean) {
        val a = Attempt(nextAttemptId++, q.id, selected, correct, fmtTime(), q)
        // 加载未完成时先入缓冲，待合并时重新编号后进入 attempts
        if (loaded) attempts.add(a) else pendingAttempts.add(a)
        recordsDirty = true
        wrongIdsCache = null // 新记录可能改变错题集/毕业判定
        scheduleFlush()
    }

    /** 答题历史（最新优先）。 */
    @Synchronized
    fun attempts(limit: Int = 500): List<Attempt> =
        attempts.takeLast(limit).asReversed()

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

    /**
     * 错题 id 集合：有答错记录且未毕业（与 wrongPool 口径一致）。
     * 结果按记录版本缓存——每次答对都会命中此函数，而它是两遍全表扫描。
     */
    @Synchronized
    fun wrongIds(): Set<Long> {
        wrongIdsCache?.let { return it }
        val ids = attempts.filter { !it.correct }.mapTo(mutableSetOf()) { it.questionId } - graduatedIds()
        wrongIdsCache = ids
        return ids
    }

    /** 某题历史被组卷抽中次数（平衡抽取用）。 */
    @Synchronized
    fun appearCount(id: Long): Int = appear[id] ?: 0

    /**
     * 出现次数快照（组卷平衡抽取用）。
     * 组卷需对整池逐题读取次数，逐题进 [appearCount] 会造成上万次锁进出并与主线程竞争，
     * 故一次性复制成不可变 Map 交由调用方在锁外遍历。
     */
    @Synchronized
    fun appearCounts(): Map<Long, Int> = appear.toMap()

    /** 组卷抽取后计数 +1。内存即时更新，写盘防抖后台执行。 */
    @Synchronized
    fun bumpAppear(ids: Collection<Long>) {
        for (id in ids) appear[id] = (appear[id] ?: 0) + 1
        appearDirty = true
        scheduleFlush()
    }

    /** 脏标记时调度一次后台写盘；已有多笔未落盘改动会合并为一次文件写入。 */
    private fun scheduleFlush() {
        if (flushScheduled) return
        flushScheduled = true
        ioScope.launch {
            delay(FLUSH_DEBOUNCE_MS)
            flushScheduled = false
            flushAsync()
        }
    }

    /** 后台写盘：快照+清脏+落盘在同一 writeMutex 临界区内串行执行，主线程零阻塞。 */
    suspend fun flushAsync() = writeMutex.withLock { doFlush() }

    /**
     * 请求异步写盘（不阻塞调用方）。Activity.onStop 用它做兜底——
     * 活动期已有 400ms 防抖持续落盘，此处若改同步 `runBlocking` 会阻塞主线程
     * 并可能排在一次在途的大写入之后，代价远大于「最多丢最近 <0.5s 改动」。
     */
    fun requestFlush() {
        ioScope.launch { flushAsync() }
    }

    /** 生命周期兜底（同步串行写盘）；仅用于确实需要「返回前已落盘」的场景（如清空记录）。 */
    fun flushSync() = runBlocking { writeMutex.withLock { doFlush() } }

    /** 实际写盘：快照在类监视器内完成（与写入方同一把锁，消除竞态）；写失败恢复脏标记等待重试。 */
    private fun doFlush() {
        val rec: List<Attempt>?
        val app: Map<Long, Int>?
        synchronized(this) {
            // loaded 前不写：此时 attempts 还不完整，落盘会用残缺列表覆盖磁盘上的完整历史
            rec = if (recordsDirty && loaded) attempts.toList().also { recordsDirty = false } else null
            app = if (appearDirty && loaded) appear.toMap().also { appearDirty = false } else null
        }
        try {
            // 原子写（临时文件 + 重命名）：避免中途失败留下截断 JSON 导致历史被静默清空
            if (rec != null) { recordsFile?.writeTextAtomic(quizJson.encodeToString(ListSerializer(Attempt.serializer()), rec)) }
            if (app != null) { appearFile?.writeTextAtomic(quizJson.encodeToString(MapSerializer(String.serializer(), Int.serializer()), app.mapKeys { it.key.toString() })) }
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
        pendingAttempts.clear()
        nextAttemptId = 1L
        wrongIdsCache = null
        recordsDirty = true
        // 置 loaded 会让进行中的加载在合并前放弃，避免旧记录被合并回来
        loaded = true
        flushSync()
    }
}
