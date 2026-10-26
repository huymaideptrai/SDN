import { useEffect, useMemo, useState } from 'react';
import axiosClient from '../api/axiosClient';
import { errorMessage } from '../api/auth';
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from '../components/ui';
import { IconNetwork, IconGauge, IconRefresh } from '../components/icons';
import TopologyMap from '../components/TopologyMap';
import BandwidthChart from '../components/BandwidthChart';
import { DevicesCard, LoadBalancingCard, QosBadges, SwitchHealthCard } from '../components/NetworkPanels';

const TOPOLOGY_POLL_MS = 5000;
const QOS_POLL_MS = 3000;
const ROUTING_POLL_MS = 3000;
const HEALTH_POLL_MS = 15000;  // backend cache 15s, không hỏi switch dồn dập
const DEVICES_POLL_MS = 10000;
// Biểu đồ hiển thị cố định 60 giây gần nhất (giữ dư 1 mẫu để đường không bị hụt ở mép trái)
const HISTORY_MS = 60_000 + QOS_POLL_MS;

const formatMbps = (v) => (v >= 1000 ? `${(v / 1000).toLocaleString('vi-VN', { maximumFractionDigits: 2 })} Gbps`
    : `${v.toLocaleString('vi-VN', { maximumFractionDigits: 2 })} Mbps`);

const Kpi = ({ label, value, hint, loading }) => (
    <div className="card kpi">
        <span className="kpi-label">{label}</span>
        {loading ? <Skeleton width={56} height={30} /> : <span className="kpi-value">{value}</span>}
        <span className="kpi-hint">{hint}</span>
    </div>
);

