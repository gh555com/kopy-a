# q3.py (v5.0.4 - "Diagnostic Build - FSM Typo Fix")
# -*- coding: utf-8 -*-
"""
v5.0.4 版本特性:
- 【FIX (P1-BUG)】: 修正 v5.0.3 中一个致命的拼写错误。
-
- 【错误详情】:
-   在 `deactivate_sticky_mode` 函数中，
-   `self.z_click_area_FZSM.setStyleSheet(self.STYLE_RED)`
-   应该是 `self.z_click_area_FSM.setStyleSheet(self.STYLE_RED)`
-   这个拼写错误 (FZSM vs FSM) 导致了用户日志中出现的
-   `AttributeError: 'TransparentPopup' object has no attribute 'z_click_area_FZSM'`
-
- 【诊断功能】:
-   本版本保留 v5.0.3 的所有诊断功能，因为用户的核心问题
-   (get_sample_size) 仍未解决。
-
- 【v5.0.3 诊断结果】:
-   用户的 pip install 失败，因为其配置的 Aliyun 镜像
-   `mirrors.aliyun.com` 中没有 `pyminiaudio` 包。
-   解决方案：强制使用官方源安装：
-   `python -m pip install -U pyminiaudio -i https://pypi.org/simple/`
"""
import sys
import os
import signal
import concurrent.futures
import random
import glob
import inspect
import threading

# --- (v5.0.3) 诊断性导入 ---
try:
    import miniaudio
except ImportError:
    print("="*60)
    print("【!!】 错误：未找到 miniaudio 库。")
    print("【!!】 v5.0.4 需要 miniaudio 引擎。")
    print("【!!】 请先在您的环境中安装： pip install pyminiaudio")
    print("="*60)
    sys.exit(1)
# --- (v5.0.3) 结束 ---

from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QVBoxLayout,
                             QTextEdit, QScrollBar, QStyleOptionSlider, QStyle)
from PyQt5.QtCore import (Qt, QTimer, QPoint, QPropertyAnimation, pyqtSignal, QBuffer,
                          QIODevice, QParallelAnimationGroup, QAbstractAnimation, QEasingCurve, QUrl,
                          QEvent, QTime, QRect)
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


