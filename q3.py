
# q3.py (v4.4.1 - Robust Sizing & UI)
# -*- coding: utf-8 -*-
"""
一个剪贴板监控工具，当有新内容被复制时，会在屏幕右下角显示一个无干扰的弹窗。

v4.4.1 版本特性 (基于 v4.4.0):
- 【BUG修复】解决了在处理图片时因 "NameError: name 'clipboard' is not defined" 导致的崩溃问题。
- 【功能增强】现在可以计算并显示未知内容 (自定义 MIME 类型) 的大小。
- 【UI优化】根据用户建议，重新设计了未知内容的显示方式：
           - 上方区域显示 "未知内容" 及其具体的 MIME 类型。
           - 下方区域直接显示其计算出的大小。
- (保留) v4.4.0 的所有功能：能检测剪贴板清空、处理非本地URL、UI防溢出等。
"""
import sys
import os
import signal
import concurrent.futures
import random
import glob
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout
from PyQt5.QtCore import (Qt, QTimer, QPoint, QPropertyAnimation, pyqtSignal, QBuffer,
                          QIODevice, QParallelAnimationGroup, QAbstractAnimation, QEasingCurve, QUrl)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QFontDatabase, QCursor


# --- 文件大小计算函数 (v4.2.1, 无改动) ---
def _get_path_size(path):
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
        elif os.path.isdir(path):
            total_size = 0
            try:
                with os.scandir(path) as entries:
                    for entry in entries:
                        try:
                            if entry.is_file(follow_symlinks=False):
                                total_size += entry.stat(follow_symlinks=False).st_size
                            elif entry.is_dir(follow_symlinks=False):
                                total_size += _get_path_size(entry.path)
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                pass
            return total_size
        else:
            return 0
    except (OSError, PermissionError):
        return 0
# --- 文件大小计算函数结束 ---


