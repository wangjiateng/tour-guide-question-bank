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
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 进行中的在线答题会话快照。
 *
 * 存**题号序列 + 逐题作答状态**而不是完整题目对象：答题页不限题量（出全池，最大科目 8200+ 题），
 * 完整快照约 4-6MB，而作答变更频繁（每次点选/翻页），落盘体积不可接受；
 * 题号序列只有 ~60KB。恢复时按 id 从 APK 内置题库（`QuestionRepository`）重取题目——
 * 题库随 APK 分发、版本内 id 稳定，顺序与选择因此完全可还原。
 *
 * 之所以必须存"序列"而非种子：`QuizBuilder.randomQuiz` 用 `Random.Default` 且会 `bumpAppear`
 * 改状态，组卷结果不可复现，无法靠种子重放。
 */
@Serializable
data class QuizProgress(
    /** 组卷所用科目（1-4；答题页科目药丸恒有值，故非空）。 */
    val subject: Int = 1,
    /** 题号序列（顺序即卷面顺序）。 */
    @SerialName("question_ids") val questionIds: List<Long> = emptyList(),
    /** 逐题已提交答案（下标与 questionIds 对齐，null = 未作答）。 */
    val answers: List<String?> = emptyList(),
    /** 逐题判定结果（null = 未揭示）。 */
    val results: List<Boolean?> = emptyList(),
    /** 已采集但未确认的多选勾选：题下标 -> 字母集合。 */
    val selections: Map<Int, Set<String>> = emptyMap(),
    @SerialName("current_page") val currentPage: Int = 0,
    @SerialName("saved_at") val savedAt: String = "",
) {
    /** 已作答题数（用于恢复卡文案）。 */
    val answeredCount: Int get() = answers.count { !it.isNullOrEmpty() }
}

/**
 * 进行中的在线笔试会话快照。
 *
 * 同样只存题号序列：恢复时 `ExamEngine.restorePaper` 依 id 重取完整题目（含答案/解析），
 * 重建脱敏试卷并**重新注入内存 session**——`ExamEngine.sessions` 是进程内 Map，重启后为空，
 * 不注入则单题判分与交卷都会返回 null。
 *
 * 判定明细（`ExamCheckResult`）不落盘：它可由 `answers` + `verdicts` 经 `examCheck` 重算，
 * 避免冗余与不一致。
 *
 * 倒计时存**绝对截止时间**（墙钟毫秒）：进程被杀期间照常计时，恢复时用
 * `deadline - now` 重算剩余秒，贴近真实考试。
 */
@Serializable
data class ExamProgress(
    @SerialName("paper_id") val paperId: String,
    @SerialName("paper_type") val paperType: Int,
    @SerialName("question_ids") val questionIds: List<Long> = emptyList(),
    /** 已选答案：题号 -> 答案串（含未点「确认答案」的多选勾选）。 */
    val answers: Map<Long, String> = emptyMap(),
    /** 已判定题号 -> 对错（未判定的题不在其中）。 */
    val verdicts: Map<Long, Boolean> = emptyMap(),
    @SerialName("deadline_epoch_ms") val deadlineEpochMs: Long = 0L,
    @SerialName("current_page") val currentPage: Int = 0,
    @SerialName("saved_at") val savedAt: String = "",
) {
    /** 已作答题数（用于恢复卡文案）。 */
    val answeredCount: Int get() = answers.size
}

/**
 * 进行中会话持久化：答题 / 笔试各一个 JSON 快照，存应用私有目录
 * files/session_quiz.json、files/session_exam.json（kotlinx.serialization）。
 * 快照只含题号序列与作答状态，体积与题库规模无关。
 *
 * 与 `RecordsStore` 同构：内存即时更新 + 脏标记 + 防抖后台写盘（400ms）+ `requestFlush()` 异步兜底。
 * 写入用「临时文件 + 重命名」原子替换，避免中途失败留下截断 JSON 被静默丢弃；
 * 差异是加了「删除」语义（会话完成/放弃即删文件，见 [clearQuiz] / [clearExam]）与
 * 「无会话 = 文件不存在或解析失败」的判定（避免 nullable 字段在 JSON 上的歧义）。
 *
 * 三个状态位各司其职：[x]Closed 控制写入口（防止结束后在途 save 把快照写回来）、
 * [x]Removed 触发删文件、[x]Dropped 让 [loadQuiz] / [loadExam] 在删除落盘前就视为「无会话」
 * （用户点放弃后立刻切页签重进的窄窗口）。
 */
