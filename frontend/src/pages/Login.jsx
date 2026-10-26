import { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import axiosClient from '../api/axiosClient';
import { setToken, errorMessage, getCurrentUser } from '../api/auth';
import { Alert, Button, Field } from '../components/ui';
import { IconLock, IconNetwork } from '../components/icons';

const Login = () => {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const navigate = useNavigate();

    if (getCurrentUser()) return <Navigate to="/dashboard" replace />;

    const handleLogin = async (e) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            const formData = new URLSearchParams();
            formData.append('username', username);
            formData.append('password', password);
            const response = await axiosClient.post('/auth/login', formData, {
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
            });
            setToken(response.data.access_token);
            navigate('/dashboard');
        } catch (err) {
            setError(errorMessage(err));
            setLoading(false);
        }
    };

    return (
        <div className="login-page">
            <div className="card login-card">
                <div className="login-head">
                    <span className="brand-mark"><IconNetwork size={22} /></span>
                    <div>
                        <h1 style={{ fontSize: 'var(--fs-xl)' }}>SDN Controller</h1>
                        <p className="page-desc">Đăng nhập để quản trị hạ tầng mạng</p>
                    </div>
                </div>
                <div className="card-body">
                    <form className="form" onSubmit={handleLogin}>
                        {error && <Alert tone="danger">{error}</Alert>}
                        <Field label="Tên đăng nhập" htmlFor="username">
                            <input id="username" className="input" autoComplete="username" autoFocus
                                value={username} onChange={(e) => setUsername(e.target.value)} required />
                        </Field>
                        <Field label="Mật khẩu" htmlFor="password">
                            <input id="password" type="password" className="input" autoComplete="current-password"
                                value={password} onChange={(e) => setPassword(e.target.value)} required />
                        </Field>
                        <Button type="submit" variant="primary" className="btn-block" loading={loading}
                            icon={<IconLock size={14} />}>
                            {loading ? 'Đang đăng nhập…' : 'Đăng nhập'}
                        </Button>
                    </form>
                </div>
            </div>
        </div>
    );
};

export default Login;
