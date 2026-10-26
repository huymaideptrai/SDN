import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ToastContext, ConfirmContext } from '../context/feedback';
import { Button } from './ui';
import { IconAlert, IconCheck, IconX } from './icons';

let toastSeq = 0;

const ConfirmDialog = ({ options, onClose }) => {
    const cancelRef = useRef(null);

    useEffect(() => {
        // Mặc định focus nút Huỷ để Enter không vô tình xác nhận thao tác nguy hiểm
        cancelRef.current?.focus();
        const onKey = (e) => { if (e.key === 'Escape') onClose(false); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [onClose]);

    return (
        <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(false); }}>
            <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby="dialog-title" aria-describedby="dialog-msg">
                <div className="dialog-body">
                    <div className="dialog-icon"><IconAlert size={18} /></div>
                    <div style={{ minWidth: 0 }}>
                        <h2 className="dialog-title" id="dialog-title">{options.title}</h2>
                        <p className="dialog-msg" id="dialog-msg">{options.message}</p>
                        {options.detail && <div className="dialog-detail">{options.detail}</div>}
                    </div>
                </div>
                <div className="dialog-actions">
                    <Button ref={cancelRef} onClick={() => onClose(false)}>Huỷ</Button>
                    <Button variant="danger-solid" onClick={() => onClose(true)}>{options.confirmLabel || 'Xác nhận'}</Button>
                </div>
            </div>
        </div>
    );
};

const FeedbackProvider = ({ children }) => {
    const [toasts, setToasts] = useState([]);
    const [dialog, setDialog] = useState(null);

    const dismiss = useCallback((id) => setToasts(list => list.filter(t => t.id !== id)), []);

    const push = useCallback((type, title, message) => {
        const id = ++toastSeq;
        setToasts(list => [...list.slice(-3), { id, type, title, message }]);
        setTimeout(() => dismiss(id), type === 'error' ? 7000 : 4000);
    }, [dismiss]);

    const toast = useMemo(() => ({
        success: (title, message) => push('success', title, message),
        error: (title, message) => push('error', title, message),
    }), [push]);

    const confirm = useCallback((options) => new Promise(resolve => setDialog({ options, resolve })), []);

    const closeDialog = useCallback((result) => {
        dialog?.resolve(result);
        setDialog(null);
    }, [dialog]);

    return (
        <ToastContext.Provider value={toast}>
            <ConfirmContext.Provider value={confirm}>
                {children}
                <div className="toasts" aria-live="polite">
                    {toasts.map(t => (
                        <div key={t.id} className={`toast ${t.type}`} role={t.type === 'error' ? 'alert' : 'status'}>
                            <span style={{ color: t.type === 'error' ? 'var(--danger)' : 'var(--success)', marginTop: 2 }}>
                                {t.type === 'error' ? <IconAlert size={16} /> : <IconCheck size={16} />}
                            </span>
                            <div className="toast-body">
                                <p className="toast-title">{t.title}</p>
                                {t.message && <p className="toast-msg">{t.message}</p>}
                            </div>
                            <button className="btn btn-ghost btn-sm btn-icon" style={{ width: 24, height: 24 }}
                                onClick={() => dismiss(t.id)} aria-label="Đóng thông báo">
                                <IconX size={14} />
                            </button>
                        </div>
                    ))}
                </div>
                {dialog && <ConfirmDialog options={dialog.options} onClose={closeDialog} />}
            </ConfirmContext.Provider>
        </ToastContext.Provider>
    );
};

export default FeedbackProvider;
