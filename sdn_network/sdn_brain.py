"""SDN Brain - Ryu controller: định tuyến theo topology + cân bằng tải theo mức sử dụng link.

Pipeline OpenFlow 1.3 (phải khớp với backend/app/services/sdn_rules.py):
  Table 0 QOS_IN    : QoS chiều vào (meter theo in_port, backend cài) -> goto 1
  Table 1 FIREWALL  : DROP / ALLOW(goto 2) do backend cài; mặc định goto 2
  Table 2 FORWARD   : luật định tuyến do controller cài (ghi metadata = port ra) -> goto 3;
                      table-miss -> controller
  Table 3 EGRESS    : metadata=P -> output P; QoS chiều ra (meter + output P, backend cài)

Không dùng MAC learning + flood như simple_switch: topology có vòng (s1-s2-s3) sẽ gây bão broadcast.
Broadcast/ARP do controller phát ra các port biên (port nối host), không bao giờ ra port trunk.
Mỗi flow IPv4 (5-tuple) được gán một đường; nếu một link quá tải, controller chuyển bớt flow sang
đường còn trống (kiểm tra mỗi REBALANCE_INTERVAL giây).
"""
import json
import os
import time

from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, DEAD_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.lib import hub
from ryu.lib.packet import arp, ether_types, ethernet, ipv4, packet, tcp, udp
from ryu.ofproto import ofproto_v1_3
from ryu.topology import event as topo_event
from webob import Response

QOS_IN_TABLE = 0
FIREWALL_TABLE = 1
FORWARD_TABLE = 2
EGRESS_TABLE = 3

ROUTE_COOKIE_BASE = 0x3 << 32
EGRESS_COOKIE_BASE = 0x4 << 32
COOKIE_KIND_MASK = 0xFFFFFFFF << 32
METADATA_MASK = 0xFFFFFFFF

FLOW_IDLE_TIMEOUT = 10          # giây: flow không còn gói thì tự xoá
STATS_INTERVAL = 2              # giây: chu kỳ đọc thống kê port / flow
REBALANCE_INTERVAL = 5          # giây: chu kỳ xét chuyển flow sang đường khác
# Dung lượng link trunk; phải khớp TRUNK_BW của custom_topology.py (cả hai đọc cùng biến môi trường)
LINK_CAPACITY_MBPS = float(os.environ.get('SDN_LINK_CAPACITY_MBPS', '50'))
RATE_SMOOTHING = 0.5            # làm mượt tốc độ flow (thống kê flow của OVS cập nhật trễ, số đo bị giật)
MIN_SAMPLE_GAP = 1.5            # giây: bỏ mẫu thống kê port quá sát nhau
# Thống kê flow của OVS chỉ cập nhật ~1 lần/giây -> cửa sổ đo ngắn sai lệch lớn (đã thấy 58 Mbps
# cho flow bị QoS giới hạn 20 Mbps). Đo tốc độ flow trên cửa sổ dài hơn.
FLOW_SAMPLE_GAP = 4.0
REBALANCE_UTIL = 0.6            # chỉ cân bằng khi link nóng nhất vượt 60% dung lượng danh định
                                # (TCLink/HTB trong VM chỉ đạt ~70% bw đặt khi bão hoà -> ngưỡng 70% sát mép)
HYSTERESIS_MBPS = 0.1 * LINK_CAPACITY_MBPS  # chỉ chuyển khi đường mới tốt hơn rõ rệt, tránh dao động
MAX_PATH_HOPS = 4
REINSTALL_GUARD = 1.0           # giây: không cài lại luật vừa cài (packet-in dồn ứ sẽ reset bộ đếm flow)
API_INSTANCE = 'sdn_brain_app'


