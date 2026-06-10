"""
项目背景：
    本脚本用于在 Windows 11 环境下批量压缩大体积视频文件，主要面向电影、电视剧等本地视频资源。
    目标是在尽量不产生肉眼可见画质损失的前提下，使用 CPU 进行 H.265 / HEVC 重编码，
    并输出为 MKV 封装格式。

运行环境：
    - Windows 11
    - Python 3.10+
    - 已安装 ffmpeg / ffprobe，并且 ffmpeg.exe、ffprobe.exe 已加入 PATH
    - 编码器使用 libx265，即 CPU 编码，不使用 GPU / NVENC

核心需求：
    1. 支持从多个输入文件夹递归查找常见视频格式，例如 mp4、mkv、ts、m2ts、mov、avi、webm 等。
    2. 输出命名格式为：原文件名.h265.mkv
       例如：
           movie.mp4      -> movie.h265.mkv
           episode01.ts  -> episode01.h265.mkv
    3. 若目标文件已存在，则直接跳过，不执行 ffprobe，也不执行 ffmpeg。
    4. 若输入文件本身已经是 xxx.h265.mkv，则跳过，避免重复压缩。
    5. 视频流使用 libx265 进行 CPU 重编码：
           preset = slow
           crf = 24
           pix_fmt = yuv420p10le
    6. 音频流、字幕流、附件流、章节、元数据等尽量保留：
           -map 0
           -map_metadata 0
           -map_chapters 0
           -c copy
           -c:v:0 libx265
    7. 不强制指定输出帧率，不使用 -r。
       使用 -fps_mode passthrough 尽量保留源视频时间戳，降低错误丢帧、补帧、重复帧风险。
    8. 编码前使用 ffprobe 检查疑似帧率声明异常：
           actual_fps = 实际读取帧数 / 视频时长
           declared_fps = avg_frame_rate
       如果 actual_fps 明显高于 declared_fps，则输出红色 WARNING。
    9. ffmpeg 的输出需要实时传递到 Python 所在终端，方便观察编码进度。
    10. 在 Windows 终端下尽量避免中文路径、中文文件名、中文提示乱码。
    11. 根据文件大小尽量均匀地分组，并按配置的并行数同时处理。
    12. 每处理完成一个视频后，输出简洁美观的总体进度提示。

主要技术路线：
    - 使用 pathlib 递归扫描输入文件夹列表中的常见视频文件。
    - 按文件大小使用贪心算法均衡分组，每个分组由一个工作线程顺序处理。
    - 使用 ffprobe 获取主视频流信息，并基于 nb_read_frames / duration 估算实际帧率。
    - 使用 subprocess.run 捕获 ffprobe JSON 输出。
    - 使用 subprocess.Popen 调用 ffmpeg，并让 ffmpeg 继承当前终端 stdout / stderr，
      从而实时显示 ffmpeg 编码进度。
    - 使用 ANSI 转义序列输出彩色提示，包括红色 warning、黄色 skip、绿色 done、青色进度条。
    - 在 Windows 下通过 chcp 65001、sys.stdout.reconfigure、PYTHONUTF8 等方式尽量启用 UTF-8 输出。
"""

import json
import os
import subprocess
import sys
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ============================== 输入配置 ==============================

# 要递归扫描的文件夹。相对路径以运行脚本时的当前目录为基准。
INPUT_DIRECTORIES: list[Path] = [
    Path("."),
]

# 最大并行编码任务数。CPU 编码负载很高，请按机器核心数和散热能力调整。
PARALLEL = 1

# 支持的视频扩展名。
VIDEO_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".ts",
    ".m2ts",
    ".mts",
    ".flv",
    ".webm",
    ".wmv",
    ".mpg",
    ".mpeg",
    ".m4v",
    ".3gp",
    ".ogv",
    ".vob",
}

# 实际估算帧率比声明 avg_frame_rate 高出多少时报警。
# 0.05 表示高出 5% 以上报警。
FPS_WARNING_THRESHOLD = 0.05

