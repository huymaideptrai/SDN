import { Alert, Badge, Card, EmptyState, ErrorState, Skeleton } from './ui';
import { IconNetwork } from './icons';

const pathLabel = (path) => path.map(d => `s${d}`).join(' → ');
const fmtMbps = (v) => `${Number(v).toLocaleString('vi-VN', { maximumFractionDigits: 1 })} Mbps`;
const fmtBytes = (b) => {
    if (b === undefined || b === null) return '—';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    let v = b;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
    return `${v.toLocaleString('vi-VN', { maximumFractionDigits: 1 })} ${units[i]}`;
};
const fmtDuration = (s) => {
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    return [d && `${d} ngày`, h && `${h} giờ`, `${m} phút`].filter(Boolean).join(' ');
};
const utilTone = (u) => (u >= 0.8 ? 'danger' : u >= 0.5 ? 'warning' : 'success');

const Meter = ({ value, tone = 'accent', label }) => (
    <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value * 100)} aria-label={label}>
        <span className={`meter-fill meter-${tone}`} style={{ width: `${Math.min(value, 1) * 100}%` }} />
    </div>
);

const Loading = () => <div style={{ padding: 20, display: 'grid', gap: 12 }}>{[0, 1, 2].map(i => <Skeleton key={i} height={18} />)}</div>;

