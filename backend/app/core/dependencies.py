from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session
from app.core.security import decode_access_token
from app.models.database import get_db
from app.models.models import User


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Phiên đăng nhập đã hết hạn hoặc không hợp lệ",
    headers={"WWW-Authenticate": "Bearer"},
)


def _user_from_token(token: str, db: Session) -> User:
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise CREDENTIALS_ERROR
    user_id = payload.get("user_id")
    if user_id is None:
        raise CREDENTIALS_ERROR
    # Đọc lại từ DB để role / trạng thái khoá tài khoản có hiệu lực ngay
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise CREDENTIALS_ERROR
    return user


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    return _user_from_token(token, db)


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ quản trị viên mới được thực hiện thao tác này"
        )
    return current_user
