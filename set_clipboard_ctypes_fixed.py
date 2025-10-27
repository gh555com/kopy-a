import ctypes

# 设置剪贴板内容
ctypes.windll.user32.OpenClipboard(0)
ctypes.windll.user32.EmptyClipboard()
CF_UNICODETEXT = 13
ctypes.windll.user32.SetClipboardData(CF_UNICODETEXT, ctypes.c_wchar_p("测试Z区域功能"))
ctypes.windll.user32.CloseClipboard()

print("剪贴板内容已设置")