# 编码输入参数。
FFMPEG_COMMAND = "ffmpeg"
FFPROBE_COMMAND = "ffprobe"
VIDEO_ENCODER = "libx265"
X265_PRESET = "slow"
X265_CRF = "24"
PIX_FMT = "yuv420p10le"
X265_PARAMS = "aq-mode=3:psy-rd=1.2:psy-rdoq=1.0:deblock=-1,-1"
MAX_MUXING_QUEUE_SIZE = "9999"
OUTPUT_SUFFIX = ".h265.mkv"

# ====================================================================


_PRINT_LOCK = threading.Lock()


def setup_windows_utf8_console() -> None:
    """
    尽量保证 Windows 终端下中文路径、中文文件名、中文提示不乱码。

    作用：
        1. 将当前 Windows 控制台代码页切到 UTF-8。
        2. 将 Python stdout / stderr / stdin 重新配置为 UTF-8。
        3. 设置环境变量，尽量让子进程继承 UTF-8 环境。

    说明：
        Windows Terminal + PowerShell 7 通常表现最好。
        旧版 cmd.exe 或旧版 Windows PowerShell 仍可能受字体、系统区域设置影响。
    """
    if os.name != "nt":
        return

    os.system("chcp 65001 > nul")

    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def color_text(text: str, color: str) -> str:
    colors = {
        "red": "\033[31m",
        "yellow": "\033[33m",
        "green": "\033[32m",
        "cyan": "\033[36m",
        "blue": "\033[34m",
        "gray": "\033[90m",
        "bold": "\033[1m",
        "reset": "\033[0m",
    }

    return f"{colors.get(color, '')}{text}{colors['reset']}"


def print_info(message: str) -> None:
    with _PRINT_LOCK:
        print(message, flush=True)


def print_success(message: str) -> None:
    with _PRINT_LOCK:
        print(color_text(message, "green"), flush=True)


def print_warning(message: str) -> None:
    with _PRINT_LOCK:
        print(color_text(message, "red"), flush=True)


def print_skip(message: str) -> None:
    with _PRINT_LOCK:
        print(color_text(message, "yellow"), flush=True)


def print_section(title: str) -> None:
    with _PRINT_LOCK:
        print(flush=True)
        print(color_text("=" * 72, "cyan"), flush=True)
        print(color_text(title, "bold"), flush=True)
        print(color_text("=" * 72, "cyan"), flush=True)


def render_progress_bar(done: int, total: int, width: int = 28) -> str:
    if total <= 0:
        return "[" + "-" * width + "]"

    ratio = done / total
    filled = round(width * ratio)
    empty = width - filled

    return "[" + "█" * filled + "·" * empty + "]"


def print_batch_progress(
    processed: int,
    total: int,
    encoded: int,
    skipped: int,
    failed: int,
) -> None:
    bar = render_progress_bar(processed, total)
    percent = processed / total * 100 if total else 100.0

    with _PRINT_LOCK:
        print(flush=True)
        print(
            color_text(
                f"Progress {bar} {processed}/{total} ({percent:.1f}%)  "
                f"done={encoded}  skipped={skipped}  failed={failed}",
                "cyan",
            ),
            flush=True,
        )


def rational_to_float(value: Optional[str]) -> float:
    if not value or value == "0/0":
        return 0.0

    value = str(value).strip()

    if "/" in value:
        try:
            num_str, den_str = value.split("/", 1)
            num = float(num_str)
            den = float(den_str)

            if den == 0:
                return 0.0

            return num / den
        except ValueError:
            return 0.0

    try:
        return float(value)
    except ValueError:
        return 0.0


def first_valid_float(*values: Any) -> float:
    for value in values:
        if value is None:
            continue

        try:
            result = float(value)
            if result > 0:
                return result
        except (TypeError, ValueError):
            continue

    return 0.0


def run_command_capture(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=os.environ.copy(),
    )


