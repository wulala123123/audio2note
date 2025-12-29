# Video to PPT (AI-Powered)

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/Frontend-React-61DAFB.svg?style=flat-square&logo=react&logoColor=black)](https://reactjs.org/)
[![TailwindCSS](https://img.shields.io/badge/Style-TailwindCSS-06B6D4.svg?style=flat-square&logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)

[English](README_EN.md) | [简体中文](README.md)

**一款美观、高效的 AI 视频转 PPT 工具。**
上传课程录屏、会议视频或演讲视频，AI 自动分析关键帧，提取清晰幻灯片，并生成可编辑的 PPTX 文件。

---

## ✨ 核心特性

- **极致现代 UI**: 采用 Vercel 风格的深色模式设计，流畅的动效体验。
- **全自动处理**: 拖入视频即可，后端自动完成关键帧提取、去重、OCR 分析与 PPT 生成。
- **实时进度反馈**: 前端实时展示后端处理状态（如“正在分析图像”、“生成 PPT 中”）。
- **隐私安全**: 所有处理在本地/私有服务器完成，保护您的数据安全。

## 🛠️ 技术栈

### Backend (Python)
- **Framework**: FastAPI
- **Processing**: OpenCV (图像处理), python-pptx (PPT 生成)
- **Async**: BackgroundTasks for non-blocking processing

### Frontend (React)
- **Build Tool**: Vite
- **Styling**: TailwindCSS (v3), Framer Motion (Animations)
- **Icons**: Lucide React

## 🚀 快速开始

### 1. 环境要求
- Python 3.9+
- Node.js 18+

### 2. 一键启动 (推荐)

双击项目根目录下的 `run.bat` 脚本，即可同时启动前端和后端服务。

### 3. 手动启动后端

```powershell
# 进入后端目录
cd backend

# 创建并激活虚拟环境 (可选)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt

# 启动服务 (默认端口 8000)
python -m uvicorn app.main:app --reload
```

### 3. 启动前端

```powershell
# 进入前端目录
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

浏览器访问: `http://localhost:5173`

## 📁 目录结构

```text
video2note_test/
├── backend/                # Python FastAPI 后端
│   ├── app/
│   │   ├── api/            # 路由定义
│   │   ├── core/           # 核心配置
│   │   ├── services/       # 业务逻辑 (视频处理, CV算法)
│   │   └── main.py         # 入口文件
│   └── output/             # 生成的文件 (自动创建)
├── frontend/               # React 前端
│   ├── src/
│   │   ├── components/     # UI 组件 (Dropzone, ProcessingView)
│   │   ├── services/       # API 请求层
│   │   └── App.jsx         # 主应用逻辑
│   └── tailwind.config.js  # 样式配置
└── README.md
```

## 📝 待办事项

- [ ] 支持更多视频格式 (WebM, MKV)
- [ ] 增加 OCR 文字识别功能
- [ ] 支持自定义 PPT 模板
- [ ] 部署文档 (Docker)

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---
© 2025 Video2Note AI. Built for Creators.