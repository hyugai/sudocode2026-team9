"""Configuration shared by local ASR and the model download command."""

from dataclasses import dataclass
import os
from pathlib import Path


MODEL_NAME = "sherpa-onnx-zipformer-vi-30M-int8-2026-02-09"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    f"{MODEL_NAME}.tar.bz2"
)
MODEL_FILES = ("encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx", "tokens.txt")


@dataclass(frozen=True)
class ASRConfig:
    model_dir: Path = Path("models") / MODEL_NAME
    num_threads: int = 2
    max_upload_bytes: int = 25 * 1024 * 1024
    max_duration_seconds: int = 120
    ffmpeg_path: str | None = None

    def __post_init__(self) -> None:
        if min(self.num_threads, self.max_upload_bytes, self.max_duration_seconds) <= 0:
            raise ValueError("ASR thread count and audio limits must be positive")

    @classmethod
    def from_env(cls) -> "ASRConfig":
        return cls(
            model_dir=Path(os.getenv("ASR_MODEL_DIR", str(cls.model_dir))).expanduser(),
            num_threads=int(os.getenv("ASR_NUM_THREADS", "2")),
            max_upload_bytes=int(os.getenv("ASR_MAX_UPLOAD_MB", "25")) * 1024 * 1024,
            max_duration_seconds=int(os.getenv("ASR_MAX_DURATION_SECONDS", "120")),
            ffmpeg_path=os.getenv("ASR_FFMPEG_PATH") or None,
        )