def probe_video(input_path: Path) -> Optional[dict[str, Any]]:
    command = [
        FFPROBE_COMMAND,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-count_frames",
        "-show_entries",
        "stream=index,codec_name,width,height,avg_frame_rate,r_frame_rate,duration,nb_frames,nb_read_frames",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(input_path),
    ]

    result = run_command_capture(command)

    if result.returncode != 0:
        print_warning("WARNING: ffprobe failed. Encoding will continue, but FPS check was skipped.")
        if result.stderr.strip():
            print_warning(result.stderr.strip())
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print_warning("WARNING: ffprobe returned invalid JSON. Encoding will continue, but FPS check was skipped.")
        return None


def check_fps_warning(input_path: Path) -> bool:
    """
    编码前检查疑似帧率声明异常。

    返回：
        True:
            可以继续编码。
        False:
            未找到视频流，应跳过该文件。
    """
    probe = probe_video(input_path)

    if not probe:
        return True

    streams = probe.get("streams") or []

    if not streams:
        print_warning("WARNING: no video stream found. Skip this file.")
        return False

    stream = streams[0]
    fmt = probe.get("format") or {}

    codec_name = stream.get("codec_name", "unknown")
    width = stream.get("width", "unknown")
    height = stream.get("height", "unknown")

    avg_fps = rational_to_float(stream.get("avg_frame_rate"))
    r_fps = rational_to_float(stream.get("r_frame_rate"))

    duration = first_valid_float(
        stream.get("duration"),
        fmt.get("duration"),
    )

    read_frames = first_valid_float(
        stream.get("nb_read_frames"),
        stream.get("nb_frames"),
    )

    actual_fps = 0.0
    if duration > 0 and read_frames > 0:
        actual_fps = read_frames / duration

    print_info(f"Codec       : {codec_name}")
    print_info(f"Resolution  : {width}x{height}")
    print_info(f"avg FPS     : {avg_fps:.3f}")
    print_info(f"r FPS       : {r_fps:.3f}")

    if actual_fps > 0:
        print_info(f"actual FPS  : {actual_fps:.3f}")
    else:
        print_info("actual FPS  : unknown")

    if avg_fps > 0 and actual_fps > 0:
        ratio = actual_fps / avg_fps

        if ratio > 1.0 + FPS_WARNING_THRESHOLD:
            print_info("")
            print_warning("WARNING: possible FPS mismatch detected!")
            print_warning(f"Declared avg FPS  : {avg_fps:.3f}")
            print_warning(f"Estimated real FPS: {actual_fps:.3f}")
            print_warning(f"Ratio             : {ratio:.3f}x")
            print_warning("The estimated real frame rate appears higher than the declared avg_frame_rate.")
            print_warning("Encoding will continue with timestamp passthrough mode.")
            print_info("")

    return True


def quote_command(command: list[str]) -> str:
    return " ".join(f'"{x}"' if " " in x else x for x in command)


@dataclass
class RuntimeState:
    stop_event: threading.Event = field(default_factory=threading.Event)
    process_lock: threading.Lock = field(default_factory=threading.Lock)
    active_processes: set[subprocess.Popen[Any]] = field(default_factory=set)


@dataclass
class BatchStats:
    total: int
    encoded: int = 0
    skipped: int = 0
    failed: int = 0
    processed: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, status: str) -> None:
        with self.lock:
            if status == "encoded":
                self.encoded += 1
            elif status == "skipped":
                self.skipped += 1
            else:
                self.failed += 1

            self.processed += 1
            print_batch_progress(
                self.processed,
                self.total,
                self.encoded,
                self.skipped,
                self.failed,
            )

    def snapshot(self) -> tuple[int, int, int, int]:
        with self.lock:
            return self.processed, self.encoded, self.skipped, self.failed


