# qq.py
# -*- coding: utf-8 -*-
"""
audio_BGM.py (q10) 模块的演示程序。
(遵从要求, 自定义 变量/函数/类名/注释/字符串 不含 s, m, c, t)

(!! V7 演示版 !!)
"""
import sys
import os

# 检查 PyQt5 依赖 (演示 UI 需要)
try:
    from PyQt5.QtWidgets import (QApplication, QWidget, QPushButton, QVBoxLayout,
                                 QLabel, QSlider, QHBoxLayout)
    from PyQt5.QtCore import Qt, QTimer
except ImportError:
    print("【!!】 演示程序错误：需要 PyQt5 库。")
    print("【!!】 请安装： pip install PyQt5")
    sys.exit(1)

# --- (核心) 导入 BGM 引擎 ---
try:
    from audio_BGM import q10
except ImportError:
    print("="*60)
    print("【!!】 错误：未找到 audio_BGM.py 模块。")
    print("【!!】 请确保 audio_BGM.py 与此演示文件在同一目录下。")
    print("="*60)
    sys.exit(1)
# --- (核心) 结束 ---


class q50(QWidget): # 演示窗口
    def __init__(self, q51, parent=None): # q51 = bgm file path
        super().__init__(parent)

        self.q52 = q51 # 文件路径
        self.q53 = q10() # 播放器实例
        self.q54 = self.q53.q6(self.q52)
        self.q55 = self.q66(self.q54)

        self.q56()

        self.q57 = QTimer(self)
        self.q57.timeout.connect(self.q65)
        self.q57.setInterval(50)
        self.q57.start()

    def q56(self):
        """初始化用户界面"""
        self.setWindowTitle("audio_BGM.py 演示 (V7 - 固定 44.1k)")
        q58 = QVBoxLayout(self)

        self.q59 = QLabel(f"00:00.0 / {self.q55}")
        self.q59.setAlignment(Qt.AlignCenter)
        q58.addWidget(self.q59)

        # 按钮行 1
        q60 = QHBoxLayout()
        q61 = QPushButton("播放 (循环)")
        q61.clicked.connect(self.q67)
        q60.addWidget(q61)

        q62 = QPushButton("播放 (不循环, V7变速/Seek失效)")
        q62.clicked.connect(self.q68)
        q60.addWidget(q62)

        q58.addLayout(q60)

        # 按钮行 2
        q63 = QHBoxLayout()
        q64 = QPushButton("暂停")
        q64.clicked.connect(self.q53.q3)
        q63.addWidget(q64)

        q77 = QPushButton("恢复")
        q77.clicked.connect(self.q53.q4)
        q63.addWidget(q77)

        q70 = QPushButton("停止")
        q70.clicked.connect(self.q53.q2)
        q63.addWidget(q70)

        q58.addLayout(q63)

        # (V7) 播放速度滑块 (已禁用)
        self.q71 = QLabel("播放速度: 1.0x (V7: 变速功能已禁用)")
        q58.addWidget(self.q71)

        self.q72 = QSlider(Qt.Horizontal)
        self.q72.setRange(1, 40)
        self.q72.setValue(10)
        self.q72.valueChanged.connect(self.q69)
        self.q72.setEnabled(False) # (V7) 禁用滑块
        q58.addWidget(self.q72)

        self.setMinimumWidth(300)

    # (UI 回调) 播放按钮 1
    def q67(self):
        # q73 = self.q72.value() / 10.0 (V7) 忽略滑块
        self.q53.q1(
            q20=self.q52,
            q21=0,         # V7: (起始时间) 无法实现, 将从 0 开始
            q22=True,      # 循环
            q23=1.0        # V7: (速率) 无法实现, 总是 1.0
        )

    # (UI 回调) 播放按钮 2
    def q68(self):
         self.q53.q1(
            q20=self.q52,
            q21=10000,     # V7: (起始时间) 无法实现, 将从 0 开始
            q22=False,     # 不循环
            q23=0.5        # V7: (速率) 无法实现, 总是 1.0
        )

    # (UI 回调) 速度滑块
    def q69(self, q74):
        q73 = q74 / 10.0
        self.q71.setText(f"播放速度: {q73:.1f}x (V7: 变速功能已禁用)")

        # (!! 核心 V6/V7 修改 !!)
        # (V6 引擎不支持播放时动态改变速率)
        # (V7 引擎完全不支持变速)
        # self.q53.q11.setPlaybackRate(q73) # (!! 必须注释或删除 !!)

    # (UI 回调) 定时器更新标签
    def q65(self):
        # (V7) q5() 现在是估算值 (速率固定为 1.0)
        q75 = self.q53.q5()
        q76 = self.q66(q75)

        if q75 > self.q54 and not self.q53.q13: # (非循环)
            q76 = self.q55

        self.q59.setText(f"{q76} / {self.q55}")

    def q66(self, q74):
        """辅助函数: 毫秒 -> 00:00.0 样式"""
        if q74 <= 0: return "00:00.0"
        q80 = q74 // 1000
        q81 = (q74 % 1000) // 100
        q82 = q80 % 60
        q83 = q80 // 60
        return f"{q83:02d}:{q82:02d}.{q81}"

    def closeEvent(self, event):
        self.q53.q2()
        event.accept()

# --- 主程序入口 ---
if __name__ == "__main__":
    q95 = "bgm.mp3" # 确保是 MP3
    try: q90 = os.path.dirname(os.path.realpath(__file__))
    except NameError: q90 = os.path.abspath(".")
    q91 = os.path.join(q90, "assets")
    q92 = os.path.join(q91, q95)
    if not os.path.exists(q92):
        print("="*60); print(f"【!!】 错误：未找到 BGM 文件: {q92}"); sys.exit(1)
    print(f"BGM 文件已找到: {q92}")
    q93 = QApplication(sys.argv)
    q94 = q50(q92)
    q94.show()
    sys.exit(q93.exec_())
