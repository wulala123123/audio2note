import React from 'react';
import { motion } from 'framer-motion';
import { FileDown, Video, CheckCircle2, ArrowRight } from 'lucide-react';
import { clsx } from 'clsx';

export const SuccessCard = ({ onReset, downloadUrl, videoUrl }) => {
    return (
        <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="w-full max-w-xl mx-auto"
        >
            <div className="relative bg-slate-900/50 backdrop-blur-sm border border-slate-800 rounded-3xl p-8 md:p-12 text-center space-y-8 shadow-2xl">
                <div className="absolute inset-0 bg-gradient-to-b from-indigo-500/10 to-transparent rounded-3xl pointer-events-none" />

                <div className="relative z-10 flex flex-col items-center gap-4">
                    <div className="w-16 h-16 rounded-full bg-green-500/10 flex items-center justify-center text-green-500 mb-2">
                        <CheckCircle2 className="w-8 h-8" />
                    </div>
                    <h2 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-slate-400">
                        转换完成!
                    </h2>
                    <p className="text-slate-400 max-w-sm mx-auto">
                        视频已成功处理，共提取 12 张幻灯片。您可以下载演示文稿或裁剪后的视频。
                    </p>
                </div>

                <div className="flex flex-col sm:flex-row gap-4 justify-center relative z-10">
                    <a href={downloadUrl} download className="group flex items-center justify-center gap-2 px-6 py-4 bg-slate-100 text-slate-950 font-medium rounded-xl hover:bg-white transition-all hover:scale-105 active:scale-95 shadow-lg shadow-indigo-500/10">
                        <FileDown className="w-5 h-5 group-hover:text-indigo-600 transition-colors" />
                        <span>下载 PPTX</span>
                    </a>

                    <button className="group flex items-center justify-center gap-2 px-6 py-4 bg-slate-800 text-slate-200 font-medium rounded-xl hover:bg-slate-700 transition-all hover:scale-105 active:scale-95 border border-slate-700">
                        <Video className="w-5 h-5 group-hover:text-emerald-400 transition-colors" />
                        <span>下载视频</span>
                    </button>
                </div>

                <button
                    onClick={onReset}
                    className="relative z-10 text-slate-500 hover:text-indigo-400 text-sm flex items-center justify-center gap-1 mx-auto transition-colors"
                >
                    处理下一个视频 <ArrowRight className="w-3 h-3" />
                </button>
            </div>
        </motion.div>
    );
};
