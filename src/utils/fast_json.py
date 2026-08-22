from typing import Any

try:
    import orjson
    def fast_loads(s: str | bytes) -> Any:
        if isinstance(s, str):
            s = s.encode("utf-8")
        return orjson.loads(s)

    def fast_dumps(obj: Any) -> str:
        return orjson.dumps(obj).decode("utf-8")

except ImportError:
    try:
        import ujson
        fast_loads = ujson.loads
        fast_dumps = ujson.dumps
    except ImportError:
        import json
        fast_loads = json.loads
        fast_dumps = json.dumps
