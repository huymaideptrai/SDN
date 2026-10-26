"""Nâng cấp schema tối thiểu cho DB đã tồn tại (dự án chưa dùng Alembic; create_all không thêm cột)."""
from sqlalchemy import inspect, text

# (bảng, cột, DDL thêm cột)
_COLUMNS = [
    ("qos_profiles", "direction", "ALTER TABLE qos_profiles ADD COLUMN direction VARCHAR NOT NULL DEFAULT 'ingress'"),
]


def upgrade(engine) -> list:
    """Thêm các cột còn thiếu. Trả về danh sách cột đã thêm."""
    added = []
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, column, ddl in _COLUMNS:
            if table not in tables:
                continue  # bảng mới sẽ do create_all tạo đủ cột
            if column not in {c["name"] for c in inspector.get_columns(table)}:
                conn.execute(text(ddl))
                added.append(f"{table}.{column}")
    return added
