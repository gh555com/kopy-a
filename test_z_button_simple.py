#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
简单测试Z按钮功能
"""
import sys
import builtins

# 定义log_message函数并添加到builtins
def log_message(message):
    print(message)
builtins.log_message = log_message

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer
from q3 import ClipboardMonitor, TransparentPopup

def test_z_button_simple():
    app = QApplication(sys.argv)
    
    # 创建ClipboardMonitor实例
    monitor = ClipboardMonitor([])
    
    # 创建测试弹窗
    test_data = {
        "top_text_snippet": "测试Z区域按钮功能",
        "bottom_text": "点击Z按钮只播放z音效"
    }
    
    popup = TransparentPopup(test_data, monitor)
    
    # 显示弹窗
    popup.show()
    
    # 模拟点击Z按钮
    def simulate_click():
        print("模拟点击Z按钮...")
        popup.play_z_sound_only()
        print("Z音效播放完成")
        
        # 1秒后再次点击测试连续播放
        QTimer.singleShot(1000, simulate_click_again)
    
    def simulate_click_again():
        print("再次点击Z按钮...")
        popup.play_z_sound_only()
        print("第二次Z音效播放完成")
        
        # 1秒后退出
        QTimer.singleShot(1000, app.quit)
    
    # 1秒后开始模拟点击
    QTimer.singleShot(1000, simulate_click)
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    test_z_button_simple()