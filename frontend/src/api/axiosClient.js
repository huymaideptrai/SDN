import axios from 'axios';

const axiosClient = axios.create({
    baseURL: 'http://127.0.0.1:8000',
    headers: {
        'Content-Type': 'application/json',
    },
});

axiosClient.interceptors.request.use((config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});
axiosClient.interceptors.response.use(
    (response) => response,
    (error) => {
        // NẾU NHẬN LỖI 401 (Unauthorized)
        if (error.response && error.response.status === 401) {
            console.error("Token hết hạn hoặc không hợp lệ. Đang đăng xuất...");
            // Xóa token lỗi
            localStorage.removeItem('access_token');
            // Ép trình duyệt chuyển hướng về trang Login
            window.location.href = '/login'; 
        }
        return Promise.reject(error);
    }
);

export default axiosClient;