# --- ClipboardMonitor (v5.0.4 诊断) ---
class ClipboardMonitor(QApplication):
    calculation_done = pyqtSignal(str, QWidget)
    COLOR_SCHEME_MODE = 4; current_color_mode = 0; COOLDOWN_TIME_MS = 100
    def __init__(self, argv):
        super().__init__(argv)

        self.active_popups = []; self.is_on_cooldown = False
        self.calculation_done.connect(self.on_calculation_finished)
        self.setup_clipboard_monitor()
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 8)
        self.last_played_sound = None; self.last_played_q_sound = None; self.last_played_z_sound = None

        # --- (v5.0.2 Logic) ---
        self.audio_engine_ok = False
        self.audio_device = None
        self.active_audio_streams = []
        self.audio_lock = threading.Lock()
        self.setup_audio_engine()
        # --- (v5.0.2 Logic) ---

        self.setup_sound_files()

    # --- (v5.0.3) 核心诊断：探测音频系统 ---
    def _probe_audio_system(self):
        """【诊断】打印出 miniaudio 能找到的所有播放设备。"""
        print("\n" + "="*20 + " DIAGNOSTIC: Probing Audio System " + "="*20)
        try:
            devices = miniaudio.Devices()
            playbacks = devices.get_playbacks()
            if not playbacks:
                print("【!!】 DIAGNOSTIC: No playback devices found by miniaudio!")
            else:
                print("DIAGNOSTIC: Available Playback Devices Found:")
                for i, d in enumerate(playbacks):
                    # d 是一个字典，包含 'name', 'backend_name' 等键
                    backend_name = d.get('backend_name', 'N/A')
                    print(f"  -> Device [{i}]: Name='{d['name']}', Backend='{backend_name}'")
        except Exception as e:
            print(f"【!!】 DIAGNOSTIC: Error during audio system probe: {e}")
        print("=" * 66 + "\n")
    # --- (v5.0.3) 结束 ---

    def setup_audio_engine(self):
        """一次性初始化 miniaudio 常驻设备和回调。"""
        # --- (v5.0.3) 在所有操作前，先进行诊断 ---
        self._probe_audio_system()
        # --- (v5.0.3) 结束 ---

        try:
            self.MA_REQUESTED_FORMAT = miniaudio.SampleFormat.SIGNED16
            self.MA_REQUESTED_CHANNELS = 2
            self.MA_REQUESTED_RATE = 44100

            sample_width = miniaudio.get_sample_size(self.MA_REQUESTED_FORMAT)
            self.MA_FRAME_WIDTH = sample_width * self.MA_REQUESTED_CHANNELS

            self.audio_device = miniaudio.Device(
                output_format=self.MA_REQUESTED_FORMAT,
                nchannels=self.MA_REQUESTED_CHANNELS,
                sample_rate=self.MA_REQUESTED_RATE,
                callback=self._audio_data_callback
            )
            self.audio_device.start()
            self.audio_engine_ok = True

            # --- (v5.0.3) 诊断：打印最终使用的后端 ---
            final_backend = self.audio_device.backend.name if self.audio_device.backend else "Unknown"
            print(f"音频引擎 (v5.0.4 - 诊断模式) 初始化成功。") # 更新版本号
            print(f"DIAGNOSTIC:  selected audio backend is '{final_backend}'.")
            # --- (v5.0.3) 结束 ---

        except Exception as e:
            print(f"【!!】 致命错误：初始化音频引擎失败: {e}")
            self.audio_engine_ok = False

    # (v5.0.2 Logic - 无改动)
    def _audio_data_callback(self, in_data, frame_count, time_info, status):
        frames_to_return = b''
        with self.audio_lock:
            try:
                if self.active_audio_streams:
                    current_stream = self.active_audio_streams[0]
                    frames_to_return = current_stream.read(frame_count)
            except Exception as e:
                # 在诊断模式下，我们想看到所有错误
                print(f"【!!】 DIAGNOSTIC (Audio Callback Error): {e}")
                frames_to_return = b''
        return frames_to_return.ljust(frame_count * self.MA_FRAME_WIDTH, b'\x00')

    def setup_sound_files(self):
        """预加载所有音效的 *文件路径*"""
        self.main_sounds = []; self.q_sounds = []; self.z_sounds = []
        try:
            script_dir = os.path.dirname(os.path.realpath(__file__))
            assets_dir = os.path.join(script_dir, 'assets')

            # --- (v5.0.3) 诊断：打印资产路径 ---
            print(f"DIAGNOSTIC: Searching for sound assets in folder: '{assets_dir}'")
            # --- (v5.0.3) 结束 ---

            def load_sound_paths_from_glob(glob_pattern):
                sound_file_paths = glob.glob(glob_pattern)
                return [p for p in sound_file_paths if p.endswith(('.mp3', '.wav'))]

            self.main_sounds = load_sound_paths_from_glob(os.path.join(assets_dir, '[1-8].*'))
            self.q_sounds = load_sound_paths_from_glob(os.path.join(assets_dir, 'q[1-9].*'))
            self.z_sounds = load_sound_paths_from_glob(os.path.join(assets_dir, 'z[1-6].*'))

            if not self.main_sounds: print("警告: 未找到 [1-8] 音效文件。")
            else: print(f"成功预加载 {len(self.main_sounds)} 个音效路径。")
            if not self.q_sounds: print("警告: 未找到 q[1-9] 音效文件。")
            else: print(f"成功预加载 {len(self.q_sounds)} 个 q 系列音效路径。")
            if not self.z_sounds: print("警告: 未找到 z[1-6] 音效文件。")
            else: print(f"成功预加载 {len(self.z_sounds)} 个 z 系列音效路径。")

        except Exception as e:
            print(f"加载音效路径时发生严重错误: {e}")
            self.main_sounds = []; self.q_sounds = []; self.z_sounds = []

    # (v5.0.2 Logic - 增加诊断)
    def _play_sound(self, sound_path):
        if not self.audio_engine_ok: return

        # --- (v5.0.3) 诊断：打印正在尝试播放的文件 ---
        print(f"DIAGNOSTIC: Attempting to play sound -> '{os.path.basename(sound_path)}'")
        # --- (v5.0.3) 结束 ---

        try:
            decoder = miniaudio.decode_file(
                sound_path,
                output_format=self.MA_REQUESTED_FORMAT,
                nchannels=self.MA_REQUESTED_CHANNELS,
                sample_rate=self.MA_REQUESTED_RATE
            )
            with self.audio_lock:
                for old_decoder in self.active_audio_streams:
                    old_decoder.close()
                self.active_audio_streams.clear()
                self.active_audio_streams.append(decoder)

        except Exception as e:
            print(f"【!!】 无法播放音效 '{os.path.basename(sound_path)}': {e}")

    def play_random_sound(self):
        if not self.main_sounds: return
        candidate_sounds = [p for p in self.main_sounds if p != self.last_played_sound]
        sound_to_play = random.choice(candidate_sounds or self.main_sounds)
        self.last_played_sound = sound_to_play
        self._play_sound(sound_to_play)

    def play_q_sound(self):
        if not self.q_sounds: return
        sound_to_play = random.choice(self.q_sounds)
        self.last_played_q_sound = sound_to_play
        self._play_sound(sound_to_play)

    def play_z_sound(self):
        if not self.z_sounds: return
        sound_to_play = random.choice(self.z_sounds)
        self.last_played_z_sound = sound_to_play
        self._play_sound(sound_to_play)

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
            except Exception as e: print(f"备用图片处理出错: {e}")
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
        if self.is_on_cooldown: return
        try: mime_data = self.clipboard().mimeData()
        except Exception: print("警告: 无法获取剪贴板数据。"); return
        if not mime_data: return
        data = self.process_clipboard_data(mime_data)
        if not data: return

        self.play_random_sound()

        sticky_popups = [p for p in self.active_popups if p.is_sticky]
        if sticky_popups: self.set_cooldown(); return
        stationary_popup = next((p for p in reversed(self.active_popups) if not p.is_sticky and not getattr(p, 'is_sliding_out', False)), None)
        if stationary_popup: stationary_popup.slide_out()
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

    def close_audio_engine(self):
        """安全地关闭音频设备和所有流。"""
        print("正在关闭音频引擎...")
        if self.audio_device:
            try:
                self.audio_device.close()
                self.audio_device = None
                print(" -> 音频设备已关闭。")
            except Exception as e:
                print(f" -> 关闭音频设备时出错: {e}")

        with self.audio_lock:
            for stream in self.active_audio_streams:
                stream.close()
            self.active_audio_streams.clear()
            print(" -> 所有活动音频流已清理。")

    def __del__(self):
        self.close_audio_engine()
        if hasattr(self, 'executor'): self.executor.shutdown(wait=False)


