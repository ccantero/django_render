"""Deployed application version.

The repository-root ``VERSION`` file is the only SemVer source. Render's
``RENDER_GIT_COMMIT`` is appended as build metadata at runtime. Document
``doc_version`` headers are a separate sequence and are not read here.

Render publishes the git commit at build and runtime, and does not publish a
deploy timestamp. ``DEPLOYED_AT`` is an optional ISO-8601 override. On Render,
the next choice is the ``VERSION`` file modification time, which is the source
checkout time baked into that deploy's slug and stays put across restarts.
If that file cannot be read, the process start time is used. Local runs and
tests leave the timestamp unknown instead of inventing a deploy.
"""

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

VERSION_PATH = Path(__file__).resolve().parent.parent / "VERSION"
CORE_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_PROCESS_STARTED_AT = datetime.now(timezone.utc)

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


def resolve_deployed_at(*, environ, version_path, process_started_at):
    parsed = _parse_deployed_at(environ.get("DEPLOYED_AT"))
    if parsed is not None:
        return parsed
    on_render = str(environ.get("RENDER", "")).strip().lower() == "true"
    if not on_render:
        return None
    try:
        mtime = version_path.stat().st_mtime
    except OSError:
        started = process_started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return started.astimezone(timezone.utc).replace(microsecond=0)
    return datetime.fromtimestamp(round(mtime), tz=timezone.utc)


def build_release_info(*, version, commit, deployed_at):
    safe_version = version if is_core_semver(version) else "0.0.0"
    safe_commit = short_commit(commit)
    payload = {
        "version": safe_version,
        "commit": safe_commit,
        "deployed_at": None,
        "display": f"v{safe_version}+{safe_commit} · unknown",
    }
    if deployed_at is None:
        return payload
    moment = deployed_at
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(BUENOS_AIRES).replace(microsecond=0)
    payload["deployed_at"] = local.isoformat(timespec="seconds")
    payload["display"] = f"v{safe_version}+{safe_commit} · {local.strftime('%d/%m %H:%M')} ART"
    return payload


def current_release_info():
    try:
        return build_release_info(
            version=read_app_version(),
            commit=short_commit(os.environ.get("RENDER_GIT_COMMIT")),
            deployed_at=resolve_deployed_at(
                environ=os.environ,
                version_path=VERSION_PATH,
                process_started_at=_PROCESS_STARTED_AT,
            ),
        )
    except Exception:
        return build_release_info(version="0.0.0", commit="dev", deployed_at=None)
