import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, Link } from 'react-router-dom';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Control from './pages/Control';

const ProtectedRoute = ({ children }) => {
    const token = localStorage.getItem('access_token');
    if (!token) return <Navigate to="/login" replace />;

    return (
        <div>
            <nav style={{ padding: '10px 20px', background: '#001529', marginBottom: '20px' }}>
                <Link to="/dashboard" style={{ color: 'white', marginRight: '20px', textDecoration: 'none', fontSize: '18px' }}>📊 Dashboard</Link>
                <Link to="/control" style={{ color: 'white', textDecoration: 'none', fontSize: '18px' }}>⚙️ Điều khiển</Link>
            </nav>
            {children}
        </div>
    );
};

function App() {
    return (
        <BrowserRouter>
            <Routes>
                <Route path="/" element={<Navigate to="/dashboard" replace />} />
                <Route path="/login" element={<Login />} />
                <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
                <Route path="/control" element={<ProtectedRoute><Control /></ProtectedRoute>} />
            </Routes>
        </BrowserRouter>
    );
}

export default App;