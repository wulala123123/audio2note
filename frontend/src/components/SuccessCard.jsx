/**
 * 文件名: SuccessCard.jsx
 * 功能描述: 处理成功后的结果展示卡片
 * 核心逻辑:
 *    - 展示"转换完成"状态
 *    - 提供生成的 PPTX 下载链接
 *    - 提供发言稿下载链接 (如启用音频转录)
 *    - 提供处理下一个视频的重置入口
 */
import React from 'react';
import { motion } from 'framer-motion';
import { FileDown, FileText, CheckCircle2, ArrowRight } from 'lucide-react';
import { clsx } from 'clsx';

export const SuccessCard = ({ onReset, downloadUrl, transcriptUrl }) => {
    return (
        <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="w-full max-w-xl mx-auto"
        >
            <div className="relative bg-slate-900/50 backdrop-blur-sm border border-slate-800 rounded-3xl p-8 md:p-12 text-center space-y-8 shadow-2xl">
                {/* 顶部绚丽光效 (装饰用途) */}
                <div className="absolute inset-0 bg-gradient-to-b from-indigo-500/10 to-transparent rounded-3xl pointer-events-none" />

                <div className="relative z-10 flex flex-col items-center gap-4">
                    {/* 成功图标 */}
                    <div className="w-16 h-16 rounded-full bg-green-500/10 flex items-center justify-center text-green-500 mb-2">
                        <CheckCircle2 className="w-8 h-8" />
                    </div>
                    {/* 渐变文本标题 */}
                    <h2 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-slate-400">
                        转换完成!
                    </h2>
                    <p className="text-slate-400 max-w-sm mx-auto">
                        视频已成功处理。您可以下载提取的演示文稿和视频发言稿。
                    </p>
                </div>

                {/* 操作按钮区 */}
                <div className="flex flex-col sm:flex-row gap-4 justify-center relative z-10">

                    {/* PPT 下载按钮 (主要操作) */}
                    {downloadUrl && (
                        <a
                            href={downloadUrl}
                            download
                            className="group flex items-center justify-center gap-2 px-6 py-4 bg-slate-100 text-slate-950 font-medium rounded-xl hover:bg-white transition-all hover:scale-105 active:scale-95 shadow-lg shadow-indigo-500/10"
                        >
                            <FileDown className="w-5 h-5 group-hover:text-indigo-600 transition-colors" />
                            <span>下载 PPT</span>
                        </a>
                    )}

                    {/* 发言稿下载按钮 */}
                    {transcriptUrl && (
                        <a
                            href={transcriptUrl}
                            download
                            className="group flex items-center justify-center gap-2 px-6 py-4 bg-slate-800 text-slate-200 font-medium rounded-xl hover:bg-slate-700 transition-all hover:scale-105 active:scale-95 border border-slate-700"
                        >
                            <FileText className="w-5 h-5 group-hover:text-emerald-400 transition-colors" />
                            <span>下载发言稿</span>
                        </a>
                    )}
                </div>

                {/* 无结果提示 */}
                {!downloadUrl && !transcriptUrl && (
                    <p className="text-slate-500 relative z-10">未生成任何输出文件</p>
                )}

                {/* 重置按钮 */}
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
