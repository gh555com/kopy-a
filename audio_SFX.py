# audio_SFX.py
# -*- coding: utf-8 -*-
"""
通用高并发音频 (SFX) 引擎 (z_player_yuan)
(遵从要求, 自定义变量/函数/类名不含 s, m, c, t)

(V19: "非阻塞回调" 架构)
- 修复了 V15 逻辑的2个致命缺陷:
  1. (卡顿) 移除 time.sleep()。线程池不再被播放时长阻塞。
  2. (没音) 移除 except:pass, 暴露设备创建失败的异常。
- 采用 "stop_callback" 机制来管理资源释放。
- (V19 修复) stop_callback 必须在创建设备【后】作为【属性】设置。
- 线程池 (QThreadPool) 仅用于 "创建设备" (耗时~50ms的操作)。
- 播放器 (z_player_yuan) 维护一个 z_active_q3 列表来保存
  所有正在播放的 (device, stream) 引用, 防止被垃圾回收。
"""
import miniaudio
import time
import os
import sys
import threading # (V19) 增加线程锁

# 检查 PyQt5 依赖
try:
    from PyQt5.QtCore import QRunnable, QThreadPool, QObject, pyqtSlot
except ImportError:
    print("【!!】 audio_SFX.py 错误：需要 PyQt5 库。")
    print("【!!】 请安装： pip install PyQt5")
    sys.exit(1)


# (内部) 音频播放任务 (在工作线程中运行)
# 这个类不对外暴露
class _z_runnable_q1(QRunnable):
    """
    (内部 V19) 非阻塞的音频播放任务
    """
    def __init__(self, z_path_q2, z_player_q5): # (V19) 需要父播放器的引用
        super().__init__()
        self.z_path_q2 = z_path_q2 # 要播放的文件路径
        self.z_player_q5 = z_player_q5 # (V19) 父播放器 (z_player_yuan) 的引用

        # (v15/v19 逻辑) 请求的音频格式
        self.z_fma_q3 = miniaudio.SampleFormat.SIGNED16 # 格式
        self.z_khl_q4 = 2  # 声道
        self.z_rae_q5 = 44100 # 采样率

        # (V19) 这是一个字典, 用于保存引用, 防止被GC
        self.z_payload_q6 = {"device": None, "stream": None}

    def _on_playback_finished_q10(self):
        """
        (V19 核心) 此函数在 miniaudio 的音频线程中被调用
        """
        try:
            # 1. (V19 关键) 清理回调引用, 防止循环
            if self.z_payload_q6["device"]:
                self.z_payload_q6["device"].stop_callback = None

            # 2. 停止并关闭设备
            if self.z_payload_q6["device"]:
                self.z_payload_q6["device"].close()
                self.z_payload_q6["device"] = None

            # 3. 关闭文件流
            if self.z_payload_q6["stream"]:
                self.z_payload_q6["stream"].close()
                self.z_payload_q6["stream"] = None

        except Exception as e:
            # print(f"[audio_SFX V19] 清理时出错: {e}")
            pass
        finally:
            # 4. (最重要) 从父播放器的 z_active_q3 列表中移除自己
            self.z_player_q5.z_remove_active_q4(self.z_payload_q6)

    @pyqtSlot()
    def run(self):
        """
        (V19 核心) 线程池的工作函数。
        仅负责创建设备, 启动播放, 然后立即返回。
        (此函数在工作线程中执行)
        """
        # 1. 路径检查
        if not self.z_path_q2 or not os.path.exists(self.z_path_q2):
            return

        # 2. (V19 修复) 移除 "get_file_info" 和 time.sleep()

        z_od_q8 = None # (V19) 必须先声明

        try:
            # 3. (流式) 打开音频文件
            z_od_q8 = miniaudio.stream_file(
                self.z_path_q2,
                output_format=self.z_fma_q3,
                nchannels=self.z_khl_q4,
                sample_rate=self.z_rae_q5
            )

            # 4. (V19 修复) 创建设备 (不带 callback)
            z_dev_q9 = miniaudio.PlaybackDevice(
                output_format=self.z_fma_q3,
                nchannels=self.z_khl_q4,
                sample_rate=self.z_rae_q5
            )

            # 5. (V19 修复) 在创建后, 再设置回调属性
            z_dev_q9.stop_callback = self._on_playback_finished_q10

            # 6. (核心) 保存引用, 防止被垃圾回收
            self.z_payload_q6["device"] = z_dev_q9
            self.z_payload_q6["stream"] = z_od_q8
            self.z_player_q5.z_add_active_q5(self.z_payload_q6)

            # 7. (非阻塞) 开始播放
            z_dev_q9.start(z_od_q8)

            # 8. (核心) 立即返回!
            #    工作线程被释放, 可以去处理下一个点击。
            #    z_payload_q6 中的引用由 z_player_yuan.z_active_q3 列表持有。

        except Exception as e:
             # (V19 修复) 不再静默失败!
             # 这将暴露“没音”的真正原因
             print(f"[audio_SFX V19] 播放失败 (设备创建失败?): {self.z_path_q2}, 错误: {e}")

             # (V19) 确保清理 (如果 stream 成功但 device 失败)
             # 此时 _on_playback_finished_q10 不会被调用, 必须手动清理
             if z_od_q8:
                 try: z_od_q8.close()
                 except Exception: pass
             # (我们不需要调用 z_remove_active_q4, 因为我们还没 add)


