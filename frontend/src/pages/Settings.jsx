import { useEffect, useRef, useState } from 'react';
import axiosClient from '../api/axiosClient';
import { errorMessage, getCurrentUser, isAdmin } from '../api/auth';
import { formatDateTime } from '../api/format';
import { useConfirm, useToast } from '../context/feedback';
import { Badge, Button, Card, EmptyState, ErrorState, Field, Skeleton } from '../components/ui';
import { IconKey, IconRefresh, IconUserPlus } from '../components/icons';
import SnmpSettings from '../components/SnmpSettings';

const ACTION_LABELS = {
    ADD_FLOW_POLICY: 'Thêm luật firewall',
    DELETE_FLOW_POLICY: 'Xoá luật firewall',
    DELETE_FLOW: 'Xoá flow',
    SET_QOS: 'Đặt giới hạn QoS',
    DELETE_QOS: 'Bỏ giới hạn QoS',
    CHANGE_PASSWORD: 'Đổi mật khẩu',
    CREATE_USER: 'Tạo người dùng',
    UPDATE_USER: 'Cập nhật người dùng',
    RESET_PASSWORD: 'Đặt lại mật khẩu',
    SET_SNMP: 'Cấu hình SNMP',
    DELETE_SNMP: 'Xoá cấu hình SNMP',
};
const ACTION_TONES = {
    ADD_FLOW_POLICY: 'accent', SET_QOS: 'info', DELETE_FLOW_POLICY: 'danger', DELETE_FLOW: 'danger', DELETE_QOS: 'danger',
    RESET_PASSWORD: 'warning', UPDATE_USER: 'warning', SET_SNMP: 'info', DELETE_SNMP: 'danger',
};

const describeDetails = (details) => {
    if (!details) return '';
    return Object.entries(details).filter(([, v]) => v !== null && v !== undefined)
        .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join('  ');
};

// ---------- Tab Tài khoản ----------
const AccountTab = () => {
    const toast = useToast();
    const [me, setMe] = useState({ status: 'loading' });
    const [form, setForm] = useState({ current: '', next: '', confirm: '' });
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        let active = true;
        const load = async () => {
            try {
                const res = await axiosClient.get('/auth/me');
                if (active) setMe({ status: 'ok', user: res.data });
            } catch (err) {
                if (active) setMe({ status: 'error', error: errorMessage(err) });
            }
        };
        load();
        return () => { active = false; };
    }, []);

    const mismatch = form.confirm !== '' && form.next !== form.confirm;
    const tooShort = form.next !== '' && form.next.length < 6;

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (mismatch || tooShort) return;
        setSaving(true);
        try {
            await axiosClient.post('/auth/change-password', { current_password: form.current, new_password: form.next });
            toast.success('Đã đổi mật khẩu', 'Lần đăng nhập sau hãy dùng mật khẩu mới.');
            setForm({ current: '', next: '', confirm: '' });
        } catch (err) {
            toast.error('Không thể đổi mật khẩu', errorMessage(err));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="grid grid-2">
            <Card title="Thông tin tài khoản">
                {me.status === 'loading' && <Skeleton height={96} />}
                {me.status === 'error' && <ErrorState message={me.error} />}
                {me.status === 'ok' && (
                    <dl className="dl">
                        <dt>Tên đăng nhập</dt><dd className="mono">{me.user.username}</dd>
                        <dt>Email</dt><dd>{me.user.email || '—'}</dd>
                        <dt>Vai trò</dt><dd>{me.user.role === 'admin' ? <Badge tone="accent">Quản trị viên</Badge> : <Badge>Chỉ xem</Badge>}</dd>
                        <dt>Ngày tạo</dt><dd>{formatDateTime(me.user.created_at)}</dd>
                        <dt>Đăng nhập gần nhất</dt><dd>{formatDateTime(me.user.last_login)}</dd>
                    </dl>
                )}
            </Card>
            <Card title="Đổi mật khẩu" subtitle="Mật khẩu tối thiểu 6 ký tự">
                <form className="form form-narrow" onSubmit={handleSubmit}>
                    <Field label="Mật khẩu hiện tại" htmlFor="pw-current">
                        <input id="pw-current" type="password" className="input" autoComplete="current-password" required
                            value={form.current} onChange={(e) => setForm({ ...form, current: e.target.value })} />
                    </Field>
                    <Field label="Mật khẩu mới" htmlFor="pw-new" hint={tooShort ? 'Cần ít nhất 6 ký tự' : undefined}>
                        <input id="pw-new" type="password" className="input" autoComplete="new-password" required minLength={6}
                            value={form.next} onChange={(e) => setForm({ ...form, next: e.target.value })} />
                    </Field>
                    <Field label="Nhập lại mật khẩu mới" htmlFor="pw-confirm" hint={mismatch ? 'Mật khẩu nhập lại không khớp' : undefined}>
                        <input id="pw-confirm" type="password" className="input" autoComplete="new-password" required
                            value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
                    </Field>
                    <Button type="submit" variant="primary" loading={saving} icon={<IconKey size={14} />}
                        disabled={mismatch || tooShort || !form.current || !form.next || !form.confirm}>
                        Đổi mật khẩu
                    </Button>
                </form>
            </Card>
        </div>
    );
};

