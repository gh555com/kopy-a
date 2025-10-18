# q3.py (v4.5.9 - Pan/Sound/HiDPI Fix)
# -*- coding: utf-8 -*-
"""
一个剪贴板监控工具，当有新内容被复制时，会在屏幕右下角显示一个无干扰的弹窗。

v4.5.9 版本特性 (基于 v4.5.8):
- 【核心修复】禁止画布平移 (新方案):
  - 移除了 v4.5.8 中低效的 mouseMoveEvent 重写 (性能恢复)。
  - 改为在 StickyTextEdit.__init__ 和 activate_sticky_mode 中，
    强制设置 self.horizontalScrollBar().setRange(0, 0)。
  - 这会从根本上阻止 QAbstractScrollArea 响应拖拽到边界的“边缘滚动”
    (Pan) 行为，画布 100% 锁死。
- 【核心修复】双重音效 (新方案):
  - StickyTextEdit.keyPressEvent (Ctrl+C) 在播放音效后，
    会立即调用 self.popup.monitor.set_cooldown() 来设置冷却。
  - ClipboardMonitor.on_clipboard_changed 检查冷却时，会立即返回，
    从而阻止播放第二重音效。
  - 移除了 on_clipboard_changed 中复杂易错的“内部复制”检查逻辑。
- 【UI 修复】分隔线 1 物理像素 (HiDPI Fix):
  - 在 paintEvent 中，绘制分隔线的 QPen 被设为 line_pen.setCosmetic(True)。
  - 这确保了无论屏幕 DPI 缩放比例如何，分隔线始终绘制为 1 物理像素。
"""
import sys
import os
import signal
import concurrent.futures
import random
import glob
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QTextEdit, QScrollBar
from PyQt5.QtCore import (Qt, QTimer, QPoint, QPropertyAnimation, pyqtSignal, QBuffer,
                          QIODevice, QParallelAnimationGroup, QAbstractAnimation, QEasingCurve, QUrl,
                          QEvent, QTime)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtGui import (QFont, QPainter, QColor, QPen, QFontDatabase, QCursor,
                         QTextOption, QTextCursor, QKeySequence)


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


# --- MODIFIED: v4.5.9 - 修复画布平移 & 双重音效 ---
class StickyTextEdit(QTextEdit):
    """
    一个自定义的 QTextEdit，用于在固定模式下正确处理复制音效，
    并修复拖拽选择时画布平移(panning)的 BUG。
    """
    internal_copy_triggered = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.popup = None

        # v4.5.9: 彻底禁止水平滚动，防止画布平移
        # 通过将范围设为 (0,0)，QAbstractScrollArea 认为无内容可滚动，
        # 从而禁用了鼠标拖拽到边缘时的“边缘滚动” (Pan) 行为。
        self.horizontalScrollBar().setRange(0, 0)

    def keyPressEvent(self, event):
        """
        重写按键事件，在 Ctrl+C 发生时立即发出信号，并设置冷却。
        """
        if event.matches(QKeySequence.Copy):
            if self.popup and self.popup.is_sticky and self.textCursor().hasSelection():
                # v4.5.3: 内部复制音效
                self.internal_copy_triggered.emit()
                # v4.5.9: 立即设置冷却，防止 on_clipboard_changed 播放第二声
                self.popup.monitor.set_cooldown()

        # 必须调用父类的方法来完成实际的复制操作
        super().keyPressEvent(event)

    # v4.5.9: 移除了 v4.5.8 中 mouseMoveEvent 的重写，恢复性能