// ---------- Cân bằng tải ----------
export const LoadBalancingCard = ({ routing }) => {
    if (routing.status === 'loading') return <Card title="Định tuyến & cân bằng tải" flush><Loading /></Card>;
    if (routing.status === 'error') return <Card title="Định tuyến & cân bằng tải"><ErrorState message={routing.error} /></Card>;
    const { capacity_mbps: cap, rebalance_threshold: threshold, links, flows, events } = routing.data;
    const activeFlows = flows.filter(f => f.rate_mbps > 0.1);

    return (
        <Card title="Định tuyến & cân bằng tải"
            subtitle={`Dung lượng link trunk ${cap} Mbps · tự chuyển flow khi link vượt ${Math.round(threshold * 100)}%`} flush>
            <div className="table-wrap">
                <table className="table responsive">
                    <thead><tr><th>Link (chiều)</th><th className="num">Tải</th><th style={{ width: '40%' }}>Mức sử dụng</th></tr></thead>
                    <tbody>
                        {links.length === 0 && <tr><td colSpan={3} className="hint">Chưa phát hiện link giữa các switch.</td></tr>}
                        {links.map(l => (
                            <tr key={`${l.src}-${l.dst}`}>
                                <td data-label="Link"><span className="mono">s{l.src} → s{l.dst}</span></td>
                                <td data-label="Tải" className="num">{fmtMbps(l.tx_mbps)}</td>
                                <td data-label="Sử dụng">
                                    <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                        <Meter value={l.utilization} tone={utilTone(l.utilization)} label={`s${l.src} tới s${l.dst}`} />
                                        <span className="mono hint" style={{ minWidth: 40, textAlign: 'right' }}>{Math.round(l.utilization * 100)}%</span>
                                    </span>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            <div style={{ padding: '16px 20px 4px' }}><p className="label">Luồng đang định tuyến ({activeFlows.length})</p></div>
            {activeFlows.length === 0 ? (
                <p className="hint" style={{ padding: '0 20px 16px' }}>Không có luồng IPv4 nào đang truyền dữ liệu.</p>
            ) : (
                <div className="table-wrap">
                    <table className="table responsive">
                        <thead><tr><th>Luồng</th><th>Đường đi</th><th className="num">Tốc độ</th><th className="num">Đã chuyển đường</th></tr></thead>
                        <tbody>
                            {activeFlows.map(f => (
                                <tr key={f.id}>
                                    <td data-label="Luồng"><span className="code-cell">{f.label}</span></td>
                                    <td data-label="Đường đi">
                                        <Badge tone={f.path.length > 2 ? 'info' : undefined}>{pathLabel(f.path)}</Badge>
                                    </td>
                                    <td data-label="Tốc độ" className="num">{fmtMbps(f.rate_mbps)}</td>
                                    <td data-label="Chuyển" className="num">{f.moves ? <Badge tone="warning">{f.moves} lần</Badge> : '—'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            <div style={{ padding: '16px 20px 4px' }}><p className="label">Lần chuyển đường gần đây</p></div>
            {events.length === 0 ? (
                <p className="hint" style={{ padding: '0 20px 16px' }}>Chưa có lần chuyển nào kể từ khi controller khởi động.</p>
            ) : (
                <ul className="event-list">
                    {events.slice(0, 6).map((e, i) => (
                        <li key={`${e.time}-${i}`}>
                            <span className="hint mono">{new Date(e.time * 1000).toLocaleTimeString('vi-VN', { hour12: false })}</span>
                            <span className="code-cell">{e.flow}</span>
                            <span>{pathLabel(e.from)} <b>⇒</b> {pathLabel(e.to)}</span>
                            <span className="hint">link nóng nhất {fmtMbps(e.bottleneck_before)} → {fmtMbps(e.bottleneck_after)}</span>
                        </li>
                    ))}
                </ul>
            )}
        </Card>
    );
};

// ---------- Phần cứng switch (SNMP) ----------
const HEALTH_STATUS = {
    ok: { tone: 'success', label: 'SNMP trực tuyến' },
    unreachable: { tone: 'danger', label: 'Không phản hồi SNMP' },
    error: { tone: 'danger', label: 'Lỗi cấu hình SNMP' },
    not_configured: { tone: undefined, label: 'Chưa cấu hình SNMP' },
};
const Unsupported = () => <span className="hint">thiết bị không cung cấp</span>;

const HealthDetail = ({ d }) => {
    const memRatio = d.memory?.total ? d.memory.used / d.memory.total : 0;
    return (
        <div className="resource-grid">
            <div>
                <div className="resource-head"><span className="label">CPU</span>
                    {d.cpu ? <span className="mono">{d.cpu.percent}%{d.cpu.cores > 1 ? ` · ${d.cpu.cores} nhân` : ''}</span> : <Unsupported />}
                </div>
                {d.cpu && <Meter value={d.cpu.percent / 100} tone={utilTone(d.cpu.percent / 100)} label={`CPU s${d.dpid}`} />}
                {d.cpu && <span className="hint">{d.cpu.source}</span>}
            </div>
            <div>
                <div className="resource-head"><span className="label">RAM</span>
                    {d.memory ? <span className="mono">{fmtBytes(d.memory.used)} / {fmtBytes(d.memory.total)}</span> : <Unsupported />}
                </div>
                {d.memory && <Meter value={memRatio} tone={utilTone(memRatio)} label={`RAM s${d.dpid}`} />}
                {d.memory && <span className="hint">{d.memory.source}</span>}
            </div>
            <div>
                <div className="resource-head"><span className="label">Bộ nhớ lưu trữ</span>{!d.storage?.length && <Unsupported />}</div>
                {(d.storage || []).map(s => (
                    <span key={s.name} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <span className="hint mono">{s.name}: {fmtBytes(s.used)} / {fmtBytes(s.total)}</span>
                        <Meter value={s.total ? s.used / s.total : 0} tone={utilTone(s.total ? s.used / s.total : 0)} label={s.name} />
                    </span>
                ))}
            </div>
            <div>
                <div className="resource-head"><span className="label">Nhiệt độ</span>{!d.temperatures?.length && <Unsupported />}</div>
                {(d.temperatures || []).map(t => (
                    <span key={t.name} className="resource-head">
                        <span className="hint">{t.name}</span>
                        <Badge tone={t.celsius >= 70 ? 'danger' : t.celsius >= 55 ? 'warning' : 'success'}>{t.celsius.toFixed(1)}°C</Badge>
                    </span>
                ))}
                {d.temperatures?.length > 0 && <span className="hint">{d.temperatures[0].source}</span>}
            </div>
        </div>
    );
};

export const SwitchHealthCard = ({ health }) => {
    const title = 'Phần cứng switch';
    const subtitle = 'CPU · RAM · bộ nhớ · nhiệt độ đọc trực tiếp từ thiết bị qua SNMP';
    if (health.status === 'loading') return <Card title={title} subtitle={subtitle} flush><Loading /></Card>;
    if (health.status === 'error') return <Card title={title} subtitle={subtitle}><ErrorState message={health.error} /></Card>;
    const devices = health.data.devices;
    const anyConfigured = devices.some(d => d.status !== 'not_configured');
    return (
        <Card title={title} subtitle={subtitle} flush>
            {!anyConfigured && (
                <div style={{ padding: '16px 20px 0' }}>
                    <Alert tone="info">
                        Chưa switch nào được cấu hình SNMP. Switch Mininet là switch phần mềm nên không có CPU/RAM/nhiệt độ riêng.
                        Với switch thật, quản trị viên khai báo địa chỉ quản lý và SNMP tại <b>Cài đặt → Thiết bị (SNMP)</b>.
                    </Alert>
                </div>
            )}
            {devices.length === 0 ? <EmptyState icon={<IconNetwork size={20} />} title="Chưa có switch nào" /> : (
                <div className="health-list">
                    {devices.map(d => {
                        const st = HEALTH_STATUS[d.status] || HEALTH_STATUS.error;
                        return (
                            <div key={d.dpid} className="health-item">
                                <div className="health-head">
                                    <div>
                                        <span className="mono">s{d.dpid}</span>
                                        {d.sys_name && <span> · {d.sys_name}</span>}
                                        {d.host && <span className="hint mono"> · {d.host}</span>}
                                        {d.sys_descr && <div className="hint">{d.sys_descr}</div>}
                                    </div>
                                    <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
                                        <Badge tone={st.tone}>{st.label}</Badge>
                                        {d.status === 'ok' && d.uptime_s !== null && <Badge>chạy {fmtDuration(d.uptime_s)}</Badge>}
                                        {d.collected_at && <span className="hint">đọc lúc {new Date(d.collected_at * 1000).toLocaleTimeString('vi-VN', { hour12: false })}</span>}
                                    </span>
                                </div>
                                {d.status === 'ok' && <HealthDetail d={d} />}
                                {(d.status === 'unreachable' || d.status === 'error') && <span className="hint">{d.error}</span>}
                            </div>
                        );
                    })}
                </div>
            )}
        </Card>
    );
};

// ---------- Thiết bị ----------
const TABLE_NAMES = { 0: 'QoS vào', 1: 'Firewall', 2: 'Định tuyến', 3: 'Egress' };

export const DevicesCard = ({ devices }) => {
    if (devices.status === 'loading') return <Card title="Thiết bị" flush><Loading /></Card>;
    if (devices.status === 'error') return <Card title="Thiết bị"><ErrorState message={devices.error} /></Card>;
    if (!devices.data.length) return <Card title="Thiết bị"><EmptyState icon={<IconNetwork size={20} />} title="Chưa có switch nào kết nối" /></Card>;
    return (
        <Card title="Thiết bị (OpenFlow)" subtitle="Phần mềm, port, số flow theo bảng và meter đọc qua OpenFlow" flush>
            <div className="table-wrap">
                <table className="table responsive">
                    <thead><tr><th>Switch</th><th>Phần mềm</th><th>Port</th><th>Flow theo bảng</th><th className="num">Meter</th></tr></thead>
                    <tbody>
                        {devices.data.map(d => (
                            <tr key={d.dpid}>
                                <td data-label="Switch"><span className="mono">{d.name}</span> <span className="hint">dpid {d.dpid}</span></td>
                                <td data-label="Phần mềm">{d.hardware} {d.software}</td>
                                <td data-label="Port"><span className="code-cell">{d.ports.map(p => p.name).join(', ')}</span></td>
                                <td data-label="Flow">
                                    <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
                                        {Object.entries(d.flows_per_table).map(([t, n]) => <Badge key={t}>{TABLE_NAMES[t] || `T${t}`}: {n}</Badge>)}
                                    </span>
                                </td>
                                <td data-label="Meter" className="num">{d.meter_count}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </Card>
    );
};

export const QosBadges = ({ port }) => {
    const parts = [];
    if (port.qos_in) parts.push(['vào', port.qos_in]);
    if (port.qos_out) parts.push(['ra', port.qos_out]);
    if (!parts.length) return <span className="hint">—</span>;
    return (
        <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {parts.map(([dir, q]) => (
                <span key={dir} style={{ display: 'inline-flex', gap: 4 }}>
                    <Badge tone="info">{dir} ≤ {q.limit_mbps.toLocaleString('vi-VN')} Mbps</Badge>
                    {q.measured
                        ? (q.dropped_mbps > 0 ? <Badge tone="warning">huỷ {fmtMbps(q.dropped_mbps)}</Badge> : <Badge tone="success">không huỷ</Badge>)
                        : <Badge>đang đo</Badge>}
                </span>
            ))}
        </span>
    );
};