// ---------- Hộp thoại đặt lại mật khẩu ----------
const ResetPasswordDialog = ({ user, onClose, onDone }) => {
    const toast = useToast();
    const [password, setPassword] = useState('');
    const [saving, setSaving] = useState(false);
    const inputRef = useRef(null);

    useEffect(() => {
        inputRef.current?.focus();
        const onKey = (e) => { if (e.key === 'Escape') onClose(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [onClose]);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setSaving(true);
        try {
            const res = await axiosClient.post(`/api/users/${user.id}/reset-password`, { new_password: password });
            toast.success('Đã đặt lại mật khẩu', res.data.message);
            onDone();
        } catch (err) {
            toast.error('Không thể đặt lại mật khẩu', errorMessage(err));
            setSaving(false);
        }
    };

    return (
        <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
            <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="reset-title" onSubmit={handleSubmit}>
                <div className="dialog-body" style={{ flexDirection: 'column' }}>
                    <h2 className="dialog-title" id="reset-title">Đặt lại mật khẩu cho {user.username}</h2>
                    <p className="dialog-msg">Người dùng sẽ phải dùng mật khẩu mới ở lần đăng nhập tiếp theo.</p>
                    <Field label="Mật khẩu mới" htmlFor="reset-pw" hint="Tối thiểu 6 ký tự">
                        <input id="reset-pw" ref={inputRef} type="password" className="input" autoComplete="new-password"
                            required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} />
                    </Field>
                </div>
                <div className="dialog-actions">
                    <Button type="button" onClick={onClose}>Huỷ</Button>
                    <Button type="submit" variant="primary" loading={saving} disabled={password.length < 6}>Đặt lại</Button>
                </div>
            </form>
        </div>
    );
};

// ---------- Tab Người dùng (admin) ----------
const UsersTab = () => {
    const toast = useToast();
    const confirm = useConfirm();
    const me = getCurrentUser();
    const [users, setUsers] = useState({ status: 'loading' });
    const [reloadKey, setReloadKey] = useState(0);
    const [form, setForm] = useState({ username: '', email: '', password: '', role: 'viewer' });
    const [creating, setCreating] = useState(false);
    const [pending, setPending] = useState(null);
    const [resetUser, setResetUser] = useState(null);

    useEffect(() => {
        let active = true;
        const load = async () => {
            try {
                const res = await axiosClient.get('/api/users');
                if (active) setUsers({ status: 'ok', list: res.data });
            } catch (err) {
                if (active) setUsers({ status: 'error', error: errorMessage(err) });
            }
        };
        load();
        return () => { active = false; };
    }, [reloadKey]);
    const reload = () => setReloadKey(k => k + 1);

    const handleCreate = async (e) => {
        e.preventDefault();
        setCreating(true);
        try {
            await axiosClient.post('/api/users', { ...form, email: form.email || null });
            toast.success('Đã tạo người dùng', `${form.username} (${form.role === 'admin' ? 'Quản trị viên' : 'Chỉ xem'})`);
            setForm({ username: '', email: '', password: '', role: 'viewer' });
            reload();
        } catch (err) {
            toast.error('Không thể tạo người dùng', errorMessage(err));
        } finally {
            setCreating(false);
        }
    };

    const update = async (user, changes, confirmOpts) => {
        if (confirmOpts && !(await confirm(confirmOpts))) return;
        setPending(user.id);
        try {
            await axiosClient.patch(`/api/users/${user.id}`, changes);
            toast.success('Đã cập nhật', user.username);
            reload();
        } catch (err) {
            toast.error('Không thể cập nhật', errorMessage(err));
        } finally {
            setPending(null);
        }
    };

    return (
        <>
            <Card title="Tạo người dùng" subtitle="Tài khoản mới đăng nhập được ngay">
                <form className="form" onSubmit={handleCreate}>
                    <div className="form-row">
                        <Field label="Tên đăng nhập" htmlFor="nu-name">
                            <input id="nu-name" className="input" required minLength={3} maxLength={50} autoComplete="off"
                                value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
                        </Field>
                        <Field label="Email (không bắt buộc)" htmlFor="nu-email">
                            <input id="nu-email" type="email" className="input" autoComplete="off"
                                value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                        </Field>
                    </div>
                    <div className="form-row">
                        <Field label="Mật khẩu" htmlFor="nu-pw" hint="Tối thiểu 6 ký tự">
                            <input id="nu-pw" type="password" className="input" required minLength={6} autoComplete="new-password"
                                value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
                        </Field>
                        <Field label="Vai trò" htmlFor="nu-role">
                            <select id="nu-role" className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                                <option value="viewer">Chỉ xem</option>
                                <option value="admin">Quản trị viên</option>
                            </select>
                        </Field>
                    </div>
                    <div><Button type="submit" variant="primary" loading={creating} icon={<IconUserPlus size={14} />}>Tạo người dùng</Button></div>
                </form>
            </Card>

            <Card title="Danh sách người dùng" actions={<Button size="sm" icon={<IconRefresh size={14} />} onClick={reload}>Làm mới</Button>} flush>
                {users.status === 'loading' && <div style={{ padding: 20, display: 'grid', gap: 12 }}>{[0, 1, 2].map(i => <Skeleton key={i} height={20} />)}</div>}
                {users.status === 'error' && <ErrorState message={users.error} onRetry={reload} />}
                {users.status === 'ok' && users.list.length === 0 && <EmptyState title="Chưa có người dùng" />}
                {users.status === 'ok' && users.list.length > 0 && (
                    <div className="table-wrap">
                        <table className="table responsive">
                            <thead>
                                <tr><th>Tên đăng nhập</th><th>Email</th><th>Vai trò</th><th>Trạng thái</th><th>Đăng nhập gần nhất</th><th className="actions"><span className="sr-only">Thao tác</span></th></tr>
                            </thead>
                            <tbody>
                                {users.list.map(u => {
                                    const self = u.id === me?.userId;
                                    return (
                                        <tr key={u.id}>
                                            <td data-label="Tên"><span className="mono">{u.username}</span>{self && <> <Badge>Bạn</Badge></>}</td>
                                            <td data-label="Email">{u.email || '—'}</td>
                                            <td data-label="Vai trò">{u.role === 'admin' ? <Badge tone="accent">Quản trị viên</Badge> : <Badge>Chỉ xem</Badge>}</td>
                                            <td data-label="Trạng thái">{u.is_active ? <Badge tone="success">Hoạt động</Badge> : <Badge tone="danger">Đã khoá</Badge>}</td>
                                            <td data-label="Đăng nhập">{formatDateTime(u.last_login)}</td>
                                            <td className="actions">
                                                {self ? <span className="hint">Đổi ở tab Tài khoản</span> : (
                                                    <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                                                        <Button size="sm" loading={pending === u.id}
                                                            onClick={() => update(u, { role: u.role === 'admin' ? 'viewer' : 'admin' }, u.role === 'admin' ? {
                                                                title: `Hạ quyền ${u.username}?`, message: 'Người dùng sẽ chỉ còn quyền xem, có hiệu lực ngay.', confirmLabel: 'Hạ quyền',
                                                            } : undefined)}>
                                                            {u.role === 'admin' ? 'Hạ xuống chỉ xem' : 'Cấp quyền quản trị'}
                                                        </Button>
                                                        <Button size="sm" icon={<IconKey size={14} />} onClick={() => setResetUser(u)}>Đặt lại mật khẩu</Button>
                                                        {u.is_active ? (
                                                            <Button size="sm" variant="danger" onClick={() => update(u, { is_active: false }, {
                                                                title: `Khoá tài khoản ${u.username}?`,
                                                                message: 'Người dùng bị đăng xuất ngay và không thể đăng nhập cho đến khi được mở khoá.',
                                                                confirmLabel: 'Khoá tài khoản',
                                                            })}>Khoá</Button>
                                                        ) : (
                                                            <Button size="sm" onClick={() => update(u, { is_active: true })}>Mở khoá</Button>
                                                        )}
                                                    </span>
                                                )}
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </Card>
            {resetUser && <ResetPasswordDialog user={resetUser} onClose={() => setResetUser(null)} onDone={() => setResetUser(null)} />}
        </>
    );
};

// ---------- Tab Nhật ký hoạt động (admin) ----------
const PAGE_SIZE = 50;

const AuditTab = () => {
    const [action, setAction] = useState('');
    const [limit, setLimit] = useState(PAGE_SIZE);
    const [reloadKey, setReloadKey] = useState(0);
    const [logs, setLogs] = useState({ key: null });
    const key = `${action}:${limit}:${reloadKey}`;

    useEffect(() => {
        // Đổi bộ lọc khi request cũ chưa xong: bỏ qua phản hồi cũ để nó không đè kết quả đã lọc
        let active = true;
        const k = `${action}:${limit}:${reloadKey}`;
        const load = async () => {
            try {
                const res = await axiosClient.get('/api/audit-logs', { params: { limit, action: action || undefined } });
                if (active) setLogs({ key: k, list: res.data, at: new Date() });
            } catch (err) {
                if (active) setLogs({ key: k, error: errorMessage(err) });
            }
        };
        load();
        return () => { active = false; };
    }, [action, limit, reloadKey]);

    const loaded = logs.key !== null;
    const refreshing = loaded && logs.key !== key;

    return (
        <Card
            title="Nhật ký hoạt động"
            subtitle={loaded && logs.at ? `Mọi thao tác thay đổi cấu hình · tải lúc ${logs.at.toLocaleTimeString('vi-VN')}` : 'Mọi thao tác thay đổi cấu hình'}
            actions={(
                <div className="toolbar">
                    <label className="inline-select">
                        <span className="label">Hành động</span>
                        <select className="select" value={action} onChange={(e) => { setAction(e.target.value); setLimit(PAGE_SIZE); }}>
                            <option value="">Tất cả</option>
                            {Object.entries(ACTION_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                        </select>
                    </label>
                    <Button size="sm" icon={<IconRefresh size={14} />} loading={refreshing} onClick={() => setReloadKey(k => k + 1)}>Làm mới</Button>
                </div>
            )}
            flush
        >
            {!loaded && <div style={{ padding: 20, display: 'grid', gap: 12 }}>{[0, 1, 2, 3].map(i => <Skeleton key={i} height={20} />)}</div>}
            {loaded && logs.error && <ErrorState message={logs.error} onRetry={() => setReloadKey(k => k + 1)} />}
            {loaded && !logs.error && logs.list.length === 0 && (
                <EmptyState title="Chưa có hoạt động nào" description={action ? 'Không có bản ghi cho hành động này.' : undefined} />
            )}
            {loaded && !logs.error && logs.list.length > 0 && (
                <>
                    <div className="table-wrap">
                        <table className="table responsive">
                            <thead><tr><th>Thời gian</th><th>Người thực hiện</th><th>Hành động</th><th>Switch</th><th>Chi tiết</th></tr></thead>
                            <tbody>
                                {logs.list.map(l => (
                                    <tr key={l.id}>
                                        <td data-label="Thời gian" style={{ whiteSpace: 'nowrap' }}>{formatDateTime(l.timestamp)}</td>
                                        <td data-label="Người"><span className="mono">{l.username || '—'}</span></td>
                                        <td data-label="Hành động"><Badge tone={ACTION_TONES[l.action]}>{ACTION_LABELS[l.action] || l.action}</Badge></td>
                                        <td data-label="Switch">{l.dpid === '-' ? '—' : `Switch ${l.dpid}`}</td>
                                        <td data-label="Chi tiết"><span className="code-cell">{describeDetails(l.details) || '—'}</span></td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    {logs.list.length >= limit && (
                        <div style={{ padding: 16, textAlign: 'center' }}>
                            <Button size="sm" loading={refreshing} onClick={() => setLimit(l => l + PAGE_SIZE)}>Tải thêm</Button>
                        </div>
                    )}
                </>
            )}
        </Card>
    );
};

const Settings = () => {
    const admin = isAdmin();
    const tabs = [
        { id: 'account', label: 'Tài khoản' },
        ...(admin ? [{ id: 'users', label: 'Người dùng' }, { id: 'devices', label: 'Thiết bị (SNMP)' }, { id: 'audit', label: 'Nhật ký hoạt động' }] : []),
    ];
    const [tab, setTab] = useState('account');

    return (
        <>
            <div className="page-head">
                <div>
                    <h1 className="page-title">Cài đặt</h1>
                    <p className="page-desc">{admin ? 'Tài khoản, người dùng và nhật ký hoạt động' : 'Thông tin và bảo mật tài khoản'}</p>
                </div>
            </div>
            <div className="tabs" role="tablist" aria-label="Cài đặt">
                {tabs.map(t => (
                    <button key={t.id} type="button" role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id}
                        aria-controls={`panel-${t.id}`} className="tab" onClick={() => setTab(t.id)}>
                        {t.label}
                    </button>
                ))}
            </div>
            <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-6)' }}>
                {tab === 'account' && <AccountTab />}
                {tab === 'users' && admin && <UsersTab />}
                {tab === 'devices' && admin && <SnmpSettings />}
                {tab === 'audit' && admin && <AuditTab />}
            </div>
        </>
    );
};

export default Settings;
