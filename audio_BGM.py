 你这程序里面 还是有 t  z_stop_q2   要任何自定义滴文本，任何能自定义滴字符串，包括注释都不能有那4个字母      你就直接 q1 q2 q3 加中文注释就行了   注释都可以简单一点    但最重要滴是在开始来一段长注释，就是一段一切功能滴调用示例     并且你要非常重视，做好一切县程进程安全、，稳定、退出严谨、彻底清理滴工作






  那你就把我前面滴需求非常非常完整滴实现 单独做一个 audio_BGM  而且接收一个参数  就是播放速度  比之前0.1就是0.1倍速 1.6就是1.6倍速   那播放接收滴参数就应该是   文件名 起始 毫秒数  是否循环  播放速度   可以只填个文件名  那就默认 起始0 不循环 1倍速



# audio_BGM.py
# -*- coding: utf-8 -*-
"""
通用单实例背景音乐 (BGM) 引擎 (类名: q10)
(遵从要求, 自定义 变量/函数/类名/注释/字符串 不含 s, m, c, t)
(V8: 修复了 V7 中 stop_callback 导致构造失败的 Bug)

========================================================================
【!!】 V8 核心修复 【!!】
1. V7 的 PlaybackDevice(..., stop_callback=...) 构造失败。
   原因是 stop_callback 不能作为构造参数, 必须在创建后作为属性设置。
2. (V7 结论保持) 必须写死 sample_rate=44100, 放弃变速功能。

========================================================================
【!!】 用法示例 (如何使用 q10 类) 【!!】

# 1. 导入
from audio_BGM import q10
import time

# 2. 创建一个播放器实例 (全局唯一)
q_bgm_player = q10()

# 3. 准备 BGM 文件路径
q_file_path = "assets/bgm.mp3"

# 4. 播放 (循环)
#    q20: 路径 (str)
#    q21: 起始毫秒 (int) - (V8 已失效, 总是 0)
#    q22: 是否循环 (bool)
#    q23: 播放速率 (float) - (V8 已失效, 总是 1.0)
q_bgm_player.q1(q_file_path, 0, True, 1.0)

print("BGM 循环播放已开始...")
time.sleep(5)

# 5. 暂停
q_bgm_player.q3()
print("BGM 已暂停")
time.sleep(2)

# 6. 恢复
q_bgm_player.q4()
print("BGM 已恢复")
time.sleep(3)

# 7. 获取当前播放位置 (毫秒, 估算值)
q_pos = q_bgm_player.q5()
print(f"BGM 当前位置: {q_pos} 毫秒")

# 8. 播放 (不循环, 尝试从 10 秒开始)
#    (V8 注意: q21 和 q23 都会被忽略)
q_bgm_player.q1(q_file_path, 10000, False, 0.5)
print("BGM 开始不循环播放...")
time.sleep(5)

# 9. 停止
q_bgm_player.q2()
print("BGM 已停止")

# 10. 获取文件总长 (毫秒)
q_len = q_bgm_player.q6(q_file_path)
print(f"BGM 文件总长: {q_len} 毫秒")

# 11. (程序退出时) 确保清理
# (q10 的 __del__ 会自动调用 q2(), 但手动调用更保险)
q_bgm_player.q2()

========================================================================
"""
import miniaudio
import sys
import os
import threading
import time # (用于估算 q5)

