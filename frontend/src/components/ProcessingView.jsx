import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Loader2, Sparkles } from 'lucide-react';

const LOG_MESSAGES = [
    "正在分析关键帧...",
    "检测画面内容...",
    "正在去除重复页面...",
    "优化图像清晰度...",
    "正在生成 PowerPoint 文件...",
    "打包资源中...",
];

export const ProcessingView = ({ progress }) => {
    const [logIndex, setLogIndex] = useState(0);

    useEffect(() => {
        const interval = setInterval(() => {
            setLogIndex(prev => (prev + 1) % LOG_MESSAGES.length);
        }, 1200);
        return () => clearInterval(interval);
    }, []);

    return (
        <div className="w-full max-w-xl mx-auto text-center space-y-10 py-12">
            <div className="space-y-6">
                <div className="relative">
                    <motion.div
                        animate={{ rotate: 360 }}
                        transition={{ duration: 3, repeat: Infinity, ease: "linear" }}
                        className="w-20 h-20 mx-auto rounded-full border-2 border-slate-800 border-t-indigo-500"
                    />
                    <div className="absolute inset-0 flex items-center justify-center text-slate-400 font-mono text-lg">
                        {Math.round(progress)}%
                    </div>
                </div>

                <div className="space-y-2">
                    <h3 className="text-2xl font-light text-slate-100 flex items-center justify-center gap-2">
                        <Sparkles className="w-5 h-5 text-indigo-400 animate-pulse" />
                        正在处理视频
                    </h3>

                    <div className="h-6 overflow-hidden relative">
                        <AnimatePresence mode="wait">
                            <motion.p
                                key={logIndex}
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0, y: -10 }}
                                className="text-slate-500 text-sm font-light"
                            >
                                {LOG_MESSAGES[logIndex]}
                            </motion.p>
                        </AnimatePresence>
                    </div>
                </div>
            </div>

            <div className="h-1.5 w-full bg-slate-900 rounded-full overflow-hidden">
                <motion.div
                    className="h-full bg-indigo-500 shadow-[0_0_15px_rgba(99,102,241,0.5)]"
                    initial={{ width: 0 }}
                    animate={{ width: `${progress}%` }}
                    transition={{ ease: "linear" }}
                />
            </div>
        </div>
    );
};
