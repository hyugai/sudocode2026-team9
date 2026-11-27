"""Load llama.cpp and run one Gemma server on one GPU."""

import json
import os
import socket
import subprocess
import tarfile
import time
from contextlib import contextmanager
from urllib.request import Request, urlopen


def download(url, path):
    subprocess.run(["curl", "-fsSL", "--retry", "2", "--connect-timeout", "30",
                    "-o", str(path), url], check=True)


def load_runtime(scratch):
    release = "b11627"
    runtime = scratch / "runtime"
    runtime.mkdir()
    for filename in (f"llama-{release}-bin-ubuntu-cuda-12.8-x64.tar.gz",
                     f"cudart-llama-{release}-bin-ubuntu-cuda-12.8-x64.tar.gz"):
        path = scratch / filename
        download(f"https://github.com/ggml-org/llama.cpp/releases/download/{release}/{filename}", path)
        with tarfile.open(path) as archive:
            archive.extractall(runtime, filter="data")
        path.unlink()
    return next(runtime.rglob("llama-server")), sorted({str(path.parent) for path in runtime.rglob("*.so*")})


def gpu_pair():
    listing = subprocess.check_output(["nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"], text=True)
    gpus = listing.split()
    if len(gpus) < 2:
        raise RuntimeError("Select GPU T4 ×2 in Kaggle.")
    return gpus[:2]


def request_json(url, payload=None, timeout=240):
    request = Request(url, data=None if payload is None else json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def complete(url, model_name, messages, schema, *, temperature=0, seed=2026, max_tokens=2048):
    response = request_json(f"{url}/v1/chat/completions", {
        "model": model_name, "messages": messages, "temperature": temperature, "seed": seed,
        "max_tokens": max_tokens, "response_format": {"type": "json_object", "schema": schema},
    })
    choice = response["choices"][0]
    if choice["finish_reason"] == "length":
        raise ValueError("Model output reached the token limit.")
    return json.loads(choice["message"]["content"])


@contextmanager
def model_server(runtime, model, gpu, log_path):
    executable, libraries = runtime
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=gpu)
    env["LD_LIBRARY_PATH"] = os.pathsep.join([*libraries, os.environ.get("LD_LIBRARY_PATH", "")])
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    args = [str(executable), "-m", str(model), "--alias", model.name, "--host", "127.0.0.1",
            "--port", str(port), "-ngl", "999", "--ctx-size", "8192", "--parallel", "1",
            "--reasoning", "off", "--no-webui", "--threads", "2", "--threads-batch", "2"]

    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(args, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 300
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    ready = request_json(f"{url}/health", timeout=2).get("status") == "ok"
                except OSError:
                    ready = False
                if ready:
                    break
                time.sleep(2)
            else:
                raise RuntimeError(f"Could not start {model.name}.")
            yield url
        except Exception:
            print(log_path.read_text(encoding="utf-8", errors="replace")[-3000:])
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