def encode_video(
    input_path: Path,
    output_path: Path,
    runtime: RuntimeState,
) -> int:
    command = [
        FFMPEG_COMMAND,
        "-hide_banner",
        "-i",
        str(input_path),

        # 保留所有输入流，包括视频、音频、字幕、附件、封面等。
        "-map",
        "0",

        # 保留源文件元数据和章节。
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",

        # 默认所有流 copy。
        "-c",
        "copy",

        # 只重编码第一个视频流。
        "-c:v:0",
        VIDEO_ENCODER,
        "-preset",
        X265_PRESET,
        "-crf",
        X265_CRF,
        "-pix_fmt",
        PIX_FMT,
        "-x265-params",
        X265_PARAMS,

        # 不强制指定 -r，尽量保留输入时间戳。
        "-fps_mode",
        "passthrough",

        # 降低复杂文件、多流文件封装时报 muxing queue 错误的概率。
        "-max_muxing_queue_size",
        MAX_MUXING_QUEUE_SIZE,

        str(output_path),
    ]

    print_info("")
    print_info(color_text("Running ffmpeg:", "bold"))
    print_info(color_text(quote_command(command), "gray"))
    print_info("")

    # 不捕获 stdout / stderr，让 ffmpeg 直接继承当前 Python 终端。
    # 这样 ffmpeg 的进度、warning、error 都会实时显示。
    process = subprocess.Popen(
        command,
        stdin=None,
        stdout=None,
        stderr=None,
        env=os.environ.copy(),
    )

    with runtime.process_lock:
        runtime.active_processes.add(process)
        should_stop = runtime.stop_event.is_set()

    if should_stop:
        process.terminate()

    try:
        return process.wait()
    finally:
        with runtime.process_lock:
            runtime.active_processes.discard(process)


