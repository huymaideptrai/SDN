import { createContext, useContext } from 'react';

// Toast: toast.success(title, message) / toast.error(title, message)
export const ToastContext = createContext(null);
// Confirm: const ok = await confirm({ title, message, detail, confirmLabel })
export const ConfirmContext = createContext(null);

export const useToast = () => useContext(ToastContext);
export const useConfirm = () => useContext(ConfirmContext);
