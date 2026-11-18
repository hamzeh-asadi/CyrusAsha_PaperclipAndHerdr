"""Stateless client shared by the board dashboard and the lower-privilege process worker.

Never load dashboard/.env here: a worker must use only its run-scoped credentials.
"""

import ipaddress
import json
import urllib.request
from http.client import HTTPException
from typing import Any, Optional
from urllib.error import HTTPError as UrllibHTTPError, URLError
from urllib.parse import urlparse


class PaperclipError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class PaperclipConnectionError(PaperclipError):
    """A retryable transport failure, not an HTTP/authentication error."""

    def __init__(self, state: str):
        self.state = state
        super().__init__(
            f"Paperclip connection {state}. Check PAPERCLIP_API_URL and the npm start terminal.", 503
        )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # An API response must be JSON, not a login page. Never forward a bearer
    # token to a redirect target.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_api = urllib.request.build_opener(_NoRedirect())
_direct_api = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def is_loopback(host: str) -> bool:
    if host.rstrip(".").lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def request_json(
    url: str,
    path: str,
    method: str = "GET",
    timeout: float = 5,
    *,
    key: str = "",
    run_id: str = "",
    data: Optional[dict] = None,
) -> Any:
    url = url.rstrip("/")
    headers = {"Accept": "application/json"}
    if key and path != "/api/health":
        headers["Authorization"] = f"Bearer {key}"
    if run_id:
        headers["X-Paperclip-Run-Id"] = run_id
    body = None
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    try:
        base = urlparse(url)
        if (
            base.scheme not in ("http", "https")
            or not base.hostname
            or base.username is not None
            or base.query
            or base.fragment
        ):
            raise ValueError("invalid base URL")
        req = urllib.request.Request(f"{url}{path}", headers=headers, method=method, data=body)
    except ValueError as exc:
        raise PaperclipError(
            "PAPERCLIP_API_URL must be an HTTP(S) base URL without credentials, query or fragment."
        ) from exc
    try:
        # Never send loopback traffic (including board credentials) to a system proxy.
        opener = _direct_api if is_loopback(base.hostname) else _api
        with opener.open(req, timeout=timeout) as response:
            return json.load(response)
    except UrllibHTTPError as exc:
        exc.close()
        if exc.code in (401, 403):
            raise PaperclipError(
                f"Paperclip HTTP {exc.code}: check PAPERCLIP_API_KEY and its permissions.", exc.code
            ) from exc
        status = exc.code if 400 <= exc.code < 500 else 502
        raise PaperclipError(f"Paperclip returned HTTP {exc.code} for {path}.", status) from exc
    except (URLError, OSError, HTTPException) as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        if isinstance(reason, ConnectionRefusedError):
            raise PaperclipConnectionError("refused") from exc
        if isinstance(reason, TimeoutError):
            raise PaperclipConnectionError("timeout") from exc
        raise PaperclipError(
            "Cannot reach Paperclip. Check PAPERCLIP_API_URL and the npm start terminal.", 503
        ) from exc
    except ValueError as exc:
        raise PaperclipError(
            "Expected JSON from Paperclip. Check PAPERCLIP_API_URL (base URL without /api)."
        ) from exc


def request_human_review(api, issue_path, key):
    """An agent cannot park an issue in review with only a comment. Bind a real decision."""
    review = api(
        issue_path + "/interactions",
        "POST",
        data={
            "kind": "request_confirmation",
            "resolverPolicy": "human_only",
            "continuationPolicy": "none",
            "idempotencyKey": "herdr-review:" + key,
            "title": "بازبینی خروجی ایجنت",
            "payload": {
                "version": 1,
                "prompt": "خروجی این زیرکار را در محیط پروژه بررسی کردید؟",
                "acceptLabel": "تأیید خروجی",
                "rejectLabel": "نیاز به اصلاح",
            },
        },
    )
    if not isinstance(review, dict) or not review.get("id") or review.get("status") != "pending":
        raise PaperclipError("درخواست بازبینی در وضعیت انتظار نیست. تیکت را در Paperclip بررسی کنید.", 409)
    issue = api(
        issue_path,
        "PATCH",
        data={
            "status": "in_review",
            "reviewInteractionId": review["id"],
            "comment": "خروجی برای بازبینی انسانی آماده است.",
        },
    )
    if not isinstance(issue, dict) or issue.get("status") != "in_review":
        raise PaperclipError("تغییر وضعیت بازبینی تأیید نشد. تیکت را در Paperclip بررسی کنید.", 409)
    return issue