class SDNBrain(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {'wsgi': WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(SDNBrain, self).__init__(*args, **kwargs)
        self.datapaths = {}            # dpid -> datapath
        self.ports = {}                # dpid -> set(port_no)
        self.adj = {}                  # dpid -> {neighbor_dpid: port_no ra phía neighbor}
        self.trunk = set()             # (dpid, port_no) nối switch-switch
        self.hosts = {}                # mac -> (dpid, port_no)
        self.host_ips = {}             # mac -> ipv4
        self.flows = {}                # flow_id -> thông tin flow đã định tuyến
        self.flow_by_key = {}          # khoá 5-tuple -> flow_id
        self.next_flow_id = 1
        self.port_samples = {}         # (dpid, port) -> (time, tx_bytes)
        self.port_rate = {}            # (dpid, port) -> Mbps (chiều ra)
        self.flow_samples = {}         # flow_id -> (time, byte_count)
        self.reroute_log = []          # nhật ký chuyển đường gần đây (KHÔNG đặt tên self.events: trùng hàng đợi sự kiện của RyuApp)
        self.started = time.time()
        self._cpu_prev = None
        self._proc_prev = {}

        kwargs['wsgi'].register(BrainRest, {API_INSTANCE: self})
        hub.spawn(self._monitor)
        hub.spawn(self._rebalance_loop)
        self.logger.info("SDN Brain Controller - dinh tuyen + can bang tai (capacity %.0f Mbps)", LINK_CAPACITY_MBPS)

    # ------------------------------------------------------------------ Kết nối switch

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        dp = ev.msg.datapath
        parser, ofp = dp.ofproto_parser, dp.ofproto
        # Xoá luật cũ còn sót từ lần chạy trước (pipeline có thể đã đổi)
        dp.send_msg(parser.OFPFlowMod(datapath=dp, table_id=ofp.OFPTT_ALL, command=ofp.OFPFC_DELETE,
                                      out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY))
        self._add(dp, QOS_IN_TABLE, 0, parser.OFPMatch(), [parser.OFPInstructionGotoTable(FIREWALL_TABLE)])
        self._add(dp, FIREWALL_TABLE, 0, parser.OFPMatch(), [parser.OFPInstructionGotoTable(FORWARD_TABLE)])
        self._add(dp, FORWARD_TABLE, 0, parser.OFPMatch(),
                  [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS,
                                                [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)])])
        dp.send_msg(parser.OFPPortDescStatsRequest(dp, 0))
        self.logger.info("Switch %s da ket noi thanh cong.", dp.id)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def state_change_handler(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[dp.id] = dp
        elif ev.state == DEAD_DISPATCHER and dp.id in self.datapaths:
            del self.datapaths[dp.id]
            self.ports.pop(dp.id, None)
            for fid in [f for f, info in self.flows.items() if dp.id in info['path']]:
                self._forget_flow(fid)

    @set_ev_cls(ofp_event.EventOFPPortDescStatsReply, MAIN_DISPATCHER)
    def port_desc_handler(self, ev):
        dp = ev.msg.datapath
        ports = {p.port_no for p in ev.msg.body if p.port_no < dp.ofproto.OFPP_MAX}
        self.ports[dp.id] = ports
        for port_no in ports:
            self._install_egress(dp, port_no)

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def port_status_handler(self, ev):
        dp, port_no = ev.msg.datapath, ev.msg.desc.port_no
        if port_no >= dp.ofproto.OFPP_MAX:
            return
        if ev.msg.reason == dp.ofproto.OFPPR_DELETE:
            self.ports.get(dp.id, set()).discard(port_no)
        else:
            self.ports.setdefault(dp.id, set()).add(port_no)
            self._install_egress(dp, port_no)

    def _install_egress(self, dp, port_no):
        parser = dp.ofproto_parser
        self._add(dp, EGRESS_TABLE, 1, parser.OFPMatch(metadata=(port_no, METADATA_MASK)),
                  [parser.OFPInstructionActions(dp.ofproto.OFPIT_APPLY_ACTIONS, [parser.OFPActionOutput(port_no)])],
                  cookie=EGRESS_COOKIE_BASE + port_no)

    # ------------------------------------------------------------------ Topology

    @set_ev_cls(topo_event.EventLinkAdd)
    def link_add_handler(self, ev):
        src, dst = ev.link.src, ev.link.dst
        self.adj.setdefault(src.dpid, {})[dst.dpid] = src.port_no
        self.trunk.add((src.dpid, src.port_no))
        self.trunk.add((dst.dpid, dst.port_no))
        # Host bị học nhầm trên port trunk (trước khi phát hiện link) -> xoá
        for mac in [m for m, loc in self.hosts.items() if loc in self.trunk]:
            del self.hosts[mac]

    @set_ev_cls(topo_event.EventLinkDelete)
    def link_delete_handler(self, ev):
        src, dst = ev.link.src, ev.link.dst
        self.adj.get(src.dpid, {}).pop(dst.dpid, None)
        self.trunk.discard((src.dpid, src.port_no))
        self.trunk.discard((dst.dpid, dst.port_no))
        # Flow đi qua link đã mất -> xoá để packet-in kế tiếp chọn đường khác
        for fid in [f for f, info in self.flows.items() if (src.dpid, dst.dpid) in self._path_links(info['path'])]:
            self._delete_flow_everywhere(fid)

    def _paths(self, src, dst):
        """Mọi đường đơn (không lặp) từ switch src tới dst, tối đa MAX_PATH_HOPS switch"""
        if src == dst:
            return [[src]]
        result, stack = [], [(src, [src])]
        while stack:
            node, path = stack.pop()
            for nxt in sorted(self.adj.get(node, {})):
                if nxt in path or len(path) >= MAX_PATH_HOPS:
                    continue
                if nxt == dst:
                    result.append(path + [nxt])
                else:
                    stack.append((nxt, path + [nxt]))
        return sorted(result, key=len)

    @staticmethod
    def _path_links(path):
        return list(zip(path, path[1:]))

    def _flow_rate(self, info):
        """Tốc độ flow đáng tin cậy (Mbps).
        Bộ đếm luật của OVS tính cả gói mà meter QoS chiều vào (bảng 0) sau đó huỷ -> phản ánh lưu lượng
        TRƯỚC QoS. Bộ đếm TX của port ra chặng đầu chỉ tính gói thật sự gửi đi -> dùng làm trần."""
        path = info['path']
        out_port = self.adj.get(path[0], {}).get(path[1]) if len(path) > 1 else info['dst_port']
        port_rate = self.port_rate.get((path[0], out_port))
        return min(info['rate'], port_rate) if port_rate is not None else info['rate']

    def _link_load(self, a, b):
        port = self.adj.get(a, {}).get(b)
        return self.port_rate.get((a, port), 0.0) if port is not None else 0.0

    def _bottleneck(self, path, extra=0.0, exclude=None):
        """Tải lớn nhất trên các link của path (Mbps); exclude: flow không tính vào tải"""
        loads = []
        for a, b in self._path_links(path):
            load = self._link_load(a, b)
            if exclude is not None and (a, b) in self._path_links(exclude['path']):
                load = max(load - self._flow_rate(exclude), 0.0)
            loads.append(load + extra)
        return max(loads) if loads else 0.0

    # ------------------------------------------------------------------ Packet-in

    def _is_edge(self, dpid, port_no):
        return (dpid, port_no) not in self.trunk

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        dp = msg.datapath
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None or eth.ethertype in (ether_types.ETH_TYPE_LLDP, ether_types.ETH_TYPE_IPV6):
            return  # LLDP do app topology xử lý; lab chỉ dùng IPv4

        if self._is_edge(dp.id, in_port) and not eth.src.startswith('33:33'):
            self.hosts[eth.src] = (dp.id, in_port)
            a = pkt.get_protocol(arp.arp)
            ip = pkt.get_protocol(ipv4.ipv4)
            if a:
                self.host_ips[eth.src] = a.src_ip
            elif ip:
                self.host_ips[eth.src] = ip.src

        dst_loc = self.hosts.get(eth.dst)
        if dst_loc is None or eth.dst == 'ff:ff:ff:ff:ff:ff':
            self._flood_edges(dp.id, in_port, msg.data)
            return

        src_sw, (dst_sw, dst_port) = dp.id, dst_loc
        ip = pkt.get_protocol(ipv4.ipv4)
        if ip is None:
            # Không phải IPv4 (VD ARP unicast): định tuyến theo MAC đích trên đường ngắn nhất.
            # PHẢI kèm eth_type: luật chỉ theo eth_dst sẽ bắt luôn gói IPv4 -> flow IP không còn
            # packet-in nên không được theo dõi / cân bằng tải.
            path = (self._paths(src_sw, dst_sw) or [None])[0]
            if path is None:
                return
            match = {'eth_type': eth.ethertype, 'eth_dst': eth.dst}
            self._install_path(path, dst_port, match, priority=5, cookie=ROUTE_COOKIE_BASE)
            self._forward(dp, in_port, path, dst_port, msg.data)
            return
        else:
            key, match = self._flow_key(ip, pkt)
            fid = self.flow_by_key.get(key)
            if fid is not None and src_sw in self.flows[fid]['path']:
                # Flow đã có đường nhưng gói tới trước khi luật được cài -> tiếp tục đường cũ từ switch này
                info = self.flows[fid]
                full = info['path']
                path = full[full.index(src_sw):]
                if time.time() - info.get('installed_at', 0) > REINSTALL_GUARD:
                    self._install_path(path, dst_port, match, priority=info['priority'], cookie=ROUTE_COOKIE_BASE + fid,
                                       idle=FLOW_IDLE_TIMEOUT, notify_first=(path == full))
                    info['installed_at'] = time.time()
                self._forward(dp, in_port, path, dst_port, msg.data)
                return
            else:
                candidates = self._paths(src_sw, dst_sw)
                if not candidates:
                    return
                # Flow mới: chọn đường có link nóng nhất ít tải nhất, hoà thì đường ngắn hơn
                path = min(candidates, key=lambda p: (round(self._bottleneck(p), 1), len(p)))
                fid = self.next_flow_id
                self.next_flow_id += 1
                # Gói phân mảnh: luật không có cổng L4 -> priority thấp hơn luật 5-tuple
                priority = 10 if any(k in match for k in ('tcp_src', 'udp_src')) or match['ip_proto'] not in (6, 17) else 9
                self.flows[fid] = {'id': fid, 'key': key, 'match': match, 'path': path, 'dst_port': dst_port,
                                   'src_mac': eth.src, 'dst_mac': eth.dst, 'created': time.time(), 'rate': 0.0,
                                   'moves': 0, 'priority': priority, 'installed_at': time.time()}
                self.flow_by_key[key] = fid
                self._install_path(path, dst_port, match, priority=priority, cookie=ROUTE_COOKIE_BASE + fid,
                                   idle=FLOW_IDLE_TIMEOUT, notify_first=True)

        self._forward(dp, in_port, path, dst_port, msg.data)

    def _forward(self, dp, in_port, path, dst_port, data):
        """Gửi gói của packet-in ra port chặng đầu tiên.
        KHÔNG dùng OFPP_TABLE (đưa lại vào pipeline): gói không khớp luật vừa cài (VD mảnh IP) sẽ lại
        table-miss -> packet-in -> nảy qua lại switch/controller vô hạn. Gói đã đi qua bảng QoS vào và
        firewall trước khi table-miss nên chỉ bỏ qua meter chiều ra cho riêng gói này."""
        out_port = self.adj[path[0]][path[1]] if len(path) > 1 else dst_port
        parser, ofp = dp.ofproto_parser, dp.ofproto
        dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=ofp.OFP_NO_BUFFER, in_port=in_port,
                                        actions=[parser.OFPActionOutput(out_port)], data=data))

    @staticmethod
    def _flow_key(ip, pkt):
        match = {'eth_type': 0x0800, 'ipv4_src': ip.src, 'ipv4_dst': ip.dst, 'ip_proto': ip.proto}
        # Gói phân mảnh (cờ MF hoặc offset != 0): mảnh sau không có header L4, Ryu sẽ đọc nhầm payload
        # thành cổng; OVS cũng không so khớp cổng với mảnh -> chỉ định tuyến theo (src, dst, proto)
        if ip.flags & 0x1 or ip.offset:
            return tuple(sorted(match.items())) + (('frag', True),), match
        l4 = pkt.get_protocol(tcp.tcp) or pkt.get_protocol(udp.udp)
        if isinstance(l4, tcp.tcp):
            match.update(tcp_src=l4.src_port, tcp_dst=l4.dst_port)
        elif isinstance(l4, udp.udp):
            match.update(udp_src=l4.src_port, udp_dst=l4.dst_port)
        return tuple(sorted(match.items())), match

    def _flood_edges(self, src_dpid, src_port, data):
        """Phát gói tới mọi port biên (nối host) của mọi switch, trừ port nguồn -> không có vòng lặp"""
        for dpid, dp in self.datapaths.items():
            parser, ofp = dp.ofproto_parser, dp.ofproto
            out_ports = [p for p in self.ports.get(dpid, ()) if self._is_edge(dpid, p) and (dpid, p) != (src_dpid, src_port)]
            if not out_ports:
                continue
            dp.send_msg(parser.OFPPacketOut(datapath=dp, buffer_id=ofp.OFP_NO_BUFFER, in_port=ofp.OFPP_CONTROLLER,
                                            actions=[parser.OFPActionOutput(p) for p in out_ports], data=data))

    def _install_path(self, path, dst_port, match_fields, priority, cookie, idle=30, notify_first=False):
        """Cài luật FORWARD trên mọi switch của path: ghi metadata = port ra rồi goto EGRESS.
        Cài từ cuối đường về đầu để gói không tới switch tiếp theo trước khi switch đó có luật."""
        hops = [(path[i], self.adj[path[i]][path[i + 1]]) for i in range(len(path) - 1)] + [(path[-1], dst_port)]
        for index, (dpid, out_port) in reversed(list(enumerate(hops))):
            dp = self.datapaths.get(dpid)
            if dp is None:
                continue
            parser, ofp = dp.ofproto_parser, dp.ofproto
            inst = [parser.OFPInstructionWriteMetadata(out_port, METADATA_MASK),
                    parser.OFPInstructionGotoTable(EGRESS_TABLE)]
            flags = ofp.OFPFF_SEND_FLOW_REM if (notify_first and index == 0) else 0
            self._add(dp, FORWARD_TABLE, priority, parser.OFPMatch(**match_fields), inst,
                      cookie=cookie, idle=idle, flags=flags)

    def _add(self, dp, table, priority, match, inst, cookie=0, idle=0, flags=0):
        dp.send_msg(dp.ofproto_parser.OFPFlowMod(datapath=dp, table_id=table, priority=priority, match=match,
                                                 instructions=inst, cookie=cookie, idle_timeout=idle, flags=flags))

    def _delete_cookie(self, dp, cookie):
        parser, ofp = dp.ofproto_parser, dp.ofproto
        dp.send_msg(parser.OFPFlowMod(datapath=dp, table_id=FORWARD_TABLE, command=ofp.OFPFC_DELETE,
                                      cookie=cookie, cookie_mask=0xFFFFFFFFFFFFFFFF,
                                      out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY))

    def _forget_flow(self, fid):
        info = self.flows.pop(fid, None)
        if info:
            self.flow_by_key.pop(info['key'], None)
        self.flow_samples.pop(fid, None)

    def _delete_flow_everywhere(self, fid):
        info = self.flows.get(fid)
        if info:
            for dpid in info['path']:
                dp = self.datapaths.get(dpid)
                if dp:
                    self._delete_cookie(dp, ROUTE_COOKIE_BASE + fid)
        self._forget_flow(fid)

    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def flow_removed_handler(self, ev):
        cookie = ev.msg.cookie
        if cookie & COOKIE_KIND_MASK != ROUTE_COOKIE_BASE or ev.msg.table_id != FORWARD_TABLE:
            return
        fid = cookie - ROUTE_COOKIE_BASE
        info = self.flows.get(fid)
        # Chỉ xoá khi luật ở switch đầu đường hết hạn (các switch sau tự hết hạn idle)
        if info and info['path'][0] == ev.msg.datapath.id:
            self._delete_flow_everywhere(fid)

    # ------------------------------------------------------------------ Thống kê & cân bằng tải

    def _monitor(self):
        while True:
            for dp in list(self.datapaths.values()):
                parser, ofp = dp.ofproto_parser, dp.ofproto
                dp.send_msg(parser.OFPPortStatsRequest(dp, 0, ofp.OFPP_ANY))
                dp.send_msg(parser.OFPFlowStatsRequest(dp, 0, FORWARD_TABLE, ofp.OFPP_ANY, ofp.OFPG_ANY,
                                                       ROUTE_COOKIE_BASE, COOKIE_KIND_MASK))
            hub.sleep(STATS_INTERVAL)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_handler(self, ev):
        now, dpid = time.time(), ev.msg.datapath.id
        for stat in ev.msg.body:
            key = (dpid, stat.port_no)
            prev = self.port_samples.get(key)
            # Bỏ mẫu quá sát nhau (các app khác như ofctl_rest cũng gửi yêu cầu thống kê)
            if prev and now - prev[0] < MIN_SAMPLE_GAP:
                continue
            if prev and stat.tx_bytes >= prev[1]:
                self.port_rate[key] = (stat.tx_bytes - prev[1]) * 8 / ((now - prev[0]) * 1e6)
            self.port_samples[key] = (now, stat.tx_bytes)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_handler(self, ev):
        now, dpid = time.time(), ev.msg.datapath.id
        for stat in ev.msg.body:
            if stat.cookie & COOKIE_KIND_MASK != ROUTE_COOKIE_BASE or stat.table_id != FORWARD_TABLE:
                continue
            fid = stat.cookie - ROUTE_COOKIE_BASE
            info = self.flows.get(fid)
            if not info or info['path'][0] != dpid:  # đo tại switch đầu đường
                continue
            prev = self.flow_samples.get(fid)
            if prev and now - prev[0] < FLOW_SAMPLE_GAP:
                continue
            if prev and stat.byte_count >= prev[1]:
                sample = (stat.byte_count - prev[1]) * 8 / ((now - prev[0]) * 1e6)
                info['rate'] = sample if info['rate'] == 0 else \
                    RATE_SMOOTHING * sample + (1 - RATE_SMOOTHING) * info['rate']
            self.flow_samples[fid] = (now, stat.byte_count)

    def _rebalance_loop(self):
        while True:
            hub.sleep(REBALANCE_INTERVAL)
            try:
                self._rebalance_once()
            except Exception:  # vòng lặp nền không được chết vì một lỗi
                self.logger.exception("Loi khi can bang tai")

    def _rebalance_once(self):
        """Chuyển tối đa 1 flow mỗi chu kỳ từ đường có link quá tải sang đường tốt hơn rõ rệt"""
        threshold = REBALANCE_UTIL * LINK_CAPACITY_MBPS
        best = None
        for info in sorted(self.flows.values(), key=lambda f: -self._flow_rate(f)):
            rate = self._flow_rate(info)
            if rate <= 0.5:
                continue
            current = self._bottleneck(info['path'])
            if current < threshold:
                continue
            for alt in self._paths(info['path'][0], info['path'][-1]):
                if alt == info['path']:
                    continue
                after = self._bottleneck(alt, extra=rate, exclude=info)
                gain = current - after
                if gain > HYSTERESIS_MBPS and (best is None or gain > best[0]):
                    best = (gain, info, alt, current, after)
            if best:
                break
        if not best:
            return
        gain, info, alt, before, after = best
        old = info['path']
        fid = info['id']
        rate = self._flow_rate(info)
        self._install_path(alt, info['dst_port'], info['match'], priority=info['priority'], cookie=ROUTE_COOKIE_BASE + fid,
                           idle=FLOW_IDLE_TIMEOUT, notify_first=True)
        info['installed_at'] = time.time()
        for dpid in set(old) - set(alt):
            dp = self.datapaths.get(dpid)
            if dp:
                self._delete_cookie(dp, ROUTE_COOKIE_BASE + fid)
        # Ước lượng ngay tải mới để chu kỳ sau không chuyển nhầm trước khi có số đo mới
        for a, b in self._path_links(old):
            key = (a, self.adj[a][b])
            self.port_rate[key] = max(self.port_rate.get(key, 0.0) - rate, 0.0)
        for a, b in self._path_links(alt):
            key = (a, self.adj[a][b])
            self.port_rate[key] = self.port_rate.get(key, 0.0) + rate
        info['path'] = alt
        info['moves'] += 1
        self.reroute_log.append({'time': time.time(), 'flow_id': fid, 'flow': self._flow_label(info),
                            'from': old, 'to': alt, 'rate_mbps': round(rate, 2),
                            'bottleneck_before': round(before, 2), 'bottleneck_after': round(after, 2)})
        self.reroute_log = self.reroute_log[-20:]
        self.logger.info("Can bang tai: flow %s chuyen %s -> %s", fid, old, alt)

    def _flow_label(self, info):
        m = info['match']
        proto = {1: 'ICMP', 6: 'TCP', 17: 'UDP'}.get(m.get('ip_proto'), str(m.get('ip_proto')))
        sport = m.get('tcp_src', m.get('udp_src'))
        dport = m.get('tcp_dst', m.get('udp_dst'))
        src = f"{m['ipv4_src']}:{sport}" if sport else m['ipv4_src']
        dst = f"{m['ipv4_dst']}:{dport}" if dport else m['ipv4_dst']
        return f"{proto} {src} -> {dst}"

    # ------------------------------------------------------------------ Dữ liệu cho REST API

    def routing_snapshot(self):
        links = []
        for a, neighbors in sorted(self.adj.items()):
            for b, port in sorted(neighbors.items()):
                rate = self.port_rate.get((a, port), 0.0)
                links.append({'src': a, 'src_port': port, 'dst': b, 'tx_mbps': round(rate, 2),
                              'utilization': round(rate / LINK_CAPACITY_MBPS, 3)})
        flows = []
        now = time.time()
        for info in sorted(self.flows.values(), key=lambda f: -self._flow_rate(f)):
            m = info['match']
            flows.append({'id': info['id'], 'label': self._flow_label(info), 'src_ip': m['ipv4_src'],
                          'dst_ip': m['ipv4_dst'], 'path': info['path'], 'rate_mbps': round(self._flow_rate(info), 2),
                          'age_s': int(now - info['created']), 'moves': info['moves']})
        return {'capacity_mbps': LINK_CAPACITY_MBPS, 'rebalance_threshold': REBALANCE_UTIL,
                'links': links, 'flows': flows, 'events': list(reversed(self.reroute_log))}

    def system_snapshot(self):
        return SystemStats.collect(self)