def is_supported_video(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS


def is_already_encoded(path: Path) -> bool:
    return path.name.lower().endswith(OUTPUT_SUFFIX)


def resolve_input_directories(directories: Sequence[Path]) -> list[Path]:
    resolved_directories: list[Path] = []

    for directory in directories:
        expanded = directory.expanduser()
        if not expanded.is_absolute():
            expanded = Path.cwd() / expanded
        resolved_directories.append(expanded.resolve())

    return resolved_directories


def iter_video_files(directories: Sequence[Path]) -> list[Path]:
    files: list[Path] = []
    seen_paths: set[str] = set()

    for directory in resolve_input_directories(directories):
        if not directory.is_dir():
            print_warning(f"WARNING: input directory does not exist or is not a directory: {directory}")
            continue

        try:
            candidates = directory.rglob("*")
            for path in candidates:
                if not is_supported_video(path):
                    continue

                resolved_path = path.resolve()
                path_key = os.path.normcase(str(resolved_path))
                if path_key in seen_paths:
                    continue

                seen_paths.add(path_key)
                files.append(resolved_path)
        except OSError as exc:
            print_warning(f"WARNING: failed to scan input directory: {directory}")
            print_warning(str(exc))

    return sorted(files, key=lambda path: str(path).lower())


def get_file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def split_video_files(video_files: list[Path], parallel: int) -> list[list[Path]]:
    if parallel <= 0:
        raise ValueError("PARALLEL must be greater than 0.")

    groups: list[list[Path]] = [[] for _ in range(parallel)]
    group_sizes = [0] * parallel
    file_sizes = {
        path: get_file_size(path)
        for path in video_files
    }

    files_by_size = sorted(
        video_files,
        key=lambda path: (-file_sizes[path], str(path).lower()),
    )

    for path in files_by_size:
        target_index = min(
            range(parallel),
            key=lambda index: (group_sizes[index], index),
        )
        groups[target_index].append(path)
        group_sizes[target_index] += file_sizes[path]

    return groups


def format_file_size(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.2f} {unit}"
        size /= 1024

    return f"{size_bytes} B"


def process_video(
    input_path: Path,
    index: int,
    total: int,
    worker_index: int,
    runtime: RuntimeState,
) -> str:
    print_section(f"[worker {worker_index}] [{index}/{total}] {input_path.name}")

    output_path = input_path.with_name(f"{input_path.stem}{OUTPUT_SUFFIX}")
    print_info(f"Input : {input_path}")
    print_info(f"Output: {output_path}")

    try:
        if is_already_encoded(input_path):
            print_skip("Skip: already encoded file.")
            return "skipped"

        # 目标文件已存在则直接跳过。
        # 放在 ffprobe 前，避免已处理文件浪费时间探测。
        if output_path.exists():
            print_skip("Skip: output already exists.")
            return "skipped"

        can_continue = check_fps_warning(input_path)
        if not can_continue:
            return "skipped"

        if runtime.stop_event.is_set():
            return "skipped"

        returncode = encode_video(input_path, output_path, runtime)

        if returncode == 0:
            print_success(f"Done: {output_path.name}")
            return "encoded"

        print_warning(f"ERROR: ffmpeg failed with exit code {returncode}")
        print_warning(f"Failed file: {input_path}")
        return "failed"

    except Exception as exc:
        print_warning(f"ERROR: unexpected exception while processing {input_path.name}")
        print_warning(str(exc))
        return "failed"


def process_group(
    group: list[Path],
    file_indexes: dict[Path, int],
    total: int,
    worker_index: int,
    stats: BatchStats,
    runtime: RuntimeState,
) -> None:
    for input_path in group:
        if runtime.stop_event.is_set():
            return

        status = process_video(
            input_path,
            file_indexes[input_path],
            total,
            worker_index,
            runtime,
        )
        stats.record(status)


def terminate_active_processes(runtime: RuntimeState) -> None:
    runtime.stop_event.set()

    with runtime.process_lock:
        processes = list(runtime.active_processes)

    for process in processes:
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass


def main() -> int:
    setup_windows_utf8_console()

    if PARALLEL <= 0:
        print_warning("ERROR: PARALLEL must be greater than 0.")
        return 1

    input_directories = resolve_input_directories(INPUT_DIRECTORIES)
    video_files = iter_video_files(INPUT_DIRECTORIES)
    total = len(video_files)

    if not video_files:
        print_info("No supported video files found in the configured input directories.")
        return 0

    worker_count = min(PARALLEL, total)
    groups = split_video_files(video_files, PARALLEL)
    file_indexes = {
        input_path: index
        for index, input_path in enumerate(video_files, start=1)
    }

    print_section("H.265 / HEVC CPU batch encoder")
    for input_directory in input_directories:
        print_info(f"Directory : {input_directory}")
    print_info(f"Files     : {total}")
    print_info(f"Parallel  : {PARALLEL} configured, {worker_count} active")
    print_info(f"Encoder   : {VIDEO_ENCODER}")
    print_info(f"Preset    : {X265_PRESET}")
    print_info(f"CRF       : {X265_CRF}")
    print_info(f"Pixel fmt : {PIX_FMT}")
    print_info("Container : MKV")

    for group_index, group in enumerate(groups, start=1):
        group_size = sum(get_file_size(path) for path in group)
        print_info(
            f"Group {group_index:>2}: {len(group):>4} files, "
            f"{format_file_size(group_size)}"
        )

    stats = BatchStats(total=total)
    runtime = RuntimeState()
    print_batch_progress(0, total, 0, 0, 0)

    executor = ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="h265-encoder",
    )
    futures = [
        executor.submit(
            process_group,
            group,
            file_indexes,
            total,
            worker_index,
            stats,
            runtime,
        )
        for worker_index, group in enumerate(groups, start=1)
        if group
    ]

    try:
        for future in futures:
            future.result()
    except KeyboardInterrupt:
        print_warning("Interrupted by user. Stopping active ffmpeg processes.")
        terminate_active_processes(runtime)
        executor.shutdown(wait=True, cancel_futures=True)
        return 130
    except Exception as exc:
        print_warning("ERROR: parallel worker failed unexpectedly.")
        print_warning(str(exc))
        terminate_active_processes(runtime)
        executor.shutdown(wait=True, cancel_futures=True)
        return 1
    finally:
        if not runtime.stop_event.is_set():
            executor.shutdown(wait=True)

    processed, encoded, skipped, failed = stats.snapshot()

    print_section("Summary")

    if failed == 0:
        print_success("Batch finished.")
    else:
        print_warning("Batch finished with failures.")

    print_info(f"Total   : {total}")
    print_info(f"Processed: {processed}")
    print_success(f"Encoded : {encoded}")
    print_skip(f"Skipped : {skipped}")

    if failed > 0:
        print_warning(f"Failed  : {failed}")
    else:
        print_info(f"Failed  : {failed}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
