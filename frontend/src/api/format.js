// Backend lưu thời gian UTC trong SQLite và trả về không kèm múi giờ -> coi chuỗi không có múi giờ là UTC
export const parseServerTime = (value) => {
    if (!value) return null;
    const hasZone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value);
    return new Date(hasZone ? value : `${value}Z`);
};

export const formatDateTime = (value) => {
    const d = parseServerTime(value);
    return d ? d.toLocaleString('vi-VN', { hour12: false }) : '—';
};
