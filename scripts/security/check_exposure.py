#!/usr/bin/env python3
"""Read-only exposure probe.

Prints the request method, URL, status code, and response size. Response
bodies are read only to count bytes and are never printed or returned.
Timeouts, connection errors, and HTTP 5xx responses are UNVERIFIED. The probe
makes one attempt and does not retry.
"""

from __future__ import annotations

import argparse
import socket
import urllib.error
import urllib.request


def classify(status, error):
    if error in {"timeout", "connection_error", "http_5xx"}:
        return "UNVERIFIED"
    if status is None or status >= 500:
        return "UNVERIFIED"
    if status == 404:
        return "PASS"
    if status == 200:
        return "EXPOSURE"
    return "OBSERVED"


def _consume(response):
    read = getattr(response, "read", None)
    if read is None:
        return 0
    size = 0
    while True:
        chunk = read(65536)
        if not chunk:
            break
        size += len(chunk)
    return size


def _error_label(exc):
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    reason = getattr(exc, "reason", None)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timeout"
    return "connection_error"


def _result(url, method, status, size, error):
    return {
        "url": url,
        "method": method.upper(),
        "status": status,
        "bytes": size,
        "error": error,
        "result": classify(status, error),
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 301/302/303/307/308 instead of requesting the Location target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_urlopen(request, timeout):
    opener = urllib.request.build_opener(_NoRedirect)
    return opener.open(request, timeout=timeout)


def probe_url(url, method="GET", timeout=10.0, urlopen=None):
    """Probe one URL once. The result never contains a response body."""
    if urlopen is None:
        urlopen = _default_urlopen
    request = urllib.request.Request(url, method=method.upper())
    try:
        response = urlopen(request, timeout)
    except urllib.error.HTTPError as exc:
        status = exc.code
        size = _consume(exc)
        error = "http_5xx" if status is not None and status >= 500 else None
        return _result(url, method, status, size, error)
    except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
        return _result(url, method, None, None, _error_label(exc))

    status = getattr(response, "status", None)
    if status is None:
        status = getattr(response, "code", None)
    size = _consume(response)
    close = getattr(response, "close", None)
    if close is not None:
        close()
    error = "http_5xx" if status is not None and status >= 500 else None
    return _result(url, method, status, size, error)


def format_result(result):
    status = "UNVERIFIED" if result["status"] is None else str(result["status"])
    size = "UNVERIFIED" if result["bytes"] is None else str(result["bytes"])
    line = (
        f"{result['method']} {result['url']} status={status} "
        f"bytes={size} result={result['result']}"
    )
    if result.get("error"):
        line += f" error={result['error']}"
    return line


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Print status code and response size for unauthenticated GET or HEAD checks."
    )
    parser.add_argument("urls", nargs="+")
    parser.add_argument("--method", choices=("GET", "HEAD"), default="GET")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)
    for url in args.urls:
        print(format_result(probe_url(url, method=args.method, timeout=args.timeout)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
