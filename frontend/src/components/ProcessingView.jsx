/**
 * 文件名: ProcessingView.jsx
 * 功能描述: 视频处理进度展示组件
 * 核心逻辑:
 *    - 展示后端传入的真实进度百分比 (0-100%)
 *    - 维护一个前端假日志轮播 (Log Carousel)，在后端无具体消息时填补空白
 *    - 使用 Framer Motion 实现平滑的进度条和数字动画
 */
import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Loader2, Sparkles } from 'lucide-react';

/**
 * 预设的进度日志消息
 * 用于在后端未返回具体消息时循环显示，提升用户等待体验
 */
const LOG_MESSAGES = [
    "正在分析关键帧...",
    "检测画面内容...",
    "正在去除重复页面...",
    "优化图像清晰度...",
    "正在生成 PowerPoint 文件...",
    "打包资源中...",
];

export const ProcessingView = ({ progress, message }) => {
    // 日志索引状态，用于循环播放预设消息
    const [logIndex, setLogIndex] = useState(0);

    /**
     * 启动日志轮播定时器
     * 每 1.2 秒切换下一条预设消息
     */
    useEffect(() => {
        const interval = setInterval(() => {
            setLogIndex(prev => (prev + 1) % LOG_MESSAGES.length);
        }, 1200);
        return () => clearInterval(interval);
    }, []);

    return (
        <div className="w-full max-w-xl mx-auto text-center space-y-10 py-12">
            <div className="space-y-6">
                {/* 圆形进度指示器 */}
                <div className="relative">
                    {/* 外圈旋转动画 */}
                    <motion.div
                        animate={{ rotate: 360 }}
                        transition={{ duration: 3, repeat: Infinity, ease: "linear" }}
                        className="w-20 h-20 mx-auto rounded-full border-2 border-slate-800 border-t-indigo-500"
                    />
                    {/* 中心数字 */}
                    <div className="absolute inset-0 flex items-center justify-center text-slate-400 font-mono text-lg">
                        {Math.round(progress)}%
                    </div>
                </div>

                <div className="space-y-2">
                    <h3 className="text-2xl font-light text-slate-100 flex items-center justify-center gap-2">
                        <Sparkles className="w-5 h-5 text-indigo-400 animate-pulse" />
                        正在处理视频
                    </h3>

                    {/* 状态消息展示区域 (高度固定防抖动) */}
                    <div className="h-6 overflow-hidden relative">
                        <AnimatePresence mode="wait">
                            <motion.p
                                // key 变化触发重渲染动画
                                // 优先显示后端 message，否则显示预设 log
                                key={message || logIndex}
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0, y: -10 }}
                                className="text-slate-500 text-sm font-light"
                            >
                                {message || LOG_MESSAGES[logIndex]}
                            </motion.p>
                        </AnimatePresence>
                    </div>
                </div>
            </div>

            {/* 线性进度条 */}
            <div className="h-1.5 w-full bg-slate-900 rounded-full overflow-hidden">
                <motion.div
                    className="h-full bg-indigo-500 shadow-[0_0_15px_rgba(99,102,241,0.5)]"
                    initial={{ width: 0 }}
                    // width 属性绑定 progress，通过 transition 实现平滑过渡
                    animate={{ width: `${progress}%` }}
                    transition={{ ease: "linear" }}
                />
            </div>
        </div>
    );
};
