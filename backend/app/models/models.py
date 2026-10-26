from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, JSON
from sqlalchemy.sql import func
from .database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    email = Column(String, unique=True, index=True)
    role = Column(String, default="viewer")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    action = Column(String, nullable=False)
    dpid = Column(String, nullable=False)
    details = Column(JSON, nullable=True)

class FlowPolicy(Base):
    __tablename__ = "flow_policies"
    
    id = Column(Integer, primary_key=True, index=True)
    dpid = Column(String, nullable=False, index=True)
    priority = Column(Integer, default=100)
    match_conditions = Column(JSON, nullable=False)
    action = Column(JSON, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    is_active = Column(Boolean, default=True)

class QoSProfile(Base):
    __tablename__ = "qos_profiles"
    
    id = Column(Integer, primary_key=True, index=True)
    dpid = Column(String, nullable=False, index=True)
    port_no = Column(Integer, nullable=False)
    max_bw = Column(Integer, nullable=False)
    description = Column(String, nullable=True)
    # "ingress": giới hạn lưu lượng đi vào switch từ port; "egress": lưu lượng đi ra khỏi port
    direction = Column(String, nullable=False, default="ingress", server_default="ingress")

class SwitchSnmp(Base):
    """Thông tin SNMP để đọc CPU/RAM/nhiệt độ của switch thật (switch Mininet không có).
    Lưu ý: community / khoá SNMPv3 lưu dạng rõ trong SQLite; API không bao giờ trả lại các giá trị này."""
    __tablename__ = "switch_snmp"

    id = Column(Integer, primary_key=True, index=True)
    dpid = Column(String, nullable=False, unique=True, index=True)
    host = Column(String, nullable=False)
    port = Column(Integer, nullable=False, default=161)
    version = Column(String, nullable=False, default="2c")   # "2c" | "3"
    community = Column(String, nullable=True)
    v3_user = Column(String, nullable=True)
    v3_auth_proto = Column(String, nullable=True)            # MD5 | SHA | SHA256
    v3_auth_key = Column(String, nullable=True)
    v3_priv_proto = Column(String, nullable=True)            # DES | AES
    v3_priv_key = Column(String, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
