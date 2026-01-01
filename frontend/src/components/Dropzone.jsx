/**
 * 文件名: Dropzone.jsx
 * 功能描述: 视频文件拖拽上传组件
 * 核心逻辑:
 *    - 封装 HTML5 Drag and Drop API
 *    - 支持点击上传 (Click to Upload)
 *    - 视觉反馈: 悬停高亮、动画缩放
 *    - 文件过滤: 仅接受 video/* 类型
 */
import React from 'react';
import { motion } from 'framer-motion';
import { UploadCloud, FileVideo } from 'lucide-react';
import { clsx } from 'clsx';

export const Dropzone = ({ onDrop, folderName = "video_slides" }) => {
    // 引用隐藏的 input 元素，用于实现点击上传
    const inputRef = React.useRef(null);

    /**
     * 处理点击事件
     * 触发 input file 的原生点击
     */
    const handleClick = () => {
        inputRef.current?.click();
    };

    /**
     * 处理文件选择事件 (Input Change)
     * 当用户通过点击弹窗选择文件后触发
     */
    const handleFileChange = (e) => {
        if (e.target.files && e.target.files.length > 0) {
            onDrop(e.target.files);
        }
    };

    /**
     * 阻止浏览器默认行为
     * Why? 浏览器默认会直接在新标签页打开拖入的文件，必须阻止此行为才能捕获文件
     */
    const handleDragOver = (e) => {
        e.preventDefault();
        e.stopPropagation();
    };

    /**
     * 处理拖拽释放事件 (Drop)
     * 从 DataTransfer 对象中提取文件列表
     */
    const handleDrop = (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            onDrop(e.dataTransfer.files);
        }
    };

    return (
        <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="w-full max-w-xl mx-auto"
        >
            {/* 隐藏的文件输入框 */}
            <input
                type="file"
                ref={inputRef}
                onChange={handleFileChange}
                style={{ display: 'none' }}
                accept="video/*"
            />

            {/* 拖拽区域容器 */}
            <div
                onClick={handleClick}
                onDragOver={handleDragOver}
                onDrop={handleDrop}
                className={clsx(
                    "relative group cursor-pointer",
                    // 样式: 圆角、虚线边框、深色半透明背景
                    "rounded-3xl border-2 border-dashed border-slate-700 bg-slate-900/50",
                    // 交互: 悬停时边框变紫、背景变深
                    "hover:border-indigo-500/50 hover:bg-slate-900/80 transition-all duration-300",
                    "h-80 flex flex-col items-center justify-center gap-6",
                    "backdrop-blur-sm"
                )}
            >
                {/* 背景光效: 仅在悬停时显示 */}
                <div className="absolute inset-0 bg-gradient-to-br from-indigo-500/5 to-purple-500/5 rounded-3xl opacity-0 group-hover:opacity-100 transition-opacity duration-500" />

                {/* 图标容器: 悬停时轻微放大 */}
                <div className="relative z-10 p-6 rounded-full bg-slate-950 border border-slate-800 shadow-2xl group-hover:scale-110 transition-transform duration-300">
                    <UploadCloud className="w-10 h-10 text-indigo-400" />
                </div>

                {/* 提示文案 */}
                <div className="text-center space-y-2 relative z-10">
                    <h3 className="text-xl font-medium text-slate-200">
                        拖入视频 或 <span className="text-indigo-400">点击上传</span>
                    </h3>
                    <p className="text-slate-500 text-sm">
                        支持 MP4, MOV, FLV • AI 自动提取幻灯片
                    </p>
                </div>
            </div>
        </motion.div>
    );
};
