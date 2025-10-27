# q3.py (v4.9.33 - "The Miniaudio V15 Multi-Thread Engine")
# -*- coding: utf-8 -*-
"""
v4.9.33 版本特性:
- 【完全替换音频引擎】: 使用基于q2.py v15逻辑的miniaudio多线程非阻塞音频引擎
- 【移除pygame依赖】: 完全移除pygame相关代码，使用纯miniaudio实现
- 【多线程并发】: 基于q1.py的多线程实现，支持多个音效同时播放
- 【无延迟播放】: 使用miniaudio直接播放，实现0延迟音效反馈
- 【资源管理】: 自动管理音频资源，避免内存泄漏
"""
import sys
import os
import signal
import concurrent.futures
import random
import glob
import inspect

# --- (v4.9.33) 核心改动：导入 miniaudio_nonblocking_v15 ---
try:
    from miniaudio_nonblocking_v15 import NonBlockingAudioEngine
except ImportError:
    print("="*60)
    print("【!!】 错误：未找到 miniaudio_nonblocking_v15 库。")
    print("【!!】 v4.9.33 需要 miniaudio_nonblocking_v15 引擎才能实现 0 延迟音效。")
    print("【!!】 请先在您的环境中安装 miniaudio_nonblocking_v15 模块。")
    print("="*60)
    sys.exit(1)
# --- (v4.9.33) 结束 ---

from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout,
                             QTextEdit, QScrollBar, QStyleOptionSlider, QStyle, QPushButton)
from PyQt5.QtCore import (Qt, QTimer, QPoint, QPropertyAnimation, pyqtSignal, QBuffer,
                          QIODevice, QParallelAnimationGroup, QAbstractAnimation, QEasingCurve, QUrl,
                          QEvent, QTime, QRect)
# --- (v4.9.33) 核心改动：不再需要 QSoundEffect ---
# from PyQt5.QtMultimedia import QSoundEffect  <-- 已移除
from PyQt5.QtGui import (QFont, QPainter, QColor, QPen, QFontDatabase, QCursor,
                         QTextOption, QTextCursor, QKeySequence, QPalette, QPixmap, QImage)


# --- (v4.9.30 - 无改动) ---
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
# --- (v4.9.30 - 无改动) ---


# --- (v4.9.30 - 无改动) ---
class StickyTextEdit(QTextEdit):
    internal_copy_triggered = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.popup = None; self.setAcceptDrops(True)
    def insertFromMimeData(self, source):
        if source.hasText():
            text = source.text();
            if text: self.textCursor().insertText(text)
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            if self.popup and self.popup.is_sticky and self.textCursor().hasSelection():
                self.internal_copy_triggered.emit()
                self.popup.monitor.set_cooldown()
        super().keyPressEvent(event)
    def mousePressEvent(self, event):
        if self.popup and self.popup.is_sticky: self.setCursorWidth(1)
        super().mousePressEvent(event)
# --- (v4.9.30 - 无改动) ---


# --- (v4.9.30 - 无改动) ---
class ClickJumpScrollBar(QScrollBar):
    def __init__(self, parent=None):
        super().__init__(parent); self.press_pos = QPoint()
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            self.press_pos = QPoint(); super().mousePressEvent(event); return
        opt = QStyleOptionSlider(); self.initStyleOption(opt)
        handle_rect = self.style().subControlRect(QStyle.CC_ScrollBar, opt, QStyle.SC_ScrollBarSlider, self)
        if handle_rect.contains(event.pos()):
            self.press_pos = QPoint(); super().mousePressEvent(event)
        else: self.press_pos = event.pos()
    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self.press_pos.isNull():
            super().mouseReleaseEvent(event); return
        moved = (event.pos() - self.press_pos).manhattanLength() > QApplication.startDragDistance()
        click_pos = self.press_pos; self.press_pos = QPoint()
        if moved: super().mouseReleaseEvent(event); return
        opt = QStyleOptionSlider(); self.initStyleOption(opt)
        handle_rect = self.style().subControlRect(QStyle.CC_ScrollBar, opt, QStyle.SC_ScrollBarSlider, self)
        track_rect = self.style().subControlRect(QStyle.CC_ScrollBar, opt, QStyle.SC_ScrollBarGroove, self)
        if not track_rect.isValid() or track_rect.isEmpty():
            super().mouseReleaseEvent(event); return
        if self.orientation() == Qt.Vertical:
            movable_range = track_rect.height() - handle_rect.height()
            if movable_range <= 0: super().mouseReleaseEvent(event); return
            ratio = (click_pos.y() - track_rect.top() - handle_rect.height() / 2.0) / movable_range
        else:
            movable_range = track_rect.width() - handle_rect.width()
            if movable_range <= 0: super().mouseReleaseEvent(event); return
            ratio = (click_pos.x() - track_rect.left() - handle_rect.width() / 2.0) / movable_range
        ratio = max(0.0, min(1.0, ratio)); new_value = self.minimum() + round(ratio * (self.maximum() - self.minimum()))
        self.setValue(int(new_value)); super().mouseReleaseEvent(event)
