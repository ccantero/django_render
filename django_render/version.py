"""Deployed application version.

The repository-root ``VERSION`` file is the only SemVer source. Render's
``RENDER_GIT_COMMIT`` is appended as build metadata at runtime. Document
``doc_version`` headers are a separate sequence and are not read here.

A clock time is shown only when a controlled step recorded one: the
``DEPLOYED_AT`` environment variable, or ``build_info.json`` written by
``python manage.py stamp_build``. File modification times and process start
are not deploy times and are not used.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

VERSION_PATH = Path(__file__).resolve().parent.parent / "VERSION"
BUILD_STAMP_PATH = VERSION_PATH.parent / "build_info.json"
CORE_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
TIMESTAMP_EXPLICIT = "explicit"
TIMESTAMP_BUILD_STAMP = "build_stamp"
TIMESTAMP_UNKNOWN = "unknown"
_TIMESTAMP_SOURCES = {TIMESTAMP_EXPLICIT, TIMESTAMP_BUILD_STAMP}

try:
    BUENOS_AIRES = ZoneInfo("America/Buenos_Aires")
except ZoneInfoNotFoundError:
    BUENOS_AIRES = timezone(timedelta(hours=-3))


def is_core_semver(value):
    return bool(CORE_SEMVER_RE.fullmatch(str(value).strip()))


def read_app_version(version_path=None):
    path = VERSION_PATH if version_path is None else version_path
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    if not is_core_semver(text):
        return "0.0.0"
    return text


def short_commit(raw):
    cleaned = re.sub(r"[^0-9a-fA-F]", "", "" if raw is None else str(raw)).lower()
    if len(cleaned) < 7:
        return "dev"
    return cleaned[:7]


def _parse_deployed_at(value):
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def write_build_stamp(path, *, now=None):
    moment = now if now is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc).replace(microsecond=0)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {"deployed_at": moment.strftime("%Y-%m-%dT%H:%M:%SZ")}
    destination.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return moment


def read_build_stamp(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return _parse_deployed_at(payload.get("deployed_at"))


def resolve_timestamp(*, environ, stamp_path):
    explicit = _parse_deployed_at(environ.get("DEPLOYED_AT"))
    if explicit is not None:
        return explicit, TIMESTAMP_EXPLICIT
    stamped = read_build_stamp(stamp_path)
    if stamped is not None:
        return stamped, TIMESTAMP_BUILD_STAMP
    return None, TIMESTAMP_UNKNOWN


def build_release_info(*, version, commit, deployed_at, timestamp_source):
    safe_version = version if is_core_semver(version) else "0.0.0"
    safe_commit = short_commit(commit)
    source = timestamp_source if timestamp_source in _TIMESTAMP_SOURCES else TIMESTAMP_UNKNOWN
    moment = deployed_at if source in _TIMESTAMP_SOURCES else None
    payload = {
        "version": safe_version,
        "commit": safe_commit,
        "deployed_at": None,
        "timestamp_source": source if moment is not None else TIMESTAMP_UNKNOWN,
        "display": f"v{safe_version}+{safe_commit} · unknown",
    }
    if moment is None:
        return payload
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(BUENOS_AIRES).replace(microsecond=0)
    payload["deployed_at"] = local.isoformat(timespec="seconds")
    payload["timestamp_source"] = source
    payload["display"] = f"v{safe_version}+{safe_commit} · {local.strftime('%d/%m %H:%M')} ART"
    return payload


def current_release_info():
    try:
        moment, source = resolve_timestamp(
            environ=os.environ,
            stamp_path=BUILD_STAMP_PATH,
        )
        return build_release_info(
            version=read_app_version(),
            commit=short_commit(os.environ.get("RENDER_GIT_COMMIT")),
            deployed_at=moment,
            timestamp_source=source,
        )
    except Exception:
        return build_release_info(
            version="0.0.0",
            commit="dev",
            deployed_at=None,
            timestamp_source=TIMESTAMP_UNKNOWN,
        )
