import subprocess
from typing import Dict, Any

class TCCmdService:
    def __init__(self):
        """Khởi tạo service tương tác với lệnh 'tc' trên Linux"""
        pass

    def run_command(self, cmd: str) -> bool:
        """Thực thi một lệnh shell và trả về True nếu thành công"""
        try:
            result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Lỗi khi chạy lệnh tc: {e.stderr}")
            return False

    def clear_qos(self, interface: str) -> bool:
        cmd = f"tc qdisc del dev {interface} root"
        subprocess.run(cmd, shell=True, capture_output=True)
        return True

    def set_bandwidth(self, interface: str, max_bw_mbps: int) -> Dict[str, Any]:
        """Thiết lập giới hạn băng thông sử dụng thuật toán TBF (Token Bucket Filter)"""
        self.clear_qos(interface)
        
        burst = max_bw_mbps * 125
        cmd = f"tc qdisc add dev {interface} root tbf rate {max_bw_mbps}mbit burst {burst}k latency 50ms"
        
        success = self.run_command(cmd)
        if success:
             return {"status": "success", "message": f"Đã bóp băng thông {interface} xuống {max_bw_mbps}Mbps"}
        return {"status": "error", "message": "Không thể cấu hình QoS"}
    
    def set_netem(self, interface: str, delay_ms: str = None, loss_percent: float = None) -> Dict[str, Any]:
        """Tạo cấu hình mô phỏng mạng (Network Emulator) - Độ trễ và rớt gói"""
        self.clear_qos(interface)
        
        cmd_parts = [f"tc qdisc add dev {interface} root netem"]
        if delay_ms:
            cmd_parts.append(f"delay {delay_ms}")
        if loss_percent:
            cmd_parts.append(f"loss {loss_percent}%")
            
        cmd = " ".join(cmd_parts)
        success = self.run_command(cmd)
        if success:
             return {"status": "success", "message": f"Đã tạo luật NetEm trên {interface}"}
        return {"status": "error", "message": "Không thể cấu hình NetEm"}