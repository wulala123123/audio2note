# 视频PPT自动提取工具

这是一个高效的Python工具，旨在全自动地从视频（如在线课程、会议录像）中检测、裁剪并提取演示文稿（PPT），最终生成一个完整的 `.pptx` 文件。

## 主要功能

-   **自动定位和裁剪**：智能识别视频帧中的PPT区域，并自动将视频裁剪为仅包含PPT内容的新视频。
-   **智能变化检测**：通过结构相似性指数（SSIM）算法，精确地检测幻灯片的翻页变化，避免提取重复或过渡的帧。
-   **一键式批量处理**：只需将所有源视频放入 `input` 文件夹，运行主程序即可一次性处理所有视频。
-   **断点续传**：程序会自动跳过已经处理过的视频，方便在中断后继续执行任务。
-   **结构化输出**：所有生成的文件（裁剪后的视频、中间图片、最终的PPTX文件）都会被清晰地组织在 `output` 文件夹中。

## 项目结构

```
.
├── input/                  # <--- 在这里放入你的源视频文件
├── output/
│   ├── image/              # 存储PPT定位过程中的调试图片
│   ├── video/              # 存储裁剪后的视频
│   ├── ppt_images/         # 存储从视频中提取出的单页PPT图片
│   └── pptx_files/         # <--- 最终生成的 .pptx 文件在这里
├── crop_ppt.py             # 步骤1：负责裁剪视频的脚本
├── extract_ppt.py          # 步骤2：负责提取PPT的脚本
├── main.py                 # <--- 运行这个文件来启动所有流程
└── requirements.txt        # 项目所需的Python库
```

## 安装指南

1.  **克隆或下载项目**
    将本项目文件下载到您的本地计算机。

2.  **创建并激活虚拟环境 (推荐)**
    在项目根目录下打开终端，并执行以下命令：
    ```bash
    # 创建虚拟环境
    python -m venv .venv
    # 激活虚拟环境 (Windows)
    .\.venv\Scripts\activate
    # 激活虚拟环境 (macOS/Linux)
    # source .venv/bin/activate
    ```

3.  **安装依赖库**
    在激活虚拟环境的终端中，运行以下命令来安装所有必需的Python库：
    ```bash
    pip install -r requirements.txt
    ```

## 使用方法

1.  **放入视频**：将一个或多个视频文件（如 `.mp4`, `.mov`, `.mkv` 等）复制到 `input` 文件夹中。

2.  **运行程序**：在项目根目录的终端中，执行主程序：
    ```bash
    python main.py
    ```

3.  **获取结果**：程序会自动执行 **视频裁剪** 和 **PPT提取** 两个步骤。处理完成后，您可以在 `output/pptx_files/` 文件夹中找到与源视频同名的 `.pptx` 文件。

## 参数调优 (可选)

如果提取效果不理想（例如，漏掉了某些页面或提取了过多相似页面），您可以打开 `extract_ppt.py` 文件，在 `main` 函数的底部找到 `extract_key_frames_persistent_reference` 函数的调用部分，并调整以下核心参数：

-   `ssim_threshold`：页面变化的敏感度。值越低，越容易将微小变化识别为新页面。
-   `frame_interval`：每隔多少帧进行一次检查。减小此值可以提高精度，但会增加处理时间。
-   `stability_frames`：确认一个新页面前需要保持稳定的帧数。增加此值可以避免提取过渡动画中的帧。

```python
# 位于 extract_ppt.py 的底部
extract_key_frames_persistent_reference(
    video_path=video_file_path,
    ssim_threshold=0.95,      # 调整此值 (0.0 ~ 1.0)
    frame_interval=20,        # 调整此值 (正整数)
    stability_frames=3        # 调整此值 (正整数)
)
```
