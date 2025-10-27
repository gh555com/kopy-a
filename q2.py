# miniaudio_test.py (v15 - 终极修复版 / 新思路)
#
# v14 失败原因:
#   v14 错误地回归了 v11 的逻辑，试图检查 'sound.at_end'，
#   而这个属性早已被证明不存在。
#
# v15 终极修复 (新思路):
#   我们已经证明 v11, v12, v13, v14 的所有轮询 (poll) 尝试都失败了。
#   (sound.at_end, device.started, device.is_started() 均不存在)
#
#   新策略：我们不再“轮询”状态，我们“等待”时间。
#
# 1. [步骤 1] 我们使用 miniaudio.get_file_info() 来获取文件的
#    精确时长 (duration)。
# 2. [步骤 4] 我们彻底删除 'while' 循环，
#    改为调用 time.sleep(文件时长 + 0.5秒)。
#    这会强制主线程等待，直到音频在后台播放完毕。
# 3. [finally] 块保持 v13/v14 的 'device.stop()'，以解决
#    "第二次运行无声" 的问题。

import miniaudio
import time
import os

# --- 请修改这里 ---
SOUND_FILE_PATH = "assets/1.wav"
# --------------------

# --- 我们在此处定义我们想要的音频格式 ---
REQUESTED_FORMAT = miniaudio.SampleFormat.SIGNED16
REQUESTED_CHANNELS = 2
REQUESTED_RATE = 44100
# ---------------------------------------------

# 检查文件是否存在
if not os.path.exists(SOUND_FILE_PATH):
    print(f"【!!】 错误：找不到声音文件 '{SOUND_FILE_PATH}'")
    print("【!!】 请修改脚本中的 SOUND_FILE_PATH 变量，使其指向一个有效的声音文件。")
    exit()

print("="*60)
print("Miniaudio 核心功能诊断测试 (v15 - 终极修复版)")
print(f"即将尝试播放: {SOUND_FILE_PATH}")
print("="*60)

sound = None
device = None
file_duration = 0.0 # (v15) 我们将在这里存储文件时长

# (v15) [步骤 1/5] 获取文件信息
try:
    print("\n[步骤 1/5] 获取音频文件信息...")
    file_info = miniaudio.get_file_info(SOUND_FILE_PATH)
    file_duration = file_info.duration
    if file_duration <= 0:
        raise ValueError("无法获取文件时长或时长为 0。")
    print(f" -> 成功：文件时长 {file_duration:.2f} 秒。")

except Exception as e:
    print(f"【!!】 致命错误：在步骤 1 (获取文件信息) 失败。")
    print(f"【!!】 错误详情: {e}")
    print("【!!】 这可能是因为文件已损坏或不是 miniaudio 支持的格式。")
    exit()


# [步骤 2/5] 尝试将文件作为 "流" 打开 (同 v14, 已确认正常)
try:
    print("\n[步骤 2/5] 将音频文件作为流打开...")
    sound = miniaudio.stream_file(
        SOUND_FILE_PATH,
        output_format=REQUESTED_FORMAT,
        nchannels=REQUESTED_CHANNELS,
        sample_rate=REQUESTED_RATE
    )
    print(" -> 成功：文件已作为音频流打开。")
    print(f"    (流被要求输出: {REQUESTED_FORMAT.name}, {REQUESTED_CHANNELS}ch, {REQUESTED_RATE}Hz)")

except Exception as e:
    print(f"【!!】 致命错误：在步骤 2 (打开流) 失败。")
    print(f"【!!】 错误详情: {e}")
    exit()


# [步骤 3/5] 尝试初始化回放设备 (同 v14, 已确认正常)
try:
    print("\n[步骤 3/5] 初始化音频回放设备...")
    device = miniaudio.PlaybackDevice(
        output_format=REQUESTED_FORMAT,
        nchannels=REQUESTED_CHANNELS,
        sample_rate=REQUESTED_RATE
    )
    print(" -> 成功：音频设备已初始化。")
    try:
        if hasattr(device.backend, 'name'): backend_info = device.backend.name
        else: backend_info = str(device.backend)
        print(f"    - 设备后端: {backend_info}")
    except Exception as print_e:
        print(f"    - (警告) 打印设备详细信息时出错: {print_e}")
except Exception as e:
    print(f"【!!】 致命错误：在步骤 3 (初始化设备) 失败。")
    print(f"【!!】 错误详情: {e}")
    if sound: sound.close()
    exit()


# [步骤 4/5] 启动设备 (同 v14, 已确认正常)
try:
    print("\n[步骤 4/5] 启动音频流...")
    device.start(sound)
    print(" -> 成功：音频流已在后台启动！")
    print(" >>>>>>>>> 你现在应该能听到声音了 <<<<<<<<<")

except Exception as e:
    print(f"【!!】 致命错误：在步骤 4 (启动音频流) 失败。")
    print(f"【!!】 错误详情: {e}")
    if device: device.close()
    if sound: sound.close()
    exit()

# [步骤 5/5] 等待播放完成 (v15 修复)
try:
    # (v15) 修复:
    # 不再轮询，我们已知确切的文件时长。
    # 我们让主线程“睡眠”

    wait_time = file_duration + 0.5  # 增加 0.5 秒的缓冲区

    print(f"\n[步骤 5/5] 正在播放，主线程将等待 {wait_time:.2f} 秒...")

    time.sleep(wait_time)

    print(" -> 成功：等待时间结束。")

except Exception as e:
    # 捕获所有可能的错误，例如 time.sleep 被中断
    print(f"\n【!!】 错误：在步骤 5 (等待播放) 期间失败。")
    print(f"【!!】 错误详情: {e}")

finally:
    # (同 v14) 彻底关闭资源，解决 "第二次运行失败" 的问题。
    # 必须先 stop()，再 close()。

    print("\n测试结束，正在关闭设备和音频流...")
    if device:
        try:
            print("    - 正在停止 (stop) 设备...")
            # 停止设备 (v13 中发现这是必须的)
            device.stop()
        except Exception as e:
            print(f"    - (警告) 尝试 stop() 设备时出错: {e}")

        print("    - 正在关闭 (close) 设备...")
        device.close()

    if sound:
        print("    - 正在关闭 (close) 音频流...")
        sound.close()

    print("设备和音频流已关闭。")
    print("="*60)
