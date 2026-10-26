from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Cấu hình đọc từ biến môi trường hoặc file backend/.env"""
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Đường dẫn tuyệt đối để không phụ thuộc thư mục đang chạy lệnh
    DATABASE_URL: str = f"sqlite:///{(BACKEND_DIR / 'sdn.db').as_posix()}"

    RYU_URL: str = "http://192.168.179.130:8080"
    RYU_TIMEOUT: float = 5.0

    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Chu kỳ đồng bộ luật từ DB xuống switch (giây). Chỉ cài bù phần thiếu nên chạy dày được;
    # đây cũng là khoảng thời gian tối đa mạng chạy KHÔNG có firewall/QoS sau khi Ryu/Mininet khởi động lại
    SYNC_INTERVAL_SECONDS: int = 5


settings = Settings()
