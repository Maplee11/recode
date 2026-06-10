# AGENTS.md

本文件用于指导 AI 编程助手、代码代理或自动化维护工具理解和修改本项目。

项目名称：H.265 CPU Batch Encoder  
项目类型：Windows 本地视频批量压缩脚本  
主要语言：Python  
核心外部依赖：ffmpeg / ffprobe  
目标平台：Windows 11

---

## 项目目标

本项目用于批量压缩大体积视频文件，主要面向电影、电视剧等本地视频资源。

核心目标是：

```text
在尽量不产生肉眼可见画质损失的前提下，
使用 CPU 编码器 libx265 将视频重编码为 H.265 / HEVC，
并输出为 MKV 封装格式。
```

本项目明确不使用 GPU 编码，例如 NVENC、QSV、AMF。

---

## 核心约束

修改本项目时必须遵守以下约束。

### 1. 必须使用 CPU 编码

视频编码器必须使用：

```text
libx265
```

不得默认改为：

```text
hevc_nvenc
h264_nvenc
av1_nvenc
hevc_qsv
hevc_amf
```

除非用户明确要求增加 GPU 编码分支。

---

### 2. 输出格式必须是 H.265 / HEVC + MKV

默认输出文件格式：

```text
原文件名.h265.mkv
```

示例：

```text
movie.mp4      -> movie.h265.mkv
episode01.ts  -> episode01.h265.mkv
source.mkv    -> source.h265.mkv
```

不得默认输出为 `.mp4`、`.avi`、`.webm` 或其他封装。

---

### 3. 已存在目标文件必须跳过

在执行 `ffprobe` 和 `ffmpeg` 之前，必须检查目标文件是否已存在。

如果：

```text
xxx.h265.mkv
```

已经存在，则必须跳过该输入文件。

这样可以避免：

```text
重复编码
覆盖已有结果
浪费时间重新探测
```

---

### 4. 已经是 `.h265.mkv` 的输入文件必须跳过

如果输入文件名已经以：

```text
.h265.mkv
```

结尾，必须跳过，避免重复压缩。

---

### 5. 不要强制指定输出帧率

默认不得使用：

```bash
-r
```

原因是强制指定输出帧率可能导致：

```text
丢帧
补帧
重复帧
音画不同步
播放节奏异常
```

本项目默认使用：

```bash
-fps_mode passthrough
```

以尽量保留源视频时间戳。

---

### 6. 必须尽量保留源视频内容

默认 ffmpeg 参数必须保留：

```bash
-map 0
-map_metadata 0
-map_chapters 0
-c copy
-c:v:0 libx265
```

含义：

```text
映射所有输入流
保留元数据
保留章节
默认所有流 copy
只重编码第一个视频流
```

应尽量保留：

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

## 推荐默认编码参数

默认视频编码参数如下：

```text
encoder  = libx265
preset   = slow
crf      = 24
pix_fmt  = yuv420p10le
container = mkv
```

默认 x265 参数：

```text
aq-mode=3:psy-rd=1.2:psy-rdoq=1.0:deblock=-1,-1
```

对应 ffmpeg 参数：

```bash
-c:v:0 libx265
-preset slow
-crf 24
-pix_fmt yuv420p10le
-x265-params "aq-mode=3:psy-rd=1.2:psy-rdoq=1.0:deblock=-1,-1"
```

---

## 画质参数调整原则

如果需要调整画质或体积，应优先修改 `CRF`。

建议范围：

```text
CRF 22~23：更高质量，体积更大，适合重要视频
CRF 24   ：默认推荐，质量和体积较均衡
CRF 25   ：更小体积，适合普通视频
CRF 26+  ：压缩更激进，不建议作为默认值
```

不要轻易修改：

```text
-fps_mode passthrough
-map 0
-c copy
-map_metadata 0
-map_chapters 0
```

这些参数关系到帧率稳定性和源内容保留。

---

## 支持的视频扩展名

默认支持以下扩展名：

```text
.mp4
.mkv
.mov
.avi
.ts
.m2ts
.mts
.flv
.webm
.wmv
.mpg
.mpeg
.m4v
.3gp
.ogv
.vob
```

新增格式时，应只增加确定属于视频容器的扩展名。

---

## 帧率异常检测逻辑

本项目需要在编码前使用 `ffprobe` 检查疑似帧率声明异常。

检测思路：

```text
declared_fps = avg_frame_rate
actual_fps   = nb_read_frames / duration
```

如果：

```text
actual_fps > declared_fps * 1.05
```

则输出红色 warning。

注意：

```text
脚本只报警，不自动修复帧率。
```

不要默认根据估算出的 `actual_fps` 自动添加 `-r`。

原因是自动修复帧率可能导致：

```text
改变视频时长
改变播放节奏
音画不同步
重复帧或丢帧
```

---

## ffmpeg 输出要求

调用 `ffmpeg` 时，必须让 `ffmpeg` 的输出实时显示在 Python 运行终端中。

推荐使用：

```python
subprocess.Popen(
    command,
    stdin=None,
    stdout=None,
    stderr=None,
    env=os.environ.copy(),
)
```

