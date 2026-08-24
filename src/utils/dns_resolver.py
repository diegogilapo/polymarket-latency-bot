import socket
import urllib.request
import json
import ssl
import certifi
import aiohttp
from src.utils.logger import get_logger

logger = get_logger("DNSResolver")

# Pre-población de caché DNS para dominios clave de Polymarket y Exchanges
_DNS_CACHE = {
    "gamma-api.polymarket.com": "172.64.153.51",
    "clob.polymarket.com": "104.18.34.205",
    "data-api.polymarket.com": "172.64.153.51",
    "ws-subscriptions-clob.polymarket.com": "104.18.34.205",
    "polygon-rpc.com": "104.18.28.188",
    "polygon.llamarpc.com": "104.21.36.195",
    "rpc.ankr.com": "104.18.22.84",
    "1rpc.io": "104.21.49.208"
}

_orig_getaddrinfo = socket.getaddrinfo

def _doh_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    # 1. Si está en caché, usar directamente
    if host in _DNS_CACHE:
        ip = _DNS_CACHE[host]
        try:
            return _orig_getaddrinfo(ip, port, family, type, proto, flags)
        except Exception:
            pass

    # 2. Intentar resolución normal
    try:
        return _orig_getaddrinfo(host, port, family, type, proto, flags)
    except socket.gaierror:
        # 3. Fallback a DNS over HTTPS directo a las IPs 1.1.1.1 y 8.8.8.8 (Sin resolución previa)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        doh_endpoints = [
            (f"https://1.1.1.1/dns-query?name={host}&type=A", {"accept": "application/dns-json", "Host": "cloudflare-dns.com", "User-Agent": "Mozilla/5.0"}),
            (f"https://8.8.8.8/resolve?name={host}&type=A", {"accept": "application/json", "Host": "dns.google", "User-Agent": "Mozilla/5.0"})
        ]

        for url, headers in doh_endpoints:
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, context=ctx, timeout=3) as resp:
                    data = json.loads(resp.read().decode())
                    for ans in data.get("Answer", []):
                        if ans.get("type") == 1:
                            ip = ans.get("data")
                            _DNS_CACHE[host] = ip
                            return _orig_getaddrinfo(ip, port, family, type, proto, flags)
            except Exception:
                continue

        raise

def setup_smart_dns():
    """Habilita resolución DNS inteligente con fallback DoH directo a IP para sortear bloqueos de ISP locales"""
    socket.getaddrinfo = _doh_getaddrinfo

def get_aiohttp_connector() -> aiohttp.TCPConnector:
    """Retorna un conector TCP ultra-optimizado para HFT con SSL certifi y resolver Threaded (DoH)"""
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    return aiohttp.TCPConnector(
        resolver=aiohttp.ThreadedResolver(),
        ssl=ssl_ctx,
        limit=150,
        ttl_dns_cache=300,
        keepalive_timeout=75.0,
        force_close=False,
        enable_cleanup_closed=True
    )
