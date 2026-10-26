from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.models import AuditLog, User
from app.schemas.schemas import AuditLogResponse, PasswordReset, UserCreate, UserDetail, UserUpdate
from app.core.security import get_password_hash
from app.core.dependencies import require_admin

router = APIRouter(prefix="/api", tags=["Quản trị"])


def _audit(db: Session, admin: User, action: str, details: dict):
    # Thao tác không gắn với switch nào -> dpid = "-" (cột NOT NULL)
    db.add(AuditLog(user_id=admin.id, action=action, dpid="-", details=details))


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy người dùng")
    return user


@router.get("/users", response_model=List[UserDetail])
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return db.query(User).order_by(User.id).all()


@router.post("/users", response_model=UserDetail)
def create_user(body: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=400, detail="Tên đăng nhập đã tồn tại")
    if body.email and db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=400, detail="Email đã được sử dụng")
    user = User(username=body.username, password_hash=get_password_hash(body.password),
                email=body.email, role=body.role)
    db.add(user)
    db.flush()
    _audit(db, admin, "CREATE_USER", {"user_id": user.id, "username": user.username, "role": user.role})
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserDetail)
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = _get_user(db, user_id)
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Không thể tự đổi vai trò hoặc tự khoá tài khoản của mình")

    # Phòng thủ thêm: người thao tác luôn là admin đang hoạt động và không được tự sửa mình,
    # nên qua API luôn còn >= 1 admin; kiểm tra này chặn trường hợp dữ liệu bị sửa ngoài API.
    loses_admin = user.role == "admin" and user.is_active and (
        (body.role is not None and body.role != "admin") or body.is_active is False)
    if loses_admin:
        active_admins = db.query(User).filter(User.role == "admin", User.is_active == True).count()
        if active_admins <= 1:
            raise HTTPException(status_code=400, detail="Hệ thống phải còn ít nhất một quản trị viên đang hoạt động")

    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(user, field, value)
    _audit(db, admin, "UPDATE_USER", {"user_id": user.id, "username": user.username, **changes})
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, body: PasswordReset, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    user = _get_user(db, user_id)
    user.password_hash = get_password_hash(body.new_password)
    _audit(db, admin, "RESET_PASSWORD", {"user_id": user.id, "username": user.username})
    db.commit()
    return {"status": "success", "message": f"Đã đặt lại mật khẩu cho {user.username}"}


@router.get("/audit-logs", response_model=List[AuditLogResponse])
def list_audit_logs(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                    action: Optional[str] = None,
                    db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    query = db.query(AuditLog, User.username).outerjoin(User, User.id == AuditLog.user_id)
    if action:
        query = query.filter(AuditLog.action == action)
    rows = query.order_by(AuditLog.id.desc()).offset(offset).limit(limit).all()
    return [AuditLogResponse(id=log.id, timestamp=log.timestamp, username=username, action=log.action,
                             dpid=log.dpid, details=log.details) for log, username in rows]
