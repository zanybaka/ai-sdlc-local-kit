"""State-file IO for the ai-task CLI.

Charter: **state.py imports nothing above `_shared`, ever.** Quota
admission control reserves under the state lock, so ``quota`` imports this
module; that edge is acyclic only while this rule holds. A helper that needs
policy, backlog or run knowledge belongs in the caller, not here.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ai_task._shared import APP_DIR, app_path, die, now

try:
    import fcntl
except ModuleNotFoundError:  # pragma: no cover - Windows fallback.
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ModuleNotFoundError:  # pragma: no cover - POSIX fallback.
    msvcrt = None  # type: ignore[assignment]

STATE_SCHEMA = 1
STATE_LOCK_TIMEOUT_ENV = "AI_TASK_STATE_LOCK_TIMEOUT_SECONDS"
DEFAULT_STATE_LOCK_TIMEOUT_SECONDS = 10.0
STATE_LOCK_POLL_SECONDS = 0.05


STATE_META_BASE_KEY = "__state_base"


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def repo_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def selected_root(repo_arg: str | None) -> Path:
    if repo_arg:
        return Path(repo_arg).expanduser().resolve()
    return repo_root(Path(os.getcwd()))


def require_initialized(root: Path) -> Path:
    path = app_path(root)
    if not path.exists():
        die(
            f"{APP_DIR} is not initialized in {root}. Run: ai-task init\n"
            "hint: without init use `ai-task backlog-order` (/sdlc-implement-task) "
            "or run ai-task init for plan/run"
        )
    return path


def default_state() -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA,
        "created_at": now(),
        "updated_at": now(),
        "last_batch": [],
        "backend_cooldowns": {},
        # Credential-dead backends: unusable until an operator
        # authenticates them, unlike the timer-based backend_cooldowns above.
        "backend_credentials": {},
        "runs": {},
        "review_queue": [],
        "leases": {},
        "quota_reservations": {},
    }


def state_path(root: Path) -> Path:
    return app_path(root) / "state.json"


def state_lock_path(root: Path) -> Path:
    return app_path(root) / "state.lock"


def _normalize_state_defaults(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("schema_version", STATE_SCHEMA)
    state.setdefault("created_at", now())
    state.setdefault("updated_at", now())
    state.setdefault("last_batch", [])
    state.setdefault("backend_cooldowns", {})
    state.setdefault("runs", {})
    state.setdefault("review_queue", [])
    state.setdefault("leases", {})
    state.setdefault("quota_reservations", {})
    if not isinstance(state.get("last_batch"), list):
        state["last_batch"] = []
    if not isinstance(state.get("backend_cooldowns"), dict):
        state["backend_cooldowns"] = {}
    if not isinstance(state.get("runs"), dict):
        state["runs"] = {}
    if not isinstance(state.get("review_queue"), list):
        state["review_queue"] = []
    if not isinstance(state.get("leases"), dict):
        state["leases"] = {}
    if not isinstance(state.get("quota_reservations"), dict):
        state["quota_reservations"] = {}
    return state


def _state_public_view(state: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in state.items() if key != STATE_META_BASE_KEY}


def _attach_state_base(state: dict[str, Any]) -> None:
    state[STATE_META_BASE_KEY] = copy.deepcopy(_state_public_view(state))


def _read_state_unlocked(root: Path) -> dict[str, Any]:
    return _normalize_state_defaults(read_json(state_path(root), default_state()))


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _merge_dict_with_base(*, latest: Any, base: Any, incoming: Any) -> dict[str, Any]:
    latest_dict = latest if isinstance(latest, dict) else {}
    base_dict = base if isinstance(base, dict) else {}
    incoming_dict = incoming if isinstance(incoming, dict) else {}
    merged = copy.deepcopy(latest_dict)

    for key in set(base_dict) - set(incoming_dict):
        merged.pop(key, None)

    for key, value in incoming_dict.items():
        base_value = base_dict.get(key, object())
        if key in base_dict and value == base_value:
            continue
        latest_value = merged.get(key)
        if (
            key in base_dict
            and isinstance(value, dict)
            and isinstance(base_value, dict)
            and isinstance(latest_value, dict)
        ):
            merged[key] = _merge_dict_with_base(
                latest=latest_value, base=base_value, incoming=value
            )
            continue
        merged[key] = copy.deepcopy(value)
    return merged


def _merge_state_with_latest(
    latest_state: dict[str, Any], incoming_state: dict[str, Any]
) -> dict[str, Any]:
    latest = _normalize_state_defaults(copy.deepcopy(_state_public_view(latest_state)))
    incoming = _normalize_state_defaults(
        copy.deepcopy(_state_public_view(incoming_state))
    )
    base_raw = incoming_state.get(STATE_META_BASE_KEY)
    if isinstance(base_raw, dict):
        base = _normalize_state_defaults(copy.deepcopy(base_raw))
    else:
        base = copy.deepcopy(latest)

    merged = copy.deepcopy(latest)
    merged["runs"] = _merge_dict_with_base(
        latest=latest.get("runs", {}),
        base=base.get("runs", {}),
        incoming=incoming.get("runs", {}),
    )
    merged["backend_cooldowns"] = _merge_dict_with_base(
        latest=latest.get("backend_cooldowns", {}),
        base=base.get("backend_cooldowns", {}),
        incoming=incoming.get("backend_cooldowns", {}),
    )
    merged["leases"] = _merge_dict_with_base(
        latest=latest.get("leases", {}),
        base=base.get("leases", {}),
        incoming=incoming.get("leases", {}),
    )
    merged["quota_reservations"] = _merge_dict_with_base(
        latest=latest.get("quota_reservations", {}),
        base=base.get("quota_reservations", {}),
        incoming=incoming.get("quota_reservations", {}),
    )

    if incoming.get("last_batch") != base.get("last_batch"):
        merged["last_batch"] = copy.deepcopy(incoming.get("last_batch", []))
    else:
        merged["last_batch"] = copy.deepcopy(latest.get("last_batch", []))

    for key, value in incoming.items():
        if key in {
            "runs",
            "backend_cooldowns",
            "leases",
            "quota_reservations",
            "last_batch",
        }:
            continue
        if key in base and value == base[key]:
            continue
        merged[key] = copy.deepcopy(value)
    return _normalize_state_defaults(merged)


def load_state(root: Path) -> dict[str, Any]:
    state = _read_state_unlocked(root)
    _attach_state_base(state)
    return state


def _state_lock_timeout_seconds() -> float:
    raw = os.environ.get(STATE_LOCK_TIMEOUT_ENV, "").strip()
    if not raw:
        return DEFAULT_STATE_LOCK_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError:
        die(f"{STATE_LOCK_TIMEOUT_ENV} must be a number of seconds")
    if timeout < 0:
        die(f"{STATE_LOCK_TIMEOUT_ENV} must be zero or positive")
    return timeout


class StateLockTimeoutError(RuntimeError):
    pass


# One-time flag so the lock-less platform warning is printed at most once per process.
_LOCKLESS_PLATFORM_WARNED = False


@contextmanager
def _state_lock(root: Path, *, timeout_seconds: float | None = None) -> Iterator[None]:
    global _LOCKLESS_PLATFORM_WARNED
    lock_path = state_lock_path(root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_timeout = (
        _state_lock_timeout_seconds() if timeout_seconds is None else timeout_seconds
    )
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is None and msvcrt is None:
            if not _LOCKLESS_PLATFORM_WARNED:
                _LOCKLESS_PLATFORM_WARNED = True
                print(
                    "WARNING: state locking unavailable on this platform — "
                    "do not run parallel ai-task processes",
                    file=sys.stderr,
                )
            yield
            return
        # fcntl raises BlockingIOError when the lock is held; msvcrt.locking with
        # LK_NBLCK raises OSError. Both are retried until the deadline.
        contended: tuple[type[OSError], ...] = (
            (BlockingIOError,) if fcntl is not None else (OSError,)
        )
        deadline = time.monotonic() + resolved_timeout
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    # Lock byte 0 of the (possibly empty) lock file: msvcrt may
                    # lock a region beyond EOF, so no payload write is needed.
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except contended:
                if time.monotonic() >= deadline:
                    raise StateLockTimeoutError(
                        "state lock is held by another ai-task process "
                        f"({lock_path}). Wait for it to finish or raise "
                        f"{STATE_LOCK_TIMEOUT_ENV}."
                    ) from None
                time.sleep(STATE_LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            else:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def save_state(root: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now()
    try:
        with _state_lock(root):
            latest = _read_state_unlocked(root)
            merged = _merge_state_with_latest(latest, state)
            _write_json_atomic(state_path(root), merged)
    except StateLockTimeoutError as exc:
        die(str(exc))
    _attach_state_base(state)
