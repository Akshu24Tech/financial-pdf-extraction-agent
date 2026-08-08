"""Trodo agent-tracing integration for finagent.

Handles initialization and context management for Trodo agent telemetry.
Site ID: e3751324-7684-484d-8dd5-b7266df80bcb (configurable via TRODO_SITE_ID env var).
"""

import os
from contextlib import contextmanager
from typing import Any, Dict, Optional

DEFAULT_SITE_ID = "e3751324-7684-484d-8dd5-b7266df80bcb"
DEFAULT_AGENT_NAME = "financial-pdf-extraction-agent"

_INITIALIZED = False
_TRODO_AVAILABLE = False

try:
    import trodo

    _TRODO_AVAILABLE = True
except ImportError:
    trodo = None


class DummyRun:
    """Fallback run object if Trodo is not installed."""

    def set_input(self, data: Any) -> None:
        pass

    def set_output(self, data: Any) -> None:
        pass

    def set_metadata(self, data: Dict[str, Any]) -> None:
        pass

    def set_error_summary(self, summary: str) -> None:
        pass


class DummySpan:
    """Fallback span object if Trodo is not installed."""

    def set_input(self, data: Any) -> None:
        pass

    def set_output(self, data: Any) -> None:
        pass

    def set_metadata(self, data: Dict[str, Any]) -> None:
        pass


def init_tracing(site_id: Optional[str] = None) -> bool:
    """Initialize Trodo tracing once per runtime process."""
    global _INITIALIZED, _TRODO_AVAILABLE
    if not _TRODO_AVAILABLE or trodo is None:
        return False
    if _INITIALIZED:
        return True

    effective_site_id = site_id or os.getenv("TRODO_SITE_ID", DEFAULT_SITE_ID)
    try:
        trodo.init(site_id=effective_site_id)
        _INITIALIZED = True
        return True
    except Exception as err:
        print(f"[finagent.tracing] Failed to initialize Trodo tracing: {err}")
        return False


@contextmanager
def wrap_agent(
    name: str = DEFAULT_AGENT_NAME,
    distinct_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Context manager wrapping an entire agent execution run in Trodo."""
    init_tracing()

    effective_distinct_id = distinct_id or os.getenv("TRODO_DISTINCT_ID", "cli-user")
    if _INITIALIZED and trodo is not None:
        kwargs = {"distinct_id": effective_distinct_id}
        if metadata:
            kwargs["metadata"] = metadata
        with trodo.wrap_agent(name, **kwargs) as run:
            yield run
    else:
        yield DummyRun()


@contextmanager
def trace_span(name: str, kind: str = "trace"):
    """Context manager for child spans inside an agent run."""
    if _INITIALIZED and trodo is not None:
        with trodo.span(name, kind=kind) as s:
            yield s
    else:
        yield DummySpan()


def flush_tracing() -> None:
    """Flush pending telemetry batches to Trodo."""
    if _INITIALIZED and trodo is not None:
        try:
            trodo.flush()
        except Exception:
            pass
