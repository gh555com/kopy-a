# miniaudio_nonblocking.py
# 基于q2.py的v15逻辑，但修改为支持多线程非阻塞播放
# 允许多个音频同时播放，实现0延迟音频反馈

import miniaudio
import time
import os
import random
import threading
import queue
import concurrent.futures

class NonBlockingAudioEngine:
    def __init__(self, asset_folder="assets"):
        print("非阻塞音频引擎 (NonBlockingAudioEngine) 正在初始化...")
        self.asset_folder = asset_folder
        self.sound_files = {
            'main': [],  # [1-8] 音效
            'q': [],     # q[1-9] 音效
            'z': []      # z[1-6] 音效
        }
        self.last_played_index = {
            'main': -1,
            'q': -1,
            'z': -1
        }

        # --- 从 v15 脚本中提取的音频格式设置 ---
        self.REQUESTED_FORMAT = miniaudio.SampleFormat.SIGNED16
        self.REQUESTED_CHANNELS = 2
        self.REQUESTED_RATE = 44100
        # ---------------------------------------------

        # 创建线程池用于音频播放
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=32)  # 支持32个并发音频播放
        
        # 启动时检查文件是否存在
        self._check_files()
        print("非阻塞音频引擎初始化完毕，所有音效文件均已找到。")

    def _check_files(self):
        """检查所有必需的音效文件是否存在，优先使用wav格式。"""
        if not os.path.isdir(self.asset_folder):
            raise FileNotFoundError(f"错误：找不到资源文件夹 '{self.asset_folder}'")

        import glob
        
        # 查找所有音效文件，优先使用wav格式
        main_files = glob.glob(os.path.join(self.asset_folder, '[1-8].wav'))
        if not main_files:  # 如果没有wav文件，则查找mp3文件
            main_files = glob.glob(os.path.join(self.asset_folder, '[1-8].mp3'))
        
        q_files = glob.glob(os.path.join(self.asset_folder, 'q[1-9].wav'))
        if not q_files:  # 如果没有wav文件，则查找mp3文件
            q_files = glob.glob(os.path.join(self.asset_folder, 'q[1-9].mp3'))
        
        z_files = glob.glob(os.path.join(self.asset_folder, 'z[1-6].wav'))
        if not z_files:  # 如果没有wav文件，则查找mp3文件
            z_files = glob.glob(os.path.join(self.asset_folder, 'z[1-6].mp3'))
        
        self.sound_files['main'] = sorted(main_files)
        self.sound_files['q'] = sorted(q_files)
        self.sound_files['z'] = sorted(z_files)
        
        print(f" -> 成功在 '{self.asset_folder}' 中找到 {len(self.sound_files['main'])} 个 [1-8] 音效。")
        print(f" -> 成功在 '{self.asset_folder}' 中找到 {len(self.sound_files['q'])} 个 q 系列音效。")
        print(f" -> 成功在 '{self.asset_folder}' 中找到 {len(self.sound_files['z'])} 个 z 系列音效。")

    def get_random_sound_file(self, sound_type='main'):
        """
        获取一个随机的音效文件路径，并确保它与上一个不同。
        sound_type: 'main', 'q', 或 'z'
        """
        if sound_type not in self.sound_files:
            return None
            
        sound_list = self.sound_files[sound_type]
        if len(sound_list) == 0:
            return None
        if len(sound_list) == 1:
            return sound_list[0]

        new_index = self.last_played_index[sound_type]
        # 循环直到找到一个与上一个不同的索引
        while new_index == self.last_played_index[sound_type]:
            new_index = random.randint(0, len(sound_list) - 1)

        self.last_played_index[sound_type] = new_index
        return sound_list[new_index]

    def play_sound_nonblocking(self, file_path):
        """
        非阻塞播放音效。
        此函数会立即返回，音频在后台线程中播放。
        """
        if not file_path or not os.path.exists(file_path):
            return
            
        # 提交播放任务到线程池
        self.executor.submit(self._play_sound_worker, file_path)

    def _play_sound_worker(self, file_path):
        """
        工作线程函数，实际执行音频播放。
        这是基于 v15 逻辑的完整播放流程。
        """
        sound = None
        device = None
        file_duration = 0.0

        # (v15) [步骤 1/5] 获取文件信息
        try:
            file_info = miniaudio.get_file_info(file_path)
            file_duration = file_info.duration
            if file_duration <= 0:
                raise ValueError("无法获取文件时长或时长为 0。")
        except Exception as e:
            print(f"【!!】 [音频引擎] 步骤 1 (获取文件信息) 失败: {e}")
            return

        # [步骤 2/5] 尝试将文件作为 "流" 打开
        try:
            sound = miniaudio.stream_file(
                file_path,
                output_format=self.REQUESTED_FORMAT,
                nchannels=self.REQUESTED_CHANNELS,
                sample_rate=self.REQUESTED_RATE
            )
        except Exception as e:
            print(f"【!!】 [音频引擎] 步骤 2 (打开流) 失败: {e}")
            return

        # [步骤 3/5] 尝试初始化回放设备
        try:
            device = miniaudio.PlaybackDevice(
                output_format=self.REQUESTED_FORMAT,
                nchannels=self.REQUESTED_CHANNELS,
                sample_rate=self.REQUESTED_RATE
            )
        except Exception as e:
            print(f"【!!】 [音频引擎] 步骤 3 (初始化设备) 失败: {e}")
            if sound: 
                sound.close()
            return

        # [步骤 4/5] 启动设备 和 [步骤 5/5] 等待播放完成
        try:
            device.start(sound)
            
            # (v15) [步骤 5/5] 等待播放完成
            wait_time = file_duration + 0.1  # 稍微增加一个小的缓冲区
            time.sleep(wait_time)  # 在工作线程中等待，不阻塞主线程

        except Exception as e:
            print(f"\n【!!】 [音频引擎] 步骤 4/5 (启动或等待) 期间失败: {e}")
        finally:
            # (v15) 彻底关闭资源
            if device:
                try:
                    device.stop()
                except Exception as e:
                    pass  # 忽略 stop 时的错误
                device.close()

            if sound:
                sound.close()

    def play_random_sound(self):
        """播放随机主音效"""
        file_path = self.get_random_sound_file('main')
        if file_path:
            self.play_sound_nonblocking(file_path)

    def play_q_sound(self):
        """播放随机q音效"""
        file_path = self.get_random_sound_file('q')
        if file_path:
            self.play_sound_nonblocking(file_path)

    def play_z_sound(self):
        """播放随机z音效"""
        file_path = self.get_random_sound_file('z')
        if file_path:
            self.play_sound_nonblocking(file_path)

    def cleanup(self):
        """清理资源"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)


# --- 用于独立测试此模块 ---
if __name__ == "__main__":
    print("="*30)
    print("正在独立测试 NonBlockingAudioEngine 模块...")

    try:
        engine = NonBlockingAudioEngine(asset_folder="assets")
        
        # 测试连续播放多个音效
        print("\n测试连续播放多个音效（非阻塞）...")
        for i in range(5):
            file_to_play = engine.get_random_sound_file('main')
            if file_to_play:
                print(f"提交播放任务 {i+1}: {file_to_play}")
                engine.play_sound_nonblocking(file_to_play)
                time.sleep(0.1)  # 短暂延迟，模拟快速点击
        
        print("所有播放任务已提交，等待完成...")
        time.sleep(5)  # 等待所有音效播放完成
        
        print("\nNonBlockingAudioEngine 模块测试完毕。")

    except FileNotFoundError as e:
        print(f"\n测试失败：{e}")
        print("请确保 'assets' 文件夹和音效文件存在于正确的位置。")
    except Exception as e:
        print(f"\n测试期间发生意外错误: {e}")