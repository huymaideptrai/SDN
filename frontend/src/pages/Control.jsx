import React, { useState, useEffect } from 'react';
import axiosClient from '../api/axiosClient';

const Control = () => {
    const [selectedDpid, setSelectedDpid] = useState(1);
    const [switchList, setSwitchList] = useState([]);
    const [flowRules, setFlowRules] = useState([]);
    const [formMsg, setFormMsg] = useState('');

    const [srcIp, setSrcIp] = useState('');
    const [dstIp, setDstIp] = useState('');
    const [action, setAction] = useState('ALLOW');
    const [priority, setPriority] = useState(100);

    const [qosPort, setQosPort] = useState(1);
    const [maxRate, setMaxRate] = useState(''); 

    useEffect(() => {
        const fetchTopology = async () => {
            try {
                const res = await axiosClient.get('/api/sdn/topology');
                if (res.data.status === 'success') {
                    const switches = res.data.nodes
                        .filter(node => node.id.startsWith('s'))
                        .map(node => parseInt(node.id.replace('s', ''))); 
                    setSwitchList([...new Set(switches)].sort());
                }
            } catch (err) {
                console.error("Lỗi tải Topology:", err);
            }
        };
        fetchTopology();
    }, []);

    const fetchFlows = async () => {
        try {
            const res = await axiosClient.get(`/api/sdn/flows/${selectedDpid}`);
            if (res.data.status === 'success') {
                setFlowRules(res.data.flows);
            }
        } catch (err) {
            console.error("Lỗi tải Flows:", err);
        }
    };

    useEffect(() => {
        fetchFlows();
    }, [selectedDpid]);

    const handleAddFlow = async (e) => {
        e.preventDefault();
        try {
            const payload = { dpid: selectedDpid, src_ip: srcIp || null, dst_ip: dstIp || null, action, priority: parseInt(priority) };
            await axiosClient.post('/api/sdn/flows', payload);
            setFormMsg('✅ Thêm luật thành công!');
            fetchFlows(); 
        } catch (err) {
            setFormMsg('❌ Lỗi: ' + (err.response?.data?.detail || 'Không thể thêm luật'));
        }
    };

    const handleDeleteFlow = async (flow) => {
        if (!window.confirm('Bạn có chắc chắn muốn xóa luật này?')) return;
        try {
            await axiosClient.delete(`/api/sdn/flows/${selectedDpid}`, { data: flow.match });
            setFormMsg('✅ Xóa luật thành công!');
            fetchFlows();
        } catch (err) {
            setFormMsg('❌ Lỗi khi xóa luật');
        }
    };

    const handleSetBandwidth = async (e) => {
        e.preventDefault();
        try {
            const payload = { dpid: selectedDpid, port: parseInt(qosPort), max_rate_mbps: parseInt(maxRate) };
            await axiosClient.post('/api/sdn/qos/config', payload);
            setFormMsg(`✅ Đã giới hạn port \({qosPort} ở mức\){maxRate} Mbps!`);
        } catch (err) {
            setFormMsg('❌ Lỗi cấu hình băng thông');
        }
    };

    return (
        <div style={{ padding: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <h2>Cấu hình & Điều khiển mạng</h2>
                <div style={{ padding: '10px', backgroundColor: '#f0f0f0', borderRadius: '5px' }}>
                    <label style={{ fontWeight: 'bold', marginRight: '10px' }}>Chọn Switch:</label>
                    <select value={selectedDpid} onChange={(e) => setSelectedDpid(parseInt(e.target.value))} style={{ padding: '5px', fontSize: '16px' }}>
                        {switchList.map(dpid => (
                            <option key={dpid} value={dpid}>
                                Switch {dpid}
                            </option>
                        ))}
                    </select>
                </div>
            </div>

            {formMsg && (
                <div style={{ padding: '10px', marginBottom: '20px', backgroundColor: '#e6f7ff', border: '1px solid #91d5ff' }}>
                    {formMsg}
                </div>
            )}

            <div style={{ display: 'flex', gap: '20px', marginBottom: '20px' }}>
                <div style={{ border: '1px solid #ccc', padding: '15px', width: '50%' }}>
                    <h3>1. Thêm luật điều hướng (Routing / Firewall)</h3>
                    <form onSubmit={handleAddFlow} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                        <input type="text" placeholder="IP Nguồn (VD: 10.0.0.1)" value={srcIp} onChange={(e) => setSrcIp(e.target.value)} />
                        <input type="text" placeholder="IP Đích (VD: 10.0.0.2)" value={dstIp} onChange={(e) => setDstIp(e.target.value)} />
                        <select value={action} onChange={(e) => setAction(e.target.value)}>
                            <option value="ALLOW">ALLOW (Cho phép)</option>
                            <option value="DROP">DROP (Chặn)</option>
                        </select>
                        <input type="number" placeholder="Độ ưu tiên (Mặc định: 100)" value={priority} onChange={(e) => setPriority(e.target.value)} />
                        <button type="submit" style={{ padding: '10px', background: '#1890ff', color: 'white', border: 'none', cursor: 'pointer' }}>Thêm Luật</button>
                    </form>
                </div>

                <div style={{ border: '1px solid #ccc', padding: '15px', width: '50%' }}>
                    <h3>2. Cấu hình giới hạn băng thông (QoS)</h3>
                    <form onSubmit={handleSetBandwidth} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                        <input type="number" placeholder="Số hiệu Port (VD: 1, 2...)" value={qosPort} onChange={(e) => setQosPort(e.target.value)} required />
                        <input type="number" placeholder="Giới hạn tối đa (Mbps)" value={maxRate} onChange={(e) => setMaxRate(e.target.value)} required />
                        <button type="submit" style={{ padding: '10px', background: '#52c41a', color: 'white', border: 'none', cursor: 'pointer' }}>Áp dụng QoS</button>
                    </form>
                </div>
            </div>

            <div style={{ border: '1px solid #ccc', padding: '15px' }}>
                <h3>Danh sách luật đang chạy trên Switch {selectedDpid}</h3>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                        <tr style={{ backgroundColor: '#f2f2f2' }}>
                            <th style={{ border: '1px solid #ddd', padding: '8px' }}>Priority</th>
                            <th style={{ border: '1px solid #ddd', padding: '8px' }}>Match</th>
                            <th style={{ border: '1px solid #ddd', padding: '8px' }}>Action</th>
                            <th style={{ border: '1px solid #ddd', padding: '8px' }}>Thao tác</th>
                        </tr>
                    </thead>
                    <tbody>
                        {flowRules.map((flow, index) => (
                            <tr key={index}>
                                <td style={{ border: '1px solid #ddd', padding: '8px', textAlign: 'center' }}>{flow.priority}</td>
                                <td style={{ border: '1px solid #ddd', padding: '8px' }}>{JSON.stringify(flow.match)}</td>
                                <td style={{ border: '1px solid #ddd', padding: '8px' }}>{JSON.stringify(flow.actions)}</td>
                                <td style={{ border: '1px solid #ddd', padding: '8px', textAlign: 'center' }}>
                                    {flow.priority < 65535 && (
                                        <button onClick={() => handleDeleteFlow(flow)} style={{ background: '#ff4d4f', color: 'white', border: 'none', padding: '5px 10px', cursor: 'pointer' }}>Xóa</button>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

export default Control;