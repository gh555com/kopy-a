#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import time
from PySide2.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLabel
from PySide2.QtCore import QTimer, Qt
from PySide2.QtGui import QClipboard

class q1(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("剪贴板测试程序")
        self.setFixedSize(300, 200)

        self.q2()
        self.q3 = QApplication.clipboard()
        self.q4()

    def q2(self):
        from PySide2.QtGui import QGuiApplication
        q5 = QGuiApplication.primaryScreen()
        q6 = q5.availableGeometry()
        q7 = self.frameGeometry()
        q8 = q6.center()
        q7.moveCenter(q8)
        self.move(q7.topLeft())

    def q4(self):
        q9 = QVBoxLayout()

        q10 = QLabel("点击按钮复制文本到剪贴板")
        q10.setAlignment(Qt.AlignCenter)
        q9.addWidget(q10)

        q11 = QPushButton("50次复制")
        q11.clicked.connect(lambda: self.q12(50))
        q9.addWidget(q11)

        q13 = QPushButton("200次复制")
        q13.clicked.connect(lambda: self.q12(200))
        q9.addWidget(q13)

        q14 = QPushButton("2000次复制")
        q14.clicked.connect(lambda: self.q12(2000))
        q9.addWidget(q14)

        self.q15 = QLabel("准备就绪")
        self.q15.setAlignment(Qt.AlignCenter)
        q9.addWidget(self.q15)

        self.setLayout(q9)

    def q12(self, q16):
        q17 = "这是测试文本 - 班次编号: "

        self.q15.setText(f"正在复制 {q16} 次...")
        QApplication.processEvents()

        self.q18 = 0
        self.q19 = q16
        self.q20 = q17

        QTimer.singleShot(10, self.q21)

    def q21(self):
        if self.q18 < self.q19:
            self.q18 += 1
            q22 = self.q20 + str(self.q18)

            self.q3.setText(q22)

            self.q15.setText(f"已复制 {self.q18}/{self.q19} 次")
            QApplication.processEvents()

            QTimer.singleShot(1, self.q21)
        else:
            self.q15.setText(f"完成! 已复制 {self.q19} 次")

if __name__ == "__main__":
    q23 = QApplication(sys.argv)
    q24 = q1()
    q24.show()
    sys.exit(q23.exec_())