object SessionStore {

    private const val QUIZ_FILE = "session_quiz.json"
    private const val EXAM_FILE = "session_exam.json"

    /** 防抖合并窗口：连续翻页/作答合并为一次写盘（快照为纯题号+作答状态，仍需避频繁 IO）。 */
    private const val FLUSH_DEBOUNCE_MS = 400L

    private var quizFile: File? = null
    private var examFile: File? = null

    // ---- 待落盘状态（类监视器保护） ----
    private var quizPending: QuizProgress? = null
    private var examPending: ExamProgress? = null
    private var quizDirty = false
    private var examDirty = false
    /** 待删除标记：会话完成/放弃后删文件，与写盘同一临界区串行。 */
    private var quizRemoved = false
    private var examRemoved = false
    /**
     * 会话已关闭标记（初始关闭=无会话）。防抖写盘有 400ms 窗口，若「结束会话」后
     * 仍有一个在途的 save 到达，会把刚删掉的快照写回来（用户下次重启又被弹续答卡）。
     * 故 clear 后置关闭，save 直接丢弃；只有 [beginQuiz]/[beginExam] 或 [resumeQuiz]/[resumeExam] 才重新打开。
     */
    private var quizClosed = true
    private var examClosed = true
    /**
     * 进程内「已丢弃」权威标记：删除是异步的（防抖 400ms），若用户点「放弃」后立刻切页签重进，
     * [loadQuiz]/[loadExam] 会读到尚未删除的旧文件而再次弹卡。故以内存标记为准，
     * 丢弃后直接返回「无会话」；新会话保存时复位。
     */
    @Volatile private var quizDropped = false
    @Volatile private var examDropped = false

    private val ioScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val writeMutex = Mutex()
    @Volatile private var flushScheduled = false

    fun init(context: Context) {
        val dir = context.applicationContext.filesDir
        quizFile = File(dir, QUIZ_FILE)
        examFile = File(dir, EXAM_FILE)
    }