# --- 修改结束 ---


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

    def process_clipboard_data(self, mime_data):
        """
        处理剪贴板数据，为弹窗准备好所有需要显示的部分。
        (v4.4.1, 无改动)
        """
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
                max_display_files = 7
                top_text_lines = [os.path.basename(p) for p in local_paths[:max_display_files]]
                if count > max_display_files: top_text_lines.append(f"... (等 {count - max_display_files} 个)")
                top_text = "\n".join(top_text_lines)
                if num_files > 0 and num_folders > 0: bottom_template = f"{count} 个项目: {{}}"
                elif num_folders > 0: bottom_template = f"{count} 个文件夹: {{}}"
                else: bottom_template = f"{count} 个文件: {{}}"
            return {"type": "file", "top_text": top_text, "bottom_template": bottom_template, "paths": local_paths}
        if mime_data.hasImage():
            pixmap = self.clipboard().pixmap()
            if pixmap.isNull(): return None
            buffer = QBuffer(); buffer.open(QIODevice.WriteOnly); pixmap.save(buffer, "PNG"); byte_size = len(buffer.data())
            return {"type": "image", "top_text": f"{pixmap.width()}×{pixmap.height()}", "bottom_text": f"截图: {self.format_size(byte_size)}"}
        if mime_data.hasText():
            text = mime_data.text()
            if text:
                try: byte_size = len(text.encode('gbk'))
                except UnicodeEncodeError: byte_size = len(text.encode('utf-8', 'replace'))
                return {"type": "text", "top_text": text, "bottom_text": f"{self.format_size(byte_size)}"}
        if all_formats:
            filtered_formats = [f for f in all_formats if not f.startswith('application/x-qt-') and f not in ('text/plain', 'text/plain;charset=utf-8', 'text/uri-list', 'UTF8_STRING', 'COMPOUND_TEXT', 'TEXT', 'STRING', 'image/png')]
            primary_type = filtered_formats[0] if filtered_formats else (all_formats[0] if all_formats else None)
            if primary_type:
                byte_data = mime_data.data(primary_type); data_size = byte_data.size()
                top_text, bottom_text = f"未知内容\n类型: {primary_type}", self.format_size(data_size)
                return {"type": "other", "top_text": top_text, "bottom_text": bottom_text}
        if not all_formats: return {"type": "clear", "top_text": "剪贴板已清空", "bottom_text": " "}
        return None

    def calculate_total_size_async(self, file_paths, popup, template):
        futures = [self.executor.submit(_get_path_size, path) for path in file_paths]
        def aggregate_and_emit_result_on_main_thread(futures_list):
            total_size = sum(future.result() for future in futures_list if future.exception() is None)
            self.calculation_done.emit(template.format(self.format_size(total_size)), popup)
        self.executor.submit(aggregate_and_emit_result_on_main_thread, futures)

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

    # --- v4.5.9: 供 StickyTextEdit 调用的外部冷却设置器 ---
    def set_cooldown(self):
        """v4.5.9: 供 StickyTextEdit 调用的外部冷却设置器。"""
        self.is_on_cooldown = True
        QTimer.singleShot(self.COOLDOWN_TIME_MS, lambda: setattr(self, 'is_on_cooldown', False))
    # --- 添加结束 ---

    # --- MODIFIED: v4.5.9 - 修复双重音效 BUG ---
    def on_clipboard_changed(self):
        if self.is_on_cooldown:
            # v4.5.9: 如果是内部复制 (Ctrl+C)，
            # StickyTextEdit.keyPressEvent 已经设置了冷却，
            # 此处会立即返回，从而阻止了第二重音效。
            return

        # 1. 立即获取并处理数据
        mime_data = self.clipboard().mimeData()
        data = self.process_clipboard_data(mime_data)

        if not data: # 无法处理的数据类型
            return

        is_any_popup_sticky = any(p.is_sticky for p in self.active_popups)

        # 2. 【v4.5.9: 逻辑简化】
        # 移除了 v4.5.6/v4.5.8 中复杂(且易错)的“内部复制”检查。
        # 该逻辑已前移到 StickyTextEdit.keyPressEvent 中。

        # 3. 如果不是内部复制，检查是否需要播放音效（外部复制）
        if data.get("type") != "clear":
            # 只要不是清空，也不是内部复制 (内部复制已在第1步被 return)，
            # 就播放音效。
            self.play_random_sound()

        # 4. 检查是否处于“固定”模式（阻止新弹窗）
        if is_any_popup_sticky:
            # 是外部复制，但处于固定模式。
            # 音效已在第 3 步播放，这里只设置冷却并阻止弹窗。
            self.set_cooldown() # v4.5.9: 调用标准冷却方法
            return # 阻止创建新弹窗

        # 5. 正常模式：显示弹窗
        # (音效已在第 3 步播放)
        new_popup = self.show_popup(data)

        if data.get("type") == "file" and "paths" in data:
            new_popup.update_bottom_text(data["bottom_template"].format("●"))
            self.calculate_total_size_async(data["paths"], new_popup, data["bottom_template"])
    # --- 修改结束 ---

    # --- v4.5.2 逻辑, 无改动 ---
    def show_popup(self, data):
        """创建并显示一个新的弹窗，但不会滑出已固定的弹窗。"""

        stationary_popup = None
        for p in reversed(self.active_popups):
            if not (hasattr(p, 'is_sliding_out') and p.is_sliding_out):
                stationary_popup = p
                break

        if stationary_popup and not stationary_popup.is_sticky:
            stationary_popup.slide_out()

        new_popup = TransparentPopup(data, self, self.current_color_mode)
        self.current_color_mode = 1 - self.current_color_mode
        new_popup.raise_()
        self.active_popups.append(new_popup)

        # v4.5.9: 调用标准冷却方法
        self.set_cooldown()

        return new_popup

    # --- v4.5.3 逻辑, 无改动 ---
    def close_popup(self, popup):
        """关闭指定的弹窗，确保在关闭卡片时正确处理生命周期。"""
        if popup in self.active_popups:
            self.active_popups.remove(popup)

        for anim_name in ['slide_anim', 'anim_group']:
            try:
                anim = getattr(popup, anim_name, None)
                if anim and anim.state() == QPropertyAnimation.Running: anim.stop()
            except (RuntimeError, AttributeError): pass
        for timer_name in ['lifecycle_timer', 'border_animation_timer']:
            timer = getattr(popup, timer_name, None)
            if timer: timer.stop()

        popup.disconnect_scrollbar_signals()
        popup.close()

    def __del__(self):
        if hasattr(self, 'executor') and self.executor: self.executor.shutdown(wait=True)


