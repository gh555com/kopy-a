# 文件名: q1.py
#
# v1.6.0
# - loop 无缝：在 _pcm_loop_stream 加入“短 crossfade”支持（默认 12ms），并用预处理避免运行时高CPU
# - 新增验证接口：NonBlockingAudioEngine.validate_environment() -> "ok" / "not ok: ..."
#   * 不依赖任何外部音频文件，仅使用内存生成PCM，验证 miniaudio/PlaybackDevice/回调协议/cleanup
# - 继承 v1.5.2：
#   * 修复 prime StopIteration：skip 移到 worker 且空读重试
#   * trim_silence 默认 True，首尾去静音剪裁（更坚决更干净）+ 缓存
#   * 非循环支持余弦淡出
#   * stream_file send(framecount) 限制 <= 16384
#   * PCM 循环段小 LRU 缓存

import miniaudio
import time
import os
import random
from concurrent.futures import ThreadPoolExecutor
import array
import sys
import math
import atexit
import threading
from functools import lru_cache
from collections import OrderedDict


# ===================== 可调参数（你想更“狠”就调这里） =====================
SILENCE_DB = -45.0                  # 静音阈值（更“狠”就改 -40.0；更“松”就改 -50.0）
TRIM_WINDOW_SECONDS = 30.0          # 只精确检测首尾各多少秒用于剪裁（性能折中）
LOUD_RUN_MS = 8.0                   # 必须连续多少毫秒超阈才算“真正有声”（更干净）

LOOP_PREDECODE_MAX_SECONDS = 300.0  # 循环时：片段<=该秒数才预解码到内存保证“无缝循环”
LOOP_CROSSFADE_MS_DEFAULT = 12.0    # 循环“尾->头” crossfade 时长（ms）。设 0 表示关闭

SOURCE_READ_FRAMES_MAX = 16384      # 关键：对 miniaudio.stream_file 的 send(framecount) 不得超过该值
EMPTY_READ_RETRIES = 6              # 空读重试次数（防止偶发空供被误判 EOF）
EMPTY_READ_SLEEP = 0.0              # 是否在空读之间 sleep（一般 0 就行）

PCM_CACHE_MAX_ITEMS = 8             # PCM 循环段缓存个数
# ==========================================================================


def _db_to_int16_threshold(db: float) -> int:
    ratio = 10 ** (db / 20.0)
    return int(32767 * ratio)


SILENCE_THR = _db_to_int16_threshold(SILENCE_DB)


@lru_cache(maxsize=64)
def _cosine_fade_table(fade_frames: int):
    if fade_frames <= 0:
        return None
    n = float(fade_frames)
    return tuple(0.5 * (1.0 + math.cos(math.pi * (i / n))) for i in range(fade_frames + 1))


@lru_cache(maxsize=64)
def _raised_cosine_crossfade_gains(n: int):
    """
    返回 (out_gains, in_gains) 长度 n
    i 从 0..n-1：
      in = 0.5 * (1 - cos(pi*(i+1)/n)) 从接近0到1
      out = 1 - in
    """
    if n <= 0:
        return (), ()
    out_g = []
    in_g = []
    for i in range(n):
        a = 0.5 * (1.0 - math.cos(math.pi * ((i + 1) / float(n))))
        in_g.append(a)
        out_g.append(1.0 - a)
    return tuple(out_g), tuple(in_g)


class PlaybackToken:
    __slots__ = ("stop_event",)

    def __init__(self):
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    @property
    def stopped(self):
        return self.stop_event.is_set()


