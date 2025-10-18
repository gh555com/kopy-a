# --- 替换旧的 ClickJumpScrollBar 类 ---
class ClickJumpScrollBar(QScrollBar):
    """
    v4.5.25: 滚动条 Bug 最终修复 (v3)。

    v4.5.23 和 v4.5.24 使用 QStyle.hitTestComplexControl 的尝试失败了。
    此版本切换到使用 QStyle.subControlRect 来手动检查点击位置，
    这种方法更底层，更可靠，不受自定义样式的影响。

    逻辑:
    1. 如果是右键点击 -> 交给 super() 处理 (菜单)。
    2. 主动获取 "滑块"、"上箭头"、"下箭头" 的精确矩形区域 (Rect)。
    3. 如果点击坐标在上述任一矩形内 -> 立即交给 super() 处理 (恢复拖动/箭头)。
    4. 如果点击坐标不在上述矩形内 (即在轨道空白处) -> 才执行自定义的“点击跳转”逻辑。
    """
    def mousePressEvent(self, event):
        # 1. 保留右键菜单功能
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        opt = QStyleOptionSlider()
        self.initStyleOption(opt)

        # 2. 主动获取所有子控件的矩形区域
        handle_rect = self.style().subControlRect(QStyle.CC_ScrollBar, opt, QStyle.SC_ScrollBarSlider, self)
        add_line_rect = self.style().subControlRect(QStyle.CC_ScrollBar, opt, QStyle.SC_ScrollBarAddLine, self)
        sub_line_rect = self.style().subControlRect(QStyle.CC_ScrollBar, opt, QStyle.SC_ScrollBarSubLine, self)

        click_pos = event.pos()

        # 3. 优先放行: 如果点击在滑块或箭头上，则完全交由父类处理
        if handle_rect.contains(click_pos) or \
           add_line_rect.contains(click_pos) or \
           sub_line_rect.contains(click_pos):
            super().mousePressEvent(event)
            return

        # 4. 如果代码执行到这里，说明 100% 点击在了轨道空白处

        # 获取 handle_rect 用于计算，即使点击不在 handle 上
        if handle_rect.isNull():
             handle_rect = QRect(0, 0, 0, 0) # 安全保护

        if self.orientation() == Qt.Vertical:
            # 使用 handle_rect.height() 而不是 0 来正确计算
            available_space = self.height() - handle_rect.height()
            click_pos_val = event.y() - handle_rect.height() / 2
        else:
            available_space = self.width() - handle_rect.width()
            click_pos_val = event.x() - handle_rect.width() / 2

        if available_space > 0:
            ratio = max(0.0, min(1.0, click_pos_val / available_space))
            new_value = self.minimum() + ratio * (self.maximum() - self.minimum())
            self.setValue(int(new_value))

        event.accept()
        return
