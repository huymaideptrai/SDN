import { useEffect, useState } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import axiosClient from '../api/axiosClient';
import { clearToken, errorMessage } from '../api/auth';
import { Button } from './ui';
import { IconDashboard, IconLogout, IconMenu, IconNetwork, IconSettings, IconSliders } from './icons';

const PAGES = [
    { to: '/dashboard', label: 'Tổng quan', icon: IconDashboard },
    { to: '/control', label: 'Điều khiển mạng', icon: IconSliders },
    { to: '/settings', label: 'Cài đặt', icon: IconSettings },
];

const STATUS_POLL_MS = 10000;

// Trạng thái thật của controller: lấy từ /api/sdn/switches, không giả lập
const ControllerStatus = () => {
    const [status, setStatus] = useState({ state: 'checking' });

    useEffect(() => {
        const check = async () => {
            try {
                const res = await axiosClient.get('/api/sdn/switches');
                setStatus({ state: 'online', switches: res.data.switches.length });
            } catch (err) {
                setStatus({ state: 'offline', message: errorMessage(err, 'Không kết nối được backend') });
            }
        };
        check();
        const id = setInterval(check, STATUS_POLL_MS);
        return () => clearInterval(id);
    }, []);

    const view = {
        checking: { dot: 'wait', text: 'Đang kiểm tra controller…' },
        online: { dot: 'ok', text: `Controller trực tuyến · ${status.switches} switch` },
        offline: { dot: 'err', text: 'Mất kết nối controller' },
    }[status.state];

    return (
        <span className="status-pill" title={status.message || view.text} aria-live="polite">
            <span className={`dot ${view.dot}`} />
            <span className="status-text">{view.text}</span>
        </span>
    );
};

const Layout = ({ user, children }) => {
    const [navOpen, setNavOpen] = useState(false);
    const location = useLocation();
    const navigate = useNavigate();
    const current = PAGES.find(p => location.pathname.startsWith(p.to));

    const handleLogout = () => {
        clearToken();
        navigate('/login');
    };

    return (
        <div className={`shell ${navOpen ? 'nav-open' : ''}`}>
            <aside className="sidebar" aria-label="Điều hướng chính">
                <div className="brand">
                    <span className="brand-mark"><IconNetwork size={16} /></span>
                    <div>
                        <div className="brand-name">SDN Controller</div>
                        <div className="brand-sub">Quản trị mạng</div>
                    </div>
                </div>
                <nav className="nav">
                    {PAGES.map(({ to, label, icon: Icon }) => (
                        <NavLink key={to} to={to} className="nav-link" onClick={() => setNavOpen(false)}>
                            <Icon size={16} />{label}
                        </NavLink>
                    ))}
                </nav>
                <div className="sidebar-footer">
                    <div className="user-row">
                        <span className="avatar" aria-hidden="true">{user.username.slice(0, 2)}</span>
                        <div style={{ minWidth: 0 }}>
                            <div className="user-name">{user.username}</div>
                            <div className="hint">{user.role === 'admin' ? 'Quản trị viên' : 'Chỉ xem'}</div>
                        </div>
                    </div>
                    <Button size="sm" variant="ghost" icon={<IconLogout size={14} />} onClick={handleLogout} className="btn-block">
                        Đăng xuất
                    </Button>
                </div>
            </aside>
            <div className="backdrop" onClick={() => setNavOpen(false)} aria-hidden="true" />

            <div className="main">
                <header className="topbar">
                    <Button variant="ghost" className="btn-icon menu-btn" onClick={() => setNavOpen(o => !o)}
                        aria-label="Mở menu" aria-expanded={navOpen}>
                        <IconMenu size={18} />
                    </Button>
                    <span className="topbar-title">{current?.label}</span>
                    <div className="topbar-right">
                        <ControllerStatus />
                    </div>
                </header>
                <main className="content">{children}</main>
            </div>
        </div>
    );
};

export default Layout;
