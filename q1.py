# 文件名: qt_color_panel.py
#
# 【V2 - 线程池版】
# 解决了“不应期”问题，现在可以并发播放，实现“蜂拥而至”

import sys
import random
from PyQt5.QtWidgets import (QApplication, QWidget, QPushButton, QVBoxLayout, QMessageBox)
from PyQt5.QtCore import (QObject, QThread, pyqtSignal, pyqtSlot, QPropertyAnimation,
                        QSequentialAnimationGroup, pyqtProperty, QRunnable, QThreadPool) # <--- 导入 QRunnable 和 QThreadPool
from PyQt5.QtGui import QColor

# 从我们刚创建的模块中导入音频引擎
try:
    from audio_player import AudioEngine
except ImportError:
    print("【!!】 致命错误：找不到 'audio_player.py' 文件。")
    print("【!!】 请确保 'audio_player.py' 与 'qt_color_panel.py' 在同一文件夹中。")
    sys.exit(1)
except FileNotFoundError as e:
    # 这个 FileNotFoundError 来自 AudioEngine 的 __init__
    print(f"【!!】 致命错误：{e}")
    print("【!!】 请确保 'assets' 文件夹存在，并且包含 z1.wav ... z8.wav 文件。")
    sys.exit(1)


# 步骤 1: 创建一个“可运行任务 (Runnable)”
# QRunnable 是 QThreadPool (线程池) 的标准任务单元
# 它比 QThread/QObject 轻量级，非常适合“发射后不管”的并发任务
class AudioRunnable(QRunnable):
    def __init__(self, audio_engine_instance, file_path_to_play):
        super().__init__()
        self.audio_engine = audio_engine_instance
        self.file_path = file_path_to_play

    @pyqtSlot()
    def run(self):
        """
        线程池中的一个“工人”会执行这个 run 方法。
        它会调用 v15 阻塞逻辑，但不会阻塞 GUI 或其他工人。
        """
        try:
            # print(f"[ThreadPool] 工作线程 {QThread.currentThreadId()} 开始播放: {self.file_path}")
            self.audio_engine.play_sound(self.file_path)
            # print(f"[ThreadPool] 工作线程 {QThread.currentThreadId()} 播放完毕。")
        except Exception as e:
            print(f"[AudioRunnable] 播放时遇到致命错误: {e}")


