import os
import signal
import sys
import threading
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel



TRUNK_BW = float(os.environ.get('SDN_LINK_CAPACITY_MBPS', '50'))
class EnterpriseTopo(Topo):
    """
            s3            s3: switch dự phòng, tạo đường thứ hai s1 -> s3 -> s2
           /  \\
    h1 -- s1 -- s2 -- h3
    h2 --/        \\-- h4
    Link mới luôn thêm SAU CÙNG để số hiệu port cũ không đổi (QoS cấu hình theo port):
      s1: eth1=s2, eth2=h1, eth3=h2, eth4=s3    s2: eth1=s1, eth2=h3, eth3=h4, eth4=s3
      s3: eth1=s1, eth2=s2
    """
    def build(self):
        s1 = self.addSwitch('s1', cls=OVSKernelSwitch, protocols='OpenFlow13')
        s2 = self.addSwitch('s2', cls=OVSKernelSwitch, protocols='OpenFlow13')
        s3 = self.addSwitch('s3', cls=OVSKernelSwitch, protocols='OpenFlow13')

        h1 = self.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')
        h2 = self.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02')
        h3 = self.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:00:03')
        h4 = self.addHost('h4', ip='10.0.0.4/24', mac='00:00:00:00:00:04')

        self.addLink(s1, s2, cls=TCLink, bw=TRUNK_BW)
        self.addLink(h1, s1)
        self.addLink(h2, s1)
        self.addLink(h3, s2)
        self.addLink(h4, s2)
        self.addLink(s1, s3, cls=TCLink, bw=TRUNK_BW)
        self.addLink(s3, s2, cls=TCLink, bw=TRUNK_BW)


def run(use_cli=True):
    setLogLevel('info')
    topo = EnterpriseTopo()
    net = Mininet(topo=topo,
                  controller=lambda name: RemoteController(name, ip='127.0.0.1', port=6653))
    net.start()
    if use_cli:
        CLI(net)
    else:
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        print("*** Mininet dang chay o che do --no-cli, gui SIGTERM de dung")
        while not stop.wait(1):
            pass
    net.stop()


if __name__ == '__main__':
    run(use_cli='--no-cli' not in sys.argv)