class NonBlockingAudioEngine:
    def __init__(self, asset_folder="assets", max_workers=32, silent=False):
        self.silent = silent
        self._log("非阻塞音频引擎 (NonBlockingAudioEngine) 正在初始化...")
        self.asset_folder = asset_folder

        self.REQUESTED_FORMAT = miniaudio.SampleFormat.SIGNED16
        self.REQUESTED_CHANNELS = 2
        self.REQUESTED_RATE = 44100
        self._frame_bytes = self.REQUESTED_CHANNELS * 2

        self.executor = ThreadPoolExecutor(max_workers=max_workers)

        self.main_sounds = []
        self.q_sounds = []
        self.z_sounds = []
        self.last_played_main = -1
        self.last_played_q = -1
        self.last_played_z = -1

        self._cleaned = False
        self._active_tokens = set()
        self._tokens_lock = threading.Lock()

        # trim 缓存：key->(mtime_ns,size,new_start,new_end)
        self._trim_cache = {}
        self._trim_cache_lock = threading.Lock()

        # PCM 缓存（LRU）：key->(mtime_ns,size,pcm_bytes,xfade_frames)
        self._pcm_cache = OrderedDict()
        self._pcm_cache_lock = threading.Lock()

        atexit.register(self.cleanup)

        self._load_sound_files()
        self._log(
            f"非阻塞音频引擎初始化完毕，共加载 {len(self.main_sounds)} 个主音效，"
            f"{len(self.q_sounds)} 个q音效，{len(self.z_sounds)} 个z音效"
        )

    def _log(self, msg: str):
        if not self.silent:
            print(msg)

    # ---------- 音效加载 ----------
    def _load_sound_files(self):
        try:
            if not os.path.isdir(self.asset_folder):
                self._log(f"提示：找不到资源文件夹 '{self.asset_folder}'，将跳过内置音效加载。")
                return

            for i in range(1, 9):
                wav_file = os.path.join(self.asset_folder, f"{i}.wav")
                mp3_file = os.path.join(self.asset_folder, f"{i}.mp3")
                if os.path.exists(wav_file):
                    self.main_sounds.append(wav_file)
                elif os.path.exists(mp3_file):
                    self.main_sounds.append(mp3_file)

            for i in range(1, 10):
                wav_file = os.path.join(self.asset_folder, f"q{i}.wav")
                mp3_file = os.path.join(self.asset_folder, f"q{i}.mp3")
                if os.path.exists(wav_file):
                    self.q_sounds.append(wav_file)
                elif os.path.exists(mp3_file):
                    self.q_sounds.append(mp3_file)

            for i in range(1, 7):
                wav_file = os.path.join(self.asset_folder, f"z{i}.wav")
                mp3_file = os.path.join(self.asset_folder, f"z{i}.mp3")
                if os.path.exists(wav_file):
                    self.z_sounds.append(wav_file)
                elif os.path.exists(mp3_file):
                    self.z_sounds.append(mp3_file)
        except Exception as e:
            self._log(f"加载音效文件时出错: {e}")

    def _get_random_sound(self, sound_list, last_played_index):
        if not sound_list:
            return None
        if len(sound_list) == 1:
            return sound_list[0]
        new_index = last_played_index
        while new_index == last_played_index:
            new_index = random.randint(0, len(sound_list) - 1)
        return sound_list[new_index]

    # ---------- generator send 适配 ----------
    def _send_primed(self, gen, value):
        try:
            return gen.send(value)
        except TypeError as e:
            if "just-started generator" in str(e):
                try:
                    gen.send(None)  # prime
                except StopIteration:
                    return b""
                return gen.send(value)
            raise

    def _read_frames_retry(self, gen, frames: int):
        """向 decoder 请求 frames 帧（frames<=16384），空读会重试几次。"""
        if frames <= 0:
            return b""
        if frames > SOURCE_READ_FRAMES_MAX:
            frames = SOURCE_READ_FRAMES_MAX

        for _ in range(EMPTY_READ_RETRIES):
            data = self._send_primed(gen, frames)
            if data:
                return bytes(data)
            if EMPTY_READ_SLEEP > 0:
                time.sleep(EMPTY_READ_SLEEP)
        return b""

    def _skip_frames(self, gen, frames_to_skip: int, token: PlaybackToken) -> bool:
        """丢弃 frames_to_skip 帧。成功返回 True；遇到 EOF/错误返回 False。"""
        remain = frames_to_skip
        while remain > 0:
            if token.stopped:
                return False
            req = SOURCE_READ_FRAMES_MAX if remain > SOURCE_READ_FRAMES_MAX else remain
            b = self._read_frames_retry(gen, req)
            if not b:
                return False
            got = len(b) // self._frame_bytes
            if got <= 0:
                return False
            remain -= got
        return True

    # ---------- 静音剪裁（更狠 + 连续 run） ----------
    def _block_peak_over_threshold(self, pcm_bytes: bytes, thr: int) -> bool:
        samples = array.array("h")
        samples.frombytes(pcm_bytes)
        if sys.byteorder != "little":
            samples.byteswap()
        if not samples:
            return False
        mx = max(samples)
        mn = min(samples)
        peak = mx if mx >= -mn else -mn
        return peak > thr

    def _find_first_loud_run_in_block(self, pcm_bytes: bytes, frames_in_block: int,
                                      thr: int, need_run: int, carry_run: int):
        samples = array.array("h")
        samples.frombytes(pcm_bytes)
        if sys.byteorder != "little":
            samples.byteswap()
        ch = self.REQUESTED_CHANNELS

        run = carry_run
        for f in range(frames_in_block):
            base = f * ch
            loud = (abs(samples[base]) > thr) or (abs(samples[base + 1]) > thr)
            if loud:
                run += 1
                if run >= need_run:
                    return f - need_run + 1, run
            else:
                run = 0
        return -1, run

    def _find_last_loud_run_end_in_block(self, pcm_bytes: bytes, frames_in_block: int,
                                         thr: int, need_run: int,
                                         carry_run: int, last_end_global: int, global_offset: int):
        samples = array.array("h")
        samples.frombytes(pcm_bytes)
        if sys.byteorder != "little":
            samples.byteswap()
        ch = self.REQUESTED_CHANNELS

        run = carry_run
        last = last_end_global
        for f in range(frames_in_block):
            base = f * ch
            loud = (abs(samples[base]) > thr) or (abs(samples[base + 1]) > thr)
            if loud:
                run += 1
                if run >= need_run:
                    last = global_offset + f
            else:
                run = 0
        return run, last

    def _trim_silence_edges_uncached(self, file_path: str, start_frame: int, end_frame: int, token: PlaybackToken):
        rate = self.REQUESTED_RATE
        total_frames = end_frame - start_frame
        if total_frames <= 0:
            return start_frame, end_frame

        window_frames = int(TRIM_WINDOW_SECONDS * rate)
        lead_frames = min(window_frames, total_frames)
        tail_frames = min(window_frames, total_frames)
        tail_start_offset = max(0, total_frames - tail_frames)

        need_run = max(1, int((LOUD_RUN_MS / 1000.0) * rate))

        src = miniaudio.stream_file(
            file_path,
            output_format=self.REQUESTED_FORMAT,
            nchannels=self.REQUESTED_CHANNELS,
            sample_rate=self.REQUESTED_RATE
        )

        try:
            # skip 到 segment 起点
            if start_frame > 0:
                if not self._skip_frames(src, start_frame, token):
                    return start_frame, end_frame

            # 头部扫描
            first_loud = None
            carry = 0
            analyzed = 0

            while analyzed < lead_frames:
                if token.stopped:
                    return start_frame, end_frame
                req = min(SOURCE_READ_FRAMES_MAX, lead_frames - analyzed)
                b = self._read_frames_retry(src, req)
                if not b:
                    break
                got = len(b) // self._frame_bytes
                if got <= 0:
                    break
                block = b[: got * self._frame_bytes]

                if self._block_peak_over_threshold(block, SILENCE_THR):
                    idx, carry = self._find_first_loud_run_in_block(block, got, SILENCE_THR, need_run, carry)
                    if idx >= 0:
                        first_loud = analyzed + idx
                        analyzed += got
                        break
                else:
                    carry = 0

                analyzed += got

            if first_loud is None:
                first_loud = lead_frames  # 头窗全静音

            # 跳到尾窗起点（从 segment 起点算）
            seg_pos = analyzed
            if seg_pos < tail_start_offset:
                if not self._skip_frames(src, tail_start_offset - seg_pos, token):
                    # 跳不过去就按“尾部全静音”处理
                    last_loud_end = tail_start_offset - 1
                    new_start = start_frame + min(first_loud, total_frames)
                    new_end = start_frame + max(new_start - start_frame, min(last_loud_end + 1, total_frames))
                    if new_end < new_start:
                        new_end = new_start
                    return new_start, new_end

                seg_pos = tail_start_offset

            # 尾部扫描（需要最后一次连续 run 的结束帧）
            carry_tail = 0
            last_loud_end = -1
            while seg_pos < total_frames:
                if token.stopped:
                    return start_frame, end_frame
                req = min(SOURCE_READ_FRAMES_MAX, total_frames - seg_pos)
                b = self._read_frames_retry(src, req)
                if not b:
                    break
                got = len(b) // self._frame_bytes
                if got <= 0:
                    break
                block = b[: got * self._frame_bytes]

                if self._block_peak_over_threshold(block, SILENCE_THR):
                    carry_tail, last_loud_end = self._find_last_loud_run_end_in_block(
                        block, got, SILENCE_THR, need_run, carry_tail, last_loud_end, seg_pos
                    )
                else:
                    carry_tail = 0

                seg_pos += got

            if last_loud_end < 0:
                # 尾窗也没满足连续 run：更狠的策略 => 直接剪掉整个尾窗
                if first_loud >= total_frames:
                    return start_frame, start_frame  # 全静音
                last_loud_end = tail_start_offset - 1

            new_start = start_frame + max(0, min(first_loud, total_frames))
            new_end = start_frame + max(0, min(last_loud_end + 1, total_frames))
            if new_end < new_start:
                new_end = new_start
            return new_start, new_end

        finally:
            try:
                src.close()
            except Exception:
                pass

    def _trim_silence_edges(self, file_path: str, start_frame: int, end_frame: int, token: PlaybackToken):
        """带缓存的 trim。"""
        try:
            st = os.stat(file_path)
            mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
            size = st.st_size
        except Exception:
            return self._trim_silence_edges_uncached(file_path, start_frame, end_frame, token)

        key = (file_path, start_frame, end_frame, SILENCE_DB, LOUD_RUN_MS, TRIM_WINDOW_SECONDS,
               self.REQUESTED_RATE, self.REQUESTED_CHANNELS)

        with self._trim_cache_lock:
            ent = self._trim_cache.get(key)
            if ent and ent[0] == mtime_ns and ent[1] == size:
                return ent[2], ent[3]

        new_start, new_end = self._trim_silence_edges_uncached(file_path, start_frame, end_frame, token)

        with self._trim_cache_lock:
            self._trim_cache[key] = (mtime_ns, size, new_start, new_end)
        return new_start, new_end

    # ---------- 余弦淡出（非循环） ----------
    def _apply_fadeout_to_chunk_s16(self, chunk_bytes: bytes, chunk_frames: int,
                                   frames_played_before_chunk: int,
                                   fade_start_frame: int, fade_frames: int, fade_gains) -> bytes:
        if fade_frames <= 0 or chunk_frames <= 0 or not fade_gains:
            return chunk_bytes

        samples = array.array("h")
        samples.frombytes(chunk_bytes)
        if sys.byteorder != "little":
            samples.byteswap()

        ch = self.REQUESTED_CHANNELS
        for f in range(chunk_frames):
            seg_f = frames_played_before_chunk + f
            if seg_f < fade_start_frame:
                continue
            offset = seg_f - fade_start_frame
            g = 0.0 if offset >= fade_frames else fade_gains[offset]
            base = f * ch
            for c in range(ch):
                v = int(samples[base + c] * g)
                if v > 32767:
                    v = 32767
                elif v < -32768:
                    v = -32768
                samples[base + c] = v

        if sys.byteorder != "little":
            samples.byteswap()
        return samples.tobytes()

    # ---------- 回调流：从“当前位置”开始输出 seg_frames ----------
    def _segment_stream_from_here(self, source_gen, seg_frames: int, fade_frames: int, token: PlaybackToken):
        if seg_frames <= 0:
            framecount = yield b""
            return

        if fade_frames > seg_frames:
            fade_frames = seg_frames
        fade_start = seg_frames - fade_frames
        fade_gains = _cosine_fade_table(fade_frames) if fade_frames > 0 else None

        played = 0
        framecount = yield b""

        while True:
            if token.stopped:
                return
            if played >= seg_frames:
                return

            want_total = int(framecount) if framecount else 0
            if want_total <= 0:
                framecount = yield b""
                continue

            remain = seg_frames - played
            want = want_total if want_total <= remain else remain

            data = self._send_primed(source_gen, want)  # want 通常很小（回调请求）
            if not data:
                return

            audio = bytes(data)
            need_len = want * self._frame_bytes
            if len(audio) < need_len:
                audio += b"\x00" * (need_len - len(audio))
            elif len(audio) > need_len:
                audio = audio[:need_len]

            if fade_frames > 0 and (played + want) > fade_start:
                audio = self._apply_fadeout_to_chunk_s16(
                    chunk_bytes=audio,
                    chunk_frames=want,
                    frames_played_before_chunk=played,
                    fade_start_frame=fade_start,
                    fade_frames=fade_frames,
                    fade_gains=fade_gains
                )

            played += want

            if want < want_total:
                audio += b"\x00" * ((want_total - want) * self._frame_bytes)

            framecount = yield audio

    # ---------- 循环 crossfade：预处理 PCM（一次性） ----------
    def _prepare_pcm_loop_crossfade(self, pcm_bytes: bytes, crossfade_ms: float):
        """
        返回 (new_pcm_bytes, xfade_frames)
        策略：
          - 把“尾部最后 xfade_frames 帧”替换成 tail/head 的加权混合（raised-cosine）
          - 循环回绕时把 pos 设为 xfade_frames（跳过头部前 xfade_frames 帧，避免重复）
        """
        try:
            xms = float(crossfade_ms or 0.0)
        except Exception:
            xms = 0.0
        if xms <= 0.0:
            return pcm_bytes, 0

        total_frames = len(pcm_bytes) // self._frame_bytes
        if total_frames < 8:
            return pcm_bytes, 0

        xfade_frames = int((xms / 1000.0) * self.REQUESTED_RATE)
        if xfade_frames <= 0:
            return pcm_bytes, 0

        # 防止太长：至少留出足够主体（不然整个段都在交叉）
        if xfade_frames * 2 >= total_frames:
            xfade_frames = max(1, total_frames // 4)

        if xfade_frames <= 0 or xfade_frames * 2 >= total_frames:
            return pcm_bytes, 0

        out_g, in_g = _raised_cosine_crossfade_gains(xfade_frames)
        if not out_g:
            return pcm_bytes, 0

        samples = array.array("h")
        samples.frombytes(pcm_bytes)
        if sys.byteorder != "little":
            samples.byteswap()

        ch = self.REQUESTED_CHANNELS
        tail_start_frame = total_frames - xfade_frames

        for i in range(xfade_frames):
            og = out_g[i]
            ig = in_g[i]
            tail_f = tail_start_frame + i
            head_f = i

            tail_base = tail_f * ch
            head_base = head_f * ch

            for c in range(ch):
                t = samples[tail_base + c]
                h = samples[head_base + c]
                v = int(t * og + h * ig)
                if v > 32767:
                    v = 32767
                elif v < -32768:
                    v = -32768
                samples[tail_base + c] = v

        if sys.byteorder != "little":
            samples.byteswap()

        return samples.tobytes(), xfade_frames

    # ---------- PCM 循环（内存） ----------
    def _pcm_loop_stream(self, pcm_bytes: bytes, token: PlaybackToken, xfade_frames: int = 0):
        total_frames = len(pcm_bytes) // self._frame_bytes
        if total_frames <= 0:
            framecount = yield b""
            return

        if xfade_frames < 0:
            xfade_frames = 0
        if xfade_frames * 2 >= total_frames:
            xfade_frames = 0

        pos = 0
        framecount = yield b""

        while True:
            if token.stopped:
                return

            want = int(framecount) if framecount else 0
            if want <= 0:
                framecount = yield b""
                continue

            out = bytearray(want * self._frame_bytes)
            filled = 0

            while filled < want:
                if token.stopped:
                    return

                remain_seg = total_frames - pos
                take = remain_seg if remain_seg < (want - filled) else (want - filled)

                s = pos * self._frame_bytes
                e = s + take * self._frame_bytes
                out[filled * self._frame_bytes: (filled + take) * self._frame_bytes] = pcm_bytes[s:e]

                filled += take
                pos += take

                if pos >= total_frames:
                    # 关键：回绕时跳过头部 xfade_frames（因为尾部已混入头部前 xfade_frames）
                    pos = xfade_frames if xfade_frames > 0 else 0

            framecount = yield bytes(out)

    def _get_pcm_cached_or_decode(self, file_path: str, start_frame: int, end_frame: int,
                                  token: PlaybackToken, crossfade_ms: float):
        """循环用：取 PCM LRU 缓存；没有则 decode 一次并缓存；并做 loop crossfade 预处理。"""
        try:
            st = os.stat(file_path)
            mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
            size = st.st_size
        except Exception:
            mtime_ns, size = None, None

        # crossfade_ms 会影响缓存内容
        try:
            xms = float(crossfade_ms or 0.0)
        except Exception:
            xms = 0.0
        xms_key = round(xms, 3)

        key = (file_path, start_frame, end_frame, self.REQUESTED_RATE, self.REQUESTED_CHANNELS, xms_key)

        with self._pcm_cache_lock:
            ent = self._pcm_cache.get(key)
            if ent and ent[0] == mtime_ns and ent[1] == size:
                self._pcm_cache.move_to_end(key)
                return ent[2], ent[3]

        total_frames = end_frame - start_frame
        if total_frames <= 0:
            return b"", 0

        src = miniaudio.stream_file(
            file_path,
            output_format=self.REQUESTED_FORMAT,
            nchannels=self.REQUESTED_CHANNELS,
            sample_rate=self.REQUESTED_RATE
        )
        try:
            if start_frame > 0:
                if not self._skip_frames(src, start_frame, token):
                    return b"", 0

            remain = total_frames
            buf = bytearray()
            while remain > 0 and (not token.stopped):
                req = SOURCE_READ_FRAMES_MAX if remain > SOURCE_READ_FRAMES_MAX else remain
                b = self._read_frames_retry(src, req)
                if not b:
                    break
                got = len(b) // self._frame_bytes
                if got <= 0:
                    break
                buf.extend(b[: got * self._frame_bytes])
                remain -= got

            pcm = bytes(buf)
        finally:
            try:
                src.close()
            except Exception:
                pass

        # 做 loop crossfade 预处理（一次）
        pcm2, xfade_frames = self._prepare_pcm_loop_crossfade(pcm, xms)

        with self._pcm_cache_lock:
            self._pcm_cache[key] = (mtime_ns, size, pcm2, xfade_frames)
            self._pcm_cache.move_to_end(key)
            while len(self._pcm_cache) > PCM_CACHE_MAX_ITEMS:
                self._pcm_cache.popitem(last=False)

        return pcm2, xfade_frames

    # ---------- token 管理 ----------
    def _register_token(self, token: PlaybackToken):
        with self._tokens_lock:
            self._active_tokens.add(token)

    def _unregister_token(self, token: PlaybackToken):
        with self._tokens_lock:
            self._active_tokens.discard(token)

    # ---------- worker ----------
    def _play_sound_worker(self, file_path, play_range, fade_out_seconds, loop, trim_silence,
                          token: PlaybackToken, loop_crossfade_ms: float):
        device = None
        decoder = None

        try:
            if not os.path.exists(file_path):
                self._log(f"【!!】 文件不存在: {file_path}")
                return

            try:
                info = miniaudio.get_file_info(file_path)
                file_duration = float(info.duration or 0.0)
                if file_duration <= 0:
                    raise ValueError("duration<=0")
            except Exception as e:
                self._log(f"【!!】 获取文件信息失败 {file_path}: {e}")
                return

            # 解析区间：默认整曲
            if play_range is None:
                start_s, end_s = 0.0, file_duration
            else:
                try:
                    start_s, end_s = float(play_range[0]), float(play_range[1])
                except Exception:
                    self._log(f"【!!】 play_range 无效（应为 (start,end)）: {play_range}")
                    return

            if start_s < 0:
                start_s = 0.0
            if end_s > file_duration:
                end_s = file_duration
            if end_s <= start_s:
                self._log(f"提示：播放区间为空或非法：({start_s}, {end_s})")
                return

            rate = self.REQUESTED_RATE
            start_frame = int(start_s * rate)
            end_frame = int(end_s * rate)

            # trim（默认开）+ 缓存
            if trim_silence and not token.stopped:
                start_frame, end_frame = self._trim_silence_edges(file_path, start_frame, end_frame, token)

            if token.stopped:
                return

            seg_frames = end_frame - start_frame
            if seg_frames <= 0:
                return

            seg_duration = seg_frames / float(rate)

            # loop：无缝 => 预解码 + crossfade 预处理 + 跳过头部 xfade_frames
            if loop:
                if seg_duration <= LOOP_PREDECODE_MAX_SECONDS:
                    pcm, xfade_frames = self._get_pcm_cached_or_decode(
                        file_path, start_frame, end_frame, token, loop_crossfade_ms
                    )
                    if token.stopped or not pcm:
                        return

                    stream = self._pcm_loop_stream(pcm, token, xfade_frames=xfade_frames)
                    try:
                        stream.send(None)  # prime
                    except StopIteration:
                        return

                    device = miniaudio.PlaybackDevice(
                        output_format=self.REQUESTED_FORMAT,
                        nchannels=self.REQUESTED_CHANNELS,
                        sample_rate=self.REQUESTED_RATE
                    )
                    device.start(stream)

                    while not token.stopped:
                        time.sleep(0.1)
                    return
                else:
                    self._log(f"提示：片段 {seg_duration:.1f}s 过长，避免预解码循环（可调 LOOP_PREDECODE_MAX_SECONDS）。")
                    # 过长：退化方案（不保证100%无缝），也不做 crossfade
                    while not token.stopped:
                        decoder = miniaudio.stream_file(
                            file_path,
                            output_format=self.REQUESTED_FORMAT,
                            nchannels=self.REQUESTED_CHANNELS,
                            sample_rate=self.REQUESTED_RATE
                        )

                        if start_frame > 0:
                            if not self._skip_frames(decoder, start_frame, token):
                                return

                        stream = self._segment_stream_from_here(decoder, seg_frames, fade_frames=0, token=token)
                        try:
                            stream.send(None)
                        except StopIteration:
                            return

                        device = miniaudio.PlaybackDevice(
                            output_format=self.REQUESTED_FORMAT,
                            nchannels=self.REQUESTED_CHANNELS,
                            sample_rate=self.REQUESTED_RATE
                        )
                        device.start(stream)

                        t_end = time.time() + seg_duration + 0.25
                        while (time.time() < t_end) and (not token.stopped):
                            time.sleep(0.05)

                        try:
                            device.stop()
                        except Exception:
                            pass
                        try:
                            device.close()
                        except Exception:
                            pass
                        device = None

                        try:
                            decoder.close()
                        except Exception:
                            pass
                        decoder = None
                    return

            # 非循环：可以余弦淡出
            try:
                fos = float(fade_out_seconds or 0.0)
            except Exception:
                fos = 0.0
            if fos < 0:
                fos = 0.0
            if fos > seg_duration:
                fos = seg_duration
            fade_frames = int(fos * rate)

            decoder = miniaudio.stream_file(
                file_path,
                output_format=self.REQUESTED_FORMAT,
                nchannels=self.REQUESTED_CHANNELS,
                sample_rate=self.REQUESTED_RATE
            )

            if start_frame > 0:
                if not self._skip_frames(decoder, start_frame, token):
                    return

            stream = self._segment_stream_from_here(decoder, seg_frames, fade_frames=fade_frames, token=token)
            try:
                stream.send(None)  # prime
            except StopIteration:
                return

            device = miniaudio.PlaybackDevice(
                output_format=self.REQUESTED_FORMAT,
                nchannels=self.REQUESTED_CHANNELS,
                sample_rate=self.REQUESTED_RATE
            )
            device.start(stream)

            t_end = time.time() + seg_duration + 0.25
            while (time.time() < t_end) and (not token.stopped):
                time.sleep(0.05)

        except Exception as e:
            self._log(f"【!!】 音频播放失败: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if device:
                try:
                    device.stop()
                except Exception:
                    pass
                try:
                    device.close()
                except Exception:
                    pass

            if decoder:
                try:
                    decoder.close()
                except Exception:
                    pass

    # ---------- 对外接口 ----------
    def play_sound_file(self, file_path, play_range=None, fade_out_seconds=0.0,
                        loop=False, trim_silence=True, loop_crossfade_ms=None):
        """
        - play_range: (start_seconds, end_seconds) 或 None(整曲)
        - loop: 是否循环（片段 or 整曲）
        - trim_silence: 默认 True，剪掉首尾 -SILENCE_DB 以下静音
        - fade_out_seconds: 非循环时可用；循环时忽略（保持连贯）
        - loop_crossfade_ms: 循环尾->头 crossfade 毫秒数，默认 LOOP_CROSSFADE_MS_DEFAULT；设 0 关闭
        返回：PlaybackToken，可 token.stop() 停止（尤其 loop=True 时很重要）
        """
        if loop_crossfade_ms is None:
            loop_crossfade_ms = LOOP_CROSSFADE_MS_DEFAULT

        token = PlaybackToken()
        self._register_token(token)
        self.executor.submit(
            self._play_wrapper,
            file_path, play_range, fade_out_seconds, loop, trim_silence, token, float(loop_crossfade_ms or 0.0)
        )
        return token

    def _play_wrapper(self, file_path, play_range, fade_out_seconds, loop, trim_silence,
                      token: PlaybackToken, loop_crossfade_ms: float):
        try:
            self._play_sound_worker(
                file_path, play_range, fade_out_seconds, loop, trim_silence, token, loop_crossfade_ms
            )
        finally:
            self._unregister_token(token)

    def stop_all(self):
        with self._tokens_lock:
            for t in list(self._active_tokens):
                try:
                    t.stop()
                except Exception:
                    pass

    def cleanup(self):
        if self._cleaned:
            return
        self._cleaned = True
        self._log("正在关闭非阻塞音频引擎...")
        try:
            self.stop_all()
            if self.executor:
                self.executor.shutdown(wait=True)
        finally:
            self._log("非阻塞音频引擎已关闭。")

    # ---------- 验证接口：不依赖任何外部文件 ----------
    @classmethod
    def validate_environment(cls, verbose=False, timeout_sec=0.15):
        """
        给“调用者/电脑”用的环境自检：
          - 不依赖任何外部音频文件
          - 验证 miniaudio 可用 + PlaybackDevice 可打开/可start/stop/close + 回调generator协议正常 + cleanup 正常
        返回：
          - "ok"
          - "not ok: <reason>"
        """
        engine = None
        device = None
        token = None
        try:
            # 1) 基本能力检查
            if not hasattr(miniaudio, "PlaybackDevice"):
                return "not ok: miniaudio.PlaybackDevice not found"

            # 2) 初始化引擎（静默）
            engine = cls(asset_folder=".", max_workers=1, silent=(not verbose))

            # 3) 生成一小段“内存PCM”（非常轻，且不需要任何文件）
            rate = engine.REQUESTED_RATE
            ch = engine.REQUESTED_CHANNELS
            frame_bytes = engine._frame_bytes

            dur = 0.12  # 秒
            frames = max(1, int(dur * rate))
            freq = 440.0
            amp = 0.08  # 很轻的音量（不想出声可以改成 0.0）
            samples = array.array("h")

            # 立体声同相
            for n in range(frames):
                s = int(32767 * amp * math.sin(2.0 * math.pi * freq * (n / float(rate))))
                samples.append(s)
                samples.append(s)

            if sys.byteorder != "little":
                samples.byteswap()
            pcm = samples.tobytes()

            # 4) 做一次 loop crossfade 预处理（验证这段代码可跑）
            pcm2, xfade_frames = engine._prepare_pcm_loop_crossfade(pcm, LOOP_CROSSFADE_MS_DEFAULT)

            # 5) 用我们自己的 _pcm_loop_stream + PlaybackDevice 真正跑一下（验证回调协议+设备）
            token = PlaybackToken()
            stream = engine._pcm_loop_stream(pcm2, token, xfade_frames=xfade_frames)
            stream.send(None)  # prime

            device = miniaudio.PlaybackDevice(
                output_format=engine.REQUESTED_FORMAT,
                nchannels=engine.REQUESTED_CHANNELS,
                sample_rate=engine.REQUESTED_RATE
            )
            device.start(stream)

            # 让它跑一小会
            time.sleep(float(timeout_sec))

            # 6) 停止并收尾
            token.stop()
            time.sleep(0.03)

            try:
                device.stop()
            except Exception:
                pass
            try:
                device.close()
            except Exception:
                pass
            device = None

            engine.cleanup()
            engine = None

            return "ok"

        except Exception as e:
            return f"not ok: {type(e).__name__}: {e}"

        finally:
            # 尽力清理
            try:
                if token is not None:
                    token.stop()
            except Exception:
                pass
            try:
                if device is not None:
                    device.stop()
            except Exception:
                pass
            try:
                if device is not None:
                    device.close()
            except Exception:
                pass
            try:
                if engine is not None:
                    engine.cleanup()
            except Exception:
                pass


# ---------------- 独立测试（可删） ----------------
if __name__ == "__main__":
    print("=" * 60)
    print("验证接口（不依赖任何外部音频文件）")
    print(NonBlockingAudioEngine.validate_environment(verbose=True))
    print("=" * 60)

    TEST_FILE = r"E:\s\wol\py\kope\Foundry_PYRMDPLAZA.mp3"
    asset_folder = os.path.dirname(TEST_FILE) or "."

    print("=" * 60)
    print("独立播放测试：区间 + 去静音(默认更狠) + 循环 crossfade(默认12ms)")
    print(f"文件: {TEST_FILE}")
    print(f"静音阈值: {SILENCE_DB} dBFS, 连续有声: {LOUD_RUN_MS} ms, 循环crossfade: {LOOP_CROSSFADE_MS_DEFAULT} ms")
    print("=" * 60)

    engine = NonBlockingAudioEngine(asset_folder=asset_folder, max_workers=8)

    # A：播放 5~9 秒（非循环），末尾2秒余弦淡出
    tokenA = engine.play_sound_file(
        TEST_FILE,
        play_range=(5.0, 9.0),
        fade_out_seconds=2.0,
        loop=False,
        trim_silence=True
    )
    time.sleep(6.0)
    tokenA.stop()

    # B：无缝循环播放 5~9 秒（默认 trim + 12ms crossfade），跑 10 秒后停止
    tokenB = engine.play_sound_file(
        TEST_FILE,
        play_range=(5.0, 9.0),
        loop=True,
        trim_silence=True,
        loop_crossfade_ms=12.0  # 你也可以设 0 关闭
    )
    time.sleep(10.0)
    tokenB.stop()

    engine.cleanup()