# --- (v4.9.30 - 无改动) ---


# --- ClipboardMonitor (已修改 v4.9.32) ---
class ClipboardMonitor(QApplication):
    calculation_done = pyqtSignal(str, QWidget)
    COLOR_SCHEME_MODE = 4; current_color_mode = 0; COOLDOWN_TIME_MS = 100
    def __init__(self, argv):
        super().__init__(argv)

        # --- (v4.9.33) 初始化基于v15逻辑的多线程非阻塞音频引擎 ---
        try:
            self.audio_engine = NonBlockingAudioEngine()
        except Exception as e:
            pass
        # --- (v4.9.33) 结束 ---

        self.active_popups = []; self.is_on_cooldown = False
        # calculation_done信号已经在类定义中声明，不需要重新定义
        self.calculation_done.connect(self.on_calculation_finished)

        try:
            self.setup_clipboard_monitor()
        except Exception as e:
            pass

        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 8)
        self.last_played_sound = None; self.last_played_q_sound = None; self.last_played_z_sound = None

        # (v4.9.33) 现在这个函数将使用基于v15逻辑的miniaudio音频引擎
        try:
            self.setup_sound_files()
        except Exception as e:
            pass

    # --- (v4.9.33) 核心改动：重写音效加载 ---
    def setup_sound_files(self):
        """使用基于v15逻辑的NonBlockingAudioEngine加载所有音效"""
        # NonBlockingAudioEngine 已经在初始化时加载了所有音效文件
        # 这里不需要额外操作，只是打印加载状态
        print(f"成功预加载 {len(self.audio_engine.main_sounds)} 个原有音效 (miniaudio v15)。")
        print(f"成功预加载 {len(self.audio_engine.q_sounds)} 个 q 系列音效 (miniaudio v15)。")
        print(f"成功预加载 {len(self.audio_engine.z_sounds)} 个 z 系列音效 (miniaudio v15)。")
    # --- (v4.9.33) 结束 ---

    # --- (v4.9.33) 核心改动：重写音效播放 ---
    def play_random_sound(self):
        """使用基于v15逻辑的NonBlockingAudioEngine播放随机主音效"""
        self.audio_engine.play_random_sound()

    def play_q_sound(self):
        """使用基于v15逻辑的NonBlockingAudioEngine播放随机q音效"""
        self.audio_engine.play_q_sound()

    def play_z_sound(self):
        """使用基于v15逻辑的NonBlockingAudioEngine播放随机z音效"""
        self.audio_engine.play_z_sound()
    # --- (v4.9.33) 结结 ---

    # (v4.9.30 - 无改动)
    def setup_clipboard_monitor(self):
        self.clipboard().dataChanged.connect(self.on_clipboard_changed)
    def process_clipboard_data(self, mime_data):
        all_formats = mime_data.formats()
        if mime_data.hasUrls():
            urls = mime_data.urls();
            if not urls: return None
            local_paths = [url.toLocalFile() for url in urls if url.isLocalFile() and os.path.exists(url.toLocalFile())]
            if not local_paths:
                remote_urls = [url for url in urls if not url.isLocalFile()]
                if remote_urls:
                    top_text = f"复制了 {len(remote_urls)} 个 URL"
                    bottom_text = remote_urls[0].toString()[:50] + ("..." if len(remote_urls[0].toString()) > 50 else "")
                    return {"type": "other", "top_text": top_text, "bottom_text": bottom_text, "top_text_snippet": top_text}
                return None
            count, num_files, num_folders = len(local_paths), sum(1 for p in local_paths if os.path.isfile(p)), sum(1 for p in local_paths if os.path.isdir(p))
            top_text = "\n".join([os.path.basename(p) for p in local_paths])
            if count == 1: bottom_template = "文件夹: {}" if num_folders == 1 else "文件: {}"
            else: bottom_template = f"{count} 个项目: {{}}" if num_files and num_folders else (f"{count} 个文件夹: {{}}" if num_folders else f"{count} 个文件: {{}}")
            return {"type": "file", "full_text": top_text, "bottom_template": bottom_template, "paths": local_paths}
        if mime_data.hasImage():
            pixmap = self.clipboard().pixmap()
            if not pixmap.isNull():
                buffer = QBuffer(); buffer.open(QIODevice.WriteOnly); pixmap.save(buffer, "PNG"); img_text = f"{pixmap.width()}×{pixmap.height()}"
                return {"type": "image", "top_text": img_text, "top_text_snippet": img_text, "bottom_text": f"截图: {self.format_size(len(buffer.data()))}"}
        image = self.clipboard().image()
        if not image.isNull():
            pixmap = QPixmap.fromImage(image); buffer = QBuffer(); buffer.open(QIODevice.WriteOnly); pixmap.save(buffer, "PNG")
            img_text = f"{pixmap.width()}×{pixmap.height()}"
            return {"type": "image", "top_text": img_text, "top_text_snippet": img_text, "bottom_text": f"截图: {self.format_size(len(buffer.data()))}"}
        image_data = mime_data.data('image/png') if 'image/png' in all_formats else b''
        if len(image_data) > 0:
            try:
                img = QImage.fromData(image_data, "PNG")
                if not img.isNull():
                    pixmap = QPixmap.fromImage(img); img_text = f"{pixmap.width()}×{pixmap.height()}"; bottom_text = f"截图: {self.format_size(len(image_data))}"
                else: img_text = "未知尺寸"; bottom_text = f"截图: {self.format_size(len(image_data))}"
                return {"type": "image", "top_text": img_text, "top_text_snippet": img_text, "bottom_text": bottom_text}
            except Exception as e:
                pass
        if mime_data.hasText():
            text = mime_data.text()
            if not text: return {"type": "text", "full_text": "", "bottom_text": self.format_size(0)}
            try: data_size = mime_data.data('text/plain').size()
            except Exception: data_size = len(text.encode('utf-8', 'replace'))
            bottom_text = self.format_size(data_size)
            return {"type": "text", "full_text": text, "bottom_text": bottom_text}
        if all_formats:
            filtered_formats = [f for f in all_formats if not f.startswith('application/x-qt-') and f not in ('text/plain', 'text/uri-list')]
            primary_type = filtered_formats[0] if filtered_formats else all_formats[0]
            if primary_type:
                if primary_type.startswith('application/x-qt-'): return None
                data_size = mime_data.data(primary_type).size(); unknown_text = f"未知内容，类型: {primary_type}"
                return {"type": "other", "top_text": unknown_text, "top_text_snippet": unknown_text, "bottom_text": self.format_size(data_size)}
        return {"type": "clear", "top_text": "剪贴板已清空", "top_text_snippet": "剪贴板已清空", "bottom_text": " "}
    # (v4.9.30 - 无改动)
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
        kb = size_bytes / 1024.0
        if kb < 1024: return f"{round(kb)} K"
        mb = kb / 1024.0; return f"{round(mb)} M"
    def set_cooldown(self):
        self.is_on_cooldown = True
        QTimer.singleShot(self.COOLDOWN_TIME_MS, lambda: setattr(self, 'is_on_cooldown', False))
    # (v4.9.30 - 无改动)
    def on_clipboard_changed(self):
        if self.is_on_cooldown:
            return
        try:
            mime_data = self.clipboard().mimeData()
        except Exception as e:
            return
        if not mime_data:
            return
        data = self.process_clipboard_data(mime_data)
        if not data:
            return

        # (v4.9.33) - 立即播放音效，不等待界面切换
        # 直接调用音频引擎，不使用QTimer.singleShot避免额外延迟
        self.play_random_sound()

        sticky_popups = [p for p in self.active_popups if p.is_sticky]
        if sticky_popups:
            self.set_cooldown(); return
        stationary_popup = next((p for p in reversed(self.active_popups) if not p.is_sticky and not getattr(p, 'is_sliding_out', False)), None)
        if stationary_popup:
            stationary_popup.slide_out()
        if self.COLOR_SCHEME_MODE in (3, 4): self.current_color_mode = 1 - self.current_color_mode
        elif self.COLOR_SCHEME_MODE == 2: self.current_color_mode = 1
        else: self.current_color_mode = 0
        new_popup = TransparentPopup(data, self, self.current_color_mode, self.COLOR_SCHEME_MODE)
        new_popup.raise_(); self.active_popups.append(new_popup); self.set_cooldown()
        if data.get("type") == "file" and "paths" in data:
            new_popup.update_bottom_text(data["bottom_template"].format("●"))
            self.calculate_total_size_async(data["paths"], new_popup, data["bottom_template"])
    # (v4.9.30 - 无改动)
    def close_popup(self, popup):
        if popup in self.active_popups: self.active_popups.remove(popup)
        if hasattr(popup, 'anim_group') and popup.anim_group is not None:
            if popup.anim_group.state() == QAbstractAnimation.Running: popup.anim_group.stop()
            popup.anim_group.deleteLater(); popup.anim_group = None
        if hasattr(popup, 'slide_anim') and popup.slide_anim is not None:
            if popup.slide_anim.state() == QAbstractAnimation.Running: popup.slide_anim.stop()
            popup.slide_anim.deleteLater(); popup.slide_anim = None
        for timer_name in ['lifecycle_timer', 'border_animation_timer']:
            timer = getattr(popup, timer_name, None)
            if timer: timer.stop(); timer.deleteLater(); setattr(popup, timer_name, None)
        popup.disconnect_scrollbar_signals(); popup.close()

    # --- (v4.9.33) 核心改动：添加清理 ---
    def __del__(self):
        # 清理基于v15逻辑的多线程非阻塞音频引擎资源
        if hasattr(self, 'audio_engine'):
            self.audio_engine.cleanup()

        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)
    # --- (v4.9.33) 结束 ---
