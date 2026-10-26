import { useEffect, useRef, useState } from 'react';
import axiosClient from '../api/axiosClient';
import { errorMessage } from '../api/auth';
import { formatDateTime } from '../api/format';
import { useConfirm, useToast } from '../context/feedback';
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Field, Skeleton } from './ui';
import { IconNetwork, IconRefresh } from './icons';

const EMPTY_FORM = {
    host: '', port: 161, version: '2c', community: '',
    v3_user: '', v3_auth_proto: 'SHA', v3_auth_key: '', v3_priv_proto: 'AES', v3_priv_key: '',
};

const describeResult = (r) => {
    if (r.status === 'ok') {
        const parts = [r.sys_name, r.cpu ? `CPU ${r.cpu.percent}%` : 'không có CPU',
            r.memory ? 'có RAM' : 'không có RAM', `${r.temperatures?.length || 0} cảm biến nhiệt`].filter(Boolean);
        return parts.join(' · ');
    }
    return r.error || 'Không phản hồi';
};

// ---------- Hộp thoại cấu hình SNMP cho một switch ----------
const SnmpDialog = ({ dpid, existing, onClose, onSaved }) => {
    const toast = useToast();
    const [form, setForm] = useState(() => (existing ? {
        ...EMPTY_FORM, host: existing.host, port: existing.port, version: existing.version,
        v3_user: existing.v3_user || '', v3_auth_proto: existing.v3_auth_proto || '', v3_priv_proto: existing.v3_priv_proto || '',
    } : EMPTY_FORM));
    const [saving, setSaving] = useState(false);
    const hostRef = useRef(null);
    const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

    useEffect(() => {
        hostRef.current?.focus();
        const onKey = (e) => { if (e.key === 'Escape') onClose(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [onClose]);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setSaving(true);
        const v3 = form.version === '3';
        const payload = {
            host: form.host, port: Number(form.port), version: form.version,
            community: v3 ? null : form.community || null,
            v3_user: v3 ? form.v3_user || null : null,
            v3_auth_proto: v3 && form.v3_auth_proto ? form.v3_auth_proto : null,
            v3_auth_key: v3 && form.v3_auth_proto ? form.v3_auth_key || null : null,
            v3_priv_proto: v3 && form.v3_auth_proto && form.v3_priv_proto ? form.v3_priv_proto : null,
            v3_priv_key: v3 && form.v3_auth_proto && form.v3_priv_proto ? form.v3_priv_key || null : null,
        };
        try {
            await axiosClient.put(`/api/devices/snmp/${dpid}`, payload);
            toast.success('Đã lưu cấu hình SNMP', `Switch ${dpid} · ${form.host}`);
            onSaved();
        } catch (err) {
            toast.error('Không thể lưu', errorMessage(err));
            setSaving(false);
        }
    };

    const keep = (has) => (has ? 'Đã lưu — bỏ trống để giữ nguyên' : '');

    return (
        <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
            <form className="dialog dialog-wide" role="dialog" aria-modal="true" aria-labelledby="snmp-title" onSubmit={handleSubmit}>
                <div className="dialog-body" style={{ flexDirection: 'column' }}>
                    <h2 className="dialog-title" id="snmp-title">SNMP cho Switch {dpid}</h2>
                    <p className="dialog-msg">Địa chỉ quản lý (management IP) và thông tin SNMP của switch thật. Switch Mininet không có SNMP.</p>
                    <div className="form-row">
                        <Field label="Địa chỉ quản lý" htmlFor="snmp-host" hint="IP hoặc tên máy">
                            <input id="snmp-host" ref={hostRef} className="input" required value={form.host} onChange={set('host')} placeholder="192.168.1.10" />
                        </Field>
                        <Field label="Cổng UDP" htmlFor="snmp-port">
                            <input id="snmp-port" type="number" min={1} max={65535} className="input" required value={form.port} onChange={set('port')} />
                        </Field>
                    </div>
                    <Field label="Phiên bản">
                        <div className="segmented" role="group" aria-label="Phiên bản SNMP">
                            {[['2c', 'SNMPv2c'], ['3', 'SNMPv3']].map(([v, label]) => (
                                <button key={v} type="button" className="scope" aria-pressed={form.version === v}
                                    onClick={() => setForm(f => ({ ...f, version: v }))}>{label}</button>
                            ))}
                        </div>
                    </Field>
                    {form.version === '2c' ? (
                        <Field label="Community" htmlFor="snmp-community" hint="Nên dùng community chỉ đọc (read-only)">
                            <input id="snmp-community" type="password" className="input" autoComplete="off" value={form.community} onChange={set('community')}
                                required={!existing?.has_community} placeholder={keep(existing?.has_community)} />
                        </Field>
                    ) : (
                        <>
                            <Field label="Tên người dùng (USM)" htmlFor="snmp-user">
                                <input id="snmp-user" className="input" autoComplete="off" required value={form.v3_user} onChange={set('v3_user')} />
                            </Field>
                            <div className="form-row">
                                <Field label="Xác thực" htmlFor="snmp-auth">
                                    <select id="snmp-auth" className="select" value={form.v3_auth_proto} onChange={set('v3_auth_proto')}>
                                        <option value="">Không (noAuth)</option>
                                        <option value="SHA">SHA</option>
                                        <option value="SHA256">SHA-256</option>
                                        <option value="MD5">MD5</option>
                                    </select>
                                </Field>
                                <Field label="Khoá xác thực" htmlFor="snmp-auth-key" hint="Tối thiểu 8 ký tự">
                                    <input id="snmp-auth-key" type="password" className="input" autoComplete="off" disabled={!form.v3_auth_proto}
                                        minLength={8} value={form.v3_auth_key} onChange={set('v3_auth_key')} placeholder={keep(existing?.has_auth_key)}
                                        required={!!form.v3_auth_proto && !existing?.has_auth_key} />
                                </Field>
                            </div>
                            <div className="form-row">
                                <Field label="Mã hoá" htmlFor="snmp-priv">
                                    <select id="snmp-priv" className="select" value={form.v3_priv_proto} onChange={set('v3_priv_proto')} disabled={!form.v3_auth_proto}>
                                        <option value="">Không (noPriv)</option>
                                        <option value="AES">AES-128</option>
                                        <option value="DES">DES</option>
                                    </select>
                                </Field>
                                <Field label="Khoá mã hoá" htmlFor="snmp-priv-key" hint="Tối thiểu 8 ký tự">
                                    <input id="snmp-priv-key" type="password" className="input" autoComplete="off" disabled={!form.v3_auth_proto || !form.v3_priv_proto}
                                        minLength={8} value={form.v3_priv_key} onChange={set('v3_priv_key')} placeholder={keep(existing?.has_priv_key)}
                                        required={!!form.v3_auth_proto && !!form.v3_priv_proto && !existing?.has_priv_key} />
                                </Field>
                            </div>
                        </>
                    )}
                </div>
                <div className="dialog-actions">
                    <Button type="button" onClick={onClose}>Huỷ</Button>
                    <Button type="submit" variant="primary" loading={saving}>Lưu cấu hình</Button>
                </div>
            </form>
        </div>
    );
};

// ---------- Tab Thiết bị (SNMP) ----------
const SnmpSettings = () => {
    const toast = useToast();
    const confirm = useConfirm();
    const [state, setState] = useState({ status: 'loading' });
    const [reloadKey, setReloadKey] = useState(0);
    const [editing, setEditing] = useState(null);
    const [testing, setTesting] = useState(null);
    const [results, setResults] = useState({});

    useEffect(() => {
        let active = true;
        const load = async () => {
            try {
                const [cfgRes, swRes] = await Promise.all([
                    axiosClient.get('/api/devices/snmp'),
                    axiosClient.get('/api/sdn/switches').catch(() => ({ data: { switches: [] } })),
                ]);
                if (!active) return;
                const configs = Object.fromEntries(cfgRes.data.map(c => [c.dpid, c]));
                const dpids = [...new Set([...swRes.data.switches, ...Object.keys(configs).map(Number)])].sort((a, b) => a - b);
                setState({ status: 'ok', dpids, configs, connected: new Set(swRes.data.switches) });
            } catch (err) {
                if (active) setState({ status: 'error', error: errorMessage(err) });
            }
        };
        load();
        return () => { active = false; };
    }, [reloadKey]);
    const reload = () => setReloadKey(k => k + 1);

    const handleTest = async (dpid) => {
        setTesting(dpid);
        try {
            const res = await axiosClient.post(`/api/devices/snmp/${dpid}/test`);
            setResults(r => ({ ...r, [dpid]: res.data }));
            if (res.data.status === 'ok') toast.success(`Switch ${dpid} phản hồi SNMP`, describeResult(res.data));
            else toast.error(`Switch ${dpid} không phản hồi SNMP`, describeResult(res.data));
        } catch (err) {
            toast.error('Không thể kiểm tra', errorMessage(err));
        } finally {
            setTesting(null);
        }
    };

    const handleDelete = async (dpid) => {
        const ok = await confirm({
            title: `Xoá cấu hình SNMP của Switch ${dpid}?`,
            message: 'Dashboard sẽ không còn đọc CPU/RAM/nhiệt độ của switch này.',
            confirmLabel: 'Xoá cấu hình',
        });
        if (!ok) return;
        try {
            const res = await axiosClient.delete(`/api/devices/snmp/${dpid}`);
            toast.success('Đã xoá', res.data.message);
            setResults(r => ({ ...r, [dpid]: undefined }));
            reload();
        } catch (err) {
            toast.error('Không thể xoá', errorMessage(err));
        }
    };

    return (
        <>
            <Alert tone="info">
                CPU, RAM, bộ nhớ và nhiệt độ được đọc trực tiếp từ switch qua <b>SNMP</b> (HOST-RESOURCES-MIB, ENTITY-SENSOR-MIB,
                MIB Cisco làm dự phòng). OpenFlow không cung cấp các số liệu này; switch Mininet là phần mềm nên không có.
                Community và khoá SNMPv3 được lưu trên máy chủ và không bao giờ hiển thị lại.
            </Alert>
            <Card title="Thiết bị (SNMP)" actions={<Button size="sm" icon={<IconRefresh size={14} />} onClick={reload}>Làm mới</Button>} flush>
                {state.status === 'loading' && <div style={{ padding: 20, display: 'grid', gap: 12 }}>{[0, 1, 2].map(i => <Skeleton key={i} height={20} />)}</div>}
                {state.status === 'error' && <ErrorState message={state.error} onRetry={reload} />}
                {state.status === 'ok' && state.dpids.length === 0 && (
                    <EmptyState icon={<IconNetwork size={20} />} title="Chưa có switch nào" description="Switch xuất hiện ở đây khi đã kết nối tới controller." />
                )}
                {state.status === 'ok' && state.dpids.length > 0 && (
                    <div className="table-wrap">
                        <table className="table responsive">
                            <thead>
                                <tr><th>Switch</th><th>Địa chỉ quản lý</th><th>SNMP</th><th>Kiểm tra gần nhất</th><th className="actions"><span className="sr-only">Thao tác</span></th></tr>
                            </thead>
                            <tbody>
                                {state.dpids.map(dpid => {
                                    const cfg = state.configs[dpid];
                                    const result = results[dpid];
                                    return (
                                        <tr key={dpid}>
                                            <td data-label="Switch">
                                                <span className="mono">s{dpid}</span>{' '}
                                                {!state.connected.has(dpid) && <Badge tone="warning">không kết nối controller</Badge>}
                                            </td>
                                            <td data-label="Địa chỉ">{cfg ? <span className="mono">{cfg.host}:{cfg.port}</span> : <span className="hint">Chưa cấu hình</span>}</td>
                                            <td data-label="SNMP">{cfg ? <Badge tone="info">{cfg.version === '3' ? `v3 · ${cfg.v3_user}` : 'v2c'}</Badge> : '—'}</td>
                                            <td data-label="Kiểm tra">
                                                {result ? (
                                                    <span>
                                                        <Badge tone={result.status === 'ok' ? 'success' : 'danger'}>{result.status === 'ok' ? 'Phản hồi' : 'Lỗi'}</Badge>{' '}
                                                        <span className="hint">{describeResult(result)}</span>
                                                    </span>
                                                ) : cfg ? <span className="hint">Cập nhật {formatDateTime(cfg.updated_at)}</span> : '—'}
                                            </td>
                                            <td className="actions">
                                                <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                                                    <Button size="sm" onClick={() => setEditing(dpid)}>{cfg ? 'Sửa' : 'Cấu hình'}</Button>
                                                    {cfg && <Button size="sm" loading={testing === dpid} onClick={() => handleTest(dpid)}>Kiểm tra kết nối</Button>}
                                                    {cfg && <Button size="sm" variant="danger" onClick={() => handleDelete(dpid)}>Xoá</Button>}
                                                </span>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </Card>
            {editing !== null && (
                <SnmpDialog dpid={editing} existing={state.configs?.[editing]}
                    onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); }} />
            )}
        </>
    );
};

export default SnmpSettings;
