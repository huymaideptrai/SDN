"""Tạo tài khoản từ dòng lệnh (cách duy nhất để tạo admin đầu tiên).

Cách dùng (chạy trong thư mục backend):
    venv\\Scripts\\python -m app.create_user <username> --role admin
"""
import argparse
import getpass
import sys
from app.models.database import SessionLocal, engine, Base
from app.models.models import User
from app.core.security import get_password_hash


def main():
    parser = argparse.ArgumentParser(description="Tạo tài khoản SDN")
    parser.add_argument("username")
    parser.add_argument("--role", choices=["admin", "viewer"], default="viewer")
    parser.add_argument("--email", default=None)
    args = parser.parse_args()

    password = getpass.getpass("Mật khẩu: ")
    if len(password) < 6 or password != getpass.getpass("Nhập lại mật khẩu: "):
        sys.exit("Mật khẩu không khớp hoặc ngắn hơn 6 ký tự")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == args.username).first():
            sys.exit(f"Tài khoản '{args.username}' đã tồn tại")
        db.add(User(username=args.username, password_hash=get_password_hash(password),
                    email=args.email, role=args.role))
        db.commit()
        print(f"Đã tạo tài khoản '{args.username}' (role={args.role})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
