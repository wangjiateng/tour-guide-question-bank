package com.daoyou.tiku.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.ui.graphics.Color

/** 判分后的选项底色（对/错）与正文文字色，随明暗主题取不同深浅。 */
object JudgeColors {
    /** 判对的选项底色：浅色主题用浅绿，暗色主题用深绿。 */
    val correctBg: Color
        @Composable @ReadOnlyComposable get() = if (isSystemInDarkTheme()) Color(0xFF1E4620) else Color(0xFFC8E6C9)

    /** 判错的选项底色：浅色主题用浅红，暗色主题用深红。 */
    val wrongBg: Color
        @Composable @ReadOnlyComposable get() = if (isSystemInDarkTheme()) Color(0xFF5A1A1C) else Color(0xFFFFCDD2)

    /** 判分后选项正文的文字色：暗色底配浅字，浅色底配深字。 */
    val revealText: Color
        @Composable @ReadOnlyComposable get() = if (isSystemInDarkTheme()) Color(0xFFEDEDED) else Color(0xFF1B1B1B)
}

/**
 * 应用主题：默认跟随系统深浅色（isSystemInDarkTheme），
 * 明暗两套 colorScheme 均取 Material3 默认色板，保证浅色观感与历史版本一致。
 */
@Composable
fun DaoyouTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = if (darkTheme) darkColorScheme() else lightColorScheme(),
        content = content,
    )
}
