"""Human-readable formatting helpers."""


def format_duration(seconds: int) -> str:
    """e.g. 60266 -> '16h 44m', 90 -> '1m 30s'."""
    s = max(0, int(seconds))
    if s >= 86400:
        d, rem = divmod(s, 86400)
        h = rem // 3600
        return f"{d}d {h}h" if h else f"{d}d"
    if s >= 3600:
        h, rem = divmod(s, 3600)
        m = rem // 60
        return f"{h}h {m}m" if m else f"{h}h"
    if s >= 60:
        m, sec = divmod(s, 60)
        return f"{m}m {sec}s" if sec else f"{m}m"
    return f"{s}s"
