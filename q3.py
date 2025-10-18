# q3.py (v4.5.20 - Unrestricted Mode)
# -*- coding: utf-8 -*-
"""
一个剪贴板监控工具，当有新内容被复制时，会在屏幕右下角显示一个无干扰的弹窗。

v4.5.20 版本特性 (基于 v4.5.19):
- 【性能】移除了所有与拖拽和画布移动相关的限制性代码。
  - 解决方案:
    1. 在 activate_sticky_mode 中，删除了
       self.top_content.horizontalScrollBar().setRange(0, 0) 这一行。
    2. 现在，当文本行过长时，拖动可以选择文本并水平移动画布，
       这恢复了 QTextEdit 的默认行为。
  - 目标: 性能至上，代码至简。

v4.5.19 版本特性:
- 【D&D】完全放开拖拽限制，允许拖拽到外部程序。
- 【Layout】修改布局为固定宽度(2022px)并水平居中。
- 【Bug 修复】修复了滚动条的定位逻辑。
"""
import sys
import os
import signal
import concurrent.futures
import random
import glob
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout,
                             QTextEdit, QScrollBar)
from PyQt5.QtCore import (Qt, QTimer, QPoint, QPropertyAnimation, pyqtSignal, QBuffer,
                          QIODevice, QParallelAnimationGroup, QAbstractAnimation, QEasingCurve, QUrl,
                          QEvent, QTime, QRect)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtGui import (QFont, QPainter, QColor, QPen, QFontDatabase, QCursor,
                         QTextOption, QTextCursor, QKeySequence, QPalette)


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
                        except (OSEError, PermissionError):
                            continue
            except (OSEError, PermissionError):
                pass
            return total_size
        else:
            return 0
    except (OSEError, PermissionError):
        return 0
# --- 文件大小计算函数结束 ---


# --- v4.5.19: 一个干净的 QTextEdit 子类 ---
class StickyTextEdit(QTextEdit):
    """
    v4.5.19/v4.5.20:
    - 这个类现在非常干净。
    - 它只包含拦截粘贴 (insertFromMimeData) 和
      拦截内部复制快捷键 (keyPressEvent) 的逻辑。
    - 所有关于鼠标拖拽的覆盖都已被移除，以实现
      最纯粹、最高性能的默认行为。
    """
    internal_copy_triggered = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.popup = None
        self.setAcceptDrops(True)

    def insertFromMimeData(self, source):
        if source.hasText():
            text = source.text()
            if text:
                self.textCursor().insertText(text)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            if self.popup and self.popup.is_sticky and self.textCursor().hasSelection():
                self.internal_copy_triggered.emit()
                self.popup.monitor.set_cooldown()

        super().keyPressEvent(event)


