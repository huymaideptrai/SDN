import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine } from 'recharts';

const WINDOW_MS = 60_000;
const TICK_MS = 15_000;
const TX = '#2dd4bf';
const RX = '#60a5fa';
const AFTER_QOS = '#fbbf24';
const LIMIT = '#f87171';
const AXIS = { stroke: '#3a4b63', tick: { fill: '#8b9bb0', fontSize: 12 } };

const clock = (ms) => new Date(ms).toLocaleTimeString('vi-VN', { hour12: false });
const has = (data, key) => data.some(d => d[key] !== undefined && d[key] !== null);

/**
 * Trục thời gian cố định 60 giây, trượt theo mẫu mới nhất.
 * data: [{ts, tx, rx, rxAfter?, txOffered?}]
 *  - rxAfter  : QoS chiều vào - lưu lượng sau meter (rx đếm trước meter)
 *  - txOffered: QoS chiều ra  - lưu lượng muốn gửi trước meter (tx đã là sau meter)
 */
const BandwidthChart = ({ data, now, limitIn, limitOut }) => {
    const end = now ?? data[data.length - 1]?.ts ?? 0;
    const start = end - WINDOW_MS;
    const ticks = [];
    for (let t = Math.ceil(start / TICK_MS) * TICK_MS; t <= end; t += TICK_MS) ticks.push(t);
    const hasIn = has(data, 'rxAfter');
    const hasOut = has(data, 'txOffered');
    const maxLimit = Math.max(limitIn ?? 0, limitOut ?? 0);

    return (
        <div className="chart-box">
            <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
                    <CartesianGrid stroke="#1c2634" vertical={false} />
                    <XAxis dataKey="ts" type="number" scale="time" domain={[start, end]} ticks={ticks}
                        allowDataOverflow tickFormatter={clock} {...AXIS} />
                    <YAxis {...AXIS} width={56} domain={[0, (max) => Math.max(max, maxLimit, 1) * 1.1]}
                        tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(1)}G` : v >= 10 ? Math.round(v) : Number(v.toFixed(1)))} />
                    <Tooltip
                        contentStyle={{ background: '#161e2a', border: '1px solid #2f3f55', borderRadius: 6, fontSize: 13 }}
                        labelStyle={{ color: '#e6edf3' }}
                        labelFormatter={clock}
                        formatter={(v, name) => [`${Number(v).toLocaleString('vi-VN')} Mbps`, name]}
                    />
                    <Legend wrapperStyle={{ fontSize: 13, color: '#8b9bb0' }} iconType="plainline" />
                    {limitIn && (
                        <ReferenceLine y={limitIn} stroke={LIMIT} strokeDasharray="4 4" ifOverflow="extendDomain"
                            label={{ value: `QoS vào ${limitIn} Mbps`, fill: LIMIT, fontSize: 12, position: 'insideTopRight' }} />
                    )}
                    {limitOut && (
                        <ReferenceLine y={limitOut} stroke={LIMIT} strokeDasharray="2 4" ifOverflow="extendDomain"
                            label={{ value: `QoS ra ${limitOut} Mbps`, fill: LIMIT, fontSize: 12, position: limitIn ? 'insideBottomRight' : 'insideTopRight' }} />
                    )}
                    <Line type="monotone" dataKey="tx" name={hasOut ? 'TX (sau QoS)' : 'TX'} stroke={TX} strokeWidth={2} dot={false} isAnimationActive={false} />
                    {hasOut && (
                        <Line type="monotone" dataKey="txOffered" name="TX muốn gửi" stroke={TX} strokeWidth={1.5}
                            strokeDasharray="5 3" strokeOpacity={0.6} dot={false} isAnimationActive={false} connectNulls />
                    )}
                    <Line type="monotone" dataKey="rx" name={hasIn ? 'RX (đến port)' : 'RX'} stroke={RX} strokeWidth={2} dot={false} isAnimationActive={false} />
                    {hasIn && (
                        <Line type="monotone" dataKey="rxAfter" name="RX sau QoS" stroke={AFTER_QOS} strokeWidth={2}
                            strokeDasharray="5 3" dot={false} isAnimationActive={false} connectNulls />
                    )}
                </LineChart>
            </ResponsiveContainer>
        </div>
    );
};

export default BandwidthChart;
