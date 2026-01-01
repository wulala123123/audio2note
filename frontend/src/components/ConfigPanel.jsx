import React from 'react';
import { motion } from 'framer-motion';
import { FileText, Mic, Settings2 } from 'lucide-react';
import { clsx } from 'clsx';

export const ConfigPanel = ({ config, onConfigChange }) => {
    return (
        <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="w-full max-w-xl mx-auto mb-8 bg-slate-900/50 backdrop-blur-sm border border-slate-800 rounded-2xl p-6"
        >
            <div className="flex items-center gap-2 mb-4 text-slate-300 font-medium">
                <Settings2 className="w-4 h-4 text-indigo-400" />
                <span>处理选项</span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <label className={clsx(
                    "relative flex items-center gap-4 p-4 rounded-xl border transition-all cursor-pointer",
                    config.enable_ppt_extraction
                        ? "bg-indigo-500/10 border-indigo-500/50"
                        : "bg-slate-800/50 border-slate-700 hover:bg-slate-800"
                )}>
                    <input
                        type="checkbox"
                        checked={config.enable_ppt_extraction}
                        onChange={(e) => onConfigChange('enable_ppt_extraction', e.target.checked)}
                        className="absolute opacity-0 w-full h-full cursor-pointer"
                    />
                    <div className={clsx(
                        "w-10 h-10 rounded-lg flex items-center justify-center transition-colors",
                        config.enable_ppt_extraction ? "bg-indigo-500 text-white" : "bg-slate-700 text-slate-400"
                    )}>
                        <FileText className="w-5 h-5" />
                    </div>
                    <div>
                        <div className={clsx("font-medium", config.enable_ppt_extraction ? "text-white" : "text-slate-400")}>
                            PPT 提取
                        </div>
                        <div className="text-xs text-slate-500 mt-0.5">自动识别并去重关键帧</div>
                    </div>
                    <div className={clsx(
                        "ml-auto w-5 h-5 rounded-full border-2 flex items-center justify-center",
                        config.enable_ppt_extraction ? "border-indigo-500 bg-indigo-500" : "border-slate-600"
                    )}>
                        {config.enable_ppt_extraction && (
                            <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                            </svg>
                        )}
                    </div>
                </label>

                <label className={clsx(
                    "relative flex items-center gap-4 p-4 rounded-xl border transition-all cursor-pointer",
                    config.enable_audio_transcription
                        ? "bg-purple-500/10 border-purple-500/50"
                        : "bg-slate-800/50 border-slate-700 hover:bg-slate-800"
                )}>
                    <input
                        type="checkbox"
                        checked={config.enable_audio_transcription}
                        onChange={(e) => onConfigChange('enable_audio_transcription', e.target.checked)}
                        className="absolute opacity-0 w-full h-full cursor-pointer"
                    />
                    <div className={clsx(
                        "w-10 h-10 rounded-lg flex items-center justify-center transition-colors",
                        config.enable_audio_transcription ? "bg-purple-500 text-white" : "bg-slate-700 text-slate-400"
                    )}>
                        <Mic className="w-5 h-5" />
                    </div>
                    <div>
                        <div className={clsx("font-medium", config.enable_audio_transcription ? "text-white" : "text-slate-400")}>
                            语音转写
                        </div>
                        <div className="text-xs text-slate-500 mt-0.5">FunASR + Gemini 纠错</div>
                    </div>
                    <div className={clsx(
                        "ml-auto w-5 h-5 rounded-full border-2 flex items-center justify-center",
                        config.enable_audio_transcription ? "border-purple-500 bg-purple-500" : "border-slate-600"
                    )}>
                        {config.enable_audio_transcription && (
                            <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                            </svg>
                        )}
                    </div>
                </label>
            </div>
        </motion.div>
    );
};