class ClipboardMonitor(QApplication):
    """
    主应用程序类 (v4.5.13 代码, 无改动)
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
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 8)
        self.active_players = []
        self.last_played_sound = None
        self.setup_sound_files()

    def setup_sound_files(self):
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
        if not self.sound_files: return
        candidate_files = self.sound_files
        if self.last_played_sound and len(self.sound_files) > 1:
            candidate_files = [f for f in self.sound_files if f != self.last_played_sound]
        if not candidate_files: candidate_files = self.sound_files
        sound_path = random.choice(candidate_files)
        self.last_played_sound = sound_path
        player = QMediaPlayer()
        url = QUrl.fromLocalFile(sound_path)
        self.active_players.append(player)
        player.mediaStatusChanged.connect(self.on_player_status_changed)
        player.setMedia(QMediaContent(url))
        player.play()

    def on_player_status_changed(self, status):
        if status == QMediaPlayer.EndOfMedia:
            player = self.sender()
            if player in self.active_players: self.active_players.remove(player)
            if player:
                try: player.disconnect()
                except RuntimeError: pass

    def setup_clipboard_monitor(self):
        self.clipboard().dataChanged.connect(self.on_clipboard_changed)

    def process_clipboard_data(self, mime_data):
        all_formats = mime_data.formats()
        if mime_data.hasUrls():
            urls = mime_data.urls()
            if not urls: return None
            local_paths = [url.toLocalFile() for url in urls if url.isLocalFile() and os.path.exists(url.toLocalFile())]
            if not local_paths:
                remote_urls = [url for url in urls if not url.isLocalFile()]
                if remote_urls:
                    top_text = f"复制了 {len(remote_urls)} 个 URL"
                    bottom_text = remote_urls[0].toString()
                    if len(bottom_text) > 50: bottom_text = bottom_text[:47] + "..."
                    return {"type": "other", "top_text": top_text, "bottom_text": bottom_text}
                return None
            count, num_files, num_folders = len(local_paths), sum(1 for p in local_paths if os.path.isfile(p)), sum(1 for p in local_paths if os.path.isdir(p))
            if count == 1:
                top_text, bottom_template = os.path.basename(local_paths[0]), "文件夹: {}" if num_folders == 1 else "文件: {}"
            else:
                top_text = "\n".join([os.path.basename(p) for p in local_paths[:7]])
                if count > 7: top_text += f"\n... (等 {count - 7} 个)"
                if num_files > 0 and num_folders > 0: bottom_template = f"{count} 个项目: {{}}"
                elif num_folders > 0: bottom_template = f"{count} 个文件夹: {{}}"
                else: bottom_template = f"{count} 个文件: {{}}"
            return {"type": "file", "top_text": top_text, "bottom_template": bottom_template, "paths": local_paths}
        if mime_data.hasImage():
            pixmap = self.clipboard().pixmap()
            if pixmap.isNull(): return None
            buffer = QBuffer(); buffer.open(QIODevice.WriteOnly); pixmap.save(buffer, "PNG");
            return {"type": "image", "top_text": f"{pixmap.width()}×{pixmap.height()}", "bottom_text": f"截图: {self.format_size(len(buffer.data()))}"}
        if mime_data.hasText():
            text = mime_data.text()
            if text:
                try: byte_size = len(text.encode('gbk'))
                except UnicodeEncodeError: byte_size = len(text.encode('utf-8', 'replace'))
                return {"type": "text", "top_text": text, "bottom_text": f"{self.format_size(byte_size)}"}
        if all_formats:
            filtered_formats = [f for f in all_formats if not f.startswith('application/x-qt-') and f not in ('text/plain', 'text/uri-list')]
            primary_type = filtered_formats[0] if filtered_formats else all_formats[0]
            if primary_type:
                data_size = mime_data.data(primary_type).size()
                return {"type": "other", "top_text": f"未知内容\n类型: {primary_type}", "bottom_text": self.format_size(data_size)}
        return {"type": "clear", "top_text": "剪贴板已清空", "bottom_text": " "}

    def calculate_total_size_async(self, file_paths, popup, template):
        futures = [self.executor.submit(_get_path_size, path) for path in file_paths]
        def aggregate_and_emit(futs):
            total_size = sum(future.result() for future in futs if not future.exception())
            self.calculation_done.emit(template.format(self.format_size(total_size)), popup)
        self.executor.submit(aggregate_and_emit, futures)

    def on_calculation_finished(self, final_text, popup):
        if popup in self.active_popups: popup.update_bottom_text(final_text)

    def format_size(self, size_bytes):
        if size_bytes is None: return "N/A"
        if size_bytes < 1024: return f"{round(size_bytes)} <i>b</i>"
        kb = size_bytes / 1024
        if kb < 1024: return f"{round(kb)} <i>K</i>"
        mb = kb / 1024
        if mb < 1024: return f"{mb:.1f} <i>Mb</i>"
        return f"{mb/1024:.1f} <i>Gb</i>"

    def set_cooldown(self):
        self.is_on_cooldown = True
        QTimer.singleShot(self.COOLDOWN_TIME_MS, lambda: setattr(self, 'is_on_cooldown', False))

    def on_clipboard_changed(self):
        if self.is_on_cooldown: return
        mime_data = self.clipboard().mimeData()
        data = self.process_clipboard_data(mime_data)
        if not data: return
        if any(p.is_sticky for p in self.active_popups):
            self.set_cooldown(); return
        if data.get("type") != "clear": self.play_random_sound()

        stationary_popup = next((p for p in reversed(self.active_popups) if not (hasattr(p, 'is_sliding_out') and p.is_sliding_out)), None)
        if stationary_popup and not stationary_popup.is_sticky:
            stationary_popup.slide_out()

        new_popup = TransparentPopup(data, self, self.current_color_mode)
        self.current_color_mode = 1 - self.current_color_mode
        new_popup.raise_()
        self.active_popups.append(new_popup)
        self.set_cooldown()

        if data.get("type") == "file" and "paths" in data:
            new_popup.update_bottom_text(data["bottom_template"].format("●"))
            self.calculate_total_size_async(data["paths"], new_popup, data["bottom_template"])

    def close_popup(self, popup):
        if popup in self.active_popups: self.active_popups.remove(popup)
        for anim_name in ['slide_anim', 'anim_group']:
            anim = getattr(popup, anim_name, None)
            if anim and anim.state() == QPropertyAnimation.Running: anim.stop()
        for timer_name in ['lifecycle_timer', 'border_animation_timer']:
            getattr(popup, timer_name, QTimer()).stop()
        popup.disconnect_scrollbar_signals()
        popup.close()

    def __del__(self):
        if hasattr(self, 'executor'): self.executor.shutdown(wait=True)


class TransparentPopup(QWidget):
    SLIDE_IN_DURATION, SLIDE_OUT_DURATION, LIFECYCLE_SECONDS = 88, 88, 19
    SCROLLBAR_WIDTH, SCROLLBAR_MARGIN_RIGHT = 11, 2

    OVERLAY_SCROLLBAR_STYLE_SHEET = """
        QScrollBar:vertical {{ border: none; background: transparent; width: {width}px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: {handle_color}; border-radius: 0px; min-height: 20px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
    """

    def __init__(self, data, monitor, color_mode=0):
        super().__init__()
        self.monitor, self.color_mode, self.original_data = monitor, color_mode, data
        self.is_sticky, self.border_thickness, self.border_dash_offset = False, 1, 0
        self.lifecycle_remaining, self.lifecycle_start_time = self.LIFECYCLE_SECONDS * 1000, None

        self.border_animation_timer = QTimer(self); self.border_animation_timer.timeout.connect(self.animate_border)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(222, 222)

        self.overlay_scrollbar = QScrollBar(self); self.overlay_scrollbar.setOrientation(Qt.Vertical); self.overlay_scrollbar.hide()
        self.is_scrollbar_connected = False

        self.setup_ui()
        self.setup_colors_and_styles()

        self.target_screen_geom = self.get_current_screen_geometry()
        self.move_to_initial_position()
        self.show()
        self.slide_in()
        self.start_lifecycle()

    def setup_colors_and_styles(self):
        common_bottom_style = "padding-top: 8px;"
        if self.color_mode == 0:
            self.background_color, self.text_color, self.border_color = QColor(0, 0, 0, 240), Qt.white, Qt.white
            dark_gold_color_0_hex = "#cd853f"
            self.bottom_text_style = f"color: {dark_gold_color_0_hex}; {common_bottom_style}"
            self.top_text_style = "color: #ffffff;"
            self.scrollbar_handle_color = "rgba(205, 133, 63, 204)"
            highlight_bg_color = QColor(dark_gold_color_0_hex)
        else:
            self.background_color, self.border_color = QColor(253, 246, 227, 250), QColor(55, 45, 15)
            self.text_color = QColor(3, 2, 1)
            dark_gold_color_1_hex = "#8B4513"
            self.bottom_text_style = f"color: {dark_gold_color_1_hex}; font-weight: bold; {common_bottom_style}"
            self.top_text_style = f"color: rgb({self.text_color.red()}, {self.text_color.green()}, {self.text_color.blue()});"
            self.scrollbar_handle_color = "rgba(139, 69, 19, 204)"
            highlight_bg_color = QColor(139, 69, 19, 191)
        self.bottom_message_label.setStyleSheet(self.bottom_text_style)
        self.top_content.setStyleSheet(f"QTextEdit {{ border: none; background-color: transparent; padding: 0; {self.top_text_style} }}")
        scroll_style = self.OVERLAY_SCROLLBAR_STYLE_SHEET.format(width=self.SCROLLBAR_WIDTH, handle_color=self.scrollbar_handle_color)
        self.overlay_scrollbar.setStyleSheet(scroll_style)
        palette = self.top_content.palette()
        palette.setColor(QPalette.Highlight, highlight_bg_color)
        palette.setColor(QPalette.HighlightedText, QColor(Qt.white))
        self.top_content.setPalette(palette)

    def setup_ui(self):
        """v4.5.19 逻辑, 无改动"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10); layout.setSpacing(10)
        font = QFont("Consolas", 11); font.setFamilies(["Consolas", "monospace", "LXGW WenKai GB Screen", "SF Pro", "Segoe UI", "Aptos", "Roboto", "Arial"])

        self.top_content = StickyTextEdit(self); self.top_content.popup = self
        self.top_content.setText(self.original_data.get("top_text"))
        self.top_content.setReadOnly(True); self.top_content.setTextInteractionFlags(Qt.NoTextInteraction)
        self.top_content.setFont(font); self.top_content.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.top_content.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.top_content.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.top_content.setMaximumHeight(162)
        self.top_content.setFixedWidth(202)
        self.top_content.setViewportMargins(0, 0, 0, 0)
        self.top_content.internal_copy_triggered.connect(self.monitor.play_random_sound)

        self.bottom_message_label = QLabel(self.original_data.get("bottom_text", ""));
        self.bottom_message_label.setFont(font)
        self.bottom_message_label.setAlignment(Qt.AlignBottom | Qt.AlignLeft);
        self.bottom_message_label.setTextFormat(Qt.RichText)
        self.bottom_message_label.installEventFilter(self)
        self.bottom_message_label.setFixedWidth(202)

        layout.addWidget(self.top_content, 0, Qt.AlignHCenter)
        layout.addStretch()
        layout.addWidget(self.bottom_message_label, 0, Qt.AlignHCenter)

    def resizeEvent(self, event):
        """v4.5.19 逻辑, 无改动"""
        super().resizeEvent(event)
        widget_geom = self.top_content.geometry()
        x = widget_geom.right() - self.SCROLLBAR_WIDTH - self.SCROLLBAR_MARGIN_RIGHT
        y, height = widget_geom.top(), widget_geom.height()
        self.overlay_scrollbar.setGeometry(int(x), int(y), int(self.SCROLLBAR_WIDTH), int(height))

    def update_overlay_scrollbar(self):
        """v4.5.19 逻辑, 无改动"""
        doc_height = self.top_content.document().size().height()
        viewport_height = self.top_content.height()
        if doc_height > viewport_height:
            self.resizeEvent(None)
            v_scrollbar = self.top_content.verticalScrollBar()
            self.overlay_scrollbar.setRange(v_scrollbar.minimum(), v_scrollbar.maximum())
            self.overlay_scrollbar.setPageStep(int(viewport_height)); v_scrollbar.setPageStep(int(viewport_height))
            self.overlay_scrollbar.setValue(v_scrollbar.value())
            self.connect_scrollbar_signals(); self.overlay_scrollbar.show()
        else:
            self.overlay_scrollbar.hide(); self.disconnect_scrollbar_signals()

    def connect_scrollbar_signals(self):
        if not self.is_scrollbar_connected:
            try:
                self.overlay_scrollbar.valueChanged.connect(self.top_content.verticalScrollBar().setValue)
                self.top_content.verticalScrollBar().valueChanged.connect(self.overlay_scrollbar.setValue)
                self.top_content.verticalScrollBar().rangeChanged.connect(self.overlay_scrollbar.setRange)
                self.is_scrollbar_connected = True
            except RuntimeError: pass

    def disconnect_scrollbar_signals(self):
        if self.is_scrollbar_connected:
            try:
                self.overlay_scrollbar.valueChanged.disconnect()
                self.top_content.verticalScrollBar().valueChanged.disconnect()
                self.top_content.verticalScrollBar().rangeChanged.disconnect()
                self.is_scrollbar_connected = False
            except RuntimeError: pass

    def eventFilter(self, obj, event):
        if obj == self.bottom_message_label and event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self.toggle_sticky_mode(); return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.is_sticky: self.slide_out()

    def get_current_screen_geometry(self):
        return (QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()).availableGeometry()

    def start_lifecycle(self):
        self.lifecycle_timer = QTimer(self); self.lifecycle_timer.setSingleShot(True)
        self.lifecycle_timer.timeout.connect(self.slide_out)
        if not self.is_sticky:
            self.lifecycle_start_time = QTime.currentTime()
            self.lifecycle_timer.start(self.lifecycle_remaining)

    def toggle_sticky_mode(self):
        self.is_sticky = not self.is_sticky
        if self.is_sticky: self.activate_sticky_mode()
        else: self.deactivate_sticky_mode()

    # --- MODIFIED: v4.5.20 - 移除画布移动限制 ---
    def activate_sticky_mode(self):
        if self.lifecycle_timer.isActive():
            self.lifecycle_timer.stop()
            self.lifecycle_remaining = max(0, self.lifecycle_remaining - self.lifecycle_start_time.msecsTo(QTime.currentTime()))

        self.border_thickness = 2; self.border_animation_timer.start(51)

        self.top_content.setReadOnly(False)
        self.top_content.setTextInteractionFlags(Qt.TextEditorInteraction)

        # v4.5.20: 移除此行，以解除对画布水平移动的限制
        # self.top_content.horizontalScrollBar().setRange(0, 0)

        self.top_content.setMaximumHeight(10000)
        self.top_content.verticalScrollBar().setValue(0)
        self.top_content.setFocus(Qt.MouseFocusReason)

        QTimer.singleShot(0, self.update_overlay_scrollbar)
        self.top_content.textChanged.connect(self.update_overlay_scrollbar)

        self.update()
    # --- 修改结束 ---

    def deactivate_sticky_mode(self):
        if self.lifecycle_remaining > 0: self.start_lifecycle()
        self.border_animation_timer.stop(); self.border_dash_offset = 0; self.border_thickness = 1

        self.top_content.setReadOnly(True)
        self.top_content.setTextInteractionFlags(Qt.NoTextInteraction)

        self.top_content.setMaximumHeight(162)
        cursor = self.top_content.textCursor(); cursor.clearSelection(); self.top_content.setTextCursor(cursor)
        self.top_content.setText(self.original_data.get("top_text"))

        self.overlay_scrollbar.hide()
        self.disconnect_scrollbar_signals()
        try:
            self.top_content.textChanged.disconnect(self.update_overlay_scrollbar)
        except TypeError: pass
        self.update()

    def animate_border(self):
        self.border_dash_offset = (self.border_dash_offset - 1) % -10; self.update()

    def slide_out(self):
        for timer in [self.lifecycle_timer, self.border_animation_timer]: timer.stop()
        if hasattr(self, 'is_sliding_out') and self.is_sliding_out: return
        self.is_sliding_out = True

        anim_group = QParallelAnimationGroup(self)
        opacity_anim = QPropertyAnimation(self, b"windowOpacity"); opacity_anim.setDuration(self.SLIDE_OUT_DURATION); opacity_anim.setEndValue(0.0)
        pos_anim = QPropertyAnimation(self, b"pos"); pos_anim.setDuration(self.SLIDE_OUT_DURATION); pos_anim.setEndValue(QPoint(self.x() - 80, self.y()))
        anim_group.addAnimation(opacity_anim); anim_group.addAnimation(pos_anim)
        anim_group.finished.connect(lambda: self.monitor.close_popup(self))
        anim_group.start(QAbstractAnimation.DeleteWhenStopped)
        self.anim_group = anim_group # Store reference

    def move_to_initial_position(self):
        self.move(self.target_screen_geom.right(), self.target_screen_geom.bottom() - self.height() - 40)

    def slide_in(self):
        end_pos = QPoint(self.target_screen_geom.right() - self.width() - 40, self.y())
        slide_anim = QPropertyAnimation(self, b"pos"); slide_anim.setDuration(self.SLIDE_IN_DURATION)
        slide_anim.setEndValue(end_pos); slide_anim.start(QPropertyAnimation.DeleteWhenStopped)
        self.slide_anim = slide_anim # Store reference

    def update_bottom_text(self, text):
        self.bottom_message_label.setText(text)

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.background_color)
        pen = QPen(self.border_color, self.border_thickness, Qt.DashLine)
        if self.is_sticky: pen.setDashOffset(self.border_dash_offset)
        painter.setPen(pen)
        adj = self.border_thickness / 2.0
        painter.drawRect(self.rect().adjusted(adj, adj, -adj, -adj))


if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling); QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = ClipboardMonitor(sys.argv)
    print("="*20 + " 系统可用字体家族名列表 " + "="*20)
    db = QFontDatabase(); print(sorted(list(set(QFont(name).family() for name in db.families()))))
    print("="*63)
    signal.signal(signal.SIGINT, lambda sig, frame: QApplication.quit())
    timer = QTimer(); timer.start(50); timer.timeout.connect(lambda: None)
    sys.exit(app.exec_())
