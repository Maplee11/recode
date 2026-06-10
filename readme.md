# H.265 CPU Batch Encoder

一个面向 Windows 本地视频归档场景的批量视频压缩脚本。

本项目使用 Python 调用 `ffmpeg` / `ffprobe`，递归扫描配置的多个文件夹，将其中的常见视频文件批量重编码为 **H.265 / HEVC + MKV**。编码过程使用 **CPU 编码器 `libx265`**，不使用 GPU / NVENC。

适用场景主要是电影、电视剧等大体积视频文件的本地压缩归档。

---

## 特性

- 支持常见视频格式：
  - `.mp4`
  - `.mkv`
  - `.ts`
  - `.m2ts`
  - `.mts`
  - `.mov`
  - `.avi`
  - `.webm`
  - `.wmv`
  - `.mpg`
  - `.mpeg`
  - `.m4v`
  - `.3gp`
  - `.ogv`
  - `.vob`

- 输出格式固定为：

```text
原文件名.h265.mkv
```

例如：

```text
movie.mp4      -> movie.h265.mkv
episode01.ts  -> episode01.h265.mkv
source.mkv    -> source.h265.mkv
```

- 若目标文件已存在，则自动跳过。
- 若输入文件已经是 `xxx.h265.mkv`，则自动跳过，避免重复压缩。
- 视频使用 `libx265` 进行 CPU 重编码。
- 音频流、字幕流、附件流、章节、元数据尽量保留。
- 不强制指定输出帧率，不使用 `-r`。
- 使用 `-fps_mode passthrough` 尽量保留源视频时间戳。
- 编码前使用 `ffprobe` 检查疑似帧率声明异常。
- 若实际估算帧率明显高于声明帧率，会输出红色 warning。
- 支持配置多个输入文件夹，并递归扫描所有子目录。
- 根据文件大小尽量均匀分成 `PARALLEL` 组，并行处理各组。
- `ffmpeg` 编码进度实时输出到当前终端。
- 每处理完成一个视频后，更新总体进度提示。
- 在 Windows 下尽量避免中文路径、中文文件名乱码。

---

## 运行环境

推荐环境：

```text
Windows 11
Python 3.10+
ffmpeg
ffprobe
```

需要确保以下命令可以在终端中直接运行：

```powershell
ffmpeg -version
ffprobe -version
```

如果不能运行，需要先将 `ffmpeg.exe` 和 `ffprobe.exe` 所在目录加入系统 `PATH`。

---

## 安装 ffmpeg

可以从 ffmpeg 官方构建版本下载 Windows 版本，也可以使用包管理器安装。

使用 winget：

```powershell
winget install Gyan.FFmpeg
```

安装后重新打开 PowerShell 或 Windows Terminal，并检查：

```powershell
ffmpeg -version
ffprobe -version
```

---

## 使用方式

运行前，在 `reenc.py` 开头修改输入配置：

```python
INPUT_DIRECTORIES: list[Path] = [
    Path(r"D:\Videos\Movies"),
    Path(r"E:\Videos\TV"),
]

PARALLEL = 2
```

相对路径以运行脚本时的当前目录为基准。脚本会递归扫描每个输入文件夹；若配置的目录互相重叠，同一个视频只会加入任务列表一次。

运行：

```powershell
python .\reenc.py
```

或者：

```powershell
py .\reenc.py
```

脚本会先汇总所有兼容视频，再按文件大小降序，将每个文件放入当前总大小最小的分组。每组内部顺序处理，各组之间最多同时运行 `PARALLEL` 个 `ffmpeg`。

`libx265` 本身也会使用多线程。`PARALLEL` 过大可能导致 CPU 满载、内存占用增加或散热压力过高，建议从 `1` 或 `2` 开始测试。

---

## 编码参数

当前默认编码参数如下：

```text
编码器：libx265
preset：slow
CRF：24
像素格式：yuv420p10le
封装格式：mkv
```

核心 ffmpeg 参数：

```bash
ffmpeg -hide_banner -i input \
  -map 0 \
  -map_metadata 0 \
  -map_chapters 0 \
  -c copy \
  -c:v:0 libx265 \
  -preset slow \
  -crf 24 \
  -pix_fmt yuv420p10le \
  -x265-params "aq-mode=3:psy-rd=1.2:psy-rdoq=1.0:deblock=-1,-1" \
  -fps_mode passthrough \
  -max_muxing_queue_size 9999 \
  output.h265.mkv
```

---

## 参数说明

### `-c copy` 与 `-c:v:0 libx265`

脚本默认先设置：

```bash
-c copy
```

表示所有流默认复制。

然后设置：

```bash
-c:v:0 libx265
```

表示只将第一个视频流重编码为 H.265 / HEVC。

因此通常会保留：

```text
音频流
多音轨
字幕流
多字幕
ASS / SSA / SRT 字幕
MKV 字体附件
章节
章节标题
元数据
封面图
其他可封装流
```

---

### `-map 0`

```bash
-map 0
```

表示映射输入文件中的所有流。

如果不加这个参数，ffmpeg 默认可能只选择一个视频流、一个音频流和一个字幕流，导致多音轨、多字幕或附件丢失。

---

### `-map_metadata 0`

```bash
-map_metadata 0
```

表示复制源文件元数据。

---

### `-map_chapters 0`

```bash
-map_chapters 0
```

