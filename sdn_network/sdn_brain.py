from ryu.app import simple_switch_13
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER
from ryu.controller.handler import set_ev_cls

class SDNBrain(simple_switch_13.SimpleSwitch13):
    def __init__(self, *args, **kwargs):
        super(SDNBrain, self).__init__(*args, **kwargs)
        self.logger.info("SDN Brain Controller - San sang nhan lenh tu FastAPI!")

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        super(SDNBrain, self).switch_features_handler(ev)
        datapath = ev.msg.datapath
        self.logger.info(f"Switch {datapath.id} da ket noi thanh cong.")