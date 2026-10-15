import React, { useState, useEffect } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import axiosClient from '../api/axiosClient';
import { useNavigate } from 'react-router-dom';

const Dashboard = () => {
    const navigate = useNavigate();
    
    // State dữ liệu hệ thống
    const [topology, setTopology] = useState({ nodes: [], links: [] });
    const [globalQosData, setGlobalQosData] = useState({});
    
    // State quản lý lựa chọn thiết bị
    const [selectedDpid, setSelectedDpid] = useState(1);
    const [switchList, setSwitchList] = useState([]);
    const [selectedPort, setSelectedPort] = useState(1); 
    const [portList, setPortList] = useState([]);

    // Xử lý Đăng xuất
    const handleLogout = () => {
        localStorage.removeItem('access_token');
        navigate('/login');
    };

    // 1. Fetch Topology
    useEffect(() => {
        const fetchTopology = async () => {
            try {
                const res = await axiosClient.get('/api/sdn/topology');
                if (res.data.status === 'success') {
                    setTopology(res.data);
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

    // 2. Fetch QoS theo Switch và Port đã chọn
    useEffect(() => {
        const fetchQoS = async () => {
            try {
                const res = await axiosClient.get(`/api/sdn/qos/${selectedDpid}`);
                if (res.data.status === 'success') {
                    const availablePorts = res.data.stats
                        .map(p => p.port)
                        .filter(p => typeof p === 'number');
                    setPortList(availablePorts);

                    const portStats = res.data.stats.find(p => p.port === selectedPort) || { tx_mbps: 0, rx_mbps: 0 };
                    const newDataPoint = {
                        time: res.data.timestamp,
                        tx: portStats.tx_mbps,
                        rx: portStats.rx_mbps
                    };

                    setGlobalQosData(prevGlobal => {
                        // Đã sửa lại cú pháp Template String đúng
                        const dictKey = `\({selectedDpid}_\){selectedPort}`; 
                        
                        const portHistory = prevGlobal[dictKey] || []; 
                        const updatedHistory = [...portHistory, newDataPoint];
                        const trimmedHistory = updatedHistory.length > 15 ? updatedHistory.slice(1) : updatedHistory;

                        return {
                            ...prevGlobal,
                            [dictKey]: trimmedHistory
                        };
                    });
                }
            } catch (err) {
                console.error("Lỗi tải QoS:", err);
            }
        };

        const intervalId = setInterval(fetchQoS, 3000);
        return () => clearInterval(intervalId);
    }, [selectedDpid, selectedPort]);

    const currentChartData = globalQosData[`\({selectedDpid}_\){selectedPort}`];
    const safeChartData = (currentChartData && currentChartData.length > 0) 
        ? currentChartData 
        : [{ time: '00:00:00', tx: 0, rx: 0 }];

    
    return (
        <div style={{ padding: '20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <h2 style={{ margin: 0 }}>SDN Controller Dashboard</h2>

                <div style={{ display: 'flex', gap: '20px', alignItems: 'center' }}>
                    {/* Chọn Switch */}
                    <div style={{ padding: '10px', backgroundColor: '#f0f0f0', borderRadius: '5px' }}>
                        <label style={{ fontWeight: 'bold', marginRight: '10px' }}>Switch:</label>
                        <select 
                            value={selectedDpid} 
                            onChange={(e) => {
                                setSelectedDpid(parseInt(e.target.value));
                                setSelectedPort(1); // Reset cổng về 1 khi đổi Switch
                            }}
                            style={{ padding: '5px', fontSize: '16px' }}
                        >
                            {switchList.length > 0 ? (
                                switchList.map(dpid => (
                                    <option key={dpid} value={dpid}>Switch {dpid}</option>
                                ))
                            ) : (
                                <option value={1}>Switch 1 (Mặc định)</option>
                            )}
                        </select>
                    </div>

                    {/* Chọn Port */}
                    <div style={{ padding: '10px', backgroundColor: '#e6f7ff', borderRadius: '5px' }}>
                        <label style={{ fontWeight: 'bold', marginRight: '10px' }}>Port:</label>
                        <select 
                            value={selectedPort} 
                            onChange={(e) => setSelectedPort(parseInt(e.target.value))}
                            style={{ padding: '5px', fontSize: '16px' }}
                        >
                            {portList.length > 0 ? (
                                portList.map(port => (
                                    <option key={port} value={port}>Port {port}</option>
                                ))
                            ) : (
                                <option value={1}>Port 1</option>
                            )}
                        </select>
                    </div>

                    {/* Nút Đăng xuất */}
                    <button onClick={handleLogout} style={{ padding: '10px 15px', backgroundColor: '#ff4d4f', color: 'white', border: 'none', borderRadius: '5px', cursor: 'pointer' }}>
                        Đăng xuất
                    </button>
                </div>
            </div>

            <div style={{ display: 'flex', gap: '20px', marginBottom: '20px' }}>
                {/* Phần 1: Topology */}
                <div style={{ border: '1px solid #ccc', padding: '10px', width: '50%' }}>
                    <h3>Mạng Topology</h3>
                    <ForceGraph2D
                        width={600}
                        height={400}
                        graphData={topology}
                        nodeLabel="name"
                        nodeVal="val"
                        nodeColor={node => node.color}
                        linkColor={() => 'rgba(255, 255, 255, 0.6)'} // Đường nối màu trắng đục
                        linkWidth={2}                                // Làm đường nối dày lên
                        linkDirectionalArrowLength={3.5}
                    />
                </div>

                {/* Phần 2: QoS */}
                <div style={{ border: '1px solid #ccc', padding: '10px', width: '50%' }}>
                    <h3>Băng thông Switch {selectedDpid} - Port {selectedPort} (Mbps)</h3>
                    <ResponsiveContainer width="100%" height={350}>
                        <LineChart data={globalQosData[`\({selectedDpid}_\){selectedPort}`] || []}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey="time" />
                            <YAxis />
                            <Tooltip />
                            <Legend />
                            <Line type="monotone" dataKey="tx" stroke="#8884d8" name="TX (Mbps)" />
                            <Line type="monotone" dataKey="rx" stroke="#82ca9d" name="RX (Mbps)" />
                        </LineChart>
                    </ResponsiveContainer>
                </div>
            </div>

        </div>
    );
}

export default Dashboard;