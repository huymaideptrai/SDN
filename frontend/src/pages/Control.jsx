import { useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import { isAdmin, errorMessage } from '../api/auth';
import { useConfirm, useToast } from '../context/feedback';
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Field, Skeleton } from '../components/ui';
import { IconGauge, IconLock, IconNetwork, IconRefresh, IconShield, IconTrash } from '../components/icons';

const KINDS = {
    policy: { label: 'Firewall', tone: 'accent' },
    qos: { label: 'QoS', tone: 'info' },
    route: { label: 'Định tuyến', tone: null },
    system: { label: 'Hệ thống', tone: null },
};
const FILTERS = ['all', 'policy', 'qos', 'route', 'system'];
const TABLE_NAMES = { 0: 'QoS vào', 1: 'Firewall', 2: 'Định tuyến', 3: 'Egress' };
const DIRECTIONS = { ingress: 'Chiều vào', egress: 'Chiều ra', both: 'Cả hai chiều' };

// Tên trường match của Ryu (kiểu cũ) -> nhãn dễ đọc
const MATCH_LABELS = {
    dl_type: 'eth', nw_src: 'src', nw_dst: 'dst', in_port: 'in_port', dl_src: 'mac_src', dl_dst: 'mac_dst',
    nw_proto: 'proto', tp_src: 'sport', tp_dst: 'dport', metadata: 'out_port',
};
const ETH_TYPES = { 2048: 'IPv4', 2054: 'ARP', 35020: 'LLDP' };
const IP_PROTOS = { 1: 'ICMP', 6: 'TCP', 17: 'UDP' };
const fmtValue = (k, v) => {
    if (k === 'dl_type') return ETH_TYPES[v] || v;
    if (k === 'nw_proto') return IP_PROTOS[v] || v;
    if (k === 'metadata') return String(v).split('/')[0];
    return v;
};
const metadataPort = (match) => Number(String(match.metadata).split('/')[0]);

const MatchView = ({ match }) => {
    const entries = Object.entries(match);
    if (!entries.length) return <span className="code-cell">*</span>;
    return (
        <span className="code-cell">
            {entries.map(([k, v]) => (
                <span key={k} className="kv">{MATCH_LABELS[k] || k}=<b>{fmtValue(k, v)}</b></span>
            ))}
        </span>
    );
};

const ActionView = ({ flow }) => {
    if (!flow.actions.length) return <Badge tone="danger">DROP</Badge>;
    if (flow.kind === 'policy') return <Badge tone="success">ALLOW</Badge>;
    return <span className="code-cell">{flow.actions.join(', ')}</span>;
};

const describeMatch = (match) => Object.entries(match).map(([k, v]) => `${MATCH_LABELS[k] || k}=${fmtValue(k, v)}`).join(', ') || '*';