# --- TransparentPopup (v5.0.4 - 拼写修正) ---
class TransparentPopup(QWidget):
    SLIDE_IN_DURATION, SLIDE_OUT_DURATION, LIFECYCLE_SECONDS = 88, 88, 19
    SCROLLBAR_WIDTH, SCROLLBAR_MARGIN_RIGHT = 11, 2
    CONTENT_AREA_MAX_HEIGHT, BOTTOM_AREA_MIN_HEIGHT = 162, 30

    STYLE_RED = "background-color: rgba(255, 0, 0, 100);"
    STYLE_BLUE = "background-color: rgba(0, 0, 255, 100);"

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
        self.full_text_to_load = self.original_data.get("full_text")
        self.slide_anim = None; self.anim_group = None; self.border_animation_timer = None

        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(222, 222)

        self.overlay_scrollbar = ClickJumpScrollBar(self)
        self.overlay_scrollbar.setOrientation(Qt.Vertical); self.overlay_scrollbar.hide()
        self.is_scrollbar_connected = False

        self.interaction_shield = None
        self.z_click_area_FSM = None
        self.z_state_is_A = True

        self.is_z_zone_blocked = False

        self.setup_ui(); self.setup_colors_and_styles()
        self.target_screen_geom = self.get_current_screen_geometry()
        self.move_to_initial_position(); self.show(); self.slide_in()
        self.start_lifecycle()

        self.interaction_shield.raise_()
        self.overlay_scrollbar.raise_()
        if self.z_click_area_FSM:
            self.z_click_area_FSM.raise_()
            self.z_click_area_FSM.show()

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

        self.z_click_area_FSM = QWidget(self)
        self.z_click_area_FSM.setStyleSheet(self.STYLE_RED)
        self.z_click_area_FSM.installEventFilter(self)
        self.z_state_is_A = True

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

            if hasattr(self, 'z_click_area_FSM') and self.z_click_area_FSM is not None:
                self.z_click_area_FSM.setGeometry(z_zone_rect)

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

            if obj == self.z_click_area_FSM:
                if self.z_state_is_A: self.monitor.play_z_sound()
                else: self.monitor.play_q_sound()

                if self.z_state_is_A: self.z_click_area_FSM.setStyleSheet(self.STYLE_BLUE)
                else: self.z_click_area_FSM.setStyleSheet(self.STYLE_RED)

                self.z_state_is_A = not self.z_state_is_A

                if self.is_z_zone_blocked: return True

                self.is_z_zone_blocked = True
                QTimer.singleShot(0, self.perform_sticky_toggle_ONLY)
                return True

            if obj == self.interaction_shield:
                if not self.is_sticky:
                    self.monitor.play_q_sound()
                    self.slide_out()
                return True

        if obj == self.interaction_shield and event.type() == QEvent.Wheel:
            QApplication.sendEvent(self.top_content.viewport(), event)
            self.top_content.viewport().update()
            return True
        return super().eventFilter(obj, event)

    def perform_sticky_toggle_ONLY(self):
        try:
            self.toggle_sticky_mode()
        except Exception as e:
            print(f"Error during perform_sticky_toggle_ONLY: {e}")
        finally:
            self.is_z_zone_blocked = False

    def mousePressEvent(self, event): super().mousePressEvent(event)
    def get_current_screen_geometry(self): return (QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()).availableGeometry()
    def start_lifecycle(self):
        self.lifecycle_timer = QTimer(self); self.lifecycle_timer.setSingleShot(True)
        self.lifecycle_timer.timeout.connect(self.slide_out)
        if not self.is_sticky:
            self.lifecycle_start_time = QTime.currentTime(); self.lifecycle_timer.start(self.lifecycle_remaining)

    def toggle_sticky_mode(self):
        self.is_sticky = not self.is_sticky
        if self.is_sticky: self.activate_sticky_mode()
        else: self.deactivate_sticky_mode()

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

        # --- (v5.0.4) 核心修正：FZSM -> FSM ---
        if hasattr(self, 'z_click_area_FSM'): # <--- 修正拼写
             self.z_click_area_FSM.setStyleSheet(self.STYLE_RED) # <--- 修正拼写
        # --- (v5.0.4) 修正结束 ---

        self.z_state_is_A = True

        self.is_z_zone_blocked = False

        QTimer.singleShot(0, lambda: self.top_content.verticalScrollBar().setValue(saved_v_scroll))
        self.update()

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


# --- 主程序入口 (v5.0.3) ---
if __name__ == "__main__":
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling); QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = ClipboardMonitor(sys.argv)

    def cleanup_on_exit(sig, frame):
        print("\nCtrl+C detected. Shutting down gracefully...")
        app.close_audio_engine()
        QApplication.quit()

    signal.signal(signal.SIGINT, cleanup_on_exit)
    app.aboutToQuit.connect(app.close_audio_engine)

    # (v5.0.3) 移除了字体打印，让诊断信息更清晰
    # print("="*20 + " 系统可用字体家族名列表 " + "="*20)
    # db = QFontDatabase(); print(sorted(list(set(QFont(name).family() for name in db.families()))))
    # print("="*63)

    timer = QTimer(); timer.start(500); timer.timeout.connect(lambda: None)
    sys.exit(app.exec_())
