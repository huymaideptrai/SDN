import ipaddress
from datetime import datetime
from typing import Optional, Literal, Dict, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class UserLogin(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=72)  # bcrypt chỉ dùng 72 byte đầu

class UserCreate(UserLogin):
    email: Optional[str] = None
    role: Literal["admin", "viewer"] = "viewer"

    @field_validator("email")
    @classmethod
    def empty_email_to_none(cls, v):
        return v or None

class Token(BaseModel):
    access_token: str
    token_type: str


def _validate_ipv4(v: Optional[str]) -> Optional[str]:
    if v is None or v.strip() == "":
        return None
    v = v.strip()
    try:
        # Chấp nhận cả IP đơn (10.0.0.1) và subnet (10.0.0.0/24)
        net = ipaddress.IPv4Network(v, strict=False)
    except ValueError:
        raise ValueError(f"'{v}' không phải địa chỉ IPv4 hoặc subnet hợp lệ")
    return v if "/" in v else str(net.network_address)


class FlowPolicyCreate(BaseModel):
    dpid: int = Field(ge=1)
    src_ip: Optional[str] = None
    dst_ip: Optional[str] = None
    # > 1 để đè lên luật học MAC (priority 1), < 65535 để không đè luật LLDP
    priority: int = Field(default=100, ge=2, le=65534)
    action: Literal["ALLOW", "DROP"]

    @field_validator("action", mode="before")
    @classmethod
    def upper_action(cls, v):
        return v.upper() if isinstance(v, str) else v

    @field_validator("src_ip", "dst_ip")
    @classmethod
    def check_ip(cls, v):
        return _validate_ipv4(v)

    @model_validator(mode="after")
    def require_one_ip(self):
        if not self.src_ip and not self.dst_ip:
            raise ValueError("Cần nhập ít nhất IP nguồn hoặc IP đích")
        return self


class FlowPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dpid: str
    priority: int
    match_conditions: Dict[str, Any]
    action: str
    is_active: bool


class FlowDelete(BaseModel):
    """Xoá một flow bất kỳ (VD: luật học MAC) theo đúng match + priority"""
    table_id: int = Field(ge=0, le=254)
    priority: int = Field(ge=1, le=65534)
    match: Dict[str, Any]


class QoSConfig(BaseModel):
    dpid: int = Field(ge=1)
    port: int = Field(ge=1, le=0xfffffeff)
    max_rate_mbps: float = Field(gt=0, le=10000)
    # ingress: lưu lượng vào switch từ port; egress: lưu lượng ra khỏi port; both: cả hai
    direction: Literal["ingress", "egress", "both"] = "ingress"
    description: Optional[str] = None


class QoSProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dpid: str
    port_no: int
    max_bw: int  # kbps
    direction: str = "ingress"
    description: Optional[str] = None


# ---------- Tài khoản / quản trị người dùng ----------

class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=72)

    @model_validator(mode="after")
    def must_differ(self):
        if self.current_password == self.new_password:
            raise ValueError("Mật khẩu mới phải khác mật khẩu hiện tại")
        return self


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=6, max_length=72)


class UserUpdate(BaseModel):
    role: Optional[Literal["admin", "viewer"]] = None
    is_active: Optional[bool] = None


class UserDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: Optional[str] = None
    role: str
    is_active: bool
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None


class AuditLogResponse(BaseModel):
    id: int
    timestamp: Optional[datetime] = None
    username: Optional[str] = None
    action: str
    dpid: str
    details: Optional[Dict[str, Any]] = None


# ---------- SNMP (tài nguyên phần cứng switch thật) ----------

class SnmpConfigIn(BaseModel):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=161, ge=1, le=65535)
    version: Literal["2c", "3"] = "2c"
    # Bỏ trống khi sửa = giữ giá trị đã lưu (giao diện không bao giờ nhận lại các giá trị bí mật)
    community: Optional[str] = Field(default=None, max_length=128)
    v3_user: Optional[str] = Field(default=None, max_length=64)
    v3_auth_proto: Optional[Literal["MD5", "SHA", "SHA256"]] = None
    v3_auth_key: Optional[str] = Field(default=None, min_length=8, max_length=128)
    v3_priv_proto: Optional[Literal["DES", "AES"]] = None
    v3_priv_key: Optional[str] = Field(default=None, min_length=8, max_length=128)

    @field_validator("host")
    @classmethod
    def strip_host(cls, v):
        v = v.strip()
        if " " in v:
            raise ValueError("Địa chỉ không hợp lệ")
        return v

    @field_validator("community", "v3_user", "v3_auth_key", "v3_priv_key", mode="before")
    @classmethod
    def empty_to_none(cls, v):
        return v or None

    @model_validator(mode="after")
    def check_v3(self):
        if self.version == "3":
            if self.v3_priv_proto and not self.v3_auth_proto:
                raise ValueError("SNMPv3 có mã hoá (priv) thì phải có xác thực (auth)")
        return self


class SnmpConfigOut(BaseModel):
    dpid: int
    host: str
    port: int
    version: str
    has_community: bool
    v3_user: Optional[str] = None
    v3_auth_proto: Optional[str] = None
    v3_priv_proto: Optional[str] = None
    has_auth_key: bool
    has_priv_key: bool
    updated_at: Optional[datetime] = None
