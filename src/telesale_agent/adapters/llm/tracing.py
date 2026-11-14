"""Optional LangSmith tracing must not flood live traffic with auth failures."""

import logging
import os

from langsmith import Client, utils

logger = logging.getLogger(__name__)
_status = {"status": "disabled", "reason": "not_configured"}


def tracing_status() -> dict[str, str]:
    return dict(_status)


def configure_tracing() -> dict[str, str]:
    """Preflight the configured project once when building a runtime.

    Keep credentials on disk untouched. A denied/unavailable optional service
    is disabled for this process (and its MCP children) until the next restart.
    """
    global _status
    utils.get_env_var.cache_clear()
    utils.get_tracer_project.cache_clear()
    if not utils.tracing_is_enabled():
        # Preserve the diagnostic if this runtime has already disabled tracing.
        if _status.get("reason") not in {"authorization_failed", "unavailable", "missing_api_key"}:
            _status = {"status": "disabled", "reason": "not_configured"}
        return tracing_status()
    reason = None
    if not utils.get_env_var("API_KEY"):
        reason = "missing_api_key"
    else:
        client = None
        try:
            client = Client(timeout_ms=2000, auto_batch_tracing=False)
            client.read_project(project_name=utils.get_tracer_project())
        except utils.LangSmithNotFoundError:
            # LangSmith may create the configured project on its first trace.
            pass
        except Exception as exc:
            # Never log exception text: SDK errors may contain request details.
            message = str(exc).lower()
            reason = ("authorization_failed" if isinstance(exc, utils.LangSmithAuthError)
                      or "403" in message or "forbidden" in message or "workspace" in message
                      else "unavailable")
        finally:
            if client is not None:
                client.close(timeout=0)
    if reason:
        for name in ("LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2"):
            os.environ[name] = "false"
        utils.get_env_var.cache_clear()
        _status = {"status": "disabled", "reason": reason}
        logger.warning("LangSmith tracing disabled for this process (%s); check API key, project and workspace permissions before restarting.", reason)
    else:
        _status = {"status": "enabled"}
    return tracing_status()
