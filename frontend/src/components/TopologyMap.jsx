import { useRef, useState } from 'react';

const W = 800;
const H = 440;
const STORAGE_KEY = 'sdn.topology.positions.v1';
const COLORS = {
    link: '#3a4b63', ok: '#2dd4bf', warn: '#fbbf24', hot: '#f87171',
    switchFill: '#132029', switchStroke: '#2dd4bf', hostFill: '#111b2a', hostStroke: '#60a5fa',
    label: '#c9d4e2', muted: '#8b9bb0', tagBg: '#0a0e14',
};

const loadSaved = () => {
    try {
        return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
    } catch {
        return {};
    }
};
const save = (positions) => {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(positions));
    } catch {
        // localStorage có thể bị chặn (chế độ riêng tư) -> chỉ mất tính năng nhớ vị trí
    }
};

// Bố cục mặc định theo tầng: switch không nối host (lõi / dự phòng) ở trên, switch truy cập ở giữa,
// host ở dưới ngay bên dưới switch của nó. Vị trí cố định, không phụ thuộc mô phỏng lực.
const defaultLayout = (nodes, links) => {
    const switches = nodes.filter(n => n.type === 'switch').sort((a, b) => a.dpid - b.dpid);
    const hostOf = {};
    for (const l of links) if (l.port !== undefined) (hostOf[l.target] ||= []).push(l.source);
    const access = switches.filter(s => hostOf[s.id]?.length);
    const core = switches.filter(s => !hostOf[s.id]?.length);
    const pos = {};
    const spread = (list, y) => list.forEach((n, i) => { pos[n.id] = { x: (W * (i + 1)) / (list.length + 1), y }; });
    spread(access.length ? access : switches, core.length && access.length ? H * 0.56 : H * 0.42);
    if (access.length) spread(core, H * 0.17);
    for (const sw of access) {
        const hs = (hostOf[sw.id] || []).sort();
        const gap = Math.min(110, (W / (access.length + 1)) / Math.max(hs.length, 1));
        hs.forEach((h, i) => { pos[h] = { x: pos[sw.id].x + (i - (hs.length - 1) / 2) * gap, y: H * 0.88 }; });
    }
    return pos;
};

const loadColor = (util) => (util === undefined ? COLORS.link : util >= 0.8 ? COLORS.hot : util >= 0.5 ? COLORS.warn : COLORS.ok);

const Tag = ({ x, y, text, color = COLORS.label }) => {
    const w = text.length * 6.3 + 8;
    return (
        <g transform={`translate(${x},${y})`} pointerEvents="none">
            <rect x={-w / 2} y={-8} width={w} height={16} rx={3} fill={COLORS.tagBg} opacity={0.9} />
            <text textAnchor="middle" dominantBaseline="central" fontSize={10.5} fill={color} fontFamily="var(--mono)">{text}</text>
        </g>
    );
};

/**
 * nodes / links: dữ liệu từ /api/sdn/topology
 * linkLoads: { "s1|s2": { util, mbps, detail } } từ /api/sdn/routing (tải theo chiều nặng hơn)
 */
