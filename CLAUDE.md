# CLAUDE.md — SDN Project

## 1. Tổng quan
Web app quản trị mạng SDN (đồ án/lab): đăng nhập (admin/viewer), topology + lưu lượng theo port, firewall ALLOW/DROP, QoS (OpenFlow meter, chiều vào/ra), định tuyến + cân bằng tải theo tải link, tài nguyên phần cứng switch qua SNMP, quản lý người dùng + nhật ký.

```
React (Vite :5173) --HTTP/JWT--> FastAPI (:8000, SQLite) --REST--> Ryu (:8080: sdn_brain + ofctl_rest + rest_topology) --OpenFlow 1.3--> Mininet/OVS
                                        \--SNMP (UDP 161)--> switch thật (CPU/RAM/nhiệt độ)
```
- Backend + frontend chạy trên Windows; Ryu + Mininet chạy trên VM Ubuntu (mục 4). UI / thông báo lỗi / comment: tiếng Việt.

## 2. Module
| Thư mục | Vai trò |
|---|---|
| `backend/app/` | FastAPI: auth JWT + phân quyền, gọi Ryu REST, SNMP, SQLite, sync worker |
| `backend/tests/` | pytest (61 test): `FakeRyu` + collector SNMP giả + DB tạm — không cần Ryu/SNMP thật |
| `frontend/src/` | React 19 SPA: Login, Dashboard, Control (firewall/QoS/bảng flow), Settings (tài khoản, người dùng, thiết bị SNMP, nhật ký) |
| `sdn_network/` | Chạy trên VM: `sdn_brain.py` (Ryu app tự viết: định tuyến + cân bằng tải + REST `/sdn/*`), `custom_topology.py`, `restart_lab.sh` |

Topology Mininet: s1, s2, s3 (dự phòng); h1,h2@s1, h3,h4@s2 (10.0.0.1–4). Port: s1 eth1→s2 eth2→h1 eth3→h2 eth4→s3; s2 eth1→s1 eth2→h3 eth3→h4 eth4→s3; s3 eth1→s1 eth2→s2. Link trunk TCLink `SDN_LINK_CAPACITY_MBPS` (mặc định 50; HTB trong VM thực tế chỉ đạt ~35 Mbps khi bão hoà). Link mới luôn thêm SAU CÙNG để số port cũ không đổi (QoS cấu hình theo port).

## 3. Pipeline OpenFlow (backend `services/sdn_rules.py` và `sdn_brain.py` PHẢI khớp)
| Bảng | Nội dung | Ai cài |
|---|---|---|
| 0 QOS_IN | `in_port=P → METER:P, goto 1` (prio 100); mặc định goto 1; LLDP 65535 | backend / brain / Ryu topology |
| 1 FIREWALL | DROP (không action) / ALLOW (`goto 2`), prio 2–65534; mặc định goto 2 | backend / brain |
| 2 FORWARD | luật định tuyến theo flow: `write_metadata(port ra), goto 3`; table-miss → controller | brain |
| 3 EGRESS | `metadata=P → output P` (prio 1); QoS chiều ra `metadata=P → METER:1000+P, output P` (prio 100) | brain / backend |

- Cookie (32 bit cao = loại): 1 firewall (+policy.id), 2 QoS vào (+port), 3 định tuyến (+flow id), 4 output egress mặc định, 5 QoS ra (+port).
- Meter: vào = port, ra = 1000 + port. Meter phải có TRƯỚC flow tham chiếu nó. Burst = rate/2 (rate/10 làm TCP chỉ đạt ~50%).
- ALLOW không dùng `OUTPUT:NORMAL` (L2 learning của OVS gây bão broadcast vì topology có vòng).
- ofctl_rest là fire-and-forget: HTTP 200 không đảm bảo switch chấp nhận → kiểm chứng bằng `/stats/flow`, `/stats/meterconfig`.
- Ryu trả match tên cũ (`dl_type`, `nw_src`, `tp_src`, `metadata` dạng "P/mask"); dpid trong rest_topology là chuỗi hex 16 ký tự.

