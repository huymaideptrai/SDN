import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Control from './pages/Control';
import Settings from './pages/Settings';
import Layout from './components/Layout';
import FeedbackProvider from './components/FeedbackProvider';
import { getCurrentUser, clearToken } from './api/auth';

const ProtectedRoute = ({ children }) => {
    const user = getCurrentUser();
    if (!user) {
        clearToken();
        return <Navigate to="/login" replace />;
    }
    return <Layout user={user}>{children}</Layout>;
};

function App() {
    return (
        <FeedbackProvider>
            <BrowserRouter>
                <Routes>
                    <Route path="/" element={<Navigate to="/dashboard" replace />} />
                    <Route path="/login" element={<Login />} />
                    <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
                    <Route path="/control" element={<ProtectedRoute><Control /></ProtectedRoute>} />
                    <Route path="/settings" element={<ProtectedRoute><Settings /></ProtectedRoute>} />
                    <Route path="*" element={<Navigate to="/dashboard" replace />} />
                </Routes>
            </BrowserRouter>
        </FeedbackProvider>
    );
}

export default App;
