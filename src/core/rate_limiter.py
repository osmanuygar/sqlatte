"""
Rate limiting middleware — reads config.yaml rate_limiting section.

Supported strategies: sliding_window, token_bucket, fixed_window
Supported key types:  session_id (X-Session-ID header), ip, user_id
"""

import time
import threading
import logging
from collections import defaultdict, deque
from typing import Dict, Deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


# ── In-memory stores (per-process; cleared on restart) ────────────────────────

# sliding_window: key → deque of request timestamps
_sliding_windows: Dict[str, Deque[float]] = defaultdict(deque)

# token_bucket: key → {"tokens": float, "last_refill": float}
_token_buckets: Dict[str, dict] = {}

# fixed_window: key → {"count": int, "window_start": float}
_fixed_windows: Dict[str, dict] = {}

_lock = threading.Lock()


# ── Strategy implementations ───────────────────────────────────────────────────

def _check_sliding_window(key: str, limit: int, window_sec: int) -> bool:
    """Return True if request is allowed."""
    now = time.time()
    cutoff = now - window_sec
    with _lock:
        dq = _sliding_windows[key]
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True


def _check_token_bucket(key: str, limit: int, window_sec: int) -> bool:
    """Refill at limit tokens per window_sec, consume 1 per request."""
    now = time.time()
    refill_rate = limit / window_sec  # tokens per second
    with _lock:
        bucket = _token_buckets.get(key)
        if bucket is None:
            _token_buckets[key] = {"tokens": limit - 1, "last_refill": now}
            return True
        elapsed = now - bucket["last_refill"]
        bucket["tokens"] = min(limit, bucket["tokens"] + elapsed * refill_rate)
        bucket["last_refill"] = now
        if bucket["tokens"] < 1:
            return False
        bucket["tokens"] -= 1
        return True


def _check_fixed_window(key: str, limit: int, window_sec: int) -> bool:
    """Fixed window: reset counter every window_sec seconds."""
    now = time.time()
    with _lock:
        win = _fixed_windows.get(key)
        if win is None or now - win["window_start"] >= window_sec:
            _fixed_windows[key] = {"count": 1, "window_start": now}
            return True
        if win["count"] >= limit:
            return False
        win["count"] += 1
        return True


_STRATEGIES = {
    "sliding_window": _check_sliding_window,
    "token_bucket":   _check_token_bucket,
    "fixed_window":   _check_fixed_window,
}


# ── Key extraction ─────────────────────────────────────────────────────────────

def _extract_key(request: Request, key_type: str) -> str:
    if key_type == "session_id":
        sid = request.headers.get("X-Session-ID", "")
        return f"sid:{sid}" if sid else f"ip:{request.client.host}"
    if key_type == "ip":
        forwarded = request.headers.get("X-Forwarded-For", "")
        ip = forwarded.split(",")[0].strip() if forwarded else request.client.host
        return f"ip:{ip}"
    # user_id — fall back to session_id
    return f"sid:{request.headers.get('X-Session-ID', request.client.host)}"


# ── Middleware ─────────────────────────────────────────────────────────────────

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Config-driven rate limiter. Reads rate_limiting section from config.yaml
    on every request so changes take effect after a config reload.
    """

    async def dispatch(self, request: Request, call_next):
        cfg = self._get_config()

        if not cfg.get("enabled", False):
            return await call_next(request)

        path = request.url.path

        # Skip excluded paths
        for excl in cfg.get("exclude_paths", []):
            if path.startswith(excl):
                return await call_next(request)

        # Only apply to protected paths
        protected = cfg.get("protected_paths", [])
        if protected and not any(path.startswith(p) for p in protected):
            return await call_next(request)

        limit      = int(cfg.get("requests_per_window", 30))
        window_sec = int(cfg.get("window_seconds", 60))
        strategy   = cfg.get("strategy", "sliding_window")
        key_type   = cfg.get("key_type", "session_id")

        check = _STRATEGIES.get(strategy, _check_sliding_window)
        key   = f"{strategy}:{_extract_key(request, key_type)}:{path}"

        allowed = check(key, limit, window_sec)

        if not allowed:
            logger.warning(
                "Rate limit exceeded: %s %s key=%s strategy=%s",
                request.method, path, key, strategy
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "detail": f"Limit: {limit} requests per {window_sec}s. Try again later.",
                    "retry_after": window_sec,
                },
                headers={"Retry-After": str(window_sec)},
            )

        return await call_next(request)

    @staticmethod
    def _get_config() -> dict:
        try:
            from src.core.config_manager_enhanced import config_manager
            return config_manager.get_config().get("rate_limiting", {})
        except Exception:
            return {}
