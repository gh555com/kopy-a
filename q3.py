# q4.py (v4.5.30 - 文本条件加载 + 滚动条精准跳转 v7)
# -*- coding: utf-8 -*-
"""
一个剪贴板监控工具，当有新内容被复制时，会在屏幕右下角显示一个无干扰的弹窗。

v4.5.30 版本特性 (基于 v4.5.29):
- 【Bug 6 修复】文本加载优化 (v1) - 感谢用户的绝妙建议
  - 问题: v4.5.22 的 QTimer 延迟加载，解决了大文本的卡顿，
    但也导致了小文本（如 "Hello"）会先显示 "●" 再显示 "Hello"，
    降低了小文本的感知效能。
  - 根源: 对所有文本“一刀切”地使用延迟加载。
  - 解决方案: "条件加载"
    1. 在 `process_clipboard_data` 中，将 `byte_size` 存入
       返回的 data 字典。
    2. 在 `TransparentPopup` 中，设置一个阈值
       (TEXT_LOAD_THRESHOLD_BYTES = 100KB)。
    3. 如果 `byte_size < 100KB`，则在 `setup_ui` 中立即
       加载文本 (v4.5.21 的完美体验)。
    4. 如果 `byte_size >= 100KB`，才使用 QTimer 延迟
       加载 (v4.5.22 的高响应体验)。
    - 这结合了两个版本的优点，解决了效能权衡问题。

- 【Bug 7 修复】滚动条 Bug 最终修复 (v7) - “指哪打哪”
  - 问题: v4.5.29 修复了滚动条的“点击不到”问题，但用户
    反馈 v4.5.26 的跳转逻辑“点击不准”，不能“指哪打哪”。
  - 根源: v4.5.26 的逻辑试图将“滑块中心”对齐到“点击点”
    (这是 QSlider 的逻辑)，而不是按比例跳转。
  - 解决方案: 在 `ClickJumpScrollBar.mouseReleaseEvent` 中，
    重写计算逻辑。
    1. 获取轨道(Groove)的矩形 `track_rect`。
    2. 计算点击位置在轨道内的相对比例 (例如 70%)。
    3. `new_value = minimum + ratio * (maximum - minimum)`。
    - 这实现了精准的“按比例跳转”。
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


# --- v4.5.19 (无改动): 一个干净的 QTextEdit 子类 ---
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


# --- MODIFIED: v4.5.30 - 滚动条精准跳转 (v7) ---
class ClickJumpScrollBar(QScrollBar):
    """
    v4.5.30: 滚动条 Bug 最终修复 (v7) - “指哪打哪”

    v4.5.26 (v4) 的逻辑：能点击，但“点击不准”。
    v4.5.30 (v7) 的逻辑：重写计算方法，实现“按比例精准跳转”。

    mousePressEvent 和 mouseReleaseEvent 的“单击/拖动”
    检测逻辑 (v4.5.26) 保持不变，因为它是健壮的。

    只修改 mouseReleaseEvent 中第 4 步的计算逻辑。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.press_pos = QPoint()
        self.press_value = 0

    def mousePressEvent(self, event):
        # 1. 只记录状态 (v4.5.26 逻辑，保持不变)
        if event.button() == Qt.LeftButton:
            self.press_pos = event.pos()
            self.press_value = self.value()

        # 2. 立即、无条件地交给父类处理 (v4.5.26 逻辑，保持不变)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        # 1. 立即交给父类处理 (v4.5.26 逻辑，保持不变)
        super().mouseReleaseEvent(event)

        if event.button() != Qt.LeftButton:
            return

        # 2. 检查这是不是一个“单纯的单击” (v4.5.26 逻辑，保持不变)
        moved = (event.pos() - self.press_pos).manhattanLength() > QApplication.startDragDistance()
        value_changed = (self.value() != self.press_value)

        if moved or value_changed:
            self.press_pos = QPoint()
            return

        # 3. 如果代码执行到这里，说明这是一个“单击” (v4.5.26 逻辑，保持不变)
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)

        handle_rect = self.style().subControlRect(QStyle.CC_ScrollBar, opt, QStyle.SC_ScrollBarSlider, self)
        add_line_rect = self.style().subControlRect(QStyle.CC_ScrollBar, opt, QStyle.SC_ScrollBarAddLine, self)
        sub_line_rect = self.style().subControlRect(QStyle.CC_ScrollBar, opt, QStyle.SC_ScrollBarSubLine, self)

        if handle_rect.contains(self.press_pos) or \
           add_line_rect.contains(self.press_pos) or \
           sub_line_rect.contains(self.press_pos):
            return # 单击在滑块或箭头上

        # 4. 如果代码执行到这里，说明这是在“轨道空白处”的“单击”

        # --- MODIFIED: v4.5.30 修复 Bug 7 (滚动条“指哪打哪”) ---

        # 获取轨道 (groove) 的矩形，这是我们计算比例的基准
        track_rect = self.style().subControlRect(QStyle.CC_ScrollBar, opt, QStyle.SC_ScrollBarGroove, self)

        if not track_rect.isValid() or track_rect.isEmpty():
            return # 没有有效的轨道

        if self.orientation() == Qt.Vertical:
            if track_rect.height() == 0: return
            # 点击位置 Y 相对于轨道顶部的距离
            relative_y = self.press_pos.y() - track_rect.top()
            # 点击位置 Y 占轨道总高度的比例
            ratio = relative_y / track_rect.height()
        else: # 水平方向
            if track_rect.width() == 0: return
            # 点击位置 X 相对于轨道左侧的距离
            relative_x = self.press_pos.x() - track_rect.left()
            # 点击位置 X 占轨道总宽度的比例
            ratio = relative_x / track_rect.width()

        # 钳制比例在 0.0 到 1.0
        ratio = max(0.0, min(1.0, ratio))

        # 根据比例计算新的 value
        new_value = self.minimum() + ratio * (self.maximum() - self.minimum())
        self.setValue(int(new_value))
        # --- 修复结束 ---

        # 重置 (v4.5.26 逻辑，保持不变)
        self.press_pos = QPoint()


