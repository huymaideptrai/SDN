#!/bin/bash
# Khởi động lại lab SDN trên VM theo đúng thứ tự: dọn -> Ryu -> Mininet
# (Mininet chạy trước Ryu làm Ryu 4.34 ngừng gửi LLDP; `mn -c` cũng kill ryu-manager)
# Cách dùng: sudo bash restart_lab.sh [thư mục chứa sdn_brain.py, custom_topology.py]
set -u
DIR="${1:-/home/huyadmin/ryu/SDN_Project}"
RYU_USER="${SUDO_USER:-huyadmin}"
RYU_BIN="/home/$RYU_USER/ryu_env/bin/ryu-manager"
CAPACITY="${SDN_LINK_CAPACITY_MBPS:-50}"

echo "== Dừng Mininet / Ryu cũ"
pkill -TERM -f '^python3 custom_topology.py' && sleep 4
pkill -f "$RYU_BIN" ; sleep 1
mn -c > /dev/null 2>&1
echo "   đã dọn"

echo "== Khởi động Ryu (capacity ${CAPACITY} Mbps)"
cd "$DIR"
sudo -u "$RYU_USER" env SDN_LINK_CAPACITY_MBPS="$CAPACITY" setsid "$RYU_BIN" --observe-links \
    sdn_brain.py ryu.app.ofctl_rest ryu.app.rest_topology > /tmp/ryu.log 2>&1 < /dev/null &
for i in $(seq 1 20); do
    ss -ltn | grep -q ':8080 ' && break
    sleep 0.5
done
ss -ltn | grep -q ':8080 ' && echo "   Ryu đang nghe :8080" || { echo "   LỖI: Ryu không khởi động"; tail -20 /tmp/ryu.log; exit 1; }

echo "== Khởi động Mininet (chạy nền)"
SDN_LINK_CAPACITY_MBPS="$CAPACITY" setsid python3 custom_topology.py --no-cli > /tmp/mininet.log 2>&1 < /dev/null &
for i in $(seq 1 30); do
    grep -q -- '--no-cli' /tmp/mininet.log 2>/dev/null && break
    sleep 1
done
grep -E 'Adding|Starting|LỖI|Error|Exception' /tmp/mininet.log | head -8
echo "== Ryu log"
grep -v -E 'HTTP/1.1|accepted' /tmp/ryu.log | tail -5
