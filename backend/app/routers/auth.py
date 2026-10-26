from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.models.database import get_db
from app.models.models import User, AuditLog
from app.schemas.schemas import Token, UserDetail, PasswordChange
from app.core.security import get_password_hash, verify_password, create_access_token
from app.core.dependencies import get_current_user

# Không có đăng ký công khai: tài khoản chỉ do admin tạo (POST /api/users)
# hoặc bằng lệnh `python -m app.create_user` trên máy chủ (tạo admin đầu tiên).
router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Sai tài khoản hoặc mật khẩu")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Tài khoản đã bị khoá")

    user.last_login = datetime.now(timezone.utc)
    db.commit()

    access_token = create_access_token(
        data={"sub": user.username, "user_id": user.id, "role": user.role}
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=UserDetail)
def read_me(current_user: User = Depends(get_current_user)):
    return current_user

@router.post("/change-password")
def change_password(body: PasswordChange, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Mật khẩu hiện tại không đúng")
    current_user.password_hash = get_password_hash(body.new_password)
    db.add(AuditLog(user_id=current_user.id, action="CHANGE_PASSWORD", dpid="-"))
    db.commit()
    return {"status": "success", "message": "Đã đổi mật khẩu"}