表示复制源文件章节信息，包括章节标题。

---

### `-fps_mode passthrough`

```bash
-fps_mode passthrough
```

表示尽量按照输入帧的时间戳输出，不主动强制固定输出帧率。

本项目不使用：

```bash
-r
```

因为强制指定帧率可能导致：

```text
丢帧
补帧
重复帧
音画不同步
播放节奏异常
```

---

## 帧率异常检查

部分视频可能存在：

```text
实际帧率与容器或流中声明的帧率不一致
```

脚本会在编码前使用 `ffprobe` 获取信息，并估算：

```text
actual_fps = 实际读取帧数 / 视频时长
declared_fps = avg_frame_rate
```

如果：

```text
actual_fps > declared_fps * 1.05
```

脚本会输出红色 warning。

示例：

```text
WARNING: possible FPS mismatch detected!
Declared avg FPS  : 24.000
Estimated real FPS: 48.000
Ratio             : 2.000x
The estimated real frame rate appears higher than the declared avg_frame_rate.
Encoding will continue with timestamp passthrough mode.
```

注意：脚本只报警，不自动强制修复帧率。

原因是自动修复帧率可能改变视频时长、播放节奏或音画同步关系。对于异常文件，建议人工检查后单独处理。

---

## 进度显示

脚本会在每个视频处理完成后显示总体进度，例如：

```text
Progress [██████████··················] 3/8 (37.5%)  done=2  skipped=1  failed=0
```

含义：

```text
done    成功完成编码的视频数量
skipped 跳过的视频数量
failed  编码失败的视频数量
```

---

## 中文路径与中文文件名

脚本会在 Windows 下尽量启用 UTF-8 控制台输出，包括：

```text
chcp 65001
PYTHONUTF8=1
PYTHONIOENCODING=utf-8
sys.stdout 使用 UTF-8
sys.stderr 使用 UTF-8
sys.stdin 使用 UTF-8
```

推荐使用：

```text
Windows Terminal + PowerShell 7
```

旧版 `cmd.exe` 或旧版 Windows PowerShell 可能仍受终端字体、系统区域设置影响。

---

## 画质与体积建议

默认参数：

```text
preset = slow
crf = 24
pix_fmt = yuv420p10le
```

适合电影、电视剧等常见视频归档。

如果更重视画质，可以改为：

```text
crf = 22 或 23
```

如果更重视体积，可以改为：

```text
crf = 25 或 26
```

一般建议：

```text
重要视频：CRF 22~23
默认归档：CRF 24
更小体积：CRF 25
```

---

## 为什么使用 10-bit HEVC

脚本默认使用：

```bash
-pix_fmt yuv420p10le
```

即使源视频是 8-bit，使用 x265 10-bit 编码通常也有好处：

```text
压缩效率更好
渐变和暗部表现更稳
色带问题更少
现代播放器支持较好
```

缺点是：

```text
编码略慢
非常旧的设备可能不支持 HEVC Main10
```

如果需要兼容旧设备，可以改成：

```bash
-pix_fmt yuv420p
```

---

## 注意事项

### 1. 不建议直接全量运行

第一次使用建议先挑选少量典型视频测试：

```text
一个 mp4
一个 mkv
一个 ts
一个带字幕的视频
一个多音轨视频
一个暗部较多的视频
一个运动较多的视频
```

确认画质、字幕、章节、音轨都正常后，再批量处理。

---

### 2. TS 文件可能存在时间戳问题

`.ts` 文件经常可能有：

```text
时间戳不连续
DTS out of order
Non-monotonous DTS
duration 不准确
广告切片残留
```

如果某些 `.ts` 文件编码结果异常，建议单独处理，不建议一开始对所有文件强制加时间戳修复参数。

---

### 3. 某些私有流可能无法封装到 MKV

脚本会尽量保留所有流，但不同容器之间仍可能存在兼容性差异。

例如：

```text
某些 data stream
某些私有流
某些损坏字幕流
某些不标准附件流
```

可能无法直接 copy 到 MKV。遇到这种情况，ffmpeg 可能报错，需要针对该文件单独处理。

---

## 常见问题

### 为什么不用 GPU 编码？

本项目目标是尽量获得更好的压缩效率和主观画质，因此使用 CPU 编码器 `libx265`。

GPU 编码，例如 NVENC，速度更快，但在同等体积下通常压缩效率不如高质量 CPU 编码。

---

### 为什么不用 AV1？

AV1 压缩率可能更高，但 CPU 编码耗时更长，兼容性也不如 HEVC 稳定。

对于电影、电视剧批量归档，`libx265 + MKV` 是更均衡的方案。

---

### 为什么输出 MKV？

MKV 对多音轨、多字幕、章节、附件、字体、封面等内容支持更灵活，适合本地归档。

相比 MP4，MKV 更适合保留复杂视频文件中的各种附加信息。

---

### 为什么不重新编码音频？

电影、电视剧的音频通常已经是 AAC、AC3、EAC3、DTS 等格式。

本项目默认直接复制音频流：

```bash
-c copy
```

这样可以避免音频二次有损压缩，也能节省编码时间。

---

## 退出码

脚本结束时：

```text
0 表示全部成功或仅有跳过
1 表示有文件编码失败
130 表示用户手动中断
```

---

## License

本项目脚本可自由使用、修改和分发。
