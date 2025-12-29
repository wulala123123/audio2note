import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Dropzone } from './components/Dropzone';
import { ProcessingView } from './components/ProcessingView';
import { SuccessCard } from './components/SuccessCard';
import { Github, Twitter } from 'lucide-react';
import { uploadVideo, checkStatus, getDownloadUrl } from './services/api';

function App() {
  const [status, setStatus] = useState('idle'); // idle, uploading, processing, success
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState('');
  const [downloadUrl, setDownloadUrl] = useState('');
  const pollingRef = useRef(null);

  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    }
  }, []);

  const handleRealUpload = async (file) => {
    try {
      setStatus('uploading');
      const { task_id } = await uploadVideo(file[0]); // Dropzone returns array

      setStatus('processing');
      startPolling(task_id);
    } catch (error) {
      console.error("Upload failed:", error);
      alert("上传失败，请重试");
      setStatus('idle');
    }
  };

  const startPolling = (taskId) => {
    pollingRef.current = setInterval(async () => {
      try {
        const data = await checkStatus(taskId);

        // Update UI
        setProgress(data.progress || 0);
        if (data.message) setMessage(data.message);

        // Check completion
        if (data.progress === 100 || data.result_url) {
          clearInterval(pollingRef.current);
          if (data.result_url) {
            setDownloadUrl(getDownloadUrl(data.result_url));
          }
          setStatus('success');
        }
      } catch (error) {
        console.error("Status check failed:", error);
      }
    }, 1000);
  };

  const handleReset = () => {
    setStatus('idle');
    setProgress(0);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-50 font-sans selection:bg-indigo-500/30 flex flex-col">
      {/* Header */}
      <header className="p-6 md:p-8 flex justify-between items-center max-w-7xl mx-auto w-full">
        <div className="flex items-center gap-2">
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

      {/* Main Content */}
      <main className="flex-1 flex flex-col items-center justify-center p-6 relative overflow-hidden">
        {/* Ambient Background */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] bg-indigo-500/10 rounded-full blur-[100px] pointer-events-none" />
        <div className="absolute top-0 right-0 w-[400px] h-[400px] bg-violet-500/5 rounded-full blur-[80px] pointer-events-none" />

        <div className="w-full max-w-4xl relative z-10">

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

          <AnimatePresence mode="wait">
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

            {status === 'success' && (
              <motion.div
                key="success"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                className="w-full"
              >
                <SuccessCard onReset={handleReset} downloadUrl={downloadUrl} />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </main>

      {/* Footer */}
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
