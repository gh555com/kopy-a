# q9.py (v4.7.0 - 懒加载架构)
# -*- coding: utf-8 -*-
"""
一个剪贴板监控工具，当有新内容被复制时，会在屏幕右下角显示一个无干扰的弹窗。

v4.7.0 版本特性:
- 【核心架构】移植了 v4.1.1 的“懒加载”设计哲学，追求极致性能。
  - 1. (NEW) 弹窗现在包含一个 QLabel (初始显示) 和一个 QTextEdit (置顶后显示)。
  - 2. (MODIFIED) 初始状态下，只显示 QLabel，内容为截断的片段，无滚动条，性能最高。
  - 3. (MODIFIED) 点击消息区进入置顶模式后，才隐藏 QLabel，显示 QTextEdit 并加载完整内容。
  - 4. (MODIFIED) 退出置顶模式时，清空 QTextEdit 内容以释放内存，并切回 QLabel。
- 【功能调整】根据用户要求:
  - 1. (MODIFIED) 颜色模式 `COLOR_SCHEME_MODE` 默认设置为 3 (交替模式)。
  - 2. (MODIFIED) "未知内容" 的提示语改为单行: "未知内容，类型: ..."。
  - 3. (MODIFIED) 对于多文件复制，不再显示 "(等 N 个)"，而是直接列出文件名列表让 QLabel 自然截断。

v4.6.0 版本特性 (保留):
- 【功能】颜色模式参数化 (1=纯黑, 2=纯白, 3=交替, 4=撞色)。
- 【Bug修复】所有历史 Bug 修复均保留，包括“内容区自动标号”和“纯文本”策略。
"""
import sys
import os
import signal
import concurrent.futures
import random
import glob
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout,
                             QTextEdit, QScrollBar, QStyleOptionSlider, QStyle)
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


# --- v4.5.37 (无改动): 修复 Bug 12 ---
class StickyTextEdit(QTextEdit):
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


