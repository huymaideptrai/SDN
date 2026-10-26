import sqlite3
from sqlalchemy import create_engine, inspect
from app.models import migrations


def test_upgrade_adds_direction_column(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE qos_profiles (id INTEGER PRIMARY KEY, dpid VARCHAR NOT NULL, port_no INTEGER NOT NULL, "
                "max_bw INTEGER NOT NULL, description VARCHAR)")
    con.execute("INSERT INTO qos_profiles (dpid, port_no, max_bw) VALUES ('1', 2, 20000)")
    con.commit()
    con.close()

    engine = create_engine(f"sqlite:///{path}")
    assert migrations.upgrade(engine) == ["qos_profiles.direction"]
    assert "direction" in {c["name"] for c in inspect(engine).get_columns("qos_profiles")}
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT direction FROM qos_profiles").scalar() == "ingress"
    # Chạy lại không làm gì
    assert migrations.upgrade(engine) == []