const Control = () => {
    const admin = isAdmin();
    const toast = useToast();
    const confirm = useConfirm();

    const [switches, setSwitches] = useState({ status: 'loading', list: [] });
    const [selectedDpid, setSelectedDpid] = useState(null);
    const [reloadKey, setReloadKey] = useState(0);
    const [data, setData] = useState({ key: null });
    const [filter, setFilter] = useState('all');

    const [fw, setFw] = useState({ src: '', dst: '', action: 'DROP', priority: 100, scope: 'all' });
    // IP host -> switch mà host đó nối vào (để cảnh báo luật đặt sai switch)
    const [hostSwitch, setHostSwitch] = useState({});
    const [qosForm, setQosForm] = useState({ port: '', rate: '', direction: 'ingress' });
    const [pending, setPending] = useState(null); // 'fw' | 'qos' | id của dòng đang xoá

    const dpid = selectedDpid ?? switches.list[0] ?? null;
    const dataKey = `${dpid}:${reloadKey}`;

    // Mỗi effect bỏ qua phản hồi của lần chạy đã bị thay thế (active=false), tránh dữ liệu cũ đè dữ liệu mới
    useEffect(() => {
        let active = true;
        const load = async () => {
            try {
                const res = await axiosClient.get('/api/sdn/switches');
                if (!active) return;
                setSwitches({ status: 'ok', list: res.data.switches });
                // Topology chỉ dùng cho cảnh báo -> lỗi ở đây không chặn trang
                const topo = await axiosClient.get('/api/sdn/topology').catch(() => null);
                if (topo && active) {
                    const macToIp = Object.fromEntries(topo.data.nodes.filter(n => n.type === 'host').map(n => [n.id, n.name]));
                    setHostSwitch(Object.fromEntries(topo.data.links.filter(l => l.port !== undefined)
                        .map(l => [macToIp[l.source], Number(l.target.slice(1))])));
                }
            } catch (err) {
                if (active) setSwitches({ status: 'error', list: [], error: errorMessage(err, 'Không tải được danh sách switch') });
            }
        };
        load();
        return () => { active = false; };
    }, [reloadKey]);

    useEffect(() => {
        if (dpid === null) return undefined;
        let active = true;
        const key = `${dpid}:${reloadKey}`;
        const load = async () => {
            try {
                const [flowsRes, qosRes, portsRes] = await Promise.all([
                    axiosClient.get(`/api/sdn/flows/${dpid}`),
                    axiosClient.get(`/api/sdn/qos/config/${dpid}`),
                    axiosClient.get(`/api/sdn/qos/${dpid}`),
                ]);
                if (!active) return;
                setData({ key, dpid, flows: flowsRes.data.flows, profiles: qosRes.data,
                    ports: portsRes.data.stats.map(p => ({ port: p.port, name: p.name })), error: null, at: new Date() });
            } catch (err) {
                if (active) setData({ key, dpid, error: errorMessage(err, 'Không tải được bảng luật') });
            }
        };
        load();
        return () => { active = false; };
    }, [dpid, reloadKey]);

    const reload = () => setReloadKey(k => k + 1);
    const loaded = data.dpid === dpid && data.key !== null;
    const refreshing = loaded && data.key !== dataKey;
    const flows = loaded && !data.error ? data.flows : [];
    const visibleFlows = filter === 'all' ? flows : flows.filter(f => f.kind === filter);
    const qosPort = qosForm.port || (loaded && data.ports?.[0]?.port) || '';

    // Cảnh báo khi cả 2 host nối vào cùng một switch KHÁC switch đang chọn: lưu lượng giữa chúng không đi qua switch này
    const srcSw = hostSwitch[fw.src.trim()];
    const dstSw = hostSwitch[fw.dst.trim()];
    const misplaced = fw.scope === 'current' && srcSw !== undefined && srcSw === dstSw && srcSw !== dpid ? srcSw : null;
    const targets = fw.scope === 'all' ? switches.list : [dpid];
    const targetLabel = fw.scope === 'all' ? `tất cả ${switches.list.length} switch` : `Switch ${dpid}`;

    const handleAddFlow = async (e) => {
        e.preventDefault();
        const base = { src_ip: fw.src || null, dst_ip: fw.dst || null, action: fw.action, priority: Number(fw.priority) };
        if (fw.action === 'DROP') {
            const ok = await confirm({
                title: 'Chặn lưu lượng?',
                message: `Luật DROP sẽ huỷ mọi gói IPv4 khớp điều kiện trên ${targetLabel} ngay lập tức.`,
                detail: `src=${base.src_ip || '*'}  dst=${base.dst_ip || '*'}  priority=${base.priority}`,
                confirmLabel: 'Áp dụng luật chặn',
            });
            if (!ok) return;
        }
        setPending('fw');
        const results = await Promise.allSettled(targets.map(d => axiosClient.post('/api/sdn/flows', { ...base, dpid: d })));
        const ok = targets.filter((_, i) => results[i].status === 'fulfilled');
        const failed = targets.map((d, i) => [d, results[i]]).filter(([, r]) => r.status === 'rejected');
        const rule = `${fw.action} ${base.src_ip || '*'} → ${base.dst_ip || '*'}`;
        if (ok.length) {
            toast.success('Đã áp dụng luật', `${rule} trên ${ok.map(d => `Switch ${d}`).join(', ')}`);
            setFw(f => ({ ...f, src: '', dst: '' }));
        }
        for (const [d, r] of failed) toast.error(`Không thể thêm luật trên Switch ${d}`, errorMessage(r.reason));
        setPending(null);
        reload();
    };

    const handleDeleteFlow = async (flow) => {
        const ok = await confirm({
            title: 'Xoá luật firewall?',
            message: 'Luật sẽ bị gỡ khỏi switch và không được đồng bộ lại.',
            detail: `table=${flow.table_id}  priority=${flow.priority}  ${describeMatch(flow.match)}`,
            confirmLabel: 'Xoá',
        });
        if (!ok) return;
        setPending(`flow-${flow.cookie}-${flow.priority}-${describeMatch(flow.match)}`);
        try {
            if (flow.kind === 'policy') {
                await axiosClient.delete(`/api/sdn/policies/${flow.policy_id}`);
            } else {
                await axiosClient.delete(`/api/sdn/flows/${dpid}`, {
                    data: { table_id: flow.table_id, priority: flow.priority, match: flow.match },
                });
            }
            toast.success('Đã xoá', describeMatch(flow.match));
            reload();
        } catch (err) {
            toast.error('Không thể xoá', errorMessage(err));
        } finally {
            setPending(null);
        }
    };

    const handleSetQos = async (e) => {
        e.preventDefault();
        setPending('qos');
        try {
            const res = await axiosClient.post('/api/sdn/qos/config', {
                dpid, port: Number(qosPort), max_rate_mbps: Number(qosForm.rate), direction: qosForm.direction,
            });
            toast.success('Đã cấu hình QoS', res.data.message);
            setQosForm(f => ({ ...f, port: '', rate: '' }));
            reload();
        } catch (err) {
            toast.error('Không thể cấu hình QoS', errorMessage(err));
        } finally {
            setPending(null);
        }
    };

    const handleRemoveQos = async (portNo, direction) => {
        const ok = await confirm({
            title: 'Bỏ giới hạn băng thông?',
            message: `Port ${portNo} của Switch ${dpid} sẽ không còn bị giới hạn tốc độ (${DIRECTIONS[direction].toLowerCase()}).`,
            confirmLabel: 'Bỏ giới hạn',
        });
        if (!ok) return;
        setPending(`qos-${portNo}-${direction}`);
        try {
            const res = await axiosClient.delete(`/api/sdn/qos/config/${dpid}/${portNo}`, { params: { direction } });
            toast.success('Đã bỏ QoS', res.data.message);
            reload();
        } catch (err) {
            toast.error('Không thể bỏ QoS', errorMessage(err));
        } finally {
            setPending(null);
        }
    };

    if (switches.status === 'loading') {
        return <Card><Skeleton height={28} width="40%" /><Skeleton height={200} style={{ marginTop: 16 }} /></Card>;
    }
    if (switches.status === 'error') {
        return <Card><ErrorState message={switches.error} onRetry={reload} /></Card>;
    }
    if (dpid === null) {
        return (
            <Card>
                <EmptyState icon={<IconNetwork size={20} />} title="Chưa có switch nào kết nối"
                    description="Khởi động Ryu rồi Mininet, sau đó tải lại trang." />
            </Card>
        );
    }

    const countOf = (kind) => (kind === 'all' ? flows.length : flows.filter(f => f.kind === kind).length);

    return (
        <>
            <div className="page-head">
                <div>
                    <h1 className="page-title">Điều khiển mạng</h1>
                    <p className="page-desc">Quản lý luật firewall và giới hạn băng thông trên từng switch</p>
                </div>
                <label className="inline-select">
                    <span className="label">Switch</span>
                    <select className="select" value={dpid} onChange={(e) => { setSelectedDpid(Number(e.target.value)); setQosForm({ port: '', rate: '' }); }}>
                        {switches.list.map(d => <option key={d} value={d}>Switch {d}</option>)}
                    </select>
                </label>
            </div>

            {!admin && (
                <Alert tone="info" icon={<IconLock size={16} />}>
                    Bạn đang ở chế độ <b>chỉ xem</b>. Liên hệ quản trị viên để thay đổi cấu hình mạng.
                </Alert>
            )}

            <div className="grid grid-2">
                {admin && (
                    <Card title="Luật firewall" subtitle="Lọc lưu lượng IPv4 theo IP nguồn / đích">
                        <form className="form" onSubmit={handleAddFlow}>
                            <div className="form-row">
                                <Field label="IP nguồn" htmlFor="fw-src" hint="IP hoặc subnet, VD 10.0.0.0/24">
                                    <input id="fw-src" className="input" placeholder="10.0.0.1" value={fw.src}
                                        onChange={(e) => setFw({ ...fw, src: e.target.value })} />
                                </Field>
                                <Field label="IP đích" htmlFor="fw-dst" hint="Để trống = mọi địa chỉ">
                                    <input id="fw-dst" className="input" placeholder="10.0.0.2" value={fw.dst}
                                        onChange={(e) => setFw({ ...fw, dst: e.target.value })} />
                                </Field>
                            </div>
                            <div className="form-row">
                                <Field label="Hành động">
                                    <div className="segmented" role="group" aria-label="Hành động">
                                        <button type="button" className="allow" aria-pressed={fw.action === 'ALLOW'} onClick={() => setFw({ ...fw, action: 'ALLOW' })}>ALLOW</button>
                                        <button type="button" className="drop" aria-pressed={fw.action === 'DROP'} onClick={() => setFw({ ...fw, action: 'DROP' })}>DROP</button>
                                    </div>
                                </Field>
                                <Field label="Độ ưu tiên" htmlFor="fw-prio" hint="2 – 65534, số lớn được xét trước">
                                    <input id="fw-prio" type="number" className="input" min={2} max={65534} required value={fw.priority}
                                        onChange={(e) => setFw({ ...fw, priority: e.target.value })} />
                                </Field>
                            </div>
                            <Field label="Áp dụng cho" hint="Luật chỉ có tác dụng trên switch mà lưu lượng thực sự đi qua">
                                <div className="segmented" role="group" aria-label="Phạm vi áp dụng">
                                    <button type="button" aria-pressed={fw.scope === 'all'} className="scope" onClick={() => setFw({ ...fw, scope: 'all' })}>
                                        Tất cả switch ({switches.list.length})
                                    </button>
                                    <button type="button" aria-pressed={fw.scope === 'current'} className="scope" onClick={() => setFw({ ...fw, scope: 'current' })}>
                                        Chỉ Switch {dpid}
                                    </button>
                                </div>
                            </Field>
                            {misplaced !== null && (
                                <Alert tone="warning">
                                    {fw.src} và {fw.dst} cùng nối vào <b>Switch {misplaced}</b>, lưu lượng giữa chúng không đi qua Switch {dpid} nên luật sẽ không có tác dụng.
                                    Chọn “Tất cả switch” hoặc đổi sang Switch {misplaced}.
                                </Alert>
                            )}
                            <Button type="submit" variant="primary" loading={pending === 'fw'} icon={<IconShield size={14} />}
                                disabled={!fw.src && !fw.dst}>
                                Áp dụng luật
                            </Button>
                        </form>
                    </Card>
                )}

                <Card title="Giới hạn băng thông (QoS)" subtitle="Giới hạn lưu lượng vào và/hoặc ra của một port (OpenFlow meter)">
                    {admin && (
                        <form className="form" onSubmit={handleSetQos}>
                            <div className="form-row">
                                <Field label="Port" htmlFor="qos-port">
                                    <select id="qos-port" className="select" value={qosPort} required disabled={!loaded || !data.ports?.length}
                                        onChange={(e) => setQosForm({ ...qosForm, port: e.target.value })}>
                                        {(data.ports || []).map(p => <option key={p.port} value={p.port}>{p.name || `Port ${p.port}`}</option>)}
                                    </select>
                                </Field>
                                <Field label="Tốc độ tối đa (Mbps)" htmlFor="qos-rate">
                                    <input id="qos-rate" type="number" className="input" min={0.1} step="any" required placeholder="VD 10"
                                        value={qosForm.rate} onChange={(e) => setQosForm({ ...qosForm, rate: e.target.value })} />
                                </Field>
                            </div>
                            <Field label="Chiều áp dụng" hint="Vào: lưu lượng từ thiết bị đi vào switch qua port · Ra: lưu lượng switch gửi ra port">
                                <div className="segmented three" role="group" aria-label="Chiều áp dụng">
                                    {Object.entries(DIRECTIONS).map(([k, label]) => (
                                        <button key={k} type="button" className="scope" aria-pressed={qosForm.direction === k}
                                            onClick={() => setQosForm({ ...qosForm, direction: k })}>{label}</button>
                                    ))}
                                </div>
                            </Field>
                            <Button type="submit" variant="primary" loading={pending === 'qos'} icon={<IconGauge size={14} />}>
                                Áp dụng giới hạn
                            </Button>
                        </form>
                    )}
                    <div style={{ marginTop: admin ? 20 : 0 }}>
                        <p className="label" style={{ marginBottom: 8 }}>Đang áp dụng</p>
                        {!loaded && <Skeleton height={36} />}
                        {loaded && data.error && <p className="hint">Không tải được danh sách QoS.</p>}
                        {loaded && !data.error && data.profiles.length === 0 && (
                            <p className="hint">Chưa có port nào bị giới hạn trên Switch {dpid}.</p>
                        )}
                        {loaded && !data.error && data.profiles.map(p => (
                            <div key={p.id} className="toolbar" style={{ justifyContent: 'space-between', padding: '8px 0', borderTop: '1px solid var(--border)' }}>
                                <span>
                                    <span className="mono">{data.ports?.find(x => x.port === p.port_no)?.name || `Port ${p.port_no}`}</span>{' '}
                                    <Badge>{DIRECTIONS[p.direction] || p.direction}</Badge>{' '}
                                    <Badge tone="info">{(p.max_bw / 1000).toLocaleString('vi-VN')} Mbps</Badge>
                                </span>
                                {admin && (
                                    <Button size="sm" variant="danger" loading={pending === `qos-${p.port_no}-${p.direction}`}
                                        onClick={() => handleRemoveQos(p.port_no, p.direction)}>
                                        Bỏ giới hạn
                                    </Button>
                                )}
                            </div>
                        ))}
                    </div>
                </Card>
            </div>

            <Card
                title={`Bảng luật · Switch ${dpid}`}
                subtitle={loaded && !data.error ? `Đọc trực tiếp từ switch lúc ${data.at.toLocaleTimeString('vi-VN')}` : 'Đọc trực tiếp từ switch'}
                actions={(
                    <Button size="sm" icon={<IconRefresh size={14} />} loading={refreshing} onClick={reload}>Làm mới</Button>
                )}
                flush
            >
                <div className="toolbar" style={{ padding: '12px 20px', borderBottom: '1px solid var(--border)' }}>
                    {FILTERS.map(k => (
                        <button key={k} type="button" className="chip" aria-pressed={filter === k} onClick={() => setFilter(k)}>
                            {k === 'all' ? 'Tất cả' : KINDS[k].label}<span className="count">{loaded ? countOf(k) : ''}</span>
                        </button>
                    ))}
                </div>

                {!loaded && (
                    <div style={{ padding: 20, display: 'grid', gap: 12 }}>
                        {[0, 1, 2, 3].map(i => <Skeleton key={i} height={20} />)}
                    </div>
                )}
                {loaded && data.error && <ErrorState message={data.error} onRetry={reload} />}
                {loaded && !data.error && visibleFlows.length === 0 && (
                    <EmptyState title="Không có luật nào"
                        description={filter === 'all' ? 'Switch chưa có flow nào ngoài luật mặc định.' : `Không có luật loại "${KINDS[filter].label}" trên switch này.`} />
                )}
                {loaded && !data.error && visibleFlows.length > 0 && (
                    <div className="table-wrap">
                        <table className="table responsive">
                            <thead>
                                <tr>
                                    <th>Loại</th><th className="num">Table</th><th className="num">Priority</th>
                                    <th>Điều kiện khớp</th><th>Hành động</th><th className="num">Packets</th>
                                    {admin && <th className="actions"><span className="sr-only">Thao tác</span></th>}
                                </tr>
                            </thead>
                            <tbody>
                                {visibleFlows.map(flow => {
                                    const rowId = `flow-${flow.cookie}-${flow.priority}-${describeMatch(flow.match)}`;
                                    return (
                                        <tr key={`${flow.table_id}-${rowId}`}>
                                            <td data-label="Loại"><Badge tone={KINDS[flow.kind]?.tone}>{KINDS[flow.kind]?.label || flow.kind}</Badge></td>
                                            <td data-label="Table" className="num" title={TABLE_NAMES[flow.table_id]}>{flow.table_id}</td>
                                            <td data-label="Priority" className="num">{flow.priority}</td>
                                            <td data-label="Khớp"><MatchView match={flow.match} /></td>
                                            <td data-label="Hành động"><ActionView flow={flow} /></td>
                                            <td data-label="Packets" className="num">{flow.packet_count.toLocaleString('vi-VN')}</td>
                                            {admin && (
                                                <td className="actions">
                                                    {flow.kind === 'policy' && (
                                                        <Button size="sm" variant="danger" icon={<IconTrash size={14} />}
                                                            loading={pending === rowId} onClick={() => handleDeleteFlow(flow)}
                                                            aria-label={`Xoá luật ${describeMatch(flow.match)}`}>
                                                            Xoá
                                                        </Button>
                                                    )}
                                                    {flow.kind === 'qos' && (() => {
                                                        const ingress = flow.table_id === 0;
                                                        const portNo = ingress ? flow.match.in_port : metadataPort(flow.match);
                                                        const dir = ingress ? 'ingress' : 'egress';
                                                        return (
                                                        <Button size="sm" variant="danger" loading={pending === `qos-${portNo}-${dir}`}
                                                            onClick={() => handleRemoveQos(portNo, dir)}>
                                                            Bỏ QoS
                                                        </Button>
                                                        );
                                                    })()}
                                                </td>
                                            )}
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </Card>
        </>
    );
};

export default Control;