    private fun fmtTime(): String =
        SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date())

    // ---------------- 答题会话 ----------------

    /**
     * 开始**新一轮**答题会话：先清掉上一轮残留快照与在途写盘，再打开写入口。
     * 顺序不能反：clear 会关闭写入口，必须在其后打开才有效。
     */
    fun beginQuiz() {
        clearQuiz()
        startQuiz()
    }

    /**
     * **续答**已有答题会话（用户点「继续」）：只打开写入口，不删快照。
     * 与 [beginQuiz] 的区别是不做删除——此刻磁盘上的快照正是要续的内容，
     * 删了会在「继续后立刻被杀」的小窗口里丢进度。
     */
    fun resumeQuiz() = startQuiz()

    /** 打开答题写入口。 */
    @Synchronized
    private fun startQuiz() {
        quizClosed = false
    }

    /** 读取答题会话快照；无会话/文件损坏返回 null（静默降级，绝不因脏数据崩溃）。 */
    suspend fun loadQuiz(): QuizProgress? = withContext(Dispatchers.IO) {
        if (quizDropped) return@withContext null
        val f = quizFile ?: return@withContext null
        try {
            if (!f.exists()) null else quizJson.decodeFromString(QuizProgress.serializer(), f.readText())
        } catch (e: Exception) {
            null
        }
    }

    /** 保存答题会话（内存置脏 + 防抖写盘）。会话已关闭时忽略。 */
    fun saveQuiz(p: QuizProgress) {
        synchronized(this) {
            if (quizClosed) return
            quizPending = p.copy(savedAt = fmtTime())
            quizDirty = true
            quizRemoved = false
            quizDropped = false
        }
        scheduleFlush()
    }

    /** 结束答题会话（退出练习 / 完成本轮 / 用户放弃）：删除快照并关闭写入口。 */
    @Synchronized
    fun clearQuiz() {
        quizPending = null
        quizDirty = false
        quizRemoved = true
        quizClosed = true
        quizDropped = true
        scheduleFlush()
    }

    // ---------------- 笔试会话 ----------------

    /**
     * 开始**新一轮**笔试会话：先清掉上一轮残留快照与在途写盘，再打开写入口。
     * 顺序不能反：clear 会关闭写入口，必须在其后打开才有效。
     */
    fun beginExam() {
        clearExam()
        startExam()
    }

    /**
     * **续答**已有笔试会话（用户点「继续」）：只打开写入口，不删快照。
     * 与 [beginExam] 的区别是不做删除——此刻磁盘上的快照正是要续的内容。
     */
    fun resumeExam() = startExam()

    /** 打开笔试写入口。 */
    @Synchronized
    private fun startExam() {
        examClosed = false
    }

    /** 读取笔试会话快照；无会话/文件损坏返回 null。 */
    suspend fun loadExam(): ExamProgress? = withContext(Dispatchers.IO) {
        if (examDropped) return@withContext null
        val f = examFile ?: return@withContext null
        try {
            if (!f.exists()) null else quizJson.decodeFromString(ExamProgress.serializer(), f.readText())
        } catch (e: Exception) {
            null
        }
    }

    /** 保存笔试会话（内存置脏 + 防抖写盘）。会话已关闭时忽略。 */
    fun saveExam(p: ExamProgress) {
        synchronized(this) {
            if (examClosed) return
            examPending = p.copy(savedAt = fmtTime())
            examDirty = true
            examRemoved = false
            examDropped = false
        }
        scheduleFlush()
    }

    /** 结束笔试会话（交卷 / 用户放弃）：删除快照并关闭写入口。 */
    @Synchronized
    fun clearExam() {
        examPending = null
        examDirty = false
        examRemoved = true
        examClosed = true
        examDropped = true
        scheduleFlush()
    }

    // ---------------- 写盘 ----------------

    /** 脏标记时调度一次后台写盘；已在窗口内的多次变更合并为一次文件写入。 */
    private fun scheduleFlush() {
        if (flushScheduled) return
        flushScheduled = true
        ioScope.launch {
            delay(FLUSH_DEBOUNCE_MS)
            // 先清标记再写盘：写盘期间的新变更会另起一次调度，不会丢
            flushScheduled = false
            flushAsync()
        }
    }

    /** 后台写盘：快照+清脏+落盘在同一 writeMutex 临界区内串行执行，主线程零阻塞。 */
    suspend fun flushAsync() = writeMutex.withLock { doFlush() }

    /**
     * 请求异步写盘（不阻塞调用方）。Activity.onStop 用它做兜底——
     * 活动期已有 400ms 防抖持续落盘，此处改同步 `runBlocking` 会在主线程排队等待，
     * 代价远大于「最多丢最近 <0.5s 进度」。
     */
    fun requestFlush() {
        ioScope.launch { flushAsync() }
    }

    /** 同步串行写盘；仅用于确实需要「返回前已落盘」的场景。 */
    fun flushSync() = runBlocking { writeMutex.withLock { doFlush() } }

    /** 实际写盘：快照在类监视器内完成（与写入方同一把锁，消除竞态）；失败恢复脏标记等待重试。 */
    private fun doFlush() {
        val quizWrite: QuizProgress?
        val examWrite: ExamProgress?
        val delQuiz: Boolean
        val delExam: Boolean
        synchronized(this) {
            quizWrite = if (quizDirty) quizPending.also { quizDirty = false } else null
            examWrite = if (examDirty) examPending.also { examDirty = false } else null
            delQuiz = quizRemoved.also { quizRemoved = false }
            delExam = examRemoved.also { examRemoved = false }
        }
        try {
            // 删除优先于写入：同一轮里若先 save 后 clear，以 clear 为准
            // 写入用原子替换（临时文件 + 重命名），避免中途失败留下截断 JSON
            if (delQuiz) quizFile?.delete()
            else quizWrite?.let { quizFile?.writeTextAtomic(quizJson.encodeToString(QuizProgress.serializer(), it)) }

            if (delExam) examFile?.delete()
            else examWrite?.let { examFile?.writeTextAtomic(quizJson.encodeToString(ExamProgress.serializer(), it)) }
        } catch (e: Exception) {
            // 写盘失败（存储满等）：恢复脏标记等待下次重试，静默同 RecordsStore
            synchronized(this) {
                if (delQuiz) quizRemoved = true else if (quizWrite != null) quizDirty = true
                if (delExam) examRemoved = true else if (examWrite != null) examDirty = true
            }
        }
    }
}