# --- (v4.9.30 - 无改动) ---


# --- TransparentPopup (v4.9.31 逻辑 - 无改动) ---
# 这个类【不需要】知道 pygame 的存在
# 它只需要调用 self.monitor.play_q_sound() 和 self.monitor.play_z_sound()
class TransparentPopup(QWidget):
    SLIDE_IN_DURATION, SLIDE_OUT_DURATION, LIFECYCLE_SECONDS = 88, 88, 119
    SCROLLBAR_WIDTH, SCROLLBAR_MARGIN_RIGHT = 11, 2
    CONTENT_AREA_MAX_HEIGHT, BOTTOM_AREA_MIN_HEIGHT = 162, 30

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

    def get_current_screen_geometry(self):
        return (QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()).availableGeometry()

    def __init__(self, data, monitor, color_mode=0, scheme_mode=4):
        super().__init__()
        self.monitor, self.color_mode, self.scheme_mode = monitor, color_mode, scheme_mode
        self.original_data = data
        self.is_sticky, self.border_thickness, self.border_dash_offset = False, 1, 0

        self.lifecycle_remaining, self.lifecycle_start_time = self.LIFECYCLE_SECONDS * 1000, None
        self.full_text_to_load = self.original_data.get("full_text")
        self.slide_anim = None; self.anim_group = None; self.border_animation_timer = None

        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(222, 222)

        self.overlay_scrollbar = ClickJumpScrollBar(self)
        self.overlay_scrollbar.setOrientation(Qt.Vertical); self.overlay_scrollbar.hide()
        self.is_scrollbar_connected = False

        self.interaction_shield = None
        self.sticky_toggle_task_id = None  # 使用任务ID代替全局锁

        # 初始化生命周期定时器
        self.lifecycle_timer = QTimer(self)
        self.lifecycle_timer.setSingleShot(True)

        # 设置初始位置 - 使用当前屏幕几何信息
        self.target_screen_geom = self.get_current_screen_geometry()

        # 设置UI和样式
        self.setup_ui()
        self.setup_colors_and_styles()

        # 初始化显示
        self.move_to_initial_position()
        self.show()  # 确保弹窗显示
        self.slide_in()
        self.start_lifecycle()

    # (v4.9.30) - 无改动
    def setup_colors_and_styles(self):
        common_bottom_style = "padding-top: 8px;"
        bg_0 = QColor(0, 0, 0, 240); text_0 = Qt.white; border_0 = Qt.white
        gold_0_hex = "#cd853f"; bottom_style_0 = f"color: {gold_0_hex}; {common_bottom_style} background-color: transparent;"
        top_style_0 = "color: #ffffff;"; scroll_handle_0 = "rgba(205, 133, 63, 204)"; highlight_0 = QColor(gold_0_hex)
        bg_1 = QColor(253, 246, 227, 250); border_1 = QColor(55, 45, 15); text_1_qcolor = QColor(3, 2, 1)
        gold_1_hex = "#8B4513"; bottom_style_1 = f"color: {gold_1_hex}; font-weight: bold; {common_bottom_style} background-color: transparent;"
        top_style_1 = f"color: rgb({text_1_qcolor.red()}, {text_1_qcolor.green()}, {text_1_qcolor.blue()});"
        scroll_handle_1 = "rgba(139, 69, 19, 204)"; highlight_1 = QColor(139, 69, 19, 191)
        main_palette_index, bottom_palette_index = (self.color_mode, 1 - self.color_mode) if self.scheme_mode == 4 else (self.color_mode, self.color_mode) if self.scheme_mode == 3 else (1,1) if self.scheme_mode == 2 else (0,0)
        self.background_color, _, self.border_color, top_text_style, self.scrollbar_handle_color, highlight_bg_color = (bg_0, text_0, border_0, top_style_0, scroll_handle_0, highlight_0) if main_palette_index == 0 else (bg_1, text_1_qcolor, border_1, top_style_1, scroll_handle_1, highlight_1)
        self.bottom_background_color, self.bottom_text_style = (bg_0, bottom_style_0) if bottom_palette_index == 0 else (bg_1, bottom_style_1)
        self.bottom_message_label.setStyleSheet(self.bottom_text_style)
        self.top_content.setStyleSheet(f"QTextEdit {{ border: none; background-color: transparent; padding: 0; {top_text_style} }}")
        self.overlay_scrollbar.setStyleSheet(self.OVERLAY_SCROLLBAR_STYLE_SHEET.format(width=self.SCROLLBAR_WIDTH, handle_color=self.scrollbar_handle_color))
        palette = self.top_content.palette(); palette.setColor(QPalette.Highlight, highlight_bg_color); palette.setColor(QPalette.HighlightedText, Qt.white); self.top_content.setPalette(palette)

    # (v4.9.30) - 无改动
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10); layout.setSpacing(10)
        font = QFont("Consolas", 11); font.setFamilies(["Consolas", "monospace", "LXGW WenKai GB Screen", "SF Pro", "Segoe UI", "Aptos", "Roboto", "Arial"])

        self.top_content = StickyTextEdit(self); self.top_content.popup = self
        initial_text = self.full_text_to_load
        if initial_text is None: initial_text = self.original_data.get("top_text_snippet", "")
        self.top_content.setPlainText(initial_text)
        self.top_content.setReadOnly(False)
        self.top_content.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.top_content.textChanged.connect(self.update_overlay_scrollbar)
        self.top_content.setFont(font)
        self.top_content.setWordWrapMode(QTextOption.WrapAnywhere)
        self.top_content.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.top_content.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.top_content.internal_copy_triggered.connect(self.monitor.play_random_sound)
        self.top_content.setCursorWidth(0)
        self.top_content.setMaximumHeight(self.CONTENT_AREA_MAX_HEIGHT)

        self.bottom_message_label = QLabel(self.original_data.get("bottom_text", ""))
        self.bottom_message_label.setFont(font); self.bottom_message_label.setAlignment(Qt.AlignBottom | Qt.AlignLeft);
        self.bottom_message_label.setMinimumHeight(self.BOTTOM_AREA_MIN_HEIGHT)

        layout.addWidget(self.top_content)
        layout.addWidget(self.bottom_message_label)
        layout.setStretch(0, 1); layout.setStretch(1, 0)

        self.interaction_shield = QWidget(self)
        self.interaction_shield.setStyleSheet("background-color: transparent;")
        self.interaction_shield.setGeometry(self.top_content.geometry())
        self.interaction_shield.installEventFilter(self)
        self.interaction_shield.show()

        # 添加Z区域按钮
        self.z_button = QPushButton("Z", self)
        self.z_button.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 200);
                border: 2px solid #000000;
                font-size: 16px;
                font-weight: bold;
                color: #000000;
            }
            QPushButton:hover {
                background-color: rgba(200, 200, 255, 220);
            }
            QPushButton:pressed {
                background-color: rgba(150, 150, 255, 240);
            }
        """)
        self.z_button.clicked.connect(self.toggle_sticky_mode)
        self.z_button.show()

    def update_scrollbar_geometry(self):
        try:
            x = self.width() - self.SCROLLBAR_WIDTH - self.SCROLLBAR_MARGIN_RIGHT
            y_start = int(self.border_thickness / 2.0)
            y_end = self.bottom_message_label.y()
            height = y_end - y_start
            self.overlay_scrollbar.setGeometry(int(x), int(y_start), int(self.SCROLLBAR_WIDTH), int(height))
        except Exception: pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_scrollbar_geometry()

        if hasattr(self, 'interaction_shield') and self.interaction_shield is not None:
            self.interaction_shield.setGeometry(self.top_content.geometry())

        if hasattr(self, 'bottom_message_label') and self.bottom_message_label is not None:
            split_y = self.bottom_message_label.y()
            z_zone_rect = QRect(0, split_y, self.width(), self.height() - split_y)

            # 设置Z按钮覆盖整个Z区域
            if hasattr(self, 'z_button') and self.z_button is not None:
                self.z_button.setGeometry(
                    z_zone_rect.x(),
                    z_zone_rect.y(),
                    z_zone_rect.width(),
                    z_zone_rect.height()
                )

    def update_overlay_scrollbar(self):
        doc_height = self.top_content.document().size().height()
        viewport_height = self.top_content.height()
        if doc_height > viewport_height and self.is_sticky:
            v_scrollbar = self.top_content.verticalScrollBar()
            self.overlay_scrollbar.setRange(v_scrollbar.minimum(), v_scrollbar.maximum())
            self.overlay_scrollbar.setPageStep(int(viewport_height)); v_scrollbar.setPageStep(int(viewport_height))
            self.overlay_scrollbar.setValue(v_scrollbar.value())
            self.connect_scrollbar_signals(); self.overlay_scrollbar.show()
        else: self.overlay_scrollbar.hide(); self.disconnect_scrollbar_signals()

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
            except (TypeError, RuntimeError): pass
            finally: self.is_scrollbar_connected = False

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:

            # --- Q 区点击逻辑 (内容区) ---
            if obj == self.interaction_shield:
                if not self.is_sticky:
                    # (v4.9.33: 现在调用基于v15逻辑的miniaudio)
                    # 直接调用音频引擎，不使用QTimer.singleShot避免额外延迟
                    self.monitor.play_q_sound()
                    self.slide_out()
                return True

        # --- 滚轮事件 (Q 区) ---
        if obj == self.interaction_shield and event.type() == QEvent.Wheel:
            QApplication.sendEvent(self.top_content.viewport(), event)
            self.top_content.viewport().update()
            return True

        return super().eventFilter(obj, event)

    def play_z_sound_only(self):
        """只播放z音效，不执行任何其他操作"""
        self.monitor.play_z_sound()

    # (v4.9.30 - 无改动)
    def mousePressEvent(self, event): super().mousePressEvent(event)
    def start_lifecycle(self):
        self.lifecycle_timer = QTimer(self); self.lifecycle_timer.setSingleShot(True)
        self.lifecycle_timer.timeout.connect(self.slide_out)
        if not self.is_sticky:
            self.lifecycle_start_time = QTime.currentTime(); self.lifecycle_timer.start(self.lifecycle_remaining)

    # (v4.9.30 - 无改动)
    def toggle_sticky_mode(self):
        # 播放z音效
        self.monitor.play_z_sound()

        # 切换粘滞模式
        self.is_sticky = not self.is_sticky
        if self.is_sticky: self.activate_sticky_mode()
        else: self.deactivate_sticky_mode()

    # (v4.9.30 - 无改动)
    def activate_sticky_mode(self):
        if self.lifecycle_timer.isActive():
            self.lifecycle_timer.stop(); self.lifecycle_remaining = max(0, self.lifecycle_remaining - self.lifecycle_start_time.msecsTo(QTime.currentTime()))
        self.border_thickness = 2
        self.update_scrollbar_geometry()
        if not self.border_animation_timer:
            self.border_animation_timer = QTimer(self)
            self.border_animation_timer.timeout.connect(self.animate_border)
        self.border_animation_timer.start(51)
        self.interaction_shield.hide()
        QTimer.singleShot(0, self.update_overlay_scrollbar)
        self.top_content.setFocus(Qt.MouseFocusReason)
        self.update()

    # (v4.9.31 逻辑 - 保持不变)
    def deactivate_sticky_mode(self):
        saved_v_scroll = self.top_content.verticalScrollBar().value()
        if self.lifecycle_remaining > 0: self.start_lifecycle()
        if self.border_animation_timer and self.border_animation_timer.isActive():
            self.border_animation_timer.stop()
        self.border_dash_offset = 0
        self.border_thickness = 1
        self.update_scrollbar_geometry()
        self.top_content.setCursorWidth(0)
        cursor = self.top_content.textCursor(); cursor.clearSelection(); self.top_content.setTextCursor(cursor)
        self.top_content.clearFocus()
        self.setFocus()
        self.overlay_scrollbar.hide(); self.disconnect_scrollbar_signals()
        self.interaction_shield.show()
        self.interaction_shield.raise_()

        # (v4.9.31) 重置任务ID
        self.sticky_toggle_task_id = None

        QTimer.singleShot(0, lambda: self.top_content.verticalScrollBar().setValue(saved_v_scroll))
        self.update()

    # (v4.9.30 - 无改动)
    def animate_border(self):
        self.border_dash_offset = (self.border_dash_offset - 1) % -10; self.update()

    def slide_out(self):
        for timer in [self.lifecycle_timer, self.border_animation_timer]:
            if timer and timer.isActive(): timer.stop()
        if getattr(self, 'is_sliding_out', False): return
        self.is_sliding_out = True; self.anim_group = QParallelAnimationGroup(self)
        opacity_anim = QPropertyAnimation(self, b"windowOpacity"); opacity_anim.setDuration(self.SLIDE_OUT_DURATION); opacity_anim.setEndValue(0.0)
        pos_anim = QPropertyAnimation(self, b"pos"); pos_anim.setDuration(self.SLIDE_OUT_DURATION); pos_anim.setEndValue(QPoint(self.x() - 80, self.y()))
        self.anim_group.addAnimation(opacity_anim); self.anim_group.addAnimation(pos_anim)
        self.anim_group.finished.connect(lambda: self.monitor.close_popup(self))
        self.anim_group.start()

    def move_to_initial_position(self):
        self.move(self.target_screen_geom.right(), self.target_screen_geom.bottom() - self.height() - 40)

    def slide_in(self):
        end_pos = QPoint(self.target_screen_geom.right() - self.width() - 40, self.y())
        self.slide_anim = QPropertyAnimation(self, b"pos"); self.slide_anim.setDuration(self.SLIDE_IN_DURATION)
        self.slide_anim.setEndValue(end_pos); self.slide_anim.start()

    def update_bottom_text(self, text): self.bottom_message_label.setText(text)
    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        split_y = self.bottom_message_label.y()
        painter.fillRect(QRect(0, 0, self.width(), split_y), self.background_color)
        painter.fillRect(QRect(0, split_y, self.width(), self.height() - split_y), self.bottom_background_color)
        pen = QPen(self.border_color, self.border_thickness, Qt.DashLine)
        if self.is_sticky: pen.setDashOffset(self.border_dash_offset)
        painter.setPen(pen); adj = self.border_thickness / 2.0
        painter.drawRect(self.rect().adjusted(int(adj), int(adj), -int(adj), -int(adj)))
# --- (v4.9.30 - 无改动) ---


# --- (v4.9.30 - 无改动) ---
if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling); QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = ClipboardMonitor(sys.argv)
    signal.signal(signal.SIGINT, lambda sig, frame: QApplication.quit())
    timer = QTimer(); timer.start(500); timer.timeout.connect(lambda: None)
    sys.exit(app.exec_())