### sdn_brain (controller)
- Không flood: broadcast/ARP do controller phát ra các port biên (port không phải trunk). Luật MAC (ARP) PHẢI kèm `eth_type`, nếu không sẽ bắt luôn gói IPv4 → flow IP không được theo dõi.
- Flow IPv4 theo 5-tuple, chọn đường có link nóng nhất ít tải nhất; mỗi 5 s chuyển tối đa 1 flow khi link > 60% (`REBALANCE_UTIL`) và đường mới tốt hơn > 10% dung lượng.
- Gói phân mảnh IP: không đọc cổng L4 (Ryu đọc nhầm payload), luật (src,dst,proto) prio 9.
- Gửi gói packet-in bằng OUTPUT trực tiếp, KHÔNG dùng `OFPP_TABLE` (gói không khớp luật vừa cài sẽ nảy switch↔controller vô hạn — từng gây storm 2.2k packet-in/s).
- Không cài lại luật vừa cài < 1 s (packet-in dồn ứ reset bộ đếm). Tốc độ flow = min(flow stats, TX port ra chặng đầu) vì bộ đếm luật OVS tính cả gói meter bảng 0 sau đó huỷ.
- Không đặt thuộc tính `self.events` trong RyuApp (trùng hàng đợi sự kiện nội bộ).

## 4. Môi trường & lệnh
- Backend: Python 3.13 venv `backend/venv`, deps pin `backend/requirements.txt` (+ `requirements-dev.txt`): FastAPI, SQLAlchemy 2, Pydantic 2 + pydantic-settings, python-jose, passlib/bcrypt 4.0.1, httpx, pysnmp 7.1.
- Frontend: React 19, react-router 7, axios, recharts 3, Vite 8, ESLint 10 (JS thuần, không thư viện UI).
- Cấu hình: `backend/.env` (không commit; mẫu `.env.example`): SECRET_KEY, DATABASE_URL (mặc định `backend/sdn.db`), RYU_URL, CORS_ORIGINS, SYNC_INTERVAL_SECONDS (5). Frontend `VITE_API_URL`.
- VM: Ubuntu 24.04 `ubuntulab`, `192.168.179.130`, user `huyadmin`, SSH key `~/.ssh/id_ed25519`. Ryu 4.34 trong `~/ryu_env` (Python 3.9), Mininet 2.3.0, OVS 3.3.9. Bản chạy: `~/ryu/SDN_Project/`. `sudo` cần mật khẩu (hỏi người dùng, không lưu).
- File chạy trên VM phải LF (`.gitattributes`); script patch Python trên Windows phải ghi `newline="\n"`.

| Việc | Lệnh |
|---|---|
| Lab (VM) | `sudo bash ~/ryu/SDN_Project/restart_lab.sh` — tự `mn -c` → Ryu → Mininet (`--no-cli`) |
| Lệnh trong host Mininet | `sudo mnexec -a $(pgrep -f 'mininet:h1$') sh -c '<lệnh>'` |
| Backend | `cd backend; venv\Scripts\python -m uvicorn app.main:app --port 8000` (chạy nền: đặt `PYTHONUTF8=1`) |
| Tạo admin đầu tiên | `cd backend; venv\Scripts\python -m app.create_user <tên> --role admin` |
| Test backend | `cd backend; venv\Scripts\python -m pytest -q` |
| Frontend | `cd frontend; npm run dev` / `npm run lint` / `npm run build` |

**Thứ tự khởi động bắt buộc trên VM: `mn -c` → Ryu → Mininet.** Mininet chạy trước thì Ryu 4.34 ngừng gửi LLDP (link biến mất sau ~10 s). `mn -c` cũng kill `ryu-manager`; restart Ryu thì phải restart cả Mininet. Qua ssh: không `pkill -f ryu-manager` (giết luôn shell ssh); chạy nền bằng `setsid … < /dev/null > log 2>&1 &` và bọc `timeout`.

## 5. API (prefix, quyền)
- `/auth`: `POST /login` (form), `GET /me`, `POST /change-password`. **Không có đăng ký công khai** — tài khoản chỉ do admin tạo (`POST /api/users`) hoặc lệnh `create_user`.
- `/api/sdn` (đọc: mọi user): `switches`, `topology` (link kèm `source_port/target_port`), `flows/{dpid}` (`kind`: policy/qos/route/system), `policies`, `qos/{dpid}` (tốc độ + `qos_in`/`qos_out`), `qos/config/{dpid}`, `routing`, `devices` (OpenFlow), `system` (máy chạy controller, UI không dùng nữa).
- `/api/sdn` (ghi: admin): `POST flows`, `DELETE policies/{id}`, `DELETE flows/{dpid}`, `POST qos/config` (`direction`: ingress/egress/both), `DELETE qos/config/{dpid}/{port}?direction=`.
- `/api/devices`: `GET health` (mọi user; status ok/unreachable/error/not_configured); admin: `GET/PUT/DELETE snmp/{dpid}`, `POST snmp/{dpid}/test`.
- `/api` (admin): `users` (GET/POST/PATCH, `reset-password`), `audit-logs`.
- Lỗi Ryu: `RyuError` → 503/404/502, body có `detail`.

