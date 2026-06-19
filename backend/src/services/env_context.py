"""Per-call environment overlay for in-process tool executors.

Connector executors read credentials via ``os.getenv(...)``. To inject org/user
env vars for a single tool call *without* a process-global mutation (which would
require a platform-wide lock and leak across concurrent calls), we install a
context-aware replacement for ``os.environ`` once, then set a per-task overlay
via a ``contextvars`` variable.

``os.getenv`` resolves ``os.environ`` each call, so swapping the module attribute
is enough — reads consult the task-local overlay first, then the real environ.
Writes, iteration, ``copy()`` and ``putenv`` side-effects all delegate to the
real ``os._Environ`` unchanged, so subprocess inheritance and everything else
behave exactly as before. The overlay is task-local (contextvars), so concurrent
tool calls for different orgs never see each other's values — no lock needed.
"""
from __future__ import annotations

import contextlib
import contextvars
import os
from collections.abc import MutableMapping

_overlay: contextvars.ContextVar[dict | None] = contextvars.ContextVar("env_overlay", default=None)
_installed = False
_real: MutableMapping | None = None


class _ContextEnviron(MutableMapping):
    """Transparent wrapper over the real os.environ that overlays a task-local
    dict on reads. All mutation delegates to the real mapping."""

    def __init__(self, real):
        self._real = real

    def __getitem__(self, key):
        ov = _overlay.get()
        if ov is not None and key in ov:
            return ov[key]
        return self._real[key]

    def get(self, key, default=None):
        ov = _overlay.get()
        if ov is not None and key in ov:
            return ov[key]
        return self._real.get(key, default)

    def __contains__(self, key):
        ov = _overlay.get()
        if ov is not None and key in ov:
            return True
        return key in self._real

    def __setitem__(self, key, value):
        self._real[key] = value

    def __delitem__(self, key):
        del self._real[key]

    def __iter__(self):
        return iter(self._real)

    def __len__(self):
        return len(self._real)

    def copy(self):
        return self._real.copy()

    # os.environ exposes these; delegate so callers that use them keep working.
    def setdefault(self, key, default=None):
        return self._real.setdefault(key, default)

    def __repr__(self):
        return repr(self._real)


def install() -> None:
    """Swap os.environ for the context-aware wrapper (idempotent)."""
    global _installed, _real
    if _installed:
        return
    _real = os.environ
    os.environ = _ContextEnviron(_real)  # type: ignore[assignment]
    _installed = True


@contextlib.contextmanager
def use_env(overlay: dict | None):
    """Apply `overlay` (KEY->value) for os.getenv reads in this task only."""
    if not overlay:
        yield
        return
    install()
    token = _overlay.set(dict(overlay))
    try:
        yield
    finally:
        _overlay.reset(token)
