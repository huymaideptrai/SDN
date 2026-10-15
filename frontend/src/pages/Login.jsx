import React, { useState } from 'react';
import axiosClient from '../api/axiosClient';
import { useNavigate } from 'react-router-dom';

const Login = () => {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const navigate = useNavigate();
    const handleLogin = async (e) => {
        e.preventDefault();
        setError('');

        try {
            const formData = new URLSearchParams();
            formData.append('username', username);
            formData.append('password', password);
            const response = await axiosClient.post('/auth/login', formData, {
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
            });

            localStorage.setItem('access_token', response.data.access_token);
            navigate('/dashboard');
            
        } catch (err) {
            setError(err.response?.data?.detail || 'Lỗi kết nối đến máy chủ');
        }
    };

    return (
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: '100px' }}>
            <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', width: '300px', gap: '15px' }}>
                <h2>Đăng nhập SDN</h2>
                {error && <p style={{ color: 'red' }}>{error}</p>}
                
                <input 
                    type="text" 
                    placeholder="Tên đăng nhập" 
                    value={username} 
                    onChange={(e) => setUsername(e.target.value)} 
                    required 
                />
                <input 
                    type="password" 
                    placeholder="Mật khẩu" 
                    value={password} 
                    onChange={(e) => setPassword(e.target.value)} 
                    required 
                />
                
                <button type="submit" style={{ padding: '10px', background: '#007BFF', color: '#fff', border: 'none', cursor: 'pointer' }}>
                    Đăng nhập
                </button>
            </form>
        </div>
    );
};

export default Login;