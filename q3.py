# q3.py
# -*- coding: utf-8 -*-
"""
一个剪贴板监控工具，当有新内容被复制时，会在屏幕右下角显示一个无干扰的弹窗。

v4.1.1 版本特性 (基于 v4.1.0 的功能增强):
- 【新增】智能识别复制内容：
  - 单个文件夹: 显示 "文件夹："
  - 多个文件夹: 显示 "X 个文件夹"
  - 多个文件: 显示 "X 个文件"
  - 文件和文件夹混合: 显示 "X 个项目"
- (保留v4.1.0) 增加了一种新的滑出动画模式（模式2，默认）：弹窗向左滑行一小段距离，同时淡出（透明度降为0）。
- (保留v4.1.0) 在代码启动部分增加了“滑出模式开关”，可选择传统的向下滑出（模式1）或新的左滑淡出（模式2）。
- (保留v4.0.2) 点击弹窗任意位置，可使其立即开始滑出并关闭。
- (保留v4.0.2) 优化了复制文本和文件时的底部标签格式。
- (保留v4.0.1) 启动时打印的字体列表，是真正可供代码使用的“字体家族名”。
- (保留v4.0) 弹窗会出现在鼠标指针所在的屏幕的右下角，完美支持多显示器环境。
- (保留v4.0) 采用字体回退链机制，优先使用高质量字体，若缺失则自动使用备用字体。
"""
import sys
import os
import signal
import concurrent.futures
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout
# --- MODIFIED START: 导入动画组、缓动曲线等相关模块 ---
from PyQt5.QtCore import (Qt, QTimer, QPoint, QPropertyAnimation, pyqtSignal, QBuffer,
                          QIODevice, QParallelAnimationGroup, QAbstractAnimation, QEasingCurve)
# --- MODIFIED END ---
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QFontDatabase, QCursor
# Removed QFontMetrics as it's not used in the final font family printing logic per user's original code


# --- NEW: 文件大小计算辅助函数 (用于ThreadPoolExecutor) ---
def _get_path_size_recursive(path):
    """
    辅助函数：计算单个文件或目录的大小（递归）。
    此函数将在ThreadPoolExecutor中执行。
    """
    if not os.path.exists(path):
        return 0

    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError as e:
            # 记录警告，但不中断计算
            sys.stderr.write(f"警告: 无法获取文件大小 '{path}' - {e}\n")
            return 0
    elif os.path.isdir(path):
        dir_size = 0
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                file_path = os.path.join(dirpath, f)
                try:
                    dir_size += os.path.getsize(file_path)
                except OSError as e:
                    # 记录警告，但不中断计算
                    sys.stderr.write(f"警告: 无法获取文件大小 '{file_path}' (在目录 '{dirpath}' 中) - {e}\n")
                    pass # 忽略无法访问的文件
        return dir_size
    return 0


