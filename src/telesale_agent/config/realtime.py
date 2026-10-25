"""Realtime settings are separate from text-model and offline ASR settings."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RealtimeSettings:
    enabled: bool = False
    model: str = "gemini-3.8-live"
    api_version: str = "v1beta"
    voice: str = "Kore"
    tools_mode: str = "read_only"
    max_sessions: int = 4
    queue_limit: int = 128
    idle_seconds: int = 120
    tool_timeout: int = 25
    session_seconds: int = 600
    origins: tuple[str, ...] = ("http://localhost:3000", "http://127.0.0.1:3000")

    @classmethod
    def from_env(cls):
        settings = cls(
            enabled=os.getenv("REALTIME_VOICE_ENABLED", "false").lower() in {"1", "true", "yes"},
            model=os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live").strip(),
            api_version=os.getenv("GEMINI_LIVE_API_VERSION", "v1beta"),
            voice=os.getenv("GEMINI_LIVE_VOICE", "Kore"),
            tools_mode=os.getenv("REALTIME_TOOLS_MODE", "read_only"),
            max_sessions=int(os.getenv("REALTIME_MAX_SESSIONS", "4")),
            queue_limit=int(os.getenv("REALTIME_AUDIO_QUEUE_LIMIT", "128")),
            idle_seconds=int(os.getenv("REALTIME_SESSION_IDLE_TIMEOUT_SECONDS", "120")),
            tool_timeout=int(os.getenv("REALTIME_TOOL_TIMEOUT_SECONDS", "25")),
            session_seconds=int(os.getenv("REALTIME_SESSION_MAX_SECONDS", "600")),
            origins=tuple(x.strip() for x in os.getenv(
                "REALTIME_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
            ).split(",") if x.strip()),
        )
        if settings.model != "gemini-3.8-live":
            raise ValueError("Realtime voice currently supports gemini-3.8-live only")
        if settings.tools_mode not in {"off", "read_only"}:
            raise ValueError("Voice write tools are not enabled: use off or read_only")
        if min(settings.max_sessions, settings.queue_limit, settings.idle_seconds,
               settings.tool_timeout, settings.session_seconds) < 1:
            raise ValueError("Realtime limits must be positive")
        if not settings.origins or "*" in settings.origins:
            raise ValueError("REALTIME_ALLOWED_ORIGINS must contain explicit origins")
        return settings