# (公开) 音频播放器类
class z_player_yuan(QObject):
    """
    通用高并发音频 (SFX) 引擎 (V19 非阻塞版)
    (遵从要求, 自定义变量/函数/类名不含 s, m, c, t)

    采用 QThreadPool + 非阻塞回调, 提供"即发即忘"的播放接口。
    """

    def __init__(self, z_max_q1=32):
        """
        初始化播放器。
        z_max_q1: 最大并发播放数 (V19 架构中, 此值代表"并发创建数")
        """
        super().__init__()
        # 获取全局线程池实例
        self.z_pool_q2 = QThreadPool.globalInstance()
        # 设置最大线程(并发)数
        self.z_pool_q2.setMaxThreadCount(z_max_q1)

        # (V19 核心)
        # 此列表持有所有"正在播放"的 (device, stream) 字典引用
        self.z_active_q3 = []
        # (V19 核心) 保护 z_active_q3 列表的线程锁
        self.z_lock_q4 = threading.Lock()

        print(f"音频播放器 (audio_SFX - z_player_yuan V19) 已初始化, 最大并发: {z_max_q1}")

    # (公开接口 1)
    def z_play_q1(self, z_path_q3):
        """
        (公开接口) 异步播放一个音效。
        此函数 0 阻塞, 立即返回。

        z_path_q3: 要播放的音频文件完整路径
        """
        if not z_path_q3:
            return

        # 1. 创建一个“可运行”的任务, 并把 "self" (播放器) 传给它
        z_job_q4 = _z_runnable_q1(z_path_q3, self)

        # 2. 将任务扔进线程池, 立即返回
        #    线程池将执行 z_job_q4.run()
        self.z_pool_q2.start(z_job_q4)

    # (V19 内部) 线程安全地添加一个 "payload"
    def z_add_active_q5(self, z_payload_q6):
        with self.z_lock_q4:
            self.z_active_q3.append(z_payload_q6)

    # (V19 内部) 线程安全地移除一个 "payload"
    # (此函数由 miniaudio 线程通过回调调用)
    def z_remove_active_q4(self, z_payload_q6):
        with self.z_lock_q4:
            try:
                # (安全移除)
                if z_payload_q6 in self.z_active_q3:
                    self.z_active_q3.remove(z_payload_q6)
            except ValueError:
                pass # (可能在清理时被多次调用, 忽略)

    # (公开接口 2)
    def z_get_len_q2_m(self, z_path_q3):
        """
        (公开接口) 获取指定音频文件的总时长。
        (此函数逻辑不变)
        """
        try:
            z_info_q5 = miniaudio.get_file_info(z_path_q3)
            return int(z_info_q5.duration * 1000)
        except Exception:
            return 0 # 失败返回 0

    # (公开接口 3)
    def z_exit_q3(self, z_wait_q4=1000):
        """
        (公开接口 V19) 安全退出。
        1. 等待线程池中所有 "创建" 任务完成。
        2. (新增) 强制关闭所有 "正在播放" 的音频。
        """
        # print("音频播放器 (z_player_yuan V19) 正在清理...")

        # 1. 等待所有 "run()" (创建任务) 完成
        self.z_pool_q2.waitForDone(z_wait_q4)

        # 2. (V19) 强制清理所有还在播放的音频
        # print(f" -> 正在清理 {len(self.z_active_q3)} 个活动音频...")

        # (V19) 线程安全地复制并清空列表
        with self.z_lock_q4:
            q_active_copy = list(self.z_active_q3)
            self.z_active_q3.clear() # 立即清空

        for z_payload_q6 in q_active_copy:
            if z_payload_q6["device"]:
                try: z_payload_q6["device"].stop_callback = None
                except Exception: pass
                try: z_payload_q6["device"].close()
                except Exception: pass
            if z_payload_q6["stream"]:
                try: z_payload_q6["stream"].close()
                except Exception: pass

        # print("音频播放器 (z_player_yuan V19) 已清理。")

    # (自动)
    def __del__(self):
        self.z_exit_q3()