class ClipboardMonitor(QApplication):
    """
    主应用程序类，处理剪贴板监控并管理弹窗。
    """
    calculation_done = pyqtSignal(str, QWidget)
    # 类变量，用于追踪当前颜色模式（0: 黑底白字, 1: 白底黑字）
    current_color_mode = 0
    # 冷却时间（毫秒）
    COOLDOWN_TIME_MS = 100

    def __init__(self, argv, slide_out_mode=2):
        super().__init__(argv)
        self.slide_out_mode = slide_out_mode  # 将滑出模式储存在实例中
        self.active_popups = []
        self.is_on_cooldown = False  # 标记是否处于冷却状态
        self.calculation_done.connect(self.on_calculation_finished)
        self.setup_clipboard_monitor()

        # --- NEW: 初始化线程池，用于并行文件大小计算 ---
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=os.cpu_count() * 2 if os.cpu_count() else 8 # 至少8个线程，或者CPU核心数的两倍
        )

    def setup_clipboard_monitor(self):
        """设置剪贴板监控机制。"""
        clipboard = self.clipboard()
        clipboard.dataChanged.connect(self.on_clipboard_changed)

    def process_clipboard_data(self):
        """
        处理剪贴板数据，为弹窗准备好所有需要显示的部分。
        返回一个包含显示信息的字典。
        """
        clipboard = self.clipboard()
        mime_data = clipboard.mimeData()

        # --- MODIFIED START: 增强对文件/文件夹类型的判断 ---
        if mime_data.hasUrls():
            urls = mime_data.urls()
            if not urls: return None

            local_paths = [url.toLocalFile() for url in urls if url.isLocalFile() and os.path.exists(url.toLocalFile())]
            if not local_paths: return None

            count = len(local_paths)
            num_files = sum(1 for p in local_paths if os.path.isfile(p))
            num_folders = sum(1 for p in local_paths if os.path.isdir(p))

            top_text = ""
            bottom_template = ""

            if count == 1:
                top_text = os.path.basename(local_paths[0])
                if num_folders == 1:
                    bottom_template = "文件夹: {}"
                else:  # 默认为文件
                    bottom_template = "文件: {}"
            else:  # count > 1
                top_text = "\n".join([os.path.basename(p) for p in local_paths])
                if num_files > 0 and num_folders > 0:
                    bottom_template = f"{count} 个项目: {{}}"
                elif num_folders > 0:  # 仅文件夹
                    bottom_template = f"{count} 个文件夹: {{}}"
                else:  # 仅文件
                    bottom_template = f"{count} 个文件: {{}}"

            return {"type": "file", "top_text": top_text, "bottom_template": bottom_template, "paths": local_paths}
        # --- MODIFIED END ---

        if mime_data.hasImage():
            pixmap = clipboard.pixmap()
            if pixmap.isNull(): return None
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly); pixmap.save(buffer, "PNG"); byte_size = len(buffer.data())
            return {"type": "image", "top_text": f"{pixmap.width()}×{pixmap.height()}", "bottom_text": f"截图: {self.format_size(byte_size)}"}

        if mime_data.hasText():
            text = mime_data.text()
            if not text: return None
            try: byte_size = len(text.encode('gbk'))
            except UnicodeEncodeError: byte_size = len(text.encode('utf-8', 'replace'))
            # return {"type": "text", "top_text": text, "bottom_text": f"&nbsp;&nbsp;&nbsp;{self.format_size(byte_size)}"}
            return {"type": "text", "top_text": text, "bottom_text": f"{self.format_size(byte_size)}"}

        return None

    # --- NEW: 文件大小异步计算，使用内部线程池 ---
    def calculate_total_size_async(self, file_paths, popup, template):
        """
        在后台线程中异步计算所有给定文件和文件夹的总大小，利用线程池并行处理。
        """
        # 提交所有路径的计算任务到类的线程池
        futures = [self.executor.submit(_get_path_size_recursive, path) for path in file_paths]

        # 使用另一个future来等待所有文件大小计算完成，并汇总结果
        def aggregate_and_emit_result_on_main_thread(futures_list):
            total_size = 0
            for future in futures_list:
                try:
                    total_size += future.result()
                except Exception as exc:
                    sys.stderr.write(f"警告: 聚合大小计算时发生错误: {exc}\n")
            # 通过信号将最终结果发送回主UI线程
            self.calculation_done.emit(template.format(self.format_size(total_size)), popup)

        # 在线程池中提交一个聚合任务，它会等待所有子任务完成，然后在主线程触发信号
        self.executor.submit(aggregate_and_emit_result_on_main_thread, futures)

    # --- DELETED: 原始的同步计算函数 calculate_total_size 已被移除 ---
    # 因为它的功能已合并到 _get_path_size_recursive 和新的异步逻辑中

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
        return f"{round(kb / 1024)} <i>Mb</i>"

    def on_clipboard_changed(self):
        """剪贴板变化的主要事件处理程序。"""
        # 检查是否处于冷却状态，如果是则不处理剪贴板变化
        if self.is_on_cooldown:
            return

        data = self.process_clipboard_data()
        if data:
            new_popup = self.show_popup(data)
            if data.get("type") == "file":
                new_popup.update_bottom_text(data["bottom_template"].format("●"))
                self.calculate_total_size_async(data["paths"], new_popup, data["bottom_template"])

    def show_popup(self, data):
        """创建并显示一个新的弹窗。"""
        for popup in self.active_popups[:]:
            popup.slide_out()

        # --- MODIFIED START: 将滑出模式和颜色模式传递给弹窗实例 ---
        new_popup = TransparentPopup(data, self, self.slide_out_mode, self.current_color_mode)
        # 切换颜色模式，为下一个弹窗做准备
        self.current_color_mode = 1 - self.current_color_mode
        # --- MODIFIED END ---
        new_popup.raise_()
        self.active_popups.append(new_popup)

        # 启动冷却时间：设置冷却状态为True，并在冷却时间后自动恢复
        self.is_on_cooldown = True
        QTimer.singleShot(self.COOLDOWN_TIME_MS, lambda: setattr(self, 'is_on_cooldown', False))

        return new_popup

    def close_popup(self, popup):
        """从活动列表中移除并关闭弹窗。"""
        if popup in self.active_popups:
            self.active_popups.remove(popup)
        popup.close()

    # --- NEW: 确保在应用程序退出时关闭线程池 ---
    def __del__(self):
        """
        确保在应用程序退出时关闭线程池，避免资源泄露。
        """
        if hasattr(self, 'executor') and self.executor:
            self.executor.shutdown(wait=True)


