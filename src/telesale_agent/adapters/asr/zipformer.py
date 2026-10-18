"""Run hynt/Zipformer-30M-RNNT-6000h locally using sherpa-onnx on CPU.

The model is the sherpa-onnx export documented at:
https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-transducer/zipformer-transducer-models.html
No downloads or external ASR requests are made while handling a turn.
"""

import asyncio
from pathlib import Path
import subprocess
import tempfile
import threading

from telesale_agent.core.errors import (
    ASRUnavailableError,
    AudioInputError,
    AudioTooLargeError,
)
from telesale_agent.core.models import TurnContext

from .config import ASRConfig, MODEL_FILES


class ZipformerASREngine:
    def __init__(self, config: ASRConfig | None = None) -> None:
        self.config = config or ASRConfig.from_env()
        self._recognizer = None
        self._lock = threading.Lock()

    async def transcribe(self, context: TurnContext) -> str | None:
        if context.input.text:
            return context.input.text
        if context.input.audio is None:
            return None
        audio = context.input.audio
        if not audio:
            raise AudioInputError("File ghi âm rỗng. Vui lòng chọn file có giọng nói.")
        if len(audio) > self.config.max_upload_bytes:
            raise AudioTooLargeError("File ghi âm vượt quá dung lượng cho phép.")
        # Loading, decoding, and inference must not block the API event loop.
        return await asyncio.to_thread(self._transcribe_sync, audio)

    def _load_recognizer(self):
        if self._recognizer is not None:
            return self._recognizer
        missing = [name for name in MODEL_FILES if not (self.config.model_dir / name).is_file()]
        if missing:
            raise ASRUnavailableError(
                "Chưa có model ASR local. Chạy python scripts/download_asr_model.py "
                "và kiểm tra ASR_MODEL_DIR."
            )
        try:
            import sherpa_onnx

            self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(self.config.model_dir / "encoder.int8.onnx"),
                decoder=str(self.config.model_dir / "decoder.onnx"),
                joiner=str(self.config.model_dir / "joiner.int8.onnx"),
                tokens=str(self.config.model_dir / "tokens.txt"),
                num_threads=self.config.num_threads,
                sample_rate=16000,
                feature_dim=80,
                decoding_method="greedy_search",
                provider="cpu",
                debug=False,
            )
        except (ImportError, OSError, RuntimeError) as exc:
            raise ASRUnavailableError(
                'Không thể nạp Zipformer local. Cài pip install -e ".[voice]" '
                "và kiểm tra các file model."
            ) from exc
        return self._recognizer

    def _decode_audio(self, audio: bytes):
        try:
            import numpy as np
            import imageio_ffmpeg

            ffmpeg = self.config.ffmpeg_path or imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError) as exc:
            raise ASRUnavailableError(
                'Chưa có bộ giải mã âm thanh local. Cài pip install -e ".[voice]".'
            ) from exc

        # A real temporary file also supports containers that require seeking (M4A).
        # Do not use the untrusted upload filename or retain recordings after ASR.
        with tempfile.TemporaryDirectory(prefix="telesale-asr-") as directory:
            source = Path(directory) / "recording"
            source.write_bytes(audio)
            try:
                decoded = subprocess.run(
                    [
                        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-threads", "1", "-protocol_whitelist", "file,pipe",
                        "-format_whitelist", "wav,mp3,mov,matroska,webm,flac,ogg",
                        "-i", str(source), "-vn", "-ac", "1",
                        "-ar", "16000", "-t", str(self.config.max_duration_seconds + 1),
                        "-f", "f32le", "pipe:1",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except OSError as exc:
                raise ASRUnavailableError("Không thể chạy FFmpeg local. Kiểm tra ASR_FFMPEG_PATH.") from exc
            except subprocess.TimeoutExpired as exc:
                raise AudioInputError("Giải mã ghi âm quá lâu. Hãy thử file ngắn hơn.") from exc

        if decoded.returncode != 0 or not decoded.stdout:
            raise AudioInputError(
                "Không đọc được âm thanh. Hãy dùng WAV, MP3, M4A, FLAC, OGG hoặc WebM hợp lệ."
            )
        samples = np.frombuffer(decoded.stdout, dtype="<f4").copy()
        if samples.size > self.config.max_duration_seconds * 16000:
            raise AudioInputError(
                f"Ghi âm dài quá {self.config.max_duration_seconds} giây. Hãy chia thành từng lượt thoại."
            )
        if not np.isfinite(samples).all():
            raise AudioInputError("File ghi âm chứa dữ liệu âm thanh không hợp lệ.")
        return samples

    def _transcribe_sync(self, audio: bytes) -> str:
        # Share a single cached recognizer safely across concurrent conversations.
        with self._lock:
            samples = self._decode_audio(audio)
            recognizer = self._load_recognizer()
            try:
                stream = recognizer.create_stream()
                stream.accept_waveform(16000, samples)
                recognizer.decode_stream(stream)
                transcript = stream.result.text.strip()
            except RuntimeError as exc:
                raise ASRUnavailableError("Zipformer local không thể nhận dạng ghi âm lúc này.") from exc
        if not transcript:
            raise AudioInputError("Không nhận dạng được giọng nói. Vui lòng thử ghi âm rõ hơn.")
        return transcript
