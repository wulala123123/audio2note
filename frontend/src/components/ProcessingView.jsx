import React, { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { Loader2, Terminal, ChevronRight } from 'lucide-react';

export const ProcessingView = ({ progress, message }) => {
    const [logs, setLogs] = useState([]);
    const scrollRef = useRef(null);

    useEffect(() => {
        if (message) {
            setLogs(prev => {
                // Avoid duplicate consecutive messages
                if (prev.length > 0 && prev[prev.length - 1] === message) return prev;
                return [...prev, message];
            });
        }
    }, [message]);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [logs]);

    return (
        <div className="w-full max-w-2xl mx-auto space-y-8 py-8">
            {/* Progress Circle & Status */}
            <div className="flex flex-col items-center justify-center gap-6">
                <div className="relative">
                    <svg className="w-32 h-32 transform -rotate-90">
                        <circle
                            cx="64"
                            cy="64"
                            r="60"
                            stroke="currentColor"
                            strokeWidth="4"
                            fill="transparent"
                            className="text-slate-800"
                        />
                        <motion.circle
                            cx="64"
                            cy="64"
                            r="60"
                            stroke="currentColor"
                            strokeWidth="4"
                            fill="transparent"
                            className="text-indigo-500"
                            initial={{ pathLength: 0 }}
                            animate={{ pathLength: progress / 100 }}
                            transition={{ ease: "linear" }}
                        />
                    </svg>
                    <div className="absolute inset-0 flex flex-col items-center justify-center">
                        <span className="text-3xl font-bold text-white">{Math.round(progress)}%</span>
                        <span className="text-xs text-slate-400 mt-1 uppercase tracking-wider">Processing</span>
                    </div>
                </div>
            </div>

            {/* Terminal Window */}
            <div className="bg-[#1e1e1e] rounded-lg border border-slate-800 shadow-2xl overflow-hidden font-mono text-sm">
                <div className="bg-[#2d2d2d] px-4 py-2 flex items-center gap-2 border-b border-black/20">
                    <div className="flex gap-1.5">
                        <div className="w-3 h-3 rounded-full bg-red-500/80" />
                        <div className="w-3 h-3 rounded-full bg-yellow-500/80" />
                        <div className="w-3 h-3 rounded-full bg-green-500/80" />
                    </div>
                    <div className="ml-2 flex items-center gap-1.5 text-slate-400 text-xs">
                        <Terminal className="w-3 h-3" />
                        <span>backend-worker — zsh</span>
                    </div>
                </div>

                <div
                    ref={scrollRef}
                    className="h-64 overflow-y-auto p-4 space-y-1 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent"
                >
                    {logs.length === 0 && (
                        <div className="text-slate-500 italic">Waiting for logs...</div>
                    )}
                    {logs.map((log, i) => (
                        <motion.div
                            key={i}
                            initial={{ opacity: 0, x: -10 }}
                            animate={{ opacity: 1, x: 0 }}
                            className="flex items-start gap-2 text-slate-300"
                        >
                            <span className="text-indigo-400 mt-0.5"><ChevronRight className="w-3 h-3" /></span>
                            <span className="break-all">{log}</span>
                        </motion.div>
                    ))}
                    {/* Blinking Cursor */}
                    <motion.div
                        animate={{ opacity: [0, 1, 0] }}
                        transition={{ repeat: Infinity, duration: 0.8 }}
                        className="w-2 h-4 bg-indigo-500 ml-5 mt-1"
                    />
                </div>
            </div>
        </div>
    );
};
