"""DNS resolver helper for Polymarket edge IPs (protects against ISP DNS poisoning/sinkholes)."""
import socket
import logging

logger = logging.getLogger(__name__)

POLYMARKET_EDGE_IPS = ["104.18.34.205", "172.64.153.51"]
_installed = False


def enable_polymarket_edge_resolver():
    """Patches socket.getaddrinfo so any polymarket.com domain resolves directly to Cloudflare edge IPs."""
    global _installed
    if _installed:
        return
    orig_getaddrinfo = socket.getaddrinfo

    def patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if isinstance(host, str) and "polymarket.com" in host:
            # Resolve directly to primary Cloudflare edge IP
            return orig_getaddrinfo(POLYMARKET_EDGE_IPS[0], port, family, type, proto, flags)
        return orig_getaddrinfo(host, port, family, type, proto, flags)

    socket.getaddrinfo = patched_getaddrinfo
    _installed = True
    logger.info("Enabled Polymarket Cloudflare edge DNS resolver.")
