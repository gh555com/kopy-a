#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试Z区域按钮功能
"""
import sys
import builtins

# 定义log_message函数并添加到builtins
def log_message(message):
    print(message)
builtins.log_message = log_message

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLabel
from PyQt5.QtCore import QTimer
from q3 import ClipboardMonitor, TransparentPopup

def test_z_button():
    app = QApplication(sys.argv)
    
    # 创建ClipboardMonitor实例
    monitor = ClipboardMonitor([])
    
    # 创建测试弹窗
    test_data = {
        "top_text_snippet": "测试Z区域按钮功能\n点击Z按钮只播放z音效",
        "bottom_text": "Z区域按钮测试"
    }
    
    popup = TransparentPopup(test_data, monitor)
    
    # 添加测试说明
    info_label = QLabel("测试说明：\n1. 点击Z区域右上角的白色按钮\n2. 应该只播放z音效，不执行其他操作\n3. 可以连续点击测试音效播放")
    info_label.setStyleSheet("""
        QLabel {
            background-color: rgba(255, 255, 255, 200);
            border: 1px solid black;
            padding: 10px;
            font-size: 12px;
        }
    """)
    info_label.setParent(popup)
    info_label.move(10, 10)
    info_label.show()
    
    # 显示弹窗
    popup.show()
    
    # 5秒后自动关闭
    QTimer.singleShot(5000, app.quit)
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    test_z_button()