class ClipboardMonitor(QApplication):
    """
    主应用程序类
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

    # --- MODIFIED: v4.5.30 - 传递 byte_size ---
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

                # --- MODIFIED: v4.5.30 修复 Bug 6 ---
                # 将 byte_size 传递给 TransparentPopup 以进行条件加载
                return {"type": "text",
                        "top_text": text,
                        "bottom_text": f"{self.format_size(byte_size)}",
                        "byte_size": byte_size} # <-- 新增
                # --- 修复结束 ---

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

    # --- v4.5.27 (无改动): 修复音效 Bug ---
    def on_clipboard_changed(self):
        if self.is_on_cooldown: return
        mime_data = self.clipboard().mimeData()
        data = self.process_clipboard_data(mime_data)
        if not data: return

        self.play_random_sound()

        if any(p.is_sticky for p in self.active_popups):
            self.set_cooldown()
            return

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
            try:
                anim = getattr(popup, anim_name, None)
                if anim and anim.state() == QPropertyAnimation.Running:
                    anim.stop()
            except RuntimeError:
                pass

        for timer_name in ['lifecycle_timer', 'border_animation_timer', 'text_load_timer']:
            timer = getattr(popup, timer_name, None)
            if timer:
                timer.stop()

        popup.disconnect_scrollbar_signals()
        popup.close()

    def __del__(self):
        if hasattr(self, 'executor'): self.executor.shutdown(wait=True)


# --- MODIFIED: v4.5.30 - 文本条件加载 ---
class TransparentPopup(QWidget):
    SLIDE_IN_DURATION, SLIDE_OUT_DURATION, LIFECYCLE_SECONDS = 88, 88, 19
    SCROLLBAR_WIDTH, SCROLLBAR_MARGIN_RIGHT = 11, 2

    # --- v4.5.30 修复 Bug 6 ---
    # 设置一个阈值，例如 100 KB
    TEXT_LOAD_THRESHOLD_BYTES = 100 * 1024

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

        self.full_text_to_load = None
        self.text_load_timer = None

        # --- MODIFIED: v4.5.30 修复 Bug 6 (文本条件加载) ---
        if self.original_data.get("type") == "text":
            text_size = self.original_data.get("byte_size", 0)

            # 只有当文本大于阈值时，才启用延迟加载
            if text_size >= self.TEXT_LOAD_THRESHOLD_BYTES:
                self.full_text_to_load = self.original_data.get("top_text", "")
            else:
                # 小文本：self.full_text_to_load 保持为 None
                # setup_ui 将会立即加载它
                pass
        # --- 修复结束 ---

        self.border_animation_timer = QTimer(self); self.border_animation_timer.timeout.connect(self.animate_border)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(222, 222)

        # v4.5.30: 使用 v7 版的滚动条
        self.overlay_scrollbar = ClickJumpScrollBar(self)
        self.overlay_scrollbar.setOrientation(Qt.Vertical); self.overlay_scrollbar.hide()
        self.is_scrollbar_connected = False

        self.setup_ui() # setup_ui 现在会根据 self.full_text_to_load 的状态来决定如何加载
        self.setup_colors_and_styles()

        self.target_screen_geom = self.get_current_screen_geometry()
        self.move_to_initial_position()
        self.show()
        self.slide_in()
        self.start_lifecycle()

        # 仅当 self.full_text_to_load 不是 None (即大文本) 时，才启动定时器
        if self.full_text_to_load is not None:
            self.text_load_timer = QTimer(self)
            self.text_load_timer.setSingleShot(True)
            self.text_load_timer.timeout.connect(self.load_full_text)
            self.text_load_timer.start(self.SLIDE_IN_DURATION + 10)

        # v4.5.29 (无改动): 堆叠顺序修复，必须保留
        self.overlay_scrollbar.raise_()

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

    # --- MODIFIED: v4.5.30 - 文本条件加载 ---
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10); layout.setSpacing(10)
        font = QFont("Consolas", 11); font.setFamilies(["Consolas", "monospace", "LXGW WenKai GB Screen", "SF Pro", "Segoe UI", "Aptos", "Roboto", "Arial"])

        self.top_content = StickyTextEdit(self); self.top_content.popup = self

        # --- MODIFIED: v4.5.30 修复 Bug 6 ---
        # 检查 self.full_text_to_load 是否在 __init__ 中被设置
        if self.full_text_to_load is not None:
            # 是大文本：显示占位符 "●"
            self.top_content.setText("●")
        else:
            # 是小文本 (或非文本)：立即加载真实内容
            self.top_content.setText(self.original_data.get("top_text"))
        # --- 修复结束 ---

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

    # v4.5.22 文本异步加载逻辑 (无改动)
    # (这个函数现在只会在 __init__ 判定为大文本时才会被调用)
    def load_full_text(self):
        if self.full_text_to_load is None: return

        try:
            self.top_content.setText(self.full_text_to_load)
            self.full_text_to_load = None

            if self.is_sticky:
                QTimer.singleShot(0, self.update_overlay_scrollbar)

        except RuntimeError:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        widget_geom = self.top_content.geometry()
        x = widget_geom.right() - self.SCROLLBAR_WIDTH - self.SCROLLBAR_MARGIN_RIGHT
        y, height = widget_geom.top(), widget_geom.height()
        self.overlay_scrollbar.setGeometry(int(x), int(y), int(self.SCROLLBAR_WIDTH), int(height))

    def update_overlay_scrollbar(self):
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

    # --- v4.5.28 (无改动): 修复滚动条点击拦截 Bug ---
    # 这个逻辑是正确的，它依赖 v4.5.29 的堆叠顺序修复
    # 和 v4.5.30 的滚动条逻辑修复
    def mousePressEvent(self, event):
        child_rects = []
        if self.overlay_scrollbar.isVisible():
            child_rects.append(self.overlay_scrollbar.geometry())

        child_rects.append(self.top_content.geometry())
        child_rects.append(self.bottom_message_label.geometry())

        is_on_child = False
        for rect in child_rects:
            if rect.contains(event.pos()):
                is_on_child = True
                break

        if is_on_child:
            super().mousePressEvent(event)
        else:
            if event.button() == Qt.LeftButton and not self.is_sticky:
                self.slide_out()
            else:
                super().mousePressEvent(event)

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

    def activate_sticky_mode(self):
        if self.lifecycle_timer.isActive():
            self.lifecycle_timer.stop()
            self.lifecycle_remaining = max(0, self.lifecycle_remaining - self.lifecycle_start_time.msecsTo(QTime.currentTime()))

        self.border_thickness = 2; self.border_animation_timer.start(51)

        self.top_content.setReadOnly(False)
        self.top_content.setTextInteractionFlags(Qt.TextEditorInteraction)

        self.top_content.horizontalScrollBar().setRange(0, 0)

        self.top_content.setMaximumHeight(10000)

        # v4.5.30 (无改动):
        # 如果 full_text_to_load 存在 (意味着是大文本且还没加载完)
        # 那么我们什么都不做，等待 load_full_text 完成。
        # 如果它为 None (小文本，或大文本已加载完)，我们才更新滚动条
        if self.full_text_to_load is None:
            self.top_content.verticalScrollBar().setValue(0)
            QTimer.singleShot(0, self.update_overlay_scrollbar)
            self.top_content.textChanged.connect(self.update_overlay_scrollbar)

        self.top_content.setFocus(Qt.MouseFocusReason)
        self.update()

    def deactivate_sticky_mode(self):
        if self.lifecycle_remaining > 0: self.start_lifecycle()
        self.border_animation_timer.stop(); self.border_dash_offset = 0; self.border_thickness = 1

        self.top_content.setReadOnly(True)
        self.top_content.setTextInteractionFlags(Qt.NoTextInteraction)

        self.top_content.setMaximumHeight(162)
        cursor = self.top_content.textCursor(); cursor.clearSelection(); self.top_content.setTextCursor(cursor)

        # --- MODIFIED: v4.5.30 修复 Bug 6 ---
        # 这里的逻辑也需要同步
        if self.full_text_to_load is not None:
            # 如果是一个大文本，并且它还没有被加载
            # (例如：复制 -> sticky -> 立即 unsticky)
            # 我们就重置为 "●"
            self.top_content.setText("●")
        else:
            # 否则 (小文本，或已加载的大文本)，重置为原始文本
            self.top_content.setText(self.original_data.get("top_text"))
        # --- 修复结束 ---

        self.overlay_scrollbar.hide()
        self.disconnect_scrollbar_signals()
        try:
            self.top_content.textChanged.disconnect(self.update_overlay_scrollbar)
        except (TypeError, RuntimeError): pass
        self.update()

    def animate_border(self):
        self.border_dash_offset = (self.border_dash_offset - 1) % -10; self.update()

    def slide_out(self):
        for timer in [self.lifecycle_timer, self.border_animation_timer, getattr(self, 'text_load_timer', None)]:
            if timer:
                timer.stop()

        if hasattr(self, 'is_sliding_out') and self.is_sliding_out: return
        self.is_sliding_out = True

        anim_group = QParallelAnimationGroup(self)
        opacity_anim = QPropertyAnimation(self, b"windowOpacity"); opacity_anim.setDuration(self.SLIDE_OUT_DURATION); opacity_anim.setEndValue(0.0)
        pos_anim = QPropertyAnimation(self, b"pos"); pos_anim.setDuration(self.SLIDE_OUT_DURATION); pos_anim.setEndValue(QPoint(self.x() - 80, self.y()))
        anim_group.addAnimation(opacity_anim); anim_group.addAnimation(pos_anim)
        anim_group.finished.connect(lambda: self.monitor.close_popup(self))
        anim_group.start(QAbstractAnimation.DeleteWhenStopped)
        self.anim_group = anim_group

    def move_to_initial_position(self):
        self.move(self.target_screen_geom.right(), self.target_screen_geom.bottom() - self.height() - 40)

    def slide_in(self):
        end_pos = QPoint(self.target_screen_geom.right() - self.width() - 40, self.y())
        slide_anim = QPropertyAnimation(self, b"pos"); slide_anim.setDuration(self.SLIDE_IN_DURATION)
        slide_anim.setEndValue(end_pos); slide_anim.start(QPropertyAnimation.DeleteWhenStopped)
        self.slide_anim = slide_anim

    def update_bottom_text(self, text):
        self.bottom_message_label.setText(text)

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.background_color)
        pen = QPen(self.border_color, self.border_thickness, Qt.DashLine)
        if self.is_sticky: pen.setDashOffset(self.border_dash_offset)
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
