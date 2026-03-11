from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import Response, current_app, jsonify, request

try:
    from .extensions import redis_client
except Exception:  # pragma: no cover
    redis_client = None


_memory_buckets: dict[str, deque[float]] = defaultdict(deque)
_memory_lock = threading.Lock()


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def parse_rate_limit(
    spec: str | None, default_limit: int = 5, default_window: int = 300
) -> tuple[int, int]:
    if not spec:
        return default_limit, default_window
    cleaned = str(spec).strip().lower()
    if not cleaned:
        return default_limit, default_window
    if "/" in cleaned:
        left, right = cleaned.split("/", 1)
        try:
            limit = int(left.strip())
        except Exception:
            limit = default_limit
        right = right.strip()
        multipliers = {
            "s": 1,
            "sec": 1,
            "second": 1,
            "seconds": 1,
            "m": 60,
            "min": 60,
            "minute": 60,
            "minutes": 60,
            "h": 3600,
            "hour": 3600,
            "hours": 3600,
        }
        try:
            if right.isdigit():
                return limit, int(right)
            for suffix, multiplier in multipliers.items():
                if right.endswith(suffix):
                    amount = int(right[: -len(suffix)].strip())
                    return limit, amount * multiplier
        except Exception:
            return default_limit, default_window
    return default_limit, default_window


def _rate_limit_storage_key(
    bucket: str, key: str, window_seconds: int, now: float
) -> str:
    return f"rl:{bucket}:{key}:{int(now // window_seconds)}"


def consume_rate_limit(
    bucket: str, key: str, limit: int, window_seconds: int
) -> tuple[bool, int]:
    now = time.time()
    storage_key = _rate_limit_storage_key(bucket, key, window_seconds, now)

    if redis_client is not None:
        try:
            current = redis_client.incr(storage_key)
            if current == 1:
                redis_client.expire(storage_key, window_seconds)
            return current <= limit, max(limit - int(current), 0)
        except Exception:
            pass

    cutoff = now - window_seconds
    with _memory_lock:
        q = _memory_buckets[storage_key]
        while q and q[0] <= cutoff:
            q.popleft()
        q.append(now)
        current = len(q)
        return current <= limit, max(limit - current, 0)


def _default_rate_limit_key() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = (
        forwarded.split(",", 1)[0].strip()
        if forwarded
        else (request.remote_addr or "unknown")
    )
    email = (
        (
            request.form.get("email")
            or request.form.get("guest_email")
            or request.args.get("email")
            or request.args.get("guest_email")
            or ""
        )
        .strip()
        .lower()
    )
    if email:
        return f"{ip}:{email}"
    return ip


def rate_limit(
    bucket: str,
    *,
    config_key: str | None = None,
    default: str = "5/300",
    methods: tuple[str, ...] = ("POST",),
    key_func=None,
):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not _truthy(current_app.config.get("RATE_LIMIT_ENABLED", True)):
                return fn(*args, **kwargs)
            if methods and request.method.upper() not in methods:
                return fn(*args, **kwargs)

            spec = current_app.config.get(config_key) if config_key else default
            limit, window_seconds = parse_rate_limit(spec)
            limiter_key = (
                key_func() if callable(key_func) else _default_rate_limit_key()
            )
            allowed, _remaining = consume_rate_limit(
                bucket, limiter_key, limit, window_seconds
            )
            if allowed:
                return fn(*args, **kwargs)

            retry_after = str(window_seconds)
            wants_json = request.path.startswith("/integrations/") or (
                request.accept_mimetypes.best == "application/json"
            )
            if wants_json:
                response = jsonify(
                    {
                        "ok": False,
                        "error": "rate_limited",
                        "message": "Too many requests. Please try again later.",
                    }
                )
                response.status_code = 429
                response.headers["Retry-After"] = retry_after
                return response

            response = Response(
                "Too many requests. Please try again later.", status=429
            )
            response.headers["Retry-After"] = retry_after
            return response

        return wrapped

    return decorator


def compute_webhook_signature(
    secret: str, payload: bytes, *, timestamp: str | None = None
) -> str:
    body = payload
    if timestamp:
        body = timestamp.encode("utf-8") + b"." + payload
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _consume_nonce(nonce_key: str, ttl_seconds: int) -> bool:
    if redis_client is not None:
        try:
            created = redis_client.set(nonce_key, "1", nx=True, ex=ttl_seconds)
            return bool(created)
        except Exception:
            pass
    now = time.time()
    cutoff = now - ttl_seconds
    with _memory_lock:
        q = _memory_buckets[nonce_key]
        while q and q[0] <= cutoff:
            q.popleft()
        if q:
            return False
        q.append(now)
    return True


def verify_webhook_request(
    *,
    payload: bytes,
    signature: str | None,
    secret: str | None,
    timestamp: str | None = None,
) -> tuple[bool, str | None]:
    if not signature or not secret:
        return False, "missing_signature"

    require_timestamp = _truthy(
        current_app.config.get("WEBHOOK_REQUIRE_TIMESTAMP", False)
    )
    ttl_seconds = int(current_app.config.get("WEBHOOK_SIGNATURE_TTL_SECONDS", 300))
    prevent_replay = _truthy(
        current_app.config.get("WEBHOOK_REPLAY_PROTECTION_ENABLED", True)
    )

    if timestamp:
        try:
            ts_int = int(str(timestamp).strip())
        except Exception:
            return False, "invalid_timestamp"
        if abs(int(time.time()) - ts_int) > ttl_seconds:
            return False, "expired_timestamp"
        expected = compute_webhook_signature(secret, payload, timestamp=str(ts_int))
        if not hmac.compare_digest(expected, (signature or "").strip()):
            return False, "invalid_signature"
        if prevent_replay:
            digest = hashlib.sha256(
                (str(ts_int) + ":" + signature).encode("utf-8")
            ).hexdigest()
            nonce_key = f"webhook-nonce:{digest}"
            if not _consume_nonce(nonce_key, ttl_seconds):
                return False, "replay_detected"
        return True, None

    if require_timestamp:
        return False, "missing_timestamp"

    expected = compute_webhook_signature(secret, payload)
    if not hmac.compare_digest(expected, (signature or "").strip()):
        return False, "invalid_signature"
    return True, None
