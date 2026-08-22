import socket
import urllib.request
import json
import ssl
import certifi
import aiohttp
from src.utils.logger import get_logger

logger = get_logger("DNSResolver")

_DNS_CACHE = {}
_orig_getaddrinfo = socket.getaddrinfo

def _doh_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    try:
        return _orig_getaddrinfo(host, port, family, type, proto, flags)
    except socket.gaierror:
        # Fallback a Cloudflare / Google DoH si el DNS local falla
        if host in _DNS_CACHE:
            ip = _DNS_CACHE[host]
            return _orig_getaddrinfo(ip, port, family, type, proto, flags)
        
        try:
            url = f"https://cloudflare-dns.com/dns-query?name={host}&type=A"
            req = urllib.request.Request(url, headers={"accept": "application/dns-json", "User-Agent": "Mozilla/5.0"})
            ctx = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(req, context=ctx, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                for ans in data.get("Answer", []):
                    if ans.get("type") == 1:
                        ip = ans.get("data")
                        _DNS_CACHE[host] = ip
                        return _orig_getaddrinfo(ip, port, family, type, proto, flags)
        except Exception as e:
            logger.debug(f"DoH fallback error for {host}: {e}")
        
        raise

def setup_smart_dns():
    """Habilita resolución DNS inteligente con fallback DoH para sortear bloqueos de ISP locales"""
    socket.getaddrinfo = _doh_getaddrinfo

def get_aiohttp_connector() -> aiohttp.TCPConnector:
    """Retorna un conector TCP ultra-optimizado para HFT con SSL certifi y pool persistente"""
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
