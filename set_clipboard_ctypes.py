import ctypes

# 设置剪贴板内容
ctypes.windll.user32.OpenClipboard(0)
ctypes.windll.user32.EmptyClipboard()
ctypes.windll.user32.SetClipboardTextW("测试Z区域功能")
ctypes.windll.user32.CloseClipboard()

print("剪贴板内容已设置")