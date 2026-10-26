import axios from 'axios';
import { getToken, clearToken } from './auth';

const axiosClient = axios.create({
    baseURL: import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000',
    headers: {
        'Content-Type': 'application/json',
    },
});

axiosClient.interceptors.request.use((config) => {
    const token = getToken();
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});
axiosClient.interceptors.response.use(
    (response) => response,
    (error) => {
        // NẾU NHẬN LỖI 401 (Unauthorized) thì đăng xuất
        if (error.response && error.response.status === 401 && window.location.pathname !== '/login') {
            console.error("Token hết hạn hoặc không hợp lệ. Đang đăng xuất...");
            clearToken();
            window.location.href = '/login';
        }
        return Promise.reject(error);
    }
);

export default axiosClient;
