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