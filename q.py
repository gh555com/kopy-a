# q.py (v1.0.1 - "Crash Fix & Rename Version")
# -*- coding: utf-8 -*-
"""
v1.0.1 版本特性:
- 【崩溃修复】: 修复了第二次复制时因 QObject 被错误删除而导致的崩溃 (使用 deleteLater() 替代 close())。
- 【重命名】: 遵照要求，将所有 'App'/'app' 相关的类和变量重命名为 'QAqqlication'/'aqq_instance'。
- 【纯净展示版】: 基于q3.py v4.9.38，去除所有编辑功能
- 【文本截断】: 上部文本区超过200字符时自动截断
- 【简化交互】: 点击任何区域都关闭展示框并播放q音效
- 【PySide2迁移】: 完全使用PySide2，无PyQt依赖
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
    print("【!!】 v1.0.0 需要 miniaudio_nonblocking_v15 引擎才能实现 0 延迟音效。")
    print("【!!】 请先在您的环境中安装 miniaudio_nonblocking_v15 模块。")
    print("="*60)
    sys.exit(1)
# --- (v4.9.33) 结束 ---

from PySide2.QtWidgets import (QApplication as QAqqlication, QWidget, QLabel, QVBoxLayout,
                             QTextEdit, QScrollBar, QStyleOptionSlider, QStyle, QPushButton)
from PySide2.QtCore import (Qt, QTimer, QPoint, QPropertyAnimation, Signal, QBuffer,
                          QIODevice, QParallelAnimationGroup, QAbstractAnimation, QEasingCurve, QUrl,
                          QEvent, QTime, QRect)
from PySide2.QtGui import (QFont, QPainter, QColor, QPen, QFontDatabase, QCursor,
                         QTextOption, QTextCursor, QKeySequence, QPalette, QPixmap, QImage)

# 使用 QAqqlication 作为 QApplication 的别名


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
        moved = (event.pos() - self.press_pos).manhattanLength() > QAqqlication.startDragDistance()
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
class ClipboardMonitor(QAqqlication):
    calculation_done = Signal(str, QWidget)
    COLOR_SCHEME_MODE = 4; current_color_mode = 0; COOLDOWN_TIME_MS = 100
    def __init__(self, argv):
        super().__init__(argv)

        # --- (v4.9.33) 初始化基于v15逻辑的多线程非阻塞音频引擎 ---
        self.audio_engine = None
        try:
            self.audio_engine = NonBlockingAudioEngine()
            print("音频引擎初始化成功")
        except Exception as e:
            print(f"音频引擎初始化失败: {e}")
            print("程序将在没有音效的情况下继续运行")
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
        if self.audio_engine:
            try:
                print(f"成功预加载 {len(self.audio_engine.main_sounds)} 个原有音效 (miniaudio v15)。")
                print(f"成功预加载 {len(self.audio_engine.q_sounds)} 个 q 系列音效 (miniaudio v15)。")
                print(f"成功预加载 {len(self.audio_engine.z_sounds)} 个 z 系列音效 (miniaudio v15)。")
            except Exception as e:
                print(f"获取音效信息时出错: {e}")
        else:
            print("音频引擎未初始化，无法加载音效")
    # --- (v4.9.33) 结束 ---

    # --- (v4.9.33) 核心改动：重写音效播放 ---
    def play_random_sound(self):
        """使用基于v15逻辑的NonBlockingAudioEngine播放随机主音效"""
        if self.audio_engine:
            try:
                self.audio_engine.play_random_sound()
            except Exception as e:
                print(f"播放随机音效时出错: {e}")

    def play_q_sound(self):
        """使用基于v15逻辑的NonBlockingAudioEngine播放随机q音效"""
        if self.audio_engine:
            try:
                self.audio_engine.play_q_sound()
            except Exception as e:
                print(f"播放q音效时出错: {e}")

    def play_z_sound(self):
        """使用基于v15逻辑的NonBlockingAudioEngine播放随机z音效"""
        if self.audio_engine:
            try:
                self.audio_engine.play_z_sound()
            except Exception as e:
                print(f"播放z音效时出错: {e}")

    def play_clear_sound(self):
        """播放剪贴板清空时的固定音效（8.wav）"""
        if self.audio_engine:
            try:
                self.audio_engine.play_sound_index('main', 8)
            except Exception as e:
                print(f"播放清空音效时出错: {e}")
    # --- (v4.9.33) 结结 ---

    # (v4.9.30 - 修改：添加异常处理)
    def setup_clipboard_monitor(self):
        # 直接设置剪贴板监控，不使用延迟
        try:
            self.clipboard().dataChanged.connect(self.on_clipboard_changed)
            print("剪贴板监控设置成功")
        except Exception as e:
            print(f"设置剪贴板监控时出错: {e}")
            # 即使设置失败，也不应该退出程序
    def process_clipboard_data(self, mime_data):
        all_formats = mime_data.formats()
        if mime_data.hasUrls():
            urls = mime_data.urls();
            if not urls: return None
            local_paths = [url.toLocalFile() for url in urls if url.isLocalFile() and os.path.exists(url.toLocalFile())]
            if not local_paths:
                # 处理远程URL，像文本一样处理
                remote_urls = [url for url in urls if not url.isLocalFile()]
                if remote_urls:
                    # 将URL文本原封不动显示在上部区域，多个URL用换行符分隔
                    url_texts = [url.toString() for url in remote_urls]
                    full_text = "\n".join(url_texts)

                    # 计算所有URL的总大小
                    total_size = sum(len(url.toString().encode('utf-8', 'replace')) for url in remote_urls)

                    return {"type": "text", "full_text": full_text, "bottom_text": self.format_size(total_size)}
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
            if not text: return {"type": "clear", "top_text": "", "top_text_snippet": "", "bottom_text": self.format_size(0)}
            try: data_size = mime_data.data('text/plain').size()
            except Exception: data_size = len(text.encode('utf-8', 'replace'))
            bottom_text = self.format_size(data_size)
            return {"type": "text", "full_text": text, "bottom_text": bottom_text}

        # 增强未知类型处理逻辑，参考1.py的实现
        if all_formats:
            # 排除Qt内部格式和已知格式，专注于未知内容
            filtered_formats = [
                f for f in all_formats
                if not f.startswith('application/x-qt-')
                and f not in ('text/plain', 'text/plain;charset=utf-8', 'text/uri-list',
                             'UTF8_STRING', 'COMPOUND_TEXT', 'TEXT', 'STRING', 'image/png')
            ]

            # 如果有过滤后的格式，使用第一个；否则使用所有格式中的第一个
            primary_type = None
            if filtered_formats:
                primary_type = filtered_formats[0]
            elif all_formats:
                primary_type = all_formats[0]

            if primary_type:
                # 获取数据并计算大小
                try:
                    byte_data = mime_data.data(primary_type)
                    data_size = byte_data.size() if byte_data else 0

                    # 尝试获取可读的文本表示
                    try:
                        text_data = byte_data.data().decode('utf-8', errors='replace')
                        # 如果是可读文本且不太长，显示文本内容
                        if len(text_data) > 0 and len(text_data) < 200:
                            return {"type": "text", "full_text": text_data, "bottom_text": self.format_size(data_size)}
                    except:
                        pass

                    # 否则显示为未知内容类型
                    unknown_text = f"未知内容，类型: {primary_type}"
                    return {"type": "other", "top_text": unknown_text, "top_text_snippet": unknown_text, "bottom_text": self.format_size(data_size)}
                except Exception as e:
                    # 如果获取数据失败，仍然尝试显示类型信息
                    unknown_text = f"未知内容，类型: {primary_type}"
                    return {"type": "other", "top_text": unknown_text, "top_text_snippet": unknown_text, "bottom_text": "大小未知"}

        return {"type": "clear", "top_text": "", "top_text_snippet": "", "bottom_text": self.format_size(0)}
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
        if size_bytes < 0: return "未知大小"
        if size_bytes < 1024: return f"{size_bytes}b"
        if size_bytes < 1024 * 1024:  # 小于1MB
            # 使用逗号分隔千位，只显示字节
            return f"{size_bytes:,}b"
        # 大于等于1MB，只显示MB单位，也使用逗号分隔千位
        mb = size_bytes / (1024 * 1024)
        return f"{mb:,.0f}M"
    def set_cooldown(self):
        self.is_on_cooldown = True
        QTimer.singleShot(self.COOLDOWN_TIME_MS, lambda: setattr(self, 'is_on_cooldown', False))
    # (v4.9.30 - 修改：添加更全面的异常处理)
    def on_clipboard_changed(self):
        if self.is_on_cooldown:
            return

        # 增强剪贴板访问的异常处理
        mime_data = None
        try:
            # 尝试获取剪贴板数据
            clipboard = self.clipboard()
            if clipboard:
                mime_data = clipboard.mimeData()
            else:
                print("无法获取剪贴板对象")
                self.set_cooldown()
                return
        except Exception as e:
            print(f"获取剪贴板数据时出错: {e}")
            # 设置冷却时间，避免快速重复尝试
            self.set_cooldown()
            return

        if not mime_data:
            self.set_cooldown()
            return

        try:
            data = self.process_clipboard_data(mime_data)
        except Exception as e:
            print(f"处理剪贴板数据时出错: {e}")
            # 不返回，继续尝试创建默认数据
            data = {"type": "clear", "top_text": "", "top_text_snippet": "", "bottom_text": self.format_size(0)}

        if not data:
            data = {"type": "clear", "top_text": "", "top_text_snippet": "", "bottom_text": self.format_size(0)}

        try:
            # (v4.9.33) - 立即播放音效，不等待界面切换
            # 直接调用音频引擎，不使用QTimer.singleShot避免额外延迟
            # 如果是剪贴板清空情况，播放固定音效8.wav
            if data.get("type") == "clear":
                try:
                    self.play_clear_sound()
                except Exception as e:
                    print(f"播放清空音效时出错: {e}")
            else:
                try:
                    self.play_random_sound()
                except Exception as e:
                    print(f"播放随机音效时出错: {e}")

            sticky_popups = [p for p in self.active_popups if p.is_sticky]
            if sticky_popups:
                self.set_cooldown(); return
            stationary_popup = next((p for p in reversed(self.active_popups) if not p.is_sticky and not getattr(p, 'is_sliding_out', False)), None)
            if stationary_popup:
                stationary_popup.slide_out()
            if self.COLOR_SCHEME_MODE in (3, 4): self.current_color_mode = 1 - self.current_color_mode
            elif self.COLOR_SCHEME_MODE == 2: self.current_color_mode = 1
            else: self.current_color_mode = 0

            try:
                new_popup = TransparentPopup(data, self, self.current_color_mode, self.COLOR_SCHEME_MODE)
                new_popup.raise_()
                self.active_popups.append(new_popup)
                self.set_cooldown()

                if data.get("type") == "file" and "paths" in data:
                    new_popup.update_bottom_text(data["bottom_template"].format("●"))
                    self.calculate_total_size_async(data["paths"], new_popup, data["bottom_template"])
            except Exception as e:
                print(f"创建或初始化弹窗时出错: {e}")
                # 即使创建弹窗失败，也设置冷却时间，避免快速重复尝试
                self.set_cooldown()
        except Exception as e:
            print(f"处理剪贴板变化时发生未预期错误: {e}")
            # 即使发生错误，也设置冷却时间，避免快速重复尝试
            self.set_cooldown()
            # 不退出程序，继续运行

    # (v1.0.1 - 崩溃修复)
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

        # --- 核心修复 ---
        # 使用 deleteLater() 替代 close() 来安全地删除 QWidget
        popup.disconnect_scrollbar_signals()
        popup.deleteLater()
        # --- 修复结束 ---

    # --- (v4.9.33) 核心改动：添加清理 ---
    def __del__(self):
        # 清理基于v15逻辑的多线程非阻塞音频引擎资源
        if hasattr(self, 'audio_engine') and self.audio_engine is not None:
            try:
                self.audio_engine.cleanup()
            except Exception as e:
                print(f"清理音频引擎时出错: {e}")

        if hasattr(self, 'executor'):
            try:
                self.executor.shutdown(wait=False)
            except Exception as e:
                print(f"清理线程池时出错: {e}")

        # 清理Qt对象
        try:
            # 断开所有信号连接
            try:
                self.calculation_done.disconnect()
            except:
                pass

            # 清理活动弹窗
            if hasattr(self, 'active_popups'):
                for popup in self.active_popups:
                    try:
                        popup.close()
                        popup.deleteLater()
                    except:
                        pass
                self.active_popups.clear()

            # 清理剪贴板连接
            try:
                clipboard = self.clipboard()
                if clipboard:
                    clipboard.dataChanged.disconnect(self.on_clipboard_changed)
            except:
                pass

        except Exception as e:
            print(f"清理Qt对象时出错: {e}")
    # --- (v4.9.33) 结束 ---
# --- (v4.9.30 - 无改动) ---


# --- TransparentPopup (v1.0.0 - 纯净展示版) ---
class TransparentPopup(QWidget):
    SLIDE_IN_DURATION, SLIDE_OUT_DURATION, LIFECYCLE_SECONDS = 88, 88, 119
    SCROLLBAR_WIDTH, SCROLLBAR_MARGIN_RIGHT = 11, 2
    CONTENT_AREA_MAX_HEIGHT, BOTTOM_AREA_MIN_HEIGHT = 177, 15

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
        return (QAqqlication.screenAt(QCursor.pos()) or QAqqlication.primaryScreen()).availableGeometry()

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
        layout.setContentsMargins(10, 5, 10, 10); layout.setSpacing(0)
        font = QFont("Consolas", 11); font.setFamilies(["Consolas", "monospace", "LXGW WenKai GB Screen", "SF Pro", "Segoe UI", "Aptos", "Roboto", "Arial"])

        # 使用QTextEdit而不是StickyTextEdit，去除编辑功能
        self.top_content = QTextEdit(self)
        initial_text = self.full_text_to_load
        if initial_text is None: initial_text = self.original_data.get("top_text_snippet", "")

        # 纯净版特性：文本超过200字符时截断
        if len(initial_text) > 200:
            initial_text = initial_text[:200] + "..."

        self.top_content.setPlainText(initial_text)
        self.top_content.setReadOnly(True)  # 设置为只读，去除编辑功能
        self.top_content.setTextInteractionFlags(Qt.TextSelectableByMouse)  # 只允许选择文本
        self.top_content.setFont(font)
        self.top_content.setWordWrapMode(QTextOption.WrapAnywhere)
        self.top_content.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.top_content.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.top_content.setCursorWidth(0)  # 不显示光标
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

    def update_overlay_scrollbar(self):
        # 纯净版不需要滚动条，因为内容是只读且截断的
        self.overlay_scrollbar.hide(); self.disconnect_scrollbar_signals()

    def connect_scrollbar_signals(self):
        # 纯净版不需要滚动条连接
        pass

    def disconnect_scrollbar_signals(self):
        # 纯净版不需要滚动条连接
        pass

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            # 纯净版特性：点击任何区域都关闭展示框并播放q音效
            self.monitor.play_q_sound()
            self.slide_out()
            return True

        return super().eventFilter(obj, event)

    # (v4.9.30 - 无改动)
    def mousePressEvent(self, event):
        # 纯净版特性：点击任何区域都关闭展示框并播放q音效
        self.monitor.play_q_sound()
        self.slide_out()
        super().mousePressEvent(event)

    def start_lifecycle(self):
        self.lifecycle_timer = QTimer(self); self.lifecycle_timer.setSingleShot(True)
        self.lifecycle_timer.timeout.connect(self.slide_out)
        if not self.is_sticky:
            self.lifecycle_start_time = QTime.currentTime(); self.lifecycle_timer.start(self.lifecycle_remaining)

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

    def update_bottom_text(self, text):
        self.bottom_message_label.setText(text)

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


# --- (v4.9.30 - 修改：添加全局异常处理) ---
if __name__ == "__main__":
    # 添加全局异常处理，防止程序因未捕获的异常而退出
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        print(f"未捕获的异常: {exc_type.__name__}: {exc_value}")
        # 记录异常但不退出程序
        import traceback
        print("异常堆栈:")
        traceback.print_tb(exc_traceback)

    sys.excepthook = handle_exception

    QAqqlication.setAttribute(Qt.AA_EnableHighDpiScaling); QAqqlication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    try:
        aqq_instance = ClipboardMonitor(sys.argv)
        signal.signal(signal.SIGINT, lambda sig, frame: QAqqlication.quit())
        timer = QTimer(); timer.start(500); timer.timeout.connect(lambda: None)
        # 使用sys.exit确保程序正常退出
        sys.exit(aqq_instance.exec_())
    except Exception as e:
        print(f"程序启动时出错: {e}")
        import traceback
        print("异常堆栈:")
        traceback.print_exc()
        # 即使启动失败，也尝试继续运行
        try:
            aqq_instance = ClipboardMonitor(sys.argv)
            signal.signal(signal.SIGINT, lambda sig, frame: QAqqlication.quit())
            timer = QTimer(); timer.start(500); timer.timeout.connect(lambda: None)
            aqq_instance.exec_()
        except Exception as e2:
            print(f"重试启动也失败: {e2}")
            print("程序无法启动，请检查环境和依赖")
