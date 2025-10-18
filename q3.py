# --- 在 StickyTextEdit.__init__ 中 ---

# v4.5.15 (错误的代码):
# self.setDragEnabled(False)

# v4.5.16 (修正后的代码):
self.setAcceptDrops(False)