不要使用下面这种方式运行 `ffmpeg` 编码任务：

```python
subprocess.run(
    command,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
```

因为这会导致 `ffmpeg` 的进度输出被 Python 捕获，无法实时显示。

`ffprobe` 可以使用 `subprocess.run(..., stdout=PIPE, stderr=PIPE)`，因为它需要解析 JSON 输出。

---

## Windows 中文输出要求

项目需要尽量避免 Windows 下中文路径、中文文件名、中文提示乱码。

应保留类似逻辑：

```python
os.system("chcp 65001 > nul")

os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
sys.stdin.reconfigure(encoding="utf-8", errors="replace")
```

推荐用户使用：

```text
Windows Terminal + PowerShell 7
```

旧版 `cmd.exe` 或旧版 Windows PowerShell 可能仍受终端字体和系统区域设置影响。

---

## 进度提示要求

脚本应在每处理完成一个视频后输出总体进度。

推荐形式：

```text
Progress [██████████··················] 3/8 (37.5%)  done=2  skipped=1  failed=0
```

含义：

```text
done    成功完成编码的视频数量
skipped 跳过的视频数量
failed  编码失败的视频数量
```

进度提示应该简洁，不应过度刷屏。

---

## 错误处理原则

### 1. 单个文件失败不应导致全批次中断

如果某个文件编码失败，应：

```text
记录失败
输出 warning / error
继续处理下一个文件
```

除非用户主动中断，例如 `Ctrl+C`。

---

### 2. 用户中断应返回 130

如果捕获到 `KeyboardInterrupt`，应返回：

```text
130
```

---

### 3. 批处理退出码

建议退出码：

```text
0   所有文件成功处理，或仅有正常跳过
1   至少一个文件编码失败
130 用户手动中断
```

---

## 代码风格

### Python 版本

推荐 Python 版本：

```text
Python 3.10+
```

可以使用：

```python
list[str]
dict[str, Any]
Path
```

不必兼容 Python 3.8 以下版本。

---

### 路径处理

必须使用：

```python
pathlib.Path
```

不要使用大量字符串拼接处理路径。

推荐：

```python
output_path = input_path.with_name(f"{input_path.stem}.h265.mkv")
```

---

### 子进程调用

命令参数必须使用 `list[str]`，不要拼接成单个 shell 字符串。

推荐：

```python
command = [
    "ffmpeg",
    "-hide_banner",
    "-i",
    str(input_path),
    ...
]
```

不推荐：

```python
command = f'ffmpeg -i "{input_path}" ...'
```

除非有明确理由，否则不要使用：

```python
shell=True
```

---

## 不应做的修改

除非用户明确要求，否则不要做以下修改：

```text
不要默认改用 GPU 编码
不要默认改用 AV1
不要默认输出 MP4
不要默认重新编码音频
不要默认删除字幕
不要默认删除章节
不要默认删除附件
不要默认强制 -r
不要默认覆盖已有输出文件
不要默认递归扫描子目录
不要默认删除源文件
不要默认编码完成后自动替换源文件
不要默认静默运行 ffmpeg
```

---

## 可以考虑的后续扩展

以下功能可以作为可选增强，但不应破坏当前默认行为：

```text
递归扫描子目录
命令行参数配置 CRF / preset / 输入目录 / 输出目录
dry-run 模式
日志文件
失败文件列表
编码前后体积对比
编码后自动校验输出文件是否可读取
按文件大小过滤
按扩展名过滤
跳过已经是 HEVC 的视频
失败后降级处理不可封装流
针对 TS 文件增加可选时间戳修复模式
```

这些扩展必须保持默认行为保守、安全、可预期。

---

## 推荐项目结构

当前项目可以保持简单结构：

```text
.
├── encode_h265.py
├── README.md
└── AGENTS.md
```

如果后续扩展为包结构，可以考虑：

```text
.
├── h265_encoder/
│   ├── __init__.py
│   ├── cli.py
│   ├── ffmpeg.py
│   ├── probe.py
│   └── progress.py
├── tests/
├── README.md
└── AGENTS.md
```

当前阶段不需要过度工程化。

---

## 测试建议

修改脚本后，建议至少用以下文件类型测试：

```text
普通 mp4
普通 mkv
ts 文件
带字幕的视频
带多音轨的视频
带章节的视频
中文文件名视频
中文路径目录
目标文件已存在的情况
输入文件已经是 .h265.mkv 的情况
```

应检查：

```text
是否正确跳过目标文件已存在的输入
是否正确跳过 .h265.mkv 输入
ffmpeg 输出是否实时显示
中文路径是否正常显示
输出文件是否可以播放
字幕是否保留
音轨是否保留
章节是否保留
进度统计是否正确
失败文件是否不影响后续处理
```

---

## 项目定位

本项目不是通用视频转码框架，而是一个面向个人本地归档需求的批量压缩脚本。

默认策略应始终偏向：

```text
安全
保守
不覆盖
不丢流
不强制改帧率
不静默失败
不擅自删除源文件
```