## 6. File quan trọng
- `backend/app/services/ryu_client.py` — `RyuSDNClient` (một `httpx.AsyncClient` dùng chung mỗi event loop; tạo client mỗi lời gọi tốn 0.2–0.9 s trên Windows), `get_ryu_client`.
- `backend/app/services/sdn_rules.py` — payload flow/meter, cookie, hằng số bảng.
- `backend/app/services/snmp_client.py` — `SnmpCollector` (MIB chuẩn trước, Cisco dự phòng), `HealthCache` (TTL 15 s, trả dữ liệu cũ + làm mới ở nền).
- `backend/app/services/state_lock.py` — `@with_switch_lock` cho mọi endpoint ghi cấu hình switch + `switch_state_lock()` cho sync worker.
- `backend/app/routers/` — `sdn.py`, `devices.py` (SNMP), `admin.py` (user, audit), `auth.py`.
- `backend/app/tasks/sync_worker.py` — mỗi 5 s cài BÙ firewall/QoS/meter thiếu trên switch (không cài lại cái đang có).
- `backend/app/models/models.py` — `users`, `audit_logs`, `flow_policies`, `qos_profiles` (`max_bw` kbps, `direction`), `switch_snmp` (community/khoá v3 lưu rõ trong SQLite, API không bao giờ trả lại). `migrations.py` thêm cột thiếu cho DB cũ (không có Alembic).
- Frontend: `api/` (axios, auth, format), `components/` (Layout, TopologyMap SVG bố cục cố định, BandwidthChart, NetworkPanels, SnmpSettings, ui, icons, FeedbackProvider), `pages/`.

## 7. Quy ước code
- Router mỏng → `sdn_rules` → `RyuSDNClient`. KHÔNG giữ transaction ghi SQLite qua `await` (Session đồng bộ chặn event loop → `database is locked`): commit trước, gọi Ryu, rồi kích hoạt/ghi audit.
- Mọi thao tác ghi có `AuditLog(user_id, action, dpid, details)` (không gắn switch: `dpid="-"`).
- Code chạy nền dùng `logging`, không `print` (print tiếng Việt ra stdout cp1252 làm chết worker).
- Frontend: hook + hàm fetch BÊN TRONG `useEffect` với cờ `active` (bỏ phản hồi cũ, tránh dữ liệu cũ đè mới), tải lại bằng `reloadKey`. CSS token trong `index.css`, primitives `components/ui.jsx`, `useToast()` / `useConfirm()` (`context/feedback.js`). Mỗi khối dữ liệu có loading / error (Thử lại) / empty. Không hiển thị số giả (`measured: false`, "—", "thiết bị không cung cấp").

## 8. Lưu ý khi sửa code / kiểm thử
- Đo tốc độ theo đồng hồ của switch (`duration_sec/nsec`), không theo giờ backend (từng lệch ~43%). Cửa sổ tối thiểu 2 s (nhiều client cùng poll).
- RX port đếm TRƯỚC meter chiều vào → "RX sau QoS" = meter in − drop. Meter chiều ra chạy trước khi gói rời port → TX đã là sau QoS.
- SNMP: mỗi lần đọc dùng `SnmpEngine` RIÊNG rồi `close_dispatcher()` — engine dùng chung + một thiết bị không phản hồi (ICMP port-unreachable trên Windows) làm mọi lần đọc song song thất bại và hỏng engine.
- Switch Mininet KHÔNG có CPU/RAM/nhiệt độ (OVS phần mềm, OpenFlow không có trường này) → thẻ "Phần cứng switch" hiện "Chưa cấu hình SNMP". Không trỏ switch thật trong DB tới simulator.
- Kiểm thử ghi trên hệ thống thật: chỉ đụng port/luật do test tạo, bấm nút theo đúng dòng; Dashboard poll liên tục nên không dùng `waitUntil: 'networkidle0'`. Kiểm thử SNMP bằng `snmpsim` (venv riêng, cần thêm `pysmi`; file `.snmprec` phải sắp OID tăng dần) trên bộ backend/frontend tách riêng (:8001/:5174, DB test).
- `backend/sdn.db` và `__pycache__` vẫn đang được git track (đã có `.gitignore` nhưng chưa `git rm --cached`).

## 9. Câu hỏi còn mở
- Có gỡ `sdn.db` / `__pycache__` khỏi git không? Commit lên `main` hay branch riêng?
- Có cần mã hoá community / khoá SNMPv3 trong DB không?
