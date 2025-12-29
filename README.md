# Video-to-PPT 智能转换工具 (FastAPI 后端重构版)

本项目是一个基于 Python 和 computer vision 技术的后端服务，能够自动处理教学视频或会议录像。它通过 OpenCV 智能识别并裁剪 PPT 区域，利用 SSIM 算法提取关键帧，最终自动生成 `.pptx` 演示文稿。

主要功能：
- **智能裁剪**: 自动识别视频中的 PPT 投影区域并进行裁剪。
- **关键帧提取**: 基于图像相似度 (SSIM) 去重，只保留内容变更的幻灯片。
- **RESTful API**: 提供标准的 HTTP 接口，易于集成 React 等前端。
- **Windows 优化**: 针对 Windows 文件系统进行特别优化，解决文件占用与路径问题。

---

## 🏗️ 项目目录结构详解

本项目采用 **Clean Architecture** (整洁架构) 分层设计，确保代码的可维护性与扩展性。

```text
video2note_test/
├── backend/                        # 后端工程根目录
│   ├── app/                        # 核心应用代码
│   │   ├── api/                    # 接口层 (Controller)
│   │   │   └── v1/
│   │   │       └── endpoints.py    # 定义 API 路由 (如 /process-video)
│   │   ├── core/                   # 核心配置
│   │   │   └── config.py           # 路径常量、环境配置管理
│   │   ├── services/               # 业务逻辑层 (Service)
│   │   │   ├── video_service.py    # 核心算法封装 (裁剪 + 提取逻辑)
│   │   │   └── files_service.py    # 文件安全操作 (解决 Windows 锁定问题)
│   │   ├── utils/                  # 通用工具函数
│   │   └── main.py                 # FastAPI 应用入口 (CORS, 中间件)
│   ├── temp/                       # [自动生成] 大文件上传临时存储区
│   ├── output/                     # [自动生成] 处理结果产出区
│   │   └── {uuid}/                 # 按任务 ID 隔离的输出文件夹
│   │       ├── cropped_video/      # 裁剪后的中间视频
│   │       ├── debug_images/       # 算法处理过程中的调试图 (定位框等)
│   │       ├── ppt_images/         # 提取出的 PPT 关键帧图片
│   │       └── ppt_output/         # 最终生成的 .pptx 文件
│   └── requirements.txt            # Python 依赖清单
├── input/                          # (旧版保留) 原始视频输入目录
└── README.md                       # 项目说明文档
```

---

## 🚀 快速开始 (Windows)

### 1. 环境准备
确保已安装 Python 3.10+。

```powershell
# 1. 进入 backend 目录
cd backend

# 2. (可选) 创建并激活虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. 安装依赖
pip install -r backend/requirements.txt
```

### 2. 启动服务
使用 `uvicorn` 启动开发服务器（支持热重载）：

```powershell
# 务必在 backend 目录下执行
uvicorn app.main:app --reload
```

启动成功后，控制台将显示类似如下信息：
```text
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

## 📚 API 接口文档

服务启动后，访问 Swagger UI 进行交互式测试：

👉 **打开浏览器访问**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 主要接口

#### `POST /api/v1/process-video`
上传视频文件并触发处理流程。

- **请求**: `multipart/form-data`, 字段名 `file` (上传视频文件)
- **响应**: JSON
  ```json
  {
    "status": "success",
    "data": {
      "guid": "a1b2c3d4-...",
      "cropped_video": "C:/.../output/.../cropped.mp4",
      "ppt_file": "C:/.../output/.../presentation.pptx"
    },
    "message": "视频处理完成"
  }
  ```

---

## 🛠️ 技术栈

- **Web 框架**: FastAPI (高性能异步框架)
- **服务器**: Uvicorn (ASGI 服务器)
- **视觉算法**: OpenCV (cv2), scikit-image (SSIM 相似度计算)
- **PPT 生成**: python-pptx
- **并发模型**: AsyncIO + ThreadPool (处理 CPU 密集型任务)

## ⚠️ 注意事项

1. **Windows 文件锁**: 代码中已包含 `secure_delete` 机制，但在处理大文件时，Windows 可能会短暂锁定文件，属正常现象。
2. **性能**: 视频处理是 CPU 密集型操作，处理 1 小时的视频可能需要数分钟，请耐心等待接口响应。