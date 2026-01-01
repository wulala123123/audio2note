/**
 * 文件名: api.js
 * 功能描述: 前端与后端交互的 API 服务层封装
 * 核心逻辑:
 *    - 封装 Axios 实例
 *    - 提供文件上传、状态轮询等核心业务接口
 *    - 统一处理后端 URL 拼接
 */
import axios from 'axios';

// 后端服务地址
// 注意: 前端开发服通常在 5173，后端在 8000
// 如遇跨域问题，请确保后端已配置 CORS 允许 localhost:5173
const BASE_URL = 'http://127.0.0.1:8000';

// 创建 axios 实例
const api = axios.create({
    baseURL: BASE_URL,
    // 超时设置为 30 秒 (防止上传大文件时过早断开)
    timeout: 30000,
});

/**
 * 上传视频文件到后端处理
 * 
 * 使用 multipart/form-data 格式发送文件。
 * 上传成功后立即返回 task_id，无需等待视频处理完成。
 * 
 * Args:
 *     file (File): 浏览器 File 对象，通常来自 Dropzone 或 input[type=file]
 * 
 * Returns:
 *     Promise<{task_id: string}>: 包含任务 ID 的对象
 *     
 * Throws:
 *     AxiosError: 如果上传失败或文件格式不被接受
 */
export const uploadVideo = async (file) => {
    const formData = new FormData();
    formData.append('file', file);

    // POST 请求发送文件
    // Why Content-Type? 虽然 axios 会自动设置，显式声明有助于代码可读性
    const response = await api.post('/api/v1/tasks/upload', formData, {
        headers: {
            'Content-Type': 'multipart/form-data',
        },
    });
    return response.data;
};

/**
 * 查询指定任务的处理状态
 * 
 * 前端需要轮询此接口来获取进度更新。
 * 
 * Args:
 *     taskId (string): 任务唯一标识符 (UUID)
 * 
 * Returns:
 *     Promise<{
 *         status: 'processing' | 'completed' | 'failed',
 *         progress: number,
 *         message: string,
 *         result_url?: string
 *     }>: 任务状态详情
 */
export const checkStatus = async (taskId) => {
    const response = await api.get(`/api/v1/tasks/${taskId}/status`);
    return response.data;
};

/**
 * 获取完整的资源下载链接
 * 
 * 处理后端返回的相对路径，拼接完整的 API 域名。
 * 
 * Args:
 *     path (string): 相对路径 (如 /static/xxx.pptx) 或 完整 URL
 * 
 * Returns:
 *     string: 可直接访问的完整 URL
 */
export const getDownloadUrl = (path) => {
    // 如果已经是完整 URL (如 S3 链接)，直接返回
    if (path.startsWith('http')) return path;

    // 拼接本地后端地址
    return `${BASE_URL}${path}`;
};
