"""Pure endpoint validation; no DNS lookups, socket access or UI dependencies."""
from dataclasses import dataclass
import ipaddress

@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int

    @classmethod
    def parse(cls, host, port):
        host = str(host).strip().lower().rstrip('.')
        if host.startswith('[') and host.endswith(']'):
            host = host[1:-1]
        if not host:
            raise ValueError('ReStim host must not be empty')
        try:
            port = int(str(port).strip())
        except (ValueError, TypeError):
            raise ValueError('ReStim port must be an integer') from None
        if not 1 <= port <= 65535:
            raise ValueError('ReStim port must be from 1 to 65535')
        try:
            address = ipaddress.ip_address(host)
            if address.is_loopback or (getattr(address, 'ipv4_mapped', None) and address.ipv4_mapped.is_loopback):
                host = 'loopback'
            else:
                host = str(address)
        except ValueError:
            if host == 'localhost':
                host = 'loopback'
        return cls(host, port)


def validate_output_endpoints(primary_host, primary_port, prostate_host, prostate_port):
    primary = Endpoint.parse(primary_host, primary_port)
    prostate = Endpoint.parse(prostate_host, prostate_port)
    if primary == prostate:
        raise ValueError(
            'Primary and Prostate point to the same ReStim destination. '
            'They send different command streams and need separate ports or hosts. '
            'For example: Primary 12346; Prostate 12350.')
    return primary, prostate