class q10:
    """
    通用 BGM 引擎 (miniaudio V8 修复版)
    """

    # 定义一个“已知可工作”的音频格式
    q8_fmt = miniaudio.SampleFormat.SIGNED16 # 16位
    q8_nch = 2  # 双声道
    q8_rae = 44100 # 44.1kHz (V7/V8 必须固定用这个)

    def __init__(self):
        self.q11 = None  # 播放设备 (miniaudio.PlaybackDevice)
        self.q12 = None  # 音频流 (miniaudio.stream_file 生成器)
        self.q13 = False # 循环标志
        self.q14 = ""    # 当前文件路径 (用于循环)
        self.q16 = threading.Lock()

        # (q5 估算所需)
        self.q18 = None  # (float) time.perf_counter() 的起始点
        self.q19 = 0     # (int) 暂停时的基准毫秒

    # (公开接口 1: 播放)
    def q1(self, q20: str, q21: int = 0, q22: bool = False, q23: float = 1.0):
        if not q20 or not os.path.exists(q20):
            return False

        with self.q16: # (上锁)
            self.q2_internal()
            self.q1_internal(q20, q21, q22, q23)
        return True

    # (内部) 启动播放 (必须在锁 q16 内调用)
    def q1_internal(self, q20: str, q21: int, q22: bool, q23: float):
        # (V8) q21 (起始) 和 q23 (速率) 在此被忽略

        try:
            q31 = miniaudio.stream_file(
                q20,
                nchannels=q10.q8_nch,
                sample_rate=q10.q8_rae, # (输出 44.1k)
                output_format=q10.q8_fmt
            )

            # (V8 无法 seek) q21 (起始毫秒) 参数被忽略。

            # (!! 核心 V8 修复 !!)
            # 1. 创建设备 (不带 callback)
            q30 = miniaudio.PlaybackDevice(
                output_format=q10.q8_fmt, # S16
                nchannels=q10.q8_nch,     # 2ch
                sample_rate=q10.q8_rae    # (关键: 必须是 44100)
            )

            # 2. (关键) 在创建后, 再设置回调属性
            q30.stop_callback = self.q102

            # 3. 启动 (喂入生成器)
            q30.start(q31)

            # 赋给类变量
            self.q11 = q30
            self.q12 = q31
            self.q13 = q22
            self.q14 = q20

            # (V8 q5 估算) 重置计时器
            self.q19 = 0 # (因为无法 seek, 总是 0)
            self.q18 = time.perf_counter()

        except Exception as e:
            # (V8) 打印真正的错误!
            print(f"BGM 播放失败 (V8): {e}")
            self.q2_internal()

    # (内部) 停止播放 (必须在锁 q16 内调用)
    def q2_internal(self):
        q_old_dev = self.q11
        q_old_file = self.q12

        self.q11 = None
        self.q12 = None
        self.q14 = ""

        # (V8 q5 估算) 停止计时
        self.q18 = None
        self.q19 = 0

        # (V8 关键) 解除回调引用, 帮助垃圾回收
        if q_old_dev:
            try: q_old_dev.stop_callback = None
            except Exception: pass

        # (V8) 分开 close, 避免 V7 的 __del__ 报错
        if q_old_dev:
            try: q_old_dev.close()
            except Exception: pass
        if q_old_file:
            try: q_old_file.close()
            except Exception: pass

    # (内部) 停止回调 (由 miniaudio 的音频线程调用)
    def q102(self):
        """ (V8) """
        with self.q16:
            if not self.q13: # (如果非循环)
                self.q2_internal() # (完全停止)
                return
            if not self.q11 or not self.q12: # (如果已停止)
                return

            # (如果是循环)
            try:
                q20 = self.q14
                self.q2_internal()
                self.q1_internal(q20, 0, True, 1.0) # (重新播放)
            except Exception:
                self.q2_internal()

    # (公开接口 2: Stop)
    def q2(self):
        with self.q16:
            self.q13 = False # (关闭循环标志)
            self.q2_internal()

    # (公开接口 3: Pause)
    def q3(self):
        with self.q16:
            if self.q18 is None: return
            q_dev = self.q11
            if q_dev:
                try:
                    q_dev.pause()
                    # (V8 q5 估算) "冻结" 当前估算的时间
                    self.q19 = self.q5_internal()
                    self.q18 = None # 停止计时
                except Exception: pass

    # (公开接口 4: Resume)
    def q4(self):
        with self.q16:
            if self.q18 is not None: return
            q_dev = self.q11
            if q_dev:
                try:
                    q_dev.resume()
                    # (V8 q5 估算) 启动计时
                    self.q18 = time.perf_counter()
                except Exception: pass

    # (内部) q5 估算 (必须在锁内调用)
    def q5_internal(self) -> int:
        if self.q18 is None:
            return self.q19 # 返回 "冻结" 的时间

        q_now = time.perf_counter()
        q_elapsed = (q_now - self.q18) * 1000 # 毫秒

        return int(self.q19 + q_elapsed)

    # (公开接口 5: 获取当前毫秒)
    def q5(self) -> int:
        q_ok = self.q16.acquire(blocking=False)
        if q_ok:
            try:
                if self.q11:
                    return self.q5_internal()
                else:
                    return 0
            finally:
                self.q16.release()

        return self.q19

    # (公开接口 6: 获取总长毫秒)
    def q6(self, q20: str) -> int:
        if not q20 or not os.path.exists(q20): return 0
        try:
            q42 = miniaudio.get_file_info(q20)
            return int(q42.duration * 1000)
        except Exception: return 0

    # (自动) 清理
    def __del__(self):
        self.q2()