class TransparentPopup(QWidget):
    """
    固定大小、带虚线边框和定制布局的弹窗。
    """
    SLIDE_IN_DURATION = 75
    SLIDE_OUT_DURATION = 111
    LIFECYCLE_SECONDS = 19

    # --- MODIFIED START: 接收并保存滑出模式和颜色模式 ---
    def __init__(self, data, monitor, slide_out_mode=2, color_mode=0):
        super().__init__()
        self.monitor = monitor
        self.slide_out_mode = slide_out_mode
        self.color_mode = color_mode  # 0: 黑底白字, 1: 白底黑字

        # 根据颜色模式设置背景色和文字颜色
        if self.color_mode == 0:
            self.background_color = QColor(0, 0, 0, 240)  # 黑色背景
            self.text_color = Qt.white  # 白色文字
            self.border_color = Qt.white  # 白色边框
        else:
            self.background_color = QColor(238, 232, 213, 250)  # 米色背景
            self.text_color = QColor(55, 45, 15)  # 黑咖啡色文字
            self.border_color = QColor(55, 45, 15)  # 黑咖啡色边框
    # --- MODIFIED END ---

        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground); self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.setFixedSize(222, 222)
        layout = QVBoxLayout(self); layout.setContentsMargins(15, 15, 15, 15); layout.setSpacing(10)

        font_fallback_list = ["Consolas", "monospace", "LXGW WenKai GB Screen", "SF Pro", "Segoe UI", "Aptos", "Roboto", "Arial"]
        font = QFont()
        font.setFamilies(font_fallback_list)
        font.setPointSize(11)
        # font.setBold(True)

        self.top_content_label = QLabel(data.get("top_text")); self.top_content_label.setFont(font)
        # 明确设置为普通文本格式以保证性能
        self.top_content_label.setTextFormat(Qt.PlainText)
        # 根据颜色模式设置顶部内容区文字颜色，只有白色背景模式下文字加粗
        if self.color_mode == 0:
            self.top_content_label.setStyleSheet("color: #ffffff;")  # 黑色背景模式不加粗
        else:
            self.top_content_label.setStyleSheet(f"color: rgb({self.text_color.red()}, {self.text_color.green()}, {self.text_color.blue()}); font-weight: bold;")  # 白色背景模式加粗
        self.top_content_label.setWordWrap(True)
        self.top_content_label.setAlignment(Qt.AlignTop | Qt.AlignLeft); self.top_content_label.setMaximumHeight(162)

        self.bottom_message_label = QLabel(data.get("bottom_text", "")); self.bottom_message_label.setFont(font)
        # 底部信息区文字颜色设置：黑色背景保持暗金色，白色背景使用更红黑的颜色
        if self.color_mode == 0:
            self.bottom_message_label.setStyleSheet("color: #cd853f;")  # 黑色背景模式不加粗
        else:
            self.bottom_message_label.setStyleSheet("color: #8B4513; font-weight: bold;")  # 白色背景模式使用红棕色，更红、更黑
        self.bottom_message_label.setAlignment(Qt.AlignBottom | Qt.AlignLeft)
        self.bottom_message_label.setTextFormat(Qt.RichText)  # 启用富文本格式以支持斜体显示

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

    # --- MODIFIED START: 重写 slide_out 方法以支持两种模式 ---
    def slide_out(self):
        """根据设定的模式执行不同的滑出动画。"""
        if hasattr(self, 'lifecycle_timer'): self.lifecycle_timer.stop()
        if hasattr(self, 'is_sliding_out') and self.is_sliding_out: return
        self.is_sliding_out = True

        # 模式 1: 向下滑出 (原有模式)
        if self.slide_out_mode == 1:
            self.slide_anim = QPropertyAnimation(self, b"pos")
            self.slide_anim.setDuration(self.SLIDE_OUT_DURATION)
            self.slide_anim.setStartValue(self.pos())
            self.slide_anim.setEndValue(QPoint(self.x(), self.target_screen_geom.bottom()))
            self.slide_anim.finished.connect(lambda: self.monitor.close_popup(self))
            self.slide_anim.start(QPropertyAnimation.DeleteWhenStopped)

        # 模式 2: 向左滑行并淡出 (新模式)
        else:
            self.anim_group = QParallelAnimationGroup(self)

            # 动画1: 透明度变化 (从1到0)
            opacity_anim = QPropertyAnimation(self, b"windowOpacity")
            opacity_anim.setDuration(self.SLIDE_OUT_DURATION)
            opacity_anim.setStartValue(1.0)
            opacity_anim.setEndValue(0.0)
            opacity_anim.setEasingCurve(QEasingCurve.InQuad)

            # 动画2: 位置变化 (向左移动80像素)
            pos_anim = QPropertyAnimation(self, b"pos")
            pos_anim.setDuration(self.SLIDE_OUT_DURATION)
            pos_anim.setStartValue(self.pos())
            pos_anim.setEndValue(QPoint(self.x() - 80, self.y()))
            pos_anim.setEasingCurve(QEasingCurve.OutQuad)

            self.anim_group.addAnimation(opacity_anim)
            self.anim_group.addAnimation(pos_anim)

            # 动画组完成后再关闭窗口
            self.anim_group.finished.connect(lambda: self.monitor.close_popup(self))
            self.anim_group.start(QAbstractAnimation.DeleteWhenStopped)
    # --- MODIFIED END ---

    def move_to_initial_position(self):
        """将窗口移动到当前屏幕的右侧外部。"""
        self.move(self.target_screen_geom.right(), self.target_screen_geom.bottom() - self.height() - 40)

    def slide_in(self):
        """动画化弹窗从当前屏幕的右侧滑入。"""
        end_pos = QPoint(self.target_screen_geom.right() - self.width() - 40, self.y())

        self.slide_anim = QPropertyAnimation(self, b"pos"); self.slide_anim.setDuration(self.SLIDE_IN_DURATION)
        self.slide_anim.setStartValue(self.pos()); self.slide_anim.setEndValue(end_pos)
        self.slide_anim.start(QPropertyAnimation.DeleteWhenStopped)

    def update_bottom_text(self, text):
        self.bottom_message_label.setText(text)

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.background_color) # 使用根据颜色模式设置的背景色
        pen = QPen(self.border_color, 1, Qt.DashLine); painter.setPen(pen)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

if __name__ == "__main__":
    # --- 滑出模式开关 ---
    # 1: 向下滑出 (原有模式)
    # 2: 向左滑行并淡出 (新模式)
    SLIDE_OUT_MODE = 2  # 在这里选择模式，默认为 2

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    # --- MODIFIED START: 将滑出模式传入主程序 ---
    app = ClipboardMonitor(sys.argv, slide_out_mode=SLIDE_OUT_MODE)
    # --- MODIFIED END ---

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
