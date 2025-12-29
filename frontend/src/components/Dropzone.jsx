import React from 'react';
import { motion } from 'framer-motion';
import { UploadCloud, FileVideo } from 'lucide-react';
import { clsx } from 'clsx';

export const Dropzone = ({ onDrop, folderName = "video_slides" }) => {
    const inputRef = React.useRef(null);

    const handleClick = () => {
        inputRef.current?.click();
    };

    const handleFileChange = (e) => {
        if (e.target.files && e.target.files.length > 0) {
            onDrop(e.target.files);
        }
    };

    const handleDragOver = (e) => {
        e.preventDefault();
        e.stopPropagation();
    };

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
            <input
                type="file"
                ref={inputRef}
                onChange={handleFileChange}
                style={{ display: 'none' }}
                accept="video/*"
            />
            <div
                onClick={handleClick}
                onDragOver={handleDragOver}
                onDrop={handleDrop}
                className={clsx(
                    "relative group cursor-pointer",
                    "rounded-3xl border-2 border-dashed border-slate-700 bg-slate-900/50",
                    "hover:border-indigo-500/50 hover:bg-slate-900/80 transition-all duration-300",
                    "h-80 flex flex-col items-center justify-center gap-6",
                    "backdrop-blur-sm"
                )}
            >
                <div className="absolute inset-0 bg-gradient-to-br from-indigo-500/5 to-purple-500/5 rounded-3xl opacity-0 group-hover:opacity-100 transition-opacity duration-500" />

                <div className="relative z-10 p-6 rounded-full bg-slate-950 border border-slate-800 shadow-2xl group-hover:scale-110 transition-transform duration-300">
                    <UploadCloud className="w-10 h-10 text-indigo-400" />
                </div>

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