class ClipboardMonitor(QApplication):
    """
    主应用程序类，处理剪贴板监控并管理弹窗。
    """
    calculation_done = pyqtSignal(str, QWidget)
    current_color_mode = 0
    COOLDOWN_TIME_MS = 100

    def __init__(self, argv):
        super().__init__(argv)
        self.active_popups = []
        self.is_on_cooldown = False
        self.calculation_done.connect(self.on_calculation_finished)
        self.setup_clipboard_monitor()

        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=os.cpu_count() * 2 if os.cpu_count() else 8
        )

        self.active_players = []
        self.last_played_sound = None
        self.setup_sound_files()

    def setup_sound_files(self):
        """查找并加载音效文件列表。"""
        try:
            script_dir = os.path.dirname(os.path.realpath(__file__))
            assets_dir = os.path.join(script_dir, 'assets')
            self.sound_files = glob.glob(os.path.join(assets_dir, '[1-8].mp3'))

            if not self.sound_files:
                print("警告: 在 'assets' 文件夹中未找到任何 mp3 音效文件。")
            else:
                print(f"成功加载 {len(self.sound_files)} 个音效文件。")
        except Exception as e:
            print(f"加载音效文件时出错: {e}")
            self.sound_files = []

    def play_random_sound(self):
        """从列表中随机选择并播放一个音效。"""
        if not self.sound_files:
            return

        candidate_files = self.sound_files
        if self.last_played_sound and len(self.sound_files) > 1:
            candidate_files = [f for f in self.sound_files if f != self.last_played_sound]
            if not candidate_files:
                candidate_files = self.sound_files

        sound_path = random.choice(candidate_files)
        self.last_played_sound = sound_path

        player = QMediaPlayer()
        url = QUrl.fromLocalFile(sound_path)
        self.active_players.append(player)
        player.mediaStatusChanged.connect(self.on_player_status_changed)
        player.setMedia(QMediaContent(url))
        player.play()

    def on_player_status_changed(self, status):
        """播放器状态改变时的槽函数。"""
        if status == QMediaPlayer.EndOfMedia:
            player = self.sender()
            if player in self.active_players:
                self.active_players.remove(player)
            if player:
                try:
                    player.disconnect()
                except RuntimeError:
                    pass

    def setup_clipboard_monitor(self):
        """设置剪贴板监控机制。"""
        clipboard = self.clipboard()
        clipboard.dataChanged.connect(self.on_clipboard_changed)

    # --- MODIFIED: v4.4.1 - 核心修改 ---
    def process_clipboard_data(self, mime_data):
        """
        处理剪贴板数据，为弹窗准备好所有需要显示的部分。
        (v4.4.1 修改: 修复bug, 计算未知内容大小, 优化UI显示)
        """
        all_formats = mime_data.formats()

        # 1. 优先处理已知类型 (文件, 图片, 文本)
        if mime_data.hasUrls():
            urls = mime_data.urls()
            if not urls: return None

            local_paths = [url.toLocalFile() for url in urls if url.isLocalFile() and os.path.exists(url.toLocalFile())]

            if not local_paths:
                remote_urls = [url for url in urls if not url.isLocalFile()]
                if remote_urls:
                    top_text = f"复制了 {len(remote_urls)} 个 URL"
                    bottom_text = remote_urls[0].toString()
                    if len(bottom_text) > 50:
                        bottom_text = bottom_text[:47] + "..."
                    return {"type": "other", "top_text": top_text, "bottom_text": bottom_text}
                return None

            count = len(local_paths)
            num_files = sum(1 for p in local_paths if os.path.isfile(p))
            num_folders = sum(1 for p in local_paths if os.path.isdir(p))

            top_text = ""
            bottom_template = ""
            if count == 1:
                top_text = os.path.basename(local_paths[0])
                if num_folders == 1: bottom_template = "文件夹: {}"
                else: bottom_template = "文件: {}"
            else:
                max_display_files = 7
                top_text_lines = [os.path.basename(p) for p in local_paths[:max_display_files]]
                if count > max_display_files:
                    top_text_lines.append(f"... (等 {count - max_display_files} 个)")
                top_text = "\n".join(top_text_lines)

                if num_files > 0 and num_folders > 0: bottom_template = f"{count} 个项目: {{}}"
                elif num_folders > 0: bottom_template = f"{count} 个文件夹: {{}}"
                else: bottom_template = f"{count} 个文件: {{}}"
            return {"type": "file", "top_text": top_text, "bottom_template": bottom_template, "paths": local_paths}

        if mime_data.hasImage():
            # 【v4.4.1 BUG修复】: 使用 self.clipboard() 代替未定义的 clipboard
            pixmap = self.clipboard().pixmap()
            if pixmap.isNull(): return None
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly); pixmap.save(buffer, "PNG"); byte_size = len(buffer.data())
            return {"type": "image", "top_text": f"{pixmap.width()}×{pixmap.height()}", "bottom_text": f"截图: {self.format_size(byte_size)}"}

        if mime_data.hasText():
            text = mime_data.text()
            if text:
                try: byte_size = len(text.encode('gbk'))
                except UnicodeEncodeError: byte_size = len(text.encode('utf-8', 'replace'))
                return {"type": "text", "top_text": text, "bottom_text": f"{self.format_size(byte_size)}"}

        # 2. 【v4.4.1 功能增强】处理 "未知" 但 "非空" 的剪贴板, 并计算其大小
        if all_formats:
            filtered_formats = [
                f for f in all_formats
                if not f.startswith('application/x-qt-')
                and f not in ('text/plain', 'text/plain;charset=utf-8', 'text/uri-list', 'UTF8_STRING', 'COMPOUND_TEXT', 'TEXT', 'STRING', 'image/png')
            ]

            primary_type = None
            if filtered_formats:
                primary_type = filtered_formats[0]
            elif all_formats:
                primary_type = all_formats[0]

            if primary_type:
                byte_data = mime_data.data(primary_type)
                data_size = byte_data.size() # QByteArray.size() is the method to get byte count

                # 【v4.4.1 UI优化】: 按新格式组织弹窗内容
                top_text = f"未知内容，类型: {primary_type}"
                bottom_text = self.format_size(data_size)

                return {"type": "other", "top_text": top_text, "bottom_text": bottom_text}

        # 3. 处理 "剪贴板被清空" 的情况
        if not all_formats:
            return {"type": "clear", "top_text": "剪贴板已清空", "bottom_text": " "}

        # 4. 最终回退
        return None
    # --- 核心修改结束 ---

    def calculate_total_size_async(self, file_paths, popup, template):
        """在后台线程中异步计算所有给定文件和文件夹的总大小。"""
        futures = [self.executor.submit(_get_path_size, path) for path in file_paths]

        def aggregate_and_emit_result_on_main_thread(futures_list):
            total_size = 0
            for future in futures_list:
                try:
                    total_size += future.result()
                except Exception as exc:
                    sys.stderr.write(f"警告: 聚合大小计算时发生错误: {exc}\n")
            self.calculation_done.emit(template.format(self.format_size(total_size)), popup)

        self.executor.submit(aggregate_and_emit_result_on_main_thread, futures)

    def on_calculation_finished(self, final_text, popup):
        """当大小计算完成时，在主线程中更新弹窗的底部标签。"""
        if popup in self.active_popups:
            popup.update_bottom_text(final_text)

    def format_size(self, size_bytes):
        """格式化文件大小显示。"""
        if size_bytes is None: return "N/A"
        if size_bytes < 1024: return f"{round(size_bytes)} <i>b</i>"
        kb = size_bytes / 1024
        if kb < 1024: return f"{round(kb)} <i>K</i>"
        mb = kb / 1024
        return f"{mb:.1f} <i>Mb</i>" if mb < 1024 else f"{round(mb/1024)} <i>Gb</i>"


    def on_clipboard_changed(self):
        """剪贴板变化的主要事件处理程序。"""
        if self.is_on_cooldown:
            return

        data = self.process_clipboard_data(self.clipboard().mimeData())

        if data:
            if data.get("type") != "clear":
                self.play_random_sound()

            new_popup = self.show_popup(data)

            if data.get("type") == "file" and "paths" in data:
                new_popup.update_bottom_text(data["bottom_template"].format("●"))
                self.calculate_total_size_async(data["paths"], new_popup, data["bottom_template"])

    def show_popup(self, data):
        """创建并显示一个新的弹窗。"""
        stationary_popup = None
        for p in self.active_popups:
            if not (hasattr(p, 'is_sliding_out') and p.is_sliding_out):
                stationary_popup = p
                break

        if stationary_popup:
            stationary_popup.slide_out()

        new_popup = TransparentPopup(data, self, self.current_color_mode)
        self.current_color_mode = 1 - self.current_color_mode
        new_popup.raise_()
        self.active_popups.append(new_popup)

        self.is_on_cooldown = True
        QTimer.singleShot(self.COOLDOWN_TIME_MS, lambda: setattr(self, 'is_on_cooldown', False))

        return new_popup

    def close_popup(self, popup):
        """关闭指定的弹窗，确保在关闭卡片时正确处理生命周期。"""
        if popup in self.active_popups:
            self.active_popups.remove(popup)
        try:
            if hasattr(popup, 'slide_anim') and popup.slide_anim.state() == QPropertyAnimation.Running:
                popup.slide_anim.stop()
        except (RuntimeError, AttributeError):
            pass
        try:
            if hasattr(popup, 'anim_group') and popup.anim_group.state() == QParallelAnimationGroup.Running:
                popup.anim_group.stop()
        except (RuntimeError, AttributeError):
            pass

        if hasattr(popup, 'lifecycle_timer'):
            popup.lifecycle_timer.stop()
        popup.close()

    def __del__(self):
        """确保在应用程序退出时关闭线程池。"""
        if hasattr(self, 'executor') and self.executor:
            self.executor.shutdown(wait=True)