# --- v4.5.32 (无改动): 滚动条事件拦截 (v9) ---
class ClickJumpScrollBar(QScrollBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.press_pos = QPoint()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            self.press_pos = QPoint()
            super().mousePressEvent(event)
            return

        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        handle_rect = self.style().subControlRect(QStyle.CC_ScrollBar, opt, QStyle.SC_ScrollBarSlider, self)

        if handle_rect.contains(event.pos()):
            self.press_pos = QPoint()
            super().mousePressEvent(event)
        else:
            self.press_pos = event.pos()
            pass

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            super().mouseReleaseEvent(event)
            return

        if self.press_pos.isNull():
            super().mouseReleaseEvent(event)
            return

        moved = (event.pos() - self.press_pos).manhattanLength() > QApplication.startDragDistance()
        click_pos = self.press_pos
        self.press_pos = QPoint()

        if moved:
            super().mouseReleaseEvent(event)
            return

        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        handle_rect = self.style().subControlRect(QStyle.CC_ScrollBar, opt, QStyle.SC_ScrollBarSlider, self)
        track_rect = self.style().subControlRect(QStyle.CC_ScrollBar, opt, QStyle.SC_ScrollBarGroove, self)

        if not track_rect.isValid() or track_rect.isEmpty():
            super().mouseReleaseEvent(event); return

        if self.orientation() == Qt.Vertical:
            handle_height = handle_rect.height()
            track_height = track_rect.height()
            movable_range = track_height - handle_height
            if movable_range <= 0:
                super().mouseReleaseEvent(event); return

            relative_y = click_pos.y() - track_rect.top()
            target_handle_top = relative_y - handle_height / 2.0
            ratio = target_handle_top / movable_range
        else:
            handle_width = handle_rect.width()
            track_width = track_rect.width()
            movable_range = track_width - handle_width
            if movable_range <= 0:
                super().mouseReleaseEvent(event); return

            relative_x = click_pos.x() - track_rect.left()
            target_handle_left = relative_x - handle_width / 2.0
            ratio = target_handle_left / movable_range

        ratio = max(0.0, min(1.0, ratio))
        value_range = self.maximum() - self.minimum()
        new_value = self.minimum() + round(ratio * value_range)

        self.setValue(int(new_value))
        super().mouseReleaseEvent(event)


# --- v4.7.0 ---
class ClipboardMonitor(QApplication):
    calculation_done = pyqtSignal(str, QWidget)

    # --- MODIFIED: v4.7.0 (默认模式设为 3) ---
    COLOR_SCHEME_MODE = 3
    # 1 = 纯黑模式 | 2 = 纯白模式 | 3 = 交替模式 | 4 = 撞色模式
    # --- 修改结束 ---

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

            count = len(local_paths)
            num_files = sum(1 for p in local_paths if os.path.isfile(p))
            num_folders = sum(1 for p in local_paths if os.path.isdir(p))

            if count == 1:
                top_text = os.path.basename(local_paths[0])
                bottom_template = "文件夹: {}" if num_folders == 1 else "文件: {}"
            else:
                # --- MODIFIED: v4.7.0 (移除智能截断，直接列出) ---
                top_text = "\n".join([os.path.basename(p) for p in local_paths])
                # --- 修改结束 ---

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
                return {"type": "text", "top_text": text, "bottom_text": f"{self.format_size(byte_size)}", "byte_size": byte_size}

        if all_formats:
            filtered_formats = [f for f in all_formats if not f.startswith('application/x-qt-') and f not in ('text/plain', 'text/uri-list')]
            primary_type = filtered_formats[0] if filtered_formats else all_formats[0]
            if primary_type:
                data_size = mime_data.data(primary_type).size()
                # --- MODIFIED: v4.7.0 (单行未知内容) ---
                return {"type": "other", "top_text": f"未知内容，类型: {primary_type}", "bottom_text": self.format_size(data_size)}
                # --- 修改结束 ---
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
        if size_bytes < 1024: return f"{round(size_bytes)} b"
        kb = size_bytes / 1024
        if kb < 1024: return f"{round(kb)} K"
        mb = kb / 1024
        if mb < 1024: return f"{mb:.1f} Mb"
        return f"{mb/1024:.1f} Gb"

    def set_cooldown(self):
        self.is_on_cooldown = True
        QTimer.singleShot(self.COOLDOWN_TIME_MS, lambda: setattr(self, 'is_on_cooldown', False))

    def on_clipboard_changed(self):
        if self.is_on_cooldown: return
        mime_data = self.clipboard().mimeData()
        data = self.process_clipboard_data(mime_data)
        if not data: return
        self.play_random_sound()
        if any(p.is_sticky for p in self.active_popups):
            self.set_cooldown(); return
        stationary_popup = next((p for p in reversed(self.active_popups) if not (hasattr(p, 'is_sliding_out') and p.is_sliding_out)), None)
        if stationary_popup and not stationary_popup.is_sticky:
            stationary_popup.slide_out()

        next_color_mode_bit = self.current_color_mode
        if self.COLOR_SCHEME_MODE == 1:
            next_color_mode_bit = 0
        elif self.COLOR_SCHEME_MODE == 2:
            next_color_mode_bit = 1
        elif self.COLOR_SCHEME_MODE == 3 or self.COLOR_SCHEME_MODE == 4:
            next_color_mode_bit = 1 - self.current_color_mode

        new_popup = TransparentPopup(data, self, next_color_mode_bit, self.COLOR_SCHEME_MODE)
        self.current_color_mode = next_color_mode_bit

        new_popup.raise_()
        self.active_popups.append(new_popup)
        self.set_cooldown()
        if data.get("type") == "file" and "paths" in data:
            new_popup.update_bottom_text(data["bottom_template"].format("●"))
            self.calculate_total_size_async(data["paths"], new_popup, data["bottom_template"])

    def close_popup(self, popup):
        if popup in self.active_popups: self.active_popups.remove(popup)
        for anim_name in ['slide_anim', 'anim_group']:
            try:
                anim = getattr(popup, anim_name, None)
                if anim and anim.state() == QPropertyAnimation.Running: anim.stop()
            except RuntimeError: pass
        for timer_name in ['lifecycle_timer', 'border_animation_timer', 'text_load_timer']:
            timer = getattr(popup, timer_name, None)
            if timer: timer.stop()
        popup.disconnect_scrollbar_signals(); popup.close()

    def __del__(self):
        if hasattr(self, 'executor'): self.executor.shutdown(wait=True)


# --- v4.7.0 ---
class TransparentPopup(QWidget):
    SLIDE_IN_DURATION, SLIDE_OUT_DURATION, LIFECYCLE_SECONDS = 88, 88, 19
    SCROLLBAR_WIDTH = 11
    SCROLLBAR_MARGIN_RIGHT = 2
    TEXT_LOAD_THRESHOLD_BYTES = 100 * 1024

    OVERLAY_SCROLLBAR_STYLE_SHEET = """
        QScrollBar:vertical {{
            border: none; background: transparent; width: {width}px; margin: 0; padding: 0px;
        }}
        QScrollBar::groove:vertical {{
            border: none; background: transparent; margin: 0px; padding: 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {handle_color}; border-radius: 0px; min-height: 20px; margin: 0px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            border: none; background: none; height: 0px; margin: 0px; padding: 0px;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none; margin: 0px; padding: 0px;
        }}
    """

    def __init__(self, data, monitor, color_mode=0, scheme_mode=4):
        super().__init__()
        self.monitor, self.color_mode, self.scheme_mode = monitor, color_mode, scheme_mode
        self.original_data = data

        self.is_sticky, self.border_thickness, self.border_dash_offset = False, 1, 0
        self.lifecycle_remaining, self.lifecycle_start_time = self.LIFECYCLE_SECONDS * 1000, None
        self.full_text_to_load, self.text_load_timer = None, None

        if self.original_data.get("type") == "text":
            text_size = self.original_data.get("byte_size", 0)
            if text_size >= self.TEXT_LOAD_THRESHOLD_BYTES:
                self.full_text_to_load = self.original_data.get("top_text", "")

        self.bottom_background_color = QColor(Qt.transparent)

        self.border_animation_timer = QTimer(self); self.border_animation_timer.timeout.connect(self.animate_border)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(222, 222)

        self.overlay_scrollbar = ClickJumpScrollBar(self)
        self.overlay_scrollbar.setOrientation(Qt.Vertical); self.overlay_scrollbar.hide()
        self.is_scrollbar_connected = False

        self.setup_ui(); self.setup_colors_and_styles()
        self.target_screen_geom = self.get_current_screen_geometry()
        self.move_to_initial_position(); self.show(); self.slide_in(); self.start_lifecycle()
        self.overlay_scrollbar.raise_()

    def setup_colors_and_styles(self):
        common_bottom_style = "padding-top: 8px;"
        bg_0 = QColor(0, 0, 0, 240); text_0 = Qt.white; border_0 = Qt.white
        gold_0_hex = "#cd853f"; bottom_style_0 = f"color: {gold_0_hex}; {common_bottom_style} background-color: transparent;"
        top_style_0 = "color: #ffffff;"; scroll_handle_0 = "rgba(205, 133, 63, 204)"; highlight_0 = QColor(gold_0_hex)
        bg_1 = QColor(253, 246, 227, 250); border_1 = QColor(55, 45, 15); text_1_qcolor = QColor(3, 2, 1)
        gold_1_hex = "#8B4513"; bottom_style_1 = f"color: {gold_1_hex}; font-weight: bold; {common_bottom_style} background-color: transparent;"
        top_style_1 = f"color: rgb({text_1_qcolor.red()}, {text_1_qcolor.green()}, {text_1_qcolor.blue()});"
        scroll_handle_1 = "rgba(139, 69, 19, 204)"; highlight_1 = QColor(139, 69, 19, 191)

        main_palette_index, bottom_palette_index = 0, 0
        if self.scheme_mode == 1: main_palette_index, bottom_palette_index = 0, 0
        elif self.scheme_mode == 2: main_palette_index, bottom_palette_index = 1, 1
        elif self.scheme_mode == 3: main_palette_index, bottom_palette_index = self.color_mode, self.color_mode
        elif self.scheme_mode == 4: main_palette_index, bottom_palette_index = self.color_mode, 1 - self.color_mode

        if main_palette_index == 0:
            self.background_color, self.text_color, self.border_color, top_text_style, self.scrollbar_handle_color, highlight_bg_color = \
                bg_0, text_0, border_0, top_style_0, scroll_handle_0, highlight_0
        else:
            self.background_color, self.text_color, self.border_color, top_text_style, self.scrollbar_handle_color, highlight_bg_color = \
                bg_1, text_1_qcolor, border_1, top_style_1, scroll_handle_1, highlight_1

        if bottom_palette_index == 0: self.bottom_background_color, self.bottom_text_style = bg_0, bottom_style_0
        else: self.bottom_background_color, self.bottom_text_style = bg_1, bottom_style_1

        self.bottom_message_label.setStyleSheet(self.bottom_text_style)
        # --- MODIFIED: v4.7.0 (为两个控件分别设置样式) ---
        self.top_content_label.setStyleSheet(top_text_style)
        self.top_content_edit.setStyleSheet(f"QTextEdit {{ border: none; background-color: transparent; padding: 0; {top_text_style} }}")
        # --- 修改结束 ---

        scroll_style = self.OVERLAY_SCROLLBAR_STYLE_SHEET.format(width=self.SCROLLBAR_WIDTH, handle_color=self.scrollbar_handle_color)
        self.overlay_scrollbar.setStyleSheet(scroll_style)

        palette = self.top_content_edit.palette()
        palette.setColor(QPalette.Highlight, highlight_bg_color); palette.setColor(QPalette.HighlightedText, QColor(Qt.white))
        self.top_content_edit.setPalette(palette)

    # --- MODIFIED: v4.7.0 (懒加载 UI 设置) ---
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10); layout.setSpacing(10)
        font = QFont("Consolas", 11); font.setFamilies(["Consolas", "monospace", "LXGW WenKai GB Screen", "SF Pro", "Segoe UI", "Aptos", "Roboto", "Arial"])

        # 1. 创建 QLabel (初始显示)
        self.top_content_label = QLabel(self.original_data.get("top_text"))
        self.top_content_label.setFont(font)
        self.top_content_label.setTextFormat(Qt.PlainText)
        self.top_content_label.setWordWrap(True)
        self.top_content_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.top_content_label.setMaximumHeight(162)

        # 2. 创建 QTextEdit (置顶后显示)
        self.top_content_edit = StickyTextEdit(self); self.top_content_edit.popup = self
        self.top_content_edit.setReadOnly(True); self.top_content_edit.setTextInteractionFlags(Qt.NoTextInteraction)
        self.top_content_edit.setFont(font); self.top_content_edit.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.top_content_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.top_content_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.top_content_edit.setMaximumHeight(162)
        self.top_content_edit.setViewportMargins(0, 0, 0, 0)
        self.top_content_edit.internal_copy_triggered.connect(self.monitor.play_random_sound)
        self.top_content_edit.hide() # 默认隐藏

        # 3. 创建底部消息区
        self.bottom_message_label = QLabel(self.original_data.get("bottom_text", ""))
        self.bottom_message_label.setFont(font)
        self.bottom_message_label.setAlignment(Qt.AlignBottom | Qt.AlignLeft);
        self.bottom_message_label.setTextFormat(Qt.PlainText)
        self.bottom_message_label.installEventFilter(self)

        # 4. 加入布局
        layout.addWidget(self.top_content_label)
        layout.addWidget(self.top_content_edit)
        layout.addStretch()
        layout.addWidget(self.bottom_message_label)
    # --- 修改结束 ---

    def load_full_text(self):
        if self.full_text_to_load is None: return
        try:
            self.top_content_edit.setPlainText(self.full_text_to_load); self.full_text_to_load = None
            if self.is_sticky: QTimer.singleShot(0, self.update_overlay_scrollbar)
        except RuntimeError: pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        x = self.width() - self.SCROLLBAR_WIDTH - self.SCROLLBAR_MARGIN_RIGHT
        y = self.border_thickness
        height = self.bottom_message_label.y() - self.border_thickness
        self.overlay_scrollbar.setGeometry(int(x), int(y), int(self.SCROLLBAR_WIDTH), int(height))

    def update_overlay_scrollbar(self):
        doc_height = self.top_content_edit.document().size().height()
        viewport_height = self.bottom_message_label.y() - self.border_thickness
        if doc_height > viewport_height:
            self.resizeEvent(None); v_scrollbar = self.top_content_edit.verticalScrollBar()
            self.overlay_scrollbar.setRange(v_scrollbar.minimum(), v_scrollbar.maximum())
            self.overlay_scrollbar.setPageStep(int(viewport_height)); v_scrollbar.setPageStep(int(viewport_height))
            self.overlay_scrollbar.setValue(v_scrollbar.value())
            self.connect_scrollbar_signals(); self.overlay_scrollbar.show()
        else:
            self.overlay_scrollbar.hide(); self.disconnect_scrollbar_signals()

    def connect_scrollbar_signals(self):
        if not self.is_scrollbar_connected:
            try:
                self.overlay_scrollbar.valueChanged.connect(self.top_content_edit.verticalScrollBar().setValue)
                self.top_content_edit.verticalScrollBar().valueChanged.connect(self.overlay_scrollbar.setValue)
                self.top_content_edit.verticalScrollBar().rangeChanged.connect(self.overlay_scrollbar.setRange)
                self.is_scrollbar_connected = True
            except RuntimeError: pass

    def disconnect_scrollbar_signals(self):
        if self.is_scrollbar_connected:
            try:
                self.overlay_scrollbar.valueChanged.disconnect()
                self.top_content_edit.verticalScrollBar().valueChanged.disconnect()
                self.top_content_edit.verticalScrollBar().rangeChanged.disconnect()
                self.is_scrollbar_connected = False
            except RuntimeError: pass

    def eventFilter(self, obj, event):
        if obj == self.bottom_message_label and event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self.toggle_sticky_mode(); return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            geom_scrollbar = self.overlay_scrollbar.geometry() if self.overlay_scrollbar.isVisible() else QRect()
            geom_message = self.bottom_message_label.geometry()
            # --- MODIFIED: v4.7.0 (根据当前可见控件判断) ---
            visible_content = self.top_content_edit if self.is_sticky else self.top_content_label
            geom_content = visible_content.geometry()
            # --- 修改结束 ---
            click_pos = event.pos()
            is_on_scrollbar = geom_scrollbar.contains(click_pos)
            is_on_message = geom_message.contains(click_pos)
            if is_on_scrollbar or is_on_message:
                super().mousePressEvent(event)
                return
            is_on_content = geom_content.contains(click_pos)
            if is_on_content:
                if self.is_sticky: super().mousePressEvent(event)
                else: self.slide_out()
                return
            if not self.is_sticky: self.slide_out()
            return
        super().mousePressEvent(event)

    def get_current_screen_geometry(self):
        return (QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()).availableGeometry()

    def start_lifecycle(self):
        self.lifecycle_timer = QTimer(self); self.lifecycle_timer.setSingleShot(True)
        self.lifecycle_timer.timeout.connect(self.slide_out)
        if not self.is_sticky:
            self.lifecycle_start_time = QTime.currentTime(); self.lifecycle_timer.start(self.lifecycle_remaining)

    def toggle_sticky_mode(self):
        self.is_sticky = not self.is_sticky
        if self.is_sticky: self.activate_sticky_mode()
        else: self.deactivate_sticky_mode()

    # --- MODIFIED: v4.7.0 (激活置顶模式 = 加载 QTextEdit) ---
    def activate_sticky_mode(self):
        if self.lifecycle_timer.isActive():
            self.lifecycle_timer.stop(); self.lifecycle_remaining = max(0, self.lifecycle_remaining - self.lifecycle_start_time.msecsTo(QTime.currentTime()))
        self.border_thickness = 2; self.border_animation_timer.start(51)

        # 切换控件可见性
        self.top_content_label.hide()
        self.top_content_edit.show()

        # 加载完整内容到 QTextEdit
        if self.full_text_to_load is not None:
            self.top_content_edit.setPlainText("●")
            self.text_load_timer = QTimer(self); self.text_load_timer.setSingleShot(True)
            self.text_load_timer.timeout.connect(self.load_full_text); self.text_load_timer.start(10)
        else:
            self.top_content_edit.setPlainText(self.original_data.get("top_text"))
            QTimer.singleShot(0, self.update_overlay_scrollbar)

        # 设置 QTextEdit 属性
        self.top_content_edit.setReadOnly(False); self.top_content_edit.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.top_content_edit.horizontalScrollBar().setRange(0, 0); self.top_content_edit.setMaximumHeight(10000)
        self.top_content_edit.verticalScrollBar().setValue(0)
        self.top_content_edit.textChanged.connect(self.update_overlay_scrollbar)
        self.top_content_edit.setFocus(Qt.MouseFocusReason)
        self.update()
    # --- 修改结束 ---

    # --- MODIFIED: v4.7.0 (取消置顶 = 切回 QLabel 并释放资源) ---
    def deactivate_sticky_mode(self):
        if self.lifecycle_remaining > 0: self.start_lifecycle()
        self.border_animation_timer.stop(); self.border_dash_offset = 0; self.border_thickness = 1

        # 清空并隐藏 QTextEdit
        try: self.top_content_edit.textChanged.disconnect(self.update_overlay_scrollbar)
        except (TypeError, RuntimeError): pass
        self.top_content_edit.setPlainText("") # 释放内存
        cursor = self.top_content_edit.textCursor(); cursor.clearSelection(); self.top_content_edit.setTextCursor(cursor)
        self.top_content_edit.setReadOnly(True); self.top_content_edit.setTextInteractionFlags(Qt.NoTextInteraction)
        self.top_content_edit.setMaximumHeight(162)
        self.top_content_edit.hide()

        # 隐藏滚动条并显示 QLabel
        self.overlay_scrollbar.hide(); self.disconnect_scrollbar_signals()
        self.top_content_label.show()

        self.update()
    # --- 修改结束 ---

    def animate_border(self):
        self.border_dash_offset = (self.border_dash_offset - 1) % -10; self.update()

    def slide_out(self):
        for timer in [self.lifecycle_timer, self.border_animation_timer, getattr(self, 'text_load_timer', None)]:
            if timer: timer.stop()
        if hasattr(self, 'is_sliding_out') and self.is_sliding_out: return
        self.is_sliding_out = True
        anim_group = QParallelAnimationGroup(self)
        opacity_anim = QPropertyAnimation(self, b"windowOpacity"); opacity_anim.setDuration(self.SLIDE_OUT_DURATION); opacity_anim.setEndValue(0.0)
        pos_anim = QPropertyAnimation(self, b"pos"); pos_anim.setDuration(self.SLIDE_OUT_DURATION); pos_anim.setEndValue(QPoint(self.x() - 80, self.y()))
        anim_group.addAnimation(opacity_anim); anim_group.addAnimation(pos_anim)
        anim_group.finished.connect(lambda: self.monitor.close_popup(self))
        anim_group.start(QAbstractAnimation.DeleteWhenStopped); self.anim_group = anim_group

    def move_to_initial_position(self):
        self.move(self.target_screen_geom.right(), self.target_screen_geom.bottom() - self.height() - 40)

    def slide_in(self):
        end_pos = QPoint(self.target_screen_geom.right() - self.width() - 40, self.y())
        slide_anim = QPropertyAnimation(self, b"pos"); slide_anim.setDuration(self.SLIDE_IN_DURATION)
        slide_anim.setEndValue(end_pos); slide_anim.start(QPropertyAnimation.DeleteWhenStopped); self.slide_anim = slide_anim

    def update_bottom_text(self, text):
        self.bottom_message_label.setText(text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        split_y = self.bottom_message_label.y()
        top_rect = QRect(0, 0, self.width(), split_y)
        painter.fillRect(top_rect, self.background_color)
        bottom_rect = QRect(0, split_y, self.width(), self.height() - split_y)
        painter.fillRect(bottom_rect, self.bottom_background_color)
        pen = QPen(self.border_color, self.border_thickness, Qt.DashLine)
        if self.is_sticky:
            pen.setDashOffset(self.border_dash_offset)
        painter.setPen(pen)
        adj = self.border_thickness / 2.0
        draw_rect = self.rect().adjusted(int(adj), int(adj), -int(adj), -int(adj))
        painter.drawRect(draw_rect)


if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling); QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = ClipboardMonitor(sys.argv)
    print("="*20 + " 系统可用字体家族名列表 " + "="*20)
    db = QFontDatabase(); print(sorted(list(set(QFont(name).family() for name in db.families()))))
    print("="*63)
    signal.signal(signal.SIGINT, lambda sig, frame: QApplication.quit())
    timer = QTimer(); timer.start(50); timer.timeout.connect(lambda: None)
    sys.exit(app.exec_())