# 步骤 2: 创建主窗口（变色面板）
class ColorPanel(QWidget):
    # 【V2 变更】我们不再需要 trigger_play 信号了
    # def trigger_play = pyqtSignal(str)

    def __init__(self, audio_engine):
        super().__init__()
        self.audio_engine = audio_engine

        # 【V2 变更】删除状态锁！我们允许并发！
        # self.is_playing = False

        # 获取全局线程池实例
        self.thread_pool = QThreadPool.globalInstance()
        # 您可以设置最大线程数，比如 10 个并发音效
        self.thread_pool.setMaxThreadCount(10)
        print(f"[ColorPanel] 线程池已初始化，最大并发数: {self.thread_pool.maxThreadCount()}")

        self.init_ui()

        # 【V2 变更】删除旧的 QThread/Worker 设置
        # self.setup_audio_thread()

    def init_ui(self):
        self.setWindowTitle('Qt5 变色音效测试面板 (V2 - 线程池并发版)')
        self.setGeometry(300, 300, 400, 300)

        self.layout = QVBoxLayout()
        self.button = QPushButton('狂点我！ (并发播放)', self) # <--- 修改按钮文字
        self.button.setMinimumHeight(100)
        self.button.setStyleSheet("font-size: 20px; font-weight: bold;")

        self.layout.addWidget(self.button)
        self.setLayout(self.layout)

        self.button.clicked.connect(self.on_button_clicked)

    # 【V2 变更】删除 setup_audio_thread(self)
    # 【V2 变更】删除 on_audio_finished(self)

    def on_button_clicked(self):
        """
        当按钮被点击时 (V2 - 线程池版)
        """
        # 【V2 变更】删除状态锁！
        # if self.is_playing:
        #     print("[ColorPanel] 忽略点击：音频已在播放中。")
        #     return

        # 【V2 变更】删除按钮禁用逻辑，我们希望按钮永远可点！
        # self.is_playing = True
        # self.button.setText("正在播放...")
        # self.button.setEnabled(False)

        # 1. 立即开始“复杂变色” (在主线程)
        # 每次点击都会重新开始动画，这会产生一种“频闪”效果，很酷
        self.start_complex_animation()

        # 2. 从引擎获取一个不重复的随机文件
        file_to_play = self.audio_engine.get_random_sound_file()

        if file_to_play:
            # 3. 创建一个“可运行任务”
            runnable_task = AudioRunnable(self.audio_engine, file_to_play)

            # 4. 把任务扔进线程池，然后立即返回！
            # GUI 不会在此处等待，可以立即响应下一次点击
            self.thread_pool.start(runnable_task)

            # 【V2 变更】删除旧的信号触发
            # self.trigger_play.emit(file_to_play)
        else:
            print("[ColorPanel] 错误：无法获取要播放的音频文件。")
            # 【V2 变更】删除状态重置
            # self.on_audio_finished()

    # --- 复杂变色动画 (无变化) ---

    def _get_color(self):
        return self.palette().color(self.backgroundRole())

    def _set_color(self, color):
        self.setStyleSheet(f"background-color: {color.name()};")

    panel_color = pyqtProperty(QColor, fget=_get_color, fset=_set_color)

    def start_complex_animation(self):
        total_duration = 1500

        # 如果上一个动画还在播，先停掉
        if hasattr(self, 'anim_group') and self.anim_group.state() == QPropertyAnimation.Running:
            self.anim_group.stop()

        self.anim_group = QSequentialAnimationGroup(self)

        anim1 = QPropertyAnimation(self, b"panel_color")
        anim1.setDuration(total_duration // 3)
        anim1.setStartValue(QColor("#111111"))
        anim1.setKeyValueAt(0.5, QColor("#FF0000"))
        anim1.setEndValue(QColor("#0000FF"))

        anim2 = QPropertyAnimation(self, b"panel_color")
        anim2.setDuration(total_duration // 3)
        anim2.setStartValue(QColor("#0000FF"))
        anim2.setKeyValueAt(0.5, QColor("#00FF00"))
        anim2.setEndValue(QColor("#FFFF00"))

        anim3 = QPropertyAnimation(self, b"panel_color")
        anim3.setDuration(total_duration // 3)
        anim3.setStartValue(QColor("#FFFF00"))
        anim3.setKeyValueAt(0.5, QColor("#FF00FF"))
        anim3.setEndValue(QApplication.palette().color(QApplication.palette().Window))

        self.anim_group.addAnimation(anim1)
        self.anim_group.addAnimation(anim2)
        self.anim_group.addAnimation(anim3)

        self.anim_group.start()

    def closeEvent(self, event):
        """在关闭窗口时，等待所有线程池任务完成（可选，但推荐）"""
        print("[ColorPanel] 收到关闭信号，正在等待所有音频任务完成...")
        # 这会阻塞主线程，直到所有已提交的任务都播放完毕
        self.thread_pool.waitForDone()
        print("[ColorPanel] 所有任务已完成。")
        event.accept()


# 步骤 3: 启动应用 (无变化)
if __name__ == '__main__':
    try:
        app = QApplication(sys.argv)

        engine = AudioEngine(asset_folder="assets")

        panel = ColorPanel(engine)
        panel.show()

        sys.exit(app.exec_())

    except FileNotFoundError as e:
        app_dummy = QApplication(sys.argv)
        QMessageBox.critical(None, "致命错误", f"{e}\n\n请确保 'assets' 文件夹和 z1-z8.wav 文件存在。")
    except Exception as e:
        app_dummy = QApplication(sys.argv)
        QMessageBox.critical(None, "未知错误", f"发生意外错误: {e}")