const TopologyMap = ({ nodes, links, linkLoads = {}, showInterfaces = true, layoutVersion = 0 }) => {
    const svgRef = useRef(null);
    const [custom, setCustom] = useState(loadSaved);
    const [drag, setDrag] = useState(null);
    const [seenVersion, setSeenVersion] = useState(layoutVersion);

    // "Đặt lại bố cục": cha tăng layoutVersion -> bỏ vị trí tự kéo
    if (layoutVersion !== seenVersion) {
        setSeenVersion(layoutVersion);
        setCustom({});
        save({});
    }

    const base = defaultLayout(nodes, links);
    const pos = (id) => custom[id] || base[id];

    const toSvg = (e) => {
        const pt = svgRef.current.createSVGPoint();
        pt.x = e.clientX;
        pt.y = e.clientY;
        const p = pt.matrixTransform(svgRef.current.getScreenCTM().inverse());
        return { x: Math.max(24, Math.min(W - 24, p.x)), y: Math.max(20, Math.min(H - 28, p.y)) };
    };
    const onMove = (e) => {
        if (!drag) return;
        setCustom(c => ({ ...c, [drag]: toSvg(e) }));
    };
    const endDrag = () => {
        if (drag) save(custom);
        setDrag(null);
    };

    return (
        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="topo-svg" role="img"
            aria-label={`Sơ đồ mạng: ${nodes.filter(n => n.type === 'switch').length} switch, ${nodes.filter(n => n.type === 'host').length} host`}
            onPointerMove={onMove} onPointerUp={endDrag} onPointerLeave={endDrag}>
            {links.map((l) => {
                const a = pos(l.source);
                const b = pos(l.target);
                if (!a || !b) return null;
                const trunk = l.port === undefined;
                const load = trunk ? linkLoads[[l.source, l.target].sort().join('|')] : undefined;
                const color = loadColor(load?.util);
                const width = load ? 2 + Math.min(load.util, 1) * 5 : 1.6;
                // Nhãn interface: link trunk đặt cách switch 46px; link xuống host đặt ở ~40% chiều dài
                // để các link host toả ra từ cùng một switch không đè nhãn lên nhau
                const at = (from, to, d) => {
                    const len = Math.hypot(to.x - from.x, to.y - from.y) || 1;
                    const dist = trunk ? d : len * 0.4;
                    return { x: from.x + ((to.x - from.x) / len) * dist, y: from.y + ((to.y - from.y) / len) * dist };
                };
                const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
                return (
                    <g key={`${l.source}-${l.target}`}>
                        <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={color} strokeWidth={width} strokeLinecap="round">
                            <title>{[l.source_port, l.target_port].filter(Boolean).join(' ↔ ')}{load ? ` · ${load.detail}` : ''}</title>
                        </line>
                        {showInterfaces && l.source_port && <Tag {...at(a, b, 46)} text={l.source_port} />}
                        {showInterfaces && l.target_port && <Tag {...at(b, a, 46)} text={l.target_port} />}
                        {load && <Tag x={mid.x} y={mid.y} text={`${Math.round(load.mbps)} Mbps · ${Math.round(load.util * 100)}%`} color={color} />}
                    </g>
                );
            })}
            {nodes.map((n) => {
                const p = pos(n.id);
                if (!p) return null;
                const isSwitch = n.type === 'switch';
                return (
                    <g key={n.id} transform={`translate(${p.x},${p.y})`} className="topo-node"
                        onPointerDown={(e) => { e.currentTarget.setPointerCapture?.(e.pointerId); setDrag(n.id); }}
                        style={{ cursor: drag === n.id ? 'grabbing' : 'grab' }}>
                        <title>{isSwitch ? `Switch ${n.dpid}` : `Host ${n.name} · MAC ${n.mac}`}</title>
                        {isSwitch ? (
                            <>
                                <rect x={-26} y={-17} width={52} height={34} rx={7} fill={COLORS.switchFill} stroke={COLORS.switchStroke} strokeWidth={1.6} />
                                <path d="M-12 -4h24M-12 4h24M8 -8l4 4-4 4M-8 0l-4 4 4 4" stroke={COLORS.switchStroke} strokeWidth={1.4} fill="none" />
                                <text y={31} textAnchor="middle" fontSize={13} fontWeight={600} fill={COLORS.label}>s{n.dpid}</text>
                            </>
                        ) : (
                            <>
                                <circle r={15} fill={COLORS.hostFill} stroke={COLORS.hostStroke} strokeWidth={1.6} />
                                <rect x={-7} y={-6} width={14} height={9} rx={1.5} stroke={COLORS.hostStroke} strokeWidth={1.3} fill="none" />
                                <path d="M-4 6h8" stroke={COLORS.hostStroke} strokeWidth={1.3} />
                                {/* Chưa biết IP (chưa có lưu lượng) -> name là MAC đầy đủ, quá dài: chỉ hiện đuôi MAC */}
                                <text y={30} textAnchor="middle" fontSize={12} fill={COLORS.label} fontFamily="var(--mono)">
                                    {n.name === n.mac ? `MAC …${n.mac.slice(-5)}` : n.name}
                                </text>
                            </>
                        )}
                    </g>
                );
            })}
        </svg>
    );
};

export default TopologyMap;
