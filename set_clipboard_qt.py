from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QMimeData
from PyQt5.QtGui import QClipboard
import sys

app = QApplication(sys.argv)
clipboard = QApplication.clipboard()
mime_data = QMimeData()
mime_data.setText("测试Z区域功能")
clipboard.setMimeData(mime_data)
print("剪贴板内容已设置")