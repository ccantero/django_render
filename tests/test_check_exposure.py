"""Mocked tests for the read-only exposure probe. These tests never open a network connection."""

import importlib.util
import io
import urllib.error
from pathlib import Path

import pytest

SECRET_BODY = "SUPER_SECRET_BODY_DO_NOT_PRINT"
MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "security" / "check_exposure.py"


def load_probe():
    spec = importlib.util.spec_from_file_location("check_exposure", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"exposure probe is missing: {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BodyResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self, _size=-1):
        data = self._body
        self._body = b""
        return data


def http_error(status, body=b""):
    return urllib.error.HTTPError(
        "https://example.test/probed",
        status,
        "status",
        hdrs=None,
        fp=io.BytesIO(body),
    )


def test_status_200_is_exposure():
    probe = load_probe()

    def urlopen(_request, timeout):
        assert timeout == 5
        return BodyResponse(200, b"ok")

    result = probe.probe_url("https://example.test/.env", timeout=5, urlopen=urlopen)

    assert result["result"] == "EXPOSURE"
    assert result["status"] == 200
    assert result["bytes"] == 2
    assert "body" not in result


def test_status_404_passes():
    probe = load_probe()

    def urlopen(_request, timeout):
        raise http_error(404, b"missing")

    result = probe.probe_url("https://example.test/.env", urlopen=urlopen)

    assert result["result"] == "PASS"
    assert result["status"] == 404
    assert result["bytes"] == 7


@pytest.mark.parametrize(
    ("error", "label"),
    [
        (TimeoutError("slow"), "timeout"),
        (urllib.error.URLError(OSError("refused")), "connection_error"),
    ],
)
def test_timeout_and_connection_error_are_unverified(error, label):
    probe = load_probe()
    calls = {"count": 0}

    def urlopen(_request, timeout):
        calls["count"] += 1
        raise error

    result = probe.probe_url("https://example.test/.env", urlopen=urlopen)

    assert calls["count"] == 1
    assert result["result"] == "UNVERIFIED"
    assert result["status"] is None
    assert result["error"] == label
    assert result["result"] != "OK"
    assert "slow" not in str(result.values())
    assert "refused" not in str(result.values())


def test_http_5xx_is_unverified_without_retry():
    probe = load_probe()
    calls = {"count": 0}

    def urlopen(_request, timeout):
        calls["count"] += 1
        raise http_error(503, b"upstream unavailable")

    result = probe.probe_url("https://example.test/.env", urlopen=urlopen)

    assert calls["count"] == 1
    assert result["result"] == "UNVERIFIED"
    assert result["status"] == 503
    assert result["error"] == "http_5xx"
    assert "upstream unavailable" not in str(result.values())


def test_response_body_is_never_printed(capsys):
    probe = load_probe()

    def urlopen(_request, timeout):
        return BodyResponse(200, SECRET_BODY.encode())

    result = probe.probe_url("https://example.test/.env", urlopen=urlopen)
    line = probe.format_result(result)
    print(line)
    captured = capsys.readouterr()

    assert SECRET_BODY not in line
    assert SECRET_BODY not in captured.out
    assert SECRET_BODY not in captured.err
    assert all(SECRET_BODY not in str(value) for value in result.values())
    assert "status=200" in line
    assert "bytes=30" in line
    assert "result=EXPOSURE" in line


def test_redirects_are_not_followed():
    probe = load_probe()
    handler = probe._NoRedirect()

    assert handler.redirect_request(
        None,
        None,
        302,
        "Found",
        {},
        "https://example.test/admin/login/",
    ) is None