// Poll một API định kỳ; bỏ qua phản hồi của lần chạy đã bị thay thế (active=false)
const usePolling = (url, intervalMs, map = (d) => d) => {
    const [state, setState] = useState({ status: 'loading' });
    useEffect(() => {
        let active = true;
        const load = async () => {
            try {
                const res = await axiosClient.get(url);
                if (active) setState({ status: 'ok', data: map(res.data), at: Date.now() });
            } catch (err) {
                if (active) setState({ status: 'error', error: errorMessage(err) });
            }
        };
        load();
        const id = setInterval(load, intervalMs);
        return () => { active = false; clearInterval(id); };
        // map là hàm thuần, không cần đưa vào deps
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [url, intervalMs]);
    return state;
};

const Dashboard = () => {
    const [topo, setTopo] = useState({ status: 'loading' });
    const [policyCount, setPolicyCount] = useState(null);
    const [reloadKey, setReloadKey] = useState(0);
    const [showInterfaces, setShowInterfaces] = useState(true);
    const [layoutVersion, setLayoutVersion] = useState(0);

    const [selectedDpid, setSelectedDpid] = useState(null);
    const [selectedPort, setSelectedPort] = useState(null);
    const [qos, setQos] = useState({ dpid: null });
    const [history, setHistory] = useState({});

    const routing = usePolling('/api/sdn/routing', ROUTING_POLL_MS);
    const health = usePolling('/api/devices/health', HEALTH_POLL_MS);
    const devices = usePolling('/api/sdn/devices', DEVICES_POLL_MS, (d) => d.devices);

    // Mỗi effect bỏ qua phản hồi của lần chạy đã bị thay thế (active=false), tránh dữ liệu cũ đè dữ liệu mới
    useEffect(() => {
        let active = true;
        const load = async () => {
            try {
                const [topoRes, policyRes] = await Promise.all([
                    axiosClient.get('/api/sdn/topology'),
                    axiosClient.get('/api/sdn/policies'),
                ]);
                if (!active) return;
                setTopo({ status: 'ok', nodes: topoRes.data.nodes, links: topoRes.data.links, updatedAt: new Date() });
                setPolicyCount(policyRes.data.length);
            } catch (err) {
                if (active) setTopo({ status: 'error', error: errorMessage(err, 'Không tải được topology') });
            }
        };
        load();
        const id = setInterval(load, TOPOLOGY_POLL_MS);
        return () => { active = false; clearInterval(id); };
    }, [reloadKey]);

    const switches = useMemo(() => (topo.nodes || []).filter(n => n.type === 'switch').sort((a, b) => a.dpid - b.dpid), [topo.nodes]);
    const hosts = (topo.nodes || []).filter(n => n.type === 'host');
    const switchLinks = (topo.links || []).filter(l => l.port === undefined);
    const dpid = selectedDpid ?? switches[0]?.dpid ?? null;

    // Tải link trunk từ controller: lấy chiều nặng hơn của mỗi cặp switch
    const linkLoads = useMemo(() => {
        const out = {};
        for (const l of routing.data?.links || []) {
            const key = [`s${l.src}`, `s${l.dst}`].sort().join('|');
            const detail = `s${l.src}→s${l.dst} ${l.tx_mbps} Mbps`;
            if (!out[key] || l.utilization > out[key].util) out[key] = { util: l.utilization, mbps: l.tx_mbps, detail };
            else out[key].detail += `, ${detail}`;
        }
        return out;
    }, [routing.data]);

    // 2. Băng thông các port của switch đang chọn
    useEffect(() => {
        if (dpid === null) return undefined;
        let active = true;
        const load = async () => {
            try {
                const res = await axiosClient.get(`/api/sdn/qos/${dpid}`);
                if (!active) return;
                const now = Date.now();
                const { stats } = res.data;
                setQos({ dpid, stats, error: null, at: now });
                setHistory(prev => {
                    const next = { ...prev };
                    for (const p of stats) {
                        if (!p.measured) continue; // mẫu đầu chưa có số đo thật -> không vẽ
                        const key = `${dpid}_${p.port}`;
                        const point = {
                            ts: now, tx: p.tx_mbps, rx: p.rx_mbps,
                            rxAfter: p.qos_in?.measured ? p.qos_in.rx_after_qos_mbps : null,
                            txOffered: p.qos_out?.measured ? p.qos_out.tx_offered_mbps : null,
                        };
                        next[key] = [...(prev[key] || []), point].filter(pt => pt.ts >= now - HISTORY_MS);
                    }
                    return next;
                });
            } catch (err) {
                if (active) setQos({ dpid, stats: null, error: errorMessage(err, 'Không tải được thống kê port') });
            }
        };
        load();
        const id = setInterval(load, QOS_POLL_MS);
        return () => { active = false; clearInterval(id); };
    }, [dpid]);

    const qosReady = qos.dpid === dpid;
    const ports = qosReady && qos.stats ? qos.stats : [];
    const portNos = ports.map(p => p.port);
    const port = selectedPort !== null && portNos.includes(selectedPort) ? selectedPort : portNos[0] ?? null;
    const portInfo = ports.find(p => p.port === port);
    const chartData = port !== null ? history[`${dpid}_${port}`] || [] : [];

    const kpiLoading = topo.status === 'loading';
    const kpiValue = (v) => (topo.status === 'ok' ? v : '—');
    const busiest = routing.data?.links?.reduce((m, l) => (l.utilization > (m?.utilization ?? -1) ? l : m), null);

    return (
        <>
            <div className="page-head">
                <div>
                    <h1 className="page-title">Tổng quan mạng</h1>
                    <p className="page-desc">
                        {topo.status === 'ok'
                            ? `Dữ liệu từ controller · cập nhật lúc ${topo.updatedAt.toLocaleTimeString('vi-VN')}`
                            : 'Trạng thái topology và lưu lượng theo thời gian thực'}
                    </p>
                </div>
            </div>

            <div className="grid grid-kpi">
                <Kpi label="Switch" value={kpiValue(switches.length)} hint="Đang kết nối controller" loading={kpiLoading} />
                <Kpi label="Host" value={kpiValue(hosts.length)} hint="Phát hiện qua lưu lượng" loading={kpiLoading} />
                <Kpi label="Liên kết switch" value={kpiValue(switchLinks.length)} hint="Phát hiện qua LLDP" loading={kpiLoading} />
                <Kpi label="Link tải cao nhất" loading={routing.status === 'loading'}
                    value={busiest ? `${Math.round(busiest.utilization * 100)}%` : '—'}
                    hint={busiest ? `s${busiest.src} → s${busiest.dst} · ${busiest.tx_mbps} Mbps` : `Luật firewall đang bật: ${policyCount ?? '—'}`} />
            </div>

            <Card
                title="Topology"
                subtitle="Kéo thả để sắp xếp · màu link theo mức tải (xanh < 50%, vàng < 80%, đỏ ≥ 80%)"
                actions={(
                    <div className="toolbar">
                        <div className="legend">
                            <span><i style={{ background: '#2dd4bf', borderRadius: 2 }} />Switch</span>
                            <span><i style={{ background: '#60a5fa' }} />Host</span>
                        </div>
                        <label className="switch-toggle">
                            <input type="checkbox" checked={showInterfaces} onChange={(e) => setShowInterfaces(e.target.checked)} />
                            Interface
                        </label>
                        <Button size="sm" variant="ghost" icon={<IconRefresh size={14} />} onClick={() => setLayoutVersion(v => v + 1)}>
                            Đặt lại bố cục
                        </Button>
                    </div>
                )}
                flush
            >
                {topo.status === 'loading' && <div className="topo-box" style={{ padding: 20 }}><Skeleton height={360} /></div>}
                {topo.status === 'error' && <ErrorState message={topo.error} onRetry={() => setReloadKey(k => k + 1)} />}
                {topo.status === 'ok' && switches.length === 0 && (
                    <EmptyState icon={<IconNetwork size={20} />} title="Chưa có switch nào kết nối"
                        description="Khởi động Ryu trước, sau đó khởi động Mininet để các switch kết nối tới controller." />
                )}
                {topo.status === 'ok' && switches.length > 0 && (
                    <div className="topo-box">
                        <TopologyMap nodes={topo.nodes} links={topo.links} linkLoads={linkLoads}
                            showInterfaces={showInterfaces} layoutVersion={layoutVersion} />
                        {hosts.length === 0 && (
                            <p className="hint" style={{ padding: '0 20px 16px' }}>
                                Chưa phát hiện host nào. Host xuất hiện sau khi phát sinh lưu lượng (VD: <code>pingall</code> trong Mininet).
                            </p>
                        )}
                    </div>
                )}
            </Card>

            <div className="grid grid-2">
                <Card
                    title="Lưu lượng theo port · 60 giây"
                    subtitle={port !== null ? `Switch ${dpid} · ${portInfo?.name || `Port ${port}`}` : 'Chọn switch và port'}
                    actions={(
                        <div className="toolbar">
                            <label className="inline-select">
                                <span className="label">Switch</span>
                                <select className="select" value={dpid ?? ''} disabled={!switches.length}
                                    onChange={(e) => { setSelectedDpid(Number(e.target.value)); setSelectedPort(null); }}>
                                    {switches.map(s => <option key={s.dpid} value={s.dpid}>Switch {s.dpid}</option>)}
                                </select>
                            </label>
                            <label className="inline-select">
                                <span className="label">Port</span>
                                <select className="select" value={port ?? ''} disabled={!ports.length}
                                    onChange={(e) => setSelectedPort(Number(e.target.value))}>
                                    {ports.map(p => <option key={p.port} value={p.port}>{p.name || `Port ${p.port}`}</option>)}
                                </select>
                            </label>
                        </div>
                    )}
                >
                    {dpid === null && topo.status !== 'loading' && (
                        <EmptyState icon={<IconGauge size={20} />} title="Không có switch để theo dõi" />
                    )}
                    {dpid !== null && !qosReady && <Skeleton height={300} />}
                    {qosReady && qos.error && <ErrorState message={qos.error} />}
                    {qosReady && !qos.error && chartData.length === 0 && (
                        <EmptyState icon={<IconGauge size={20} />} title="Đang thu thập số liệu"
                            description="Tốc độ được tính từ chênh lệch giữa hai lần đo; điểm đầu tiên sẽ xuất hiện sau vài giây." />
                    )}
                    {qosReady && !qos.error && chartData.length > 0 && (
                        <>
                            <BandwidthChart data={chartData} now={qos.at}
                                limitIn={portInfo?.qos_in?.limit_mbps} limitOut={portInfo?.qos_out?.limit_mbps} />
                            {(portInfo?.qos_in || portInfo?.qos_out) && (
                                <p className="hint" style={{ marginTop: 8 }}>
                                    {portInfo.qos_in && 'QoS vào: RX đếm mọi gói tới cổng (kể cả gói bị huỷ), đường “RX sau QoS” là phần được chuyển tiếp. '}
                                    {portInfo.qos_out && 'QoS ra: meter chạy trước khi gói rời cổng nên TX đã là sau QoS; đường mờ là lưu lượng muốn gửi.'}
                                </p>
                            )}
                        </>
                    )}
                </Card>

                <LoadBalancingCard routing={routing} />
            </div>

            {qosReady && ports.length > 0 && (
                <Card title={`Port của Switch ${dpid}`} subtitle="Tốc độ hiện tại (cập nhật mỗi 3 giây)" flush>
                    <div className="table-wrap">
                        <table className="table responsive">
                            <thead>
                                <tr>
                                    <th>Port</th><th>Interface</th><th className="num">TX</th><th className="num">RX (đến port)</th>
                                    <th className="num">RX sau QoS</th><th className="num">QoS</th><th>Trạng thái</th>
                                </tr>
                            </thead>
                            <tbody>
                                {ports.map(p => (
                                    <tr key={p.port}>
                                        <td data-label="Port"><span className="mono">{p.port}</span></td>
                                        <td data-label="Interface"><span className="mono">{p.name || '—'}</span></td>
                                        <td data-label="TX" className="num">
                                            {p.measured ? formatMbps(p.tx_mbps) : '—'}
                                            {p.qos_out?.measured && <div className="hint">muốn gửi {formatMbps(p.qos_out.tx_offered_mbps)}</div>}
                                        </td>
                                        <td data-label="RX (đến port)" className="num">{p.measured ? formatMbps(p.rx_mbps) : '—'}</td>
                                        <td data-label="RX sau QoS" className="num">
                                            {p.qos_in?.measured ? formatMbps(p.qos_in.rx_after_qos_mbps) : '—'}
                                        </td>
                                        <td data-label="QoS" className="num"><QosBadges port={p} /></td>
                                        <td data-label="Trạng thái">
                                            {!p.measured ? <Badge>Đang đo</Badge>
                                                : p.tx_mbps + p.rx_mbps > 0 ? <Badge tone="success">Có lưu lượng</Badge>
                                                    : <Badge>Không có lưu lượng</Badge>}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </Card>
            )}

            <div className="grid grid-2">
                <SwitchHealthCard health={health} />
                <DevicesCard devices={devices} />
            </div>
        </>
    );
};

export default Dashboard;
