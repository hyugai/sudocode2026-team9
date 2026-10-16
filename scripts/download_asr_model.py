"""Download the official sherpa-onnx export of hynt's Vietnamese Zipformer.

Run once before using voice input. Serving requests never downloads models.
"""

import argparse
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv

from telesale_agent.adapters.asr.config import ASRConfig, MODEL_FILES, MODEL_NAME, MODEL_URL


def download_model(destination: Path) -> None:
    if all((destination / name).is_file() and (destination / name).stat().st_size for name in MODEL_FILES):
        print(f"Model already available: {destination.resolve()}")
        return

    with tempfile.TemporaryDirectory(prefix="zipformer-download-") as directory:
        archive_path = Path(directory) / "model.tar.bz2"
        print(f"Downloading {MODEL_URL}", flush=True)
        with urlopen(MODEL_URL, timeout=60) as response, archive_path.open("wb") as output:
            shutil.copyfileobj(response, output)
        with tarfile.open(archive_path, "r:bz2") as archive:
            names = [*MODEL_FILES, "bpe.model", "test_wavs/0.wav"]
            # Extract only known regular files; never trust paths or links in a tar.
            members = [archive.getmember(f"{MODEL_NAME}/{name}") for name in names]
            if any(not member.isfile() or member.size <= 0 for member in members):
                raise ValueError("The model archive contains invalid files")
            destination.mkdir(parents=True, exist_ok=True)
            for name, member in zip(names, members):
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                pending = target.with_name(target.name + ".tmp")
                with archive.extractfile(member) as source, pending.open("wb") as output:
                    shutil.copyfileobj(source, output)
                pending.replace(target)
    print(f"Model ready: {destination.resolve()}")


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=ASRConfig.from_env().model_dir)
    args = parser.parse_args()
    download_model(args.model_dir)