class TransparentPopup(QWidget):
    """
    固定大小、带虚线边框和定制布局的弹窗。
    """
    SLIDE_IN_DURATION = 88
    SLIDE_OUT_DURATION = 88
    LIFECYCLE_SECONDS = 19

    def __init__(self, data, monitor, color_mode=0):
        super().__init__()
        self.monitor = monitor
        self.color_mode = color_mode

        if self.color_mode == 0:
            self.background_color = QColor(0, 0, 0, 240)
            self.text_color = Qt.white
            self.border_color = Qt.white
        else:
            self.background_color = QColor(238, 232, 213, 250)
            self.text_color = QColor(55, 45, 15)
            self.border_color = QColor(55, 45, 15)

        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.setFixedSize(222, 222)
        layout = QVBoxLayout(self); layout.setContentsMargins(15, 15, 15, 15); layout.setSpacing(10)

        font_fallback_list = ["Consolas", "monospace", "LXGW WenKai GB Screen", "SF Pro", "Segoe UI", "Aptos", "Roboto", "Arial"]
        font = QFont()
        font.setFamilies(font_fallback_list)
        font.setPointSize(11)

        self.top_content_label = QLabel(data.get("top_text")); self.top_content_label.setFont(font)
        self.top_content_label.setTextFormat(Qt.PlainText)
        if self.color_mode == 0:
            self.top_content_label.setStyleSheet("color: #ffffff;")
        else:
            self.top_content_label.setStyleSheet(f"color: rgb({self.text_color.red()}, {self.text_color.green()}, {self.text_color.blue()}); font-weight: bold;")
        self.top_content_label.setWordWrap(True)
        self.top_content_label.setAlignment(Qt.AlignTop | Qt.AlignLeft); self.top_content_label.setMaximumHeight(162)

        self.bottom_message_label = QLabel(data.get("bottom_text", "")); self.bottom_message_label.setFont(font)
        if self.color_mode == 0:
            self.bottom_message_label.setStyleSheet("color: #cd853f;")
        else:
            self.bottom_message_label.setStyleSheet("color: #8B4513; font-weight: bold;")
        self.bottom_message_label.setAlignment(Qt.AlignBottom | Qt.AlignLeft)
        self.bottom_message_label.setTextFormat(Qt.RichText)

        layout.addWidget(self.top_content_label); layout.addStretch(); layout.addWidget(self.bottom_message_label)

        self.target_screen_geom = self.get_current_screen_geometry()
        self.move_to_initial_position()
        self.show()
        self.slide_in()
        self.start_lifecycle()

    def mousePressEvent(self, event):
        """当鼠标点击弹窗时，立即触发滑出动画。"""
        if event.button() == Qt.LeftButton:
            self.slide_out()

    def get_current_screen_geometry(self):
        """获取鼠标指针当前所在屏幕的可用几何区域。"""
        current_screen = QApplication.screenAt(QCursor.pos())
        if current_screen:
            return current_screen.availableGeometry()
        return QApplication.primaryScreen().availableGeometry()

    def start_lifecycle(self):
        self.lifecycle_timer = QTimer(self); self.lifecycle_timer.setSingleShot(True)
        self.lifecycle_timer.timeout.connect(self.slide_out); self.lifecycle_timer.start(self.LIFECYCLE_SECONDS * 1000)

    def slide_out(self):
        """执行滑出动画。"""
        if hasattr(self, 'lifecycle_timer'): self.lifecycle_timer.stop()
        if hasattr(self, 'is_sliding_out') and self.is_sliding_out: return
        self.is_sliding_out = True

        try:
            if hasattr(self, 'slide_anim') and self.slide_anim.state() == QPropertyAnimation.Running:
                self.slide_anim.stop()
        except (RuntimeError, AttributeError):
            pass

        self.anim_group = QParallelAnimationGroup(self)
        opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        opacity_anim.setDuration(self.SLIDE_OUT_DURATION); opacity_anim.setStartValue(1.0)
        opacity_anim.setEndValue(0.0); opacity_anim.setEasingCurve(QEasingCurve.InQuad)

        pos_anim = QPropertyAnimation(self, b"pos")
        pos_anim.setDuration(self.SLIDE_OUT_DURATION); pos_anim.setStartValue(self.pos())
        pos_anim.setEndValue(QPoint(self.x() - 80, self.y())); pos_anim.setEasingCurve(QEasingCurve.OutQuad)

        self.anim_group.addAnimation(opacity_anim)
        self.anim_group.addAnimation(pos_anim)
        self.anim_group.finished.connect(lambda: self.monitor.close_popup(self))
        self.anim_group.start(QAbstractAnimation.DeleteWhenStopped)

    def move_to_initial_position(self):
        """将窗口移动到当前屏幕的右侧外部。"""
        self.move(self.target_screen_geom.right(), self.target_screen_geom.bottom() - self.height() - 40)

    def slide_in(self):
        """动画化弹窗从当前屏幕的右侧滑入。"""
        end_pos = QPoint(self.target_screen_geom.right() - self.width() - 40, self.y())
        self.slide_anim = QPropertyAnimation(self, b"pos")
        self.slide_anim.setDuration(self.SLIDE_IN_DURATION)
        self.slide_anim.setStartValue(self.pos()); self.slide_anim.setEndValue(end_pos)
        self.slide_anim.start(QPropertyAnimation.DeleteWhenStopped)

    def update_bottom_text(self, text):
        self.bottom_message_label.setText(text)

    def paintEvent(self, event):
        """绘制弹窗背景和虚线边框。"""
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.background_color)
        pen = QPen(self.border_color, 1, Qt.DashLine); painter.setPen(pen)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = ClipboardMonitor(sys.argv)

    print("="*20 + " 系统可用字体家族名列表 " + "="*20)
    print(" (这些是您可以复制并粘贴到代码中的名字) ")
    db = QFontDatabase()
    verified_families = set()
    for name in db.families():
        font = QFont(name)
        verified_families.add(font.family())
    print(sorted(list(verified_families)))
    print("="*63)

    signal.signal(signal.SIGINT, lambda sig, frame: QApplication.quit())
    timer = QTimer(); timer.start(50); timer.timeout.connect(lambda: None)

    sys.exit(app.exec_())
