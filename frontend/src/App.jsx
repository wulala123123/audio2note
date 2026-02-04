/**
 * 文件名: App.jsx
 * 功能描述: 前端应用主入口组件
 * 核心逻辑:
 *    - 管理应用全局状态 (status): idle -> uploading -> processing -> success
 *    - 编排业务流程: 上传视频 -> 启动轮询 -> 显示进度 -> 展示结果
 *    - 维护轮询定时器 (Polling Timer) 的生命周期
 */
import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Dropzone } from './components/Dropzone';
import { ProcessingView } from './components/ProcessingView';
import { SuccessCard } from './components/SuccessCard';
import { Github, Twitter } from 'lucide-react';
import { uploadVideo, checkStatus, getDownloadUrl } from './services/api';

function App() {
  /**
   * 全局状态管理
   * status: 当前应用所处阶段
   *    - 'idle': 空闲状态，等待用户拖入视频
   *    - 'uploading': 正在调用后端上传接口
   *    - 'processing': 后端正在处理 (提取关键帧/OCR/生成PPT)
   *    - 'success': 处理完成，显示下载卡片
   */
  const [status, setStatus] = useState('idle');
  const [progress, setProgress] = useState(0);     // 0-100 的进度值
  const [message, setMessage] = useState('');      // 当前处理阶段的文字描述
  const [downloadUrl, setDownloadUrl] = useState(''); // PPT 下载链接
  const [transcriptUrl, setTranscriptUrl] = useState(''); // 发言稿下载链接

  // 使用 useRef 存储定时器 ID，以便在组件卸载或状态变更时清除
  const pollingRef = useRef(null);

  /**
   * 生命周期管理: 组件卸载时清理定时器
   * 防止用户关闭页面后仍在后台轮询
   */
  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    }
  }, []);

  /**
   * 处理视频上传逻辑
   * 
   * Args:
   *    file (FileList | Array): 用户选择的文件列表
   */
  const handleRealUpload = async (file) => {
    try {
      setStatus('uploading');

      // 注意: Dropzone 返回的是数组，取第一个文件
      const { task_id } = await uploadVideo(file[0]);

      // 上传成功后立即切换到处理状态，并开始轮询
      setStatus('processing');
      startPolling(task_id);

    } catch (error) {
      console.error("Upload failed:", error);

      let errorMsg = "上传失败，请重试";
      if (error.response) {
        // 后端返回了错误响应 (如 413, 500)
        errorMsg += `\n错误代码: ${error.response.status}`;
        errorMsg += `\n错误信息: ${error.response.data?.detail || error.response.statusText}`;
      } else if (error.request) {
        // 请求已发出但无响应 (如网络断开)
        errorMsg += "\n网络错误: 无法连接到服务器";
      } else {
        // 其他错误
        errorMsg += `\n详细信息: ${error.message}`;
      }

      alert(errorMsg);
      setStatus('idle');
    }
  };

  /**
   * 启动状态轮询
   * 
   * 每秒请求一次后端查询任务状态，直到任务完成或组件卸载。
   * 
   * Args:
   *    taskId (string): 任务 ID
   */
  const startPolling = (taskId) => {
    // 清除可能存在的旧定时器
    if (pollingRef.current) clearInterval(pollingRef.current);

    pollingRef.current = setInterval(async () => {
      try {
        const data = await checkStatus(taskId);

        // 更新 UI 状态
        setProgress(data.progress || 0);
        if (data.message) setMessage(data.message);

        // 检查任务是否完成
        // 完成条件: 进度 100% 或者 后端返回了 result_url
        if (data.progress === 100 || data.result_url) {
          clearInterval(pollingRef.current); // 停止轮询

          if (data.result_url) {
            setDownloadUrl(getDownloadUrl(data.result_url));
          }
          if (data.transcript_url) {
            setTranscriptUrl(getDownloadUrl(data.transcript_url));
          }

          setStatus('success');
        }
      } catch (error) {
        console.error("Status check failed:", error);
        // 注意: 轮询失败一般不立即中断，因为可能是临时的网络波动
      }
    }, 1000); // 轮询间隔: 1000ms
  };

  /**
   * 重置应用状态
   * 用户点击"处理下一个视频"时触发
   */
  const handleReset = () => {
    setStatus('idle');
    setProgress(0);
    setMessage('');
    setDownloadUrl('');
    setTranscriptUrl('');
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-50 font-sans selection:bg-indigo-500/30 flex flex-col">
      {/* 顶部导航栏 */}
      <header className="p-6 md:p-8 flex justify-between items-center max-w-7xl mx-auto w-full">
        <div className="flex items-center gap-2">
          {/* Logo 图标 */}
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center font-bold text-white">
            V
          </div>
          <h1 className="text-xl font-bold tracking-tight text-white">
            Video to <span className="text-indigo-400">PPT</span>
          </h1>
        </div>
        <nav className="flex items-center gap-4 text-sm font-medium text-slate-400">
          <a href="#" className="hover:text-white transition-colors">Documentation</a>
          <a href="#" className="hover:text-white transition-colors">Pricing</a>
        </nav>
      </header>

      {/* 主内容区域 */}
      <main className="flex-1 flex flex-col items-center justify-center p-6 relative overflow-hidden">
        {/* 背景光效动画 (Ambient Background) */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] bg-indigo-500/10 rounded-full blur-[100px] pointer-events-none" />
        <div className="absolute top-0 right-0 w-[400px] h-[400px] bg-violet-500/5 rounded-full blur-[80px] pointer-events-none" />

        <div className="w-full max-w-4xl relative z-10">

          {/* 欢迎标题 (仅在 Idle 状态显示) */}
          {status === 'idle' && (
            <div className="text-center mb-12 space-y-4">
              <motion.h1
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-4xl md:text-6xl font-bold tracking-tight text-white"
              >
                视频转 PPT, <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-400 to-purple-400">一键搞定</span>
              </motion.h1>
              <motion.p
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.1 }}
                className="text-lg text-slate-400 max-w-2xl mx-auto"
              >
                上传课程视频、会议录屏或演讲视频，AI 自动提取关键帧、生成大纲并导出为可编辑的 PPTX 文件。
              </motion.p>
            </div>
          )}

          {/* 状态组件切换 (使用 AnimatePresence 实现平滑过渡) */}
          <AnimatePresence mode="wait">

            {/* 状态 1: 拖拽上传区域 */}
            {status === 'idle' && (
              <motion.div
                key="dropzone"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9, position: 'absolute' }}
                className="w-full"
              >
                <Dropzone onDrop={handleRealUpload} />
              </motion.div>
            )}

            {/* 状态 2: 上传中 Loading 动画 */}
            {status === 'uploading' && (
              <motion.div
                key="uploading"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex flex-col items-center justify-center space-y-4 h-80 w-full"
              >
                <div className="w-12 h-12 border-4 border-slate-800 border-t-indigo-500 rounded-full animate-spin" />
                <p className="text-slate-400 font-medium animate-pulse">正在上传视频...</p>
              </motion.div>
            )}

            {/* 状态 3: 后端处理进度条 */}
            {status === 'processing' && (
              <motion.div
                key="processing"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                className="w-full"
              >
                <ProcessingView progress={progress} message={message} />
              </motion.div>
            )}

            {/* 状态 4: 成功结果卡片 */}
            {status === 'success' && (
              <motion.div
                key="success"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                className="w-full"
              >
                <SuccessCard onReset={handleReset} downloadUrl={downloadUrl} transcriptUrl={transcriptUrl} />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </main>

      {/* 页脚 */}
      <footer className="p-6 text-center text-slate-600 text-sm">
        <div className="flex items-center justify-center gap-6 mb-4">
          <Github className="w-5 h-5 hover:text-slate-400 cursor-pointer transition-colors" />
          <Twitter className="w-5 h-5 hover:text-slate-400 cursor-pointer transition-colors" />
        </div>
        <p>© 2025 Video2Note AI. Built for Creators.</p>
      </footer>
    </div>
  );
}

export default App;
