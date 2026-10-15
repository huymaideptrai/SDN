from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime


class UserLogin(BaseModel):
    username: str
    password: str

class UserCreate(UserLogin):
    email: Optional[str] = None
    role: str = "viewer"

class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    
    class Config:
        orm_mode = True


class Token(BaseModel):
    access_token: str
    token_type: str


class FlowPolicyCreate(BaseModel):
    dpid: str
    src_ip: Optional[str] = None
    dst_ip: Optional[str] = None
    priority: int = 100
    match_conditions: Dict[str, Any]
    action: str


class QoSProfileCreate(BaseModel):
    dpid: str
    port_no: int
    max_bw: int
    latency: Optional[str] = None
    packet_loss: Optional[float] = None
    description: Optional[str] = None