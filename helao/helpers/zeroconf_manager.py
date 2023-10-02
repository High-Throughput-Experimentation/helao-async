"""Zeroconf service broadcast class used by HELAO servers

Service properties will include instrument tag and a broader group tag. The group tag
will designate service resources that may be shared across instruments.

"""

import socket
from zeroconf import IPVersion, ServiceInfo, Zeroconf


class ZeroConfManager:
    def __init__(self, server_name: str, server_host: str, server_port: int):
        self.server_name = server_name
        self.server_host = server_host
        self.server_port = server_port
        
        props = {'instrument': socket.gethostname(), 'group': None}
        info = ServiceInfo(
            "_http._tcp.local.",
            "Paul's Test Web Site._http._tcp.local.",
            addresses=[socket.inet_aton("127.0.0.1")],
            port=80,
            properties=props,
            server="ash-2.local.",
        )

zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
print("Registration of a service, press Ctrl-C to exit...")
zeroconf.register_service(info)
try:
    while True:
        sleep(0.1)
except KeyboardInterrupt:
    pass
finally:
    print("Unregistering...")
    zeroconf.unregister_service(info)
    zeroconf.close()


