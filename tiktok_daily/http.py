import json
import time
import urllib.error
import urllib.parse
import urllib.request


class APIError(RuntimeError):
    def __init__(self, service, status=None, uncertain=False, code=None):
        self.status, self.uncertain = status, uncertain
        self.code = code
        super().__init__(f"{service} request failed (HTTP {status or 'connection/invalid response'}; uncertain={uncertain}; code={code or 'unspecified'})")


class HTTP:
    """Never log remote bodies, headers, request payloads, or credentials."""

    def __init__(self, sleep=time.sleep):
        self.sleep = sleep

    def json(self, url, payload=None, token=None, safe_retry=False, timeout=60, extra_headers=None):
        headers = {"Accept": "application/json", "User-Agent": "daily-image-publisher/1.0"}
        if extra_headers:
            headers.update(extra_headers)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        service = urllib.parse.urlsplit(url).hostname
        attempts = 3 if safe_retry else 1
        for attempt in range(attempts):
            delay = 2 ** (attempt + 1)
            try:
                req = urllib.request.Request(url, data=data, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                code = None
                try:
                    candidate = json.loads(exc.read(16384)).get("error", {}).get("code")
                    if candidate in {"insufficient_quota", "rate_limit_exceeded", "invalid_api_key", "model_not_found", "billing_hard_limit_reached", "organization_not_verified", "unsupported_parameter"}:
                        code = candidate
                except (ValueError, AttributeError, OSError):
                    pass
                retryable = exc.code in (429, 500, 502, 503, 504)
                if code in {"insufficient_quota", "invalid_api_key", "model_not_found", "billing_hard_limit_reached", "organization_not_verified", "unsupported_parameter"}:
                    retryable = False
                try:
                    delay = min(60, max(delay, int(exc.headers.get("Retry-After", "0"))))
                except (ValueError, TypeError):
                    pass
                if not retryable or attempt == attempts - 1:
                    # Server failures on writes can have occurred after accepting them.
                    raise APIError(service, exc.code, uncertain=exc.code >= 500, code=code) from None
            except (OSError, ValueError, TimeoutError):
                if attempt == attempts - 1:
                    raise APIError(service, uncertain=True) from None
            self.sleep(delay)

    def image(self, url, expected_digest):
        import hashlib
        for attempt in range(5):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "daily-image-publisher/1.0"})
                with urllib.request.urlopen(req, timeout=30) as response:
                    data = response.read(20_000_001)
                if len(data) <= 20_000_000 and hashlib.sha256(data).hexdigest() == expected_digest:
                    return
            except (OSError, ValueError):
                pass
            if attempt < 4:
                self.sleep(min(30, 2 ** (attempt + 1)))
        raise RuntimeError("Public image is not accessible or its hash does not match")
