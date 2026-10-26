const TOKEN_KEY = 'access_token';

export const getToken = () => localStorage.getItem(TOKEN_KEY);

export const setToken = (token) => localStorage.setItem(TOKEN_KEY, token);

export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

// Đọc payload JWT (chỉ để hiển thị giao diện; quyền thật do backend kiểm tra)
export const getCurrentUser = () => {
    const token = getToken();
    if (!token) return null;
    try {
        const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
        const payload = JSON.parse(atob(base64));
        if (payload.exp && payload.exp * 1000 < Date.now()) return null;
        return { username: payload.sub, userId: payload.user_id, role: payload.role };
    } catch {
        return null;
    }
};

export const isAdmin = () => getCurrentUser()?.role === 'admin';

// Chuyển lỗi axios thành câu thông báo dễ đọc
export const errorMessage = (err, fallback = 'Lỗi kết nối đến máy chủ') => {
    const detail = err?.response?.data?.detail;
    if (Array.isArray(detail)) {
        // Lỗi validate của FastAPI (422)
        return detail.map(d => d.msg?.replace(/^Value error, /, '')).join('; ');
    }
    return detail || fallback;
};
