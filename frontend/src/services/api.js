import axios from 'axios';

const BASE_URL = 'http://127.0.0.1:8000';

const api = axios.create({
    baseURL: BASE_URL,
});

/**
 * Uploads a video file to the backend with processing options.
 * @param {File} file 
 * @param {Object} options
 * @param {boolean} options.enable_ppt_extraction
 * @param {boolean} options.enable_audio_transcription
 * @returns {Promise<{task_id: string}>}
 */
export const uploadVideo = async (file, options = {}) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('enable_ppt_extraction', options.enable_ppt_extraction ?? true);
    formData.append('enable_audio_transcription', options.enable_audio_transcription ?? true);

    const response = await api.post('/api/v1/tasks/upload', formData, {
        headers: {
            'Content-Type': 'multipart/form-data',
        },
    });
    return response.data;
};

/**
 * Checks the status of a task.
 * @param {string} taskId 
 * @returns {Promise<{progress: number, message: string, result_url?: string}>}
 */
export const checkStatus = async (taskId) => {
    const response = await api.get(`/api/v1/tasks/${taskId}/status`);
    return response.data;
};

export const getDownloadUrl = (path) => {
    if (path.startsWith('http')) return path;
    return `${BASE_URL}${path}`;
};