class SystemStats(object):
    """Số liệu của máy chủ chạy Ryu/Mininet đọc từ /proc (không cần thư viện ngoài)"""

    @staticmethod
    def _cpu_times():
        with open('/proc/stat') as f:
            values = [int(v) for v in f.readline().split()[1:]]
        idle = values[3] + values[4]  # idle + iowait
        return sum(values), idle

    @staticmethod
    def _proc_by_name(name):
        for pid in os.listdir('/proc'):
            if not pid.isdigit():
                continue
            try:
                with open('/proc/%s/comm' % pid) as f:
                    if f.read().strip() == name:
                        return int(pid)
            except (IOError, OSError):
                continue
        return None

    @staticmethod
    def _proc_stats(pid):
        with open('/proc/%d/stat' % pid) as f:
            fields = f.read().rsplit(')', 1)[1].split()
        cpu_ticks = int(fields[11]) + int(fields[12])  # utime + stime
        rss_kb = 0
        with open('/proc/%d/status' % pid) as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    rss_kb = int(line.split()[1])
        return cpu_ticks, rss_kb

    @classmethod
    def collect(cls, app):
        now = time.time()
        total, idle = cls._cpu_times()
        cpu_percent = None
        if app._cpu_prev:
            d_total, d_idle = total - app._cpu_prev[0], idle - app._cpu_prev[1]
            if d_total > 0:
                cpu_percent = round(100.0 * (d_total - d_idle) / d_total, 1)
        app._cpu_prev = (total, idle)

        mem = {}
        with open('/proc/meminfo') as f:
            for line in f:
                key, value = line.split(':', 1)
                mem[key] = int(value.split()[0]) * 1024
        disk = os.statvfs('/')
        with open('/proc/uptime') as f:
            uptime = float(f.read().split()[0])
        load1, load5, load15 = os.getloadavg()

        temps = []
        base = '/sys/class/thermal'
        if os.path.isdir(base):
            for zone in sorted(os.listdir(base)):
                path = os.path.join(base, zone, 'temp')
                if zone.startswith('thermal_zone') and os.path.exists(path):
                    try:
                        with open(path) as f:
                            temps.append({'sensor': zone, 'celsius': int(f.read()) / 1000.0})
                    except (IOError, OSError, ValueError):
                        pass

        ticks = os.sysconf('SC_CLK_TCK')
        processes = []
        for label, name in (('Ryu controller', 'ryu-manager'), ('Open vSwitch', 'ovs-vswitchd')):
            pid = os.getpid() if name == 'ryu-manager' else cls._proc_by_name(name)
            if pid is None:
                processes.append({'name': label, 'running': False})
                continue
            try:
                cpu_ticks, rss_kb = cls._proc_stats(pid)
            except (IOError, OSError):
                processes.append({'name': label, 'running': False})
                continue
            prev = app._proc_prev.get(name)
            p_cpu = None
            if prev and now > prev[0]:
                p_cpu = round(100.0 * (cpu_ticks - prev[1]) / ticks / (now - prev[0]), 1)
            app._proc_prev[name] = (now, cpu_ticks)
            processes.append({'name': label, 'running': True, 'pid': pid, 'cpu_percent': p_cpu,
                              'rss_bytes': rss_kb * 1024})

        return {
            'hostname': os.uname()[1],
            'cpu_count': os.cpu_count(),
            'cpu_percent': cpu_percent,
            'load_avg': [round(load1, 2), round(load5, 2), round(load15, 2)],
            'memory': {'total': mem.get('MemTotal', 0), 'available': mem.get('MemAvailable', 0)},
            'disk': {'total': disk.f_blocks * disk.f_frsize, 'free': disk.f_bavail * disk.f_frsize},
            'uptime_s': int(uptime),
            'controller_uptime_s': int(now - app.started),
            'temperatures': temps,
            'processes': processes,
        }


class BrainRest(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(BrainRest, self).__init__(req, link, data, **config)
        self.app = data[API_INSTANCE]

    @staticmethod
    def _json(data):
        return Response(content_type='application/json', charset='utf-8', body=json.dumps(data).encode('utf-8'))

    @route('sdn', '/sdn/routing', methods=['GET'])
    def routing(self, req, **kwargs):
        return self._json(self.app.routing_snapshot())

    @route('sdn', '/sdn/system', methods=['GET'])
    def system(self, req, **kwargs):
        return self._json(self.app.system_snapshot())