class TransparentPopup(QWidget):
    SLIDE_IN_DURATION, SLIDE_OUT_DURATION, LIFECYCLE_SECONDS = 88, 88, 19

    # --- v4.5.7: 滚动条宽度 11px (无改动) ---
    SCROLLBAR_WIDTH = 11
    SCROLLBAR_MARGIN_RIGHT = 2 # 紧贴 2px 的固定边框

    # --- v4.5.3: 悬浮滚动条样式 (无改动) ---
    OVERLAY_SCROLLBAR_STYLE_SHEET = """
        QScrollBar:vertical {{
            border: none;
            background: transparent;
            width: {width}px;
            margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: {handle_color};
            border-radius: 0px;
            min-height: 20px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}
    """

    # --- v4.5.7: 构造函数 (无改动) ---
    def __init__(self, data, monitor, color_mode=0):
        super().__init__()
        self.monitor, self.color_mode, self.original_data = monitor, color_mode, data
        self.is_sticky, self.border_thickness, self.border_dash_offset = False, 1, 0
        self.lifecycle_remaining, self.lifecycle_start_time = self.LIFECYCLE_SECONDS * 1000, None

        self.separator_color = QColor(Qt.transparent)

        self.border_animation_timer = QTimer(self)
        self.border_animation_timer.timeout.connect(self.animate_border)

        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(222, 222)

        self.overlay_scrollbar = QScrollBar(self)
        self.overlay_scrollbar.setOrientation(Qt.Vertical)
        self.overlay_scrollbar.hide()
        self.is_scrollbar_connected = False

        self.setup_ui()
        self.setup_colors_and_styles()

        self.target_screen_geom = self.get_current_screen_geometry()
        self.move_to_initial_position()
        self.show()
        self.slide_in()
        self.start_lifecycle()
    # --- v4.5.7: 函数结束 ---

    # --- v4.5.8: 颜色/透明度/背景色 (无改动) ---
    def setup_colors_and_styles(self):
        """设置颜色并 *立即应用* 样式表。"""

        common_bottom_style = "padding-top: 8px;"

        if self.color_mode == 0:
            self.background_color, self.text_color, self.border_color = QColor(0, 0, 0, 240), Qt.white, Qt.white

            # 模式0: 暗金, 不加粗
            dark_gold_color_0_hex = "#cd853f" # rgb(205, 133, 63)
            self.bottom_text_style = (f"color: {dark_gold_color_0_hex}; {common_bottom_style}")
            self.top_text_style = "color: #ffffff;"

            # v4.5.8: 80% 不透明滚动块 (255 * 0.8 = 204)
            self.scrollbar_handle_color = "rgba(205, 133, 63, 204)"
            # v4.5.8: 100% 不透明分隔线
            self.separator_color = QColor(205, 133, 63, 255)

        else:
            # v4.5.8: 更新亮色背景色
            self.background_color, self.border_color = QColor(253, 246, 227, 250), QColor(55, 45, 15)
            self.text_color = QColor(3, 2, 1)

            # 模式1: 红棕色, 加粗
            dark_gold_color_1_hex = "#8B4513" # rgb(139, 69, 19)
            self.bottom_text_style = (f"color: {dark_gold_color_1_hex}; font-weight: bold; {common_bottom_style}")
            self.top_text_style = f"color: rgb({self.text_color.red()}, {self.text_color.green()}, {self.text_color.blue()});"

            # v4.5.8: 80% 不透明滚动块
            self.scrollbar_handle_color = "rgba(139, 69, 19, 204)"
            # v4.5.8: 100% 不透明分隔线
            self.separator_color = QColor(139, 69, 19, 255)

        # 1. 应用底部标签样式
        self.bottom_message_label.setStyleSheet(self.bottom_text_style)

        # 2. 应用顶部文本样式
        self.top_content.setStyleSheet(
            f"QTextEdit {{ border: none; background-color: transparent; padding: 0; {self.top_text_style} }}"
        )

        # 3. 应用悬浮滚动条样式
        scroll_style = self.OVERLAY_SCROLLBAR_STYLE_SHEET.format(
            width=self.SCROLLBAR_WIDTH, handle_color=self.scrollbar_handle_color
        )
        self.overlay_scrollbar.setStyleSheet(scroll_style)
    # --- 修改结束 ---

    # --- v4.5.8: setup_ui (无改动) ---
    def setup_ui(self):
        """初始化 UI 控件 (使用布局)。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10) # 15 -> 10
        layout.setSpacing(10)

        font = QFont("Consolas", 11)
        font.setFamilies(["Consolas", "monospace", "LXGW WenKai GB Screen", "SF Pro", "Segoe UI", "Aptos", "Roboto", "Arial"])

        # v4.5.8: top_content 现在是 StickyTextEdit 的实例
        self.top_content = StickyTextEdit(self)
        self.top_content.popup = self

        self.top_content.setText(self.original_data.get("top_text"))
        self.top_content.setReadOnly(True); self.top_content.setFont(font)
        self.top_content.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.top_content.setTextInteractionFlags(Qt.NoTextInteraction)

        self.top_content.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.top_content.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.top_content.setMaximumHeight(162)

        self.top_content.setViewportMargins(0, 0, 0, 0)

        self.top_content.internal_copy_triggered.connect(self.monitor.play_random_sound)

        self.bottom_message_label = QLabel(self.original_data.get("bottom_text", ""))
        self.bottom_message_label.setFont(font)
        self.bottom_message_label.setAlignment(Qt.AlignBottom | Qt.AlignLeft)
        self.bottom_message_label.setTextFormat(Qt.RichText)
        self.bottom_message_label.installEventFilter(self)

        layout.addWidget(self.top_content)
        layout.addStretch()
        layout.addWidget(self.bottom_message_label)
    # --- 修改结束 ---

    # --- v4.5.7: 滚动条“顶天立地” (无改动) ---
    def resizeEvent(self, event):
        """
        在窗口大小改变时（包括显示时）重新定位悬浮滚动条。
        v4.5.7: 重写 Y 和 Height 算法，使其忽略 margin，参考 border_thickness。
        """
        super().resizeEvent(event)

        # X: 紧贴右侧边框
        x = self.width() - self.SCROLLBAR_WIDTH - self.SCROLLBAR_MARGIN_RIGHT

        # Y: 从顶部 border 的内侧开始 (不再是 margin 10px 处)
        y = self.border_thickness

        # Height: 从顶部 border 内侧一直到底部分隔线的 Y 坐标
        height = self.bottom_message_label.y() - self.border_thickness

        self.overlay_scrollbar.setGeometry(int(x), int(y), int(self.SCROLLBAR_WIDTH), int(height))
    # --- 修改结束 ---

    # --- v4.5.7: 滚动条视口 (无改动) ---
    def update_overlay_scrollbar(self):
        """
        检查是否需要显示滚动条，并同步其状态。
        """
        doc_height = self.top_content.document().size().height()

        # v4.5.7: 视口高度必须匹配 resizeEvent 的新逻辑
        # (从顶部 border 内侧到底部分隔线)
        viewport_height = self.bottom_message_label.y() - self.border_thickness

        if doc_height > viewport_height:
            # 确保几何形状是最新的
            self.resizeEvent(None)

            v_scrollbar = self.top_content.verticalScrollBar()
            self.overlay_scrollbar.setRange(v_scrollbar.minimum(), v_scrollbar.maximum())

            # 关键：PageStep 必须反映新的、更大的视口高度
            self.overlay_scrollbar.setPageStep(int(viewport_height))
            v_scrollbar.setPageStep(int(viewport_height)) # 保持内部滚动条同步

            self.overlay_scrollbar.setValue(v_scrollbar.value())

            self.connect_scrollbar_signals()
            self.overlay_scrollbar.show()
        else:
            self.overlay_scrollbar.hide()
            self.disconnect_scrollbar_signals()
    # --- 修改结束 ---

    # --- v4.5.3: 滚动条控制函数 (无改动) ---
    def connect_scrollbar_signals(self):
        """安全地连接滚动条信号。"""
        if not self.is_scrollbar_connected:
            try:
                self.overlay_scrollbar.valueChanged.connect(self.top_content.verticalScrollBar().setValue)
                self.top_content.verticalScrollBar().valueChanged.connect(self.overlay_scrollbar.setValue)
                self.top_content.verticalScrollBar().rangeChanged.connect(self.overlay_scrollbar.setRange)
                self.is_scrollbar_connected = True
            except Exception as e:
                print(f"连接信号时出错: {e}")

    def disconnect_scrollbar_signals(self):
        """安全地断开滚动条信号。"""
        if self.is_scrollbar_connected:
            try:
                self.overlay_scrollbar.valueChanged.disconnect(self.top_content.verticalScrollBar().setValue)
                self.top_content.verticalScrollBar().valueChanged.disconnect(self.overlay_scrollbar.setValue)
                self.top_content.verticalScrollBar().rangeChanged.disconnect(self.overlay_scrollbar.setRange)
                self.is_scrollbar_connected = False
            except Exception as e:
                pass
    # --- v4.5.3: 函数结束 ---

    # --- v4.5.3/v4.5.4: 其余函数 (无改动) ---
    def eventFilter(self, obj, event):
        if obj == self.bottom_message_label and event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self.toggle_sticky_mode()
            return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.is_sticky: self.slide_out()

    def get_current_screen_geometry(self):
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        return screen.availableGeometry()

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

    # --- MODIFIED: v4.5.9 - 强化画布平移修复 ---
    def activate_sticky_mode(self):
        if self.lifecycle_timer.isActive():
            self.lifecycle_timer.stop()
            self.lifecycle_remaining = max(0, self.lifecycle_remaining - self.lifecycle_start_time.msecsTo(QTime.currentTime()))

        self.border_thickness = 2
        self.border_animation_timer.start(51)

        self.top_content.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.top_content.setMaximumHeight(10000)
        self.top_content.setText(self.original_data.get("top_text"))
        self.top_content.verticalScrollBar().setValue(0)
        self.top_content.setFocus(Qt.MouseFocusReason)

        # v4.5.9: 再次禁用水平滚动，防止画布平移
        # (在 StickyTextEdit.__init__ 中已设置，此处为双重保险)
        self.top_content.horizontalScrollBar().setRange(0, 0)

        QTimer.singleShot(0, self.update_overlay_scrollbar)
        self.top_content.textChanged.connect(self.update_overlay_scrollbar)

        self.update() # 触发 paintEvent 和 resizeEvent
    # --- 修改结束 ---

    def deactivate_sticky_mode(self):
        if self.lifecycle_remaining > 0: self.start_lifecycle()
        self.border_animation_timer.stop(); self.border_dash_offset = 0; self.border_thickness = 1

        self.top_content.setTextInteractionFlags(Qt.NoTextInteraction)
        self.top_content.setMaximumHeight(162)
        cursor = self.top_content.textCursor(); cursor.clearSelection(); self.top_content.setTextCursor(cursor)

        self.overlay_scrollbar.hide()
        self.disconnect_scrollbar_signals()
        try:
            self.top_content.textChanged.disconnect(self.update_overlay_scrollbar)
        except TypeError:
            pass

        self.update() # 触发 paintEvent 和 resizeEvent

    def animate_border(self):
        self.border_dash_offset = (self.border_dash_offset - 1) % -10
        self.update()

    def slide_out(self):
        for timer_name in ['lifecycle_timer', 'border_animation_timer']:
            getattr(self, timer_name).stop()
        if hasattr(self, 'is_sliding_out') and self.is_sliding_out: return
        self.is_sliding_out = True
        try:
            if hasattr(self, 'slide_anim') and self.slide_anim.state() == QPropertyAnimation.Running: self.slide_anim.stop()
        except (RuntimeError, AttributeError): pass
        self.anim_group = QParallelAnimationGroup(self)
        opacity_anim = QPropertyAnimation(self, b"windowOpacity"); opacity_anim.setDuration(self.SLIDE_OUT_DURATION); opacity_anim.setEndValue(0.0)
        pos_anim = QPropertyAnimation(self, b"pos"); pos_anim.setDuration(self.SLIDE_OUT_DURATION); pos_anim.setEndValue(QPoint(self.x() - 80, self.y()))
        for anim in [opacity_anim, pos_anim]: self.anim_group.addAnimation(anim)
        self.anim_group.finished.connect(lambda: self.monitor.close_popup(self))
        self.anim_group.start(QAbstractAnimation.DeleteWhenStopped)

    def move_to_initial_position(self):
        self.move(self.target_screen_geom.right(), self.target_screen_geom.bottom() - self.height() - 40)

    def slide_in(self):
        end_pos = QPoint(self.target_screen_geom.right() - self.width() - 40, self.y())
        self.slide_anim = QPropertyAnimation(self, b"pos"); self.slide_anim.setDuration(self.SLIDE_IN_DURATION)
        self.slide_anim.setEndValue(end_pos); self.slide_anim.start(QPropertyAnimation.DeleteWhenStopped)

    def update_bottom_text(self, text):
        self.bottom_message_label.setText(text)

    # --- MODIFIED: v4.5.9 - 修复分隔线 1px (HiDPI Fix) ---
    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)

        # 1. 绘制背景
        painter.fillRect(self.rect(), self.background_color)

        # 2. 绘制自定义分隔线 (在主边框 *之下*)
        y_separator = self.bottom_message_label.y()
        x_start = self.border_thickness
        x_end = self.width() - self.border_thickness

        # 宽度硬编码为 1px
        line_pen = QPen(self.separator_color, 1, Qt.SolidLine)
        # v4.5.9: 设为 Cosmetic 保证 1 物理像素宽度，不受 DPI 缩放影响
        line_pen.setCosmetic(True)
        painter.setPen(line_pen)
        painter.drawLine(int(x_start), int(y_separator), int(x_end), int(y_separator))

        # 3. 绘制主边框 (在分隔线 *之上*, 覆盖两端)
        pen = QPen(self.border_color, self.border_thickness, Qt.DashLine)
        if self.is_sticky: pen.setDashOffset(self.border_dash_offset)
        painter.setPen(pen)

        half_pen = self.border_thickness / 2.0
        painter.drawRect(self.rect().adjusted(half_pen, half_pen, -half_pen, -half_pen))
    # --- 修改结束 ---


if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling); QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = ClipboardMonitor(sys.argv)
    print("="*20 + " 系统可用字体家族名列表 " + "="*20)
    db = QFontDatabase(); print(sorted(list(set(QFont(name).family() for name in db.families()))))
    print("="*63)
    signal.signal(signal.SIGINT, lambda sig, frame: QApplication.quit())
    timer = QTimer(); timer.start(50); timer.timeout.connect(lambda: None)
    sys.exit(app.exec_())
