"""Generate complete Vietnamese customer journeys on two Kaggle GPUs."""

import json
import os
import re
from pathlib import Path
import socket
import subprocess
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from threading import Lock
from urllib.request import Request, urlopen


KAGGLE_INPUT = Path("/kaggle/input")
QWEN_FILE = "Qwen3-30B-A3B-Q4_K_M.gguf"
ROLE_LABEL = re.compile(
    r"^\s*(kh[aá]ch(?: h[aà]ng)?|nh[aâ]n vi[eê]n|t[oổ]ng [dđ][aà]i|agent|customer|assistant)\s*:", re.I)
PLACEHOLDER = re.compile(
    r"\b(?:TBD|XXX|TODO)\b"
    r"|\[\s*(?:địa chỉ(?: giao hàng)?|số điện thoại|sđt|tên khách(?: hàng)?|tên sản phẩm|sản phẩm|giá|"
    r"chi tiết liên hệ|addr_(?:alt_)?cust_\d+|address|phone|name|customer_name|product)\s*\]"
    r"|\{\{?\s*[a-z_][a-z_0-9]*\s*\}\}?|<\s*[a-z_][a-z_0-9]*\s*>", re.I)


def load_inputs(directory):
    cases = read_jsonl(directory / "blueprints.jsonl")
    personas = {row["persona_id"]: row for row in json.loads(
        (directory / "personas.json").read_text(encoding="utf-8"))["personas"]}
    prompts = json.loads((directory / "prompts.json").read_text(encoding="utf-8"))
    return cases, personas, prompts

def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_row(file, value):
    file.write(json.dumps(value, ensure_ascii=False) + "\n")
    file.flush()


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
def model_server(runtime, model, gpus, log_path, slots=1):
    executable, libraries = runtime
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=",".join(gpus))
    env["LD_LIBRARY_PATH"] = os.pathsep.join([*libraries, os.environ.get("LD_LIBRARY_PATH", "")])
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    args = [str(executable), "-m", str(model), "--alias", model.name, "--host", "127.0.0.1",
            "--port", str(port), "-ngl", "999", "--ctx-size", str(8192 * slots),
            "--parallel", str(slots), "--reasoning", "off", "--no-webui"]
    args.extend(["--split-mode", "layer", "--tensor-split", "1,1", "--cont-batching"])

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


def format_errors(sessions, plans):
    if not isinstance(sessions, dict) or sessions.keys() != plans.keys():
        return ["Use exactly the planned session keys."]

    errors = []
    for key, turns in sessions.items():
        if (not isinstance(turns, list) or not 2 <= len(turns) <= 5
                or any(not isinstance(turn, str) or not turn.strip() or turn.splitlines() != [turn]
                       for turn in turns)):
            errors.append(f"{key} needs 2–5 nonempty single-line customer turns.")
        elif any(ROLE_LABEL.search(turn) or PLACEHOLDER.search(turn) for turn in turns):
            errors.append(f"{key} contains a speaker label or an unfilled placeholder.")
    return errors


def generate_journey(case, personas, prompts, url, model_name, save):
    keys = list(case["sessions"])
    schema = {"type": "object", "required": keys, "additionalProperties": False,
              "properties": {key: {"type": "array", "minItems": 2, "maxItems": 5,
                                   "items": {"type": "string"}} for key in keys}}
    persona = personas[case["persona_id"]]
    goals = "; ".join(session["customer_goal"] for session in case["sessions"].values())
    blueprint = {
        **case,
        "persona_prompt": persona["system_prompt"].format(goal=goals, **prompts["persona_prompt_values"]),
        "persona_style": persona["style"],
        "persona_patience": persona["patience_initial"],
        "sessions": {key: {**plan, "required_facts": [
            {"meaning": fact["meaning"], "value": fact["value"]} for fact in plan["required_facts"]
        ]} for key, plan in case["sessions"].items()},
    }
    system = prompts["generation_system_prompt"] + (
        "\nNếu dữ kiện giữ nguyên, khách có thể quy chiếu rõ đến phiên trước. "
        "Nêu đúng dữ kiện mới hoặc đã thay đổi trong phiên tương ứng."
    )

    errors = []
    for attempt in (1, 2):
        prompt = {**blueprint, "retry_feedback": errors} if errors else blueprint
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}]
        try:
            sessions = complete(url, model_name, messages, schema, temperature=0.7, seed=2025 + attempt)
            errors = format_errors(sessions, case["sessions"])
        except ValueError as error:
            sessions, errors = None, [str(error)]
        save({"scenario_id": case["scenario_id"], "attempt": attempt,
              "sessions": sessions, "format_errors": errors})
        if not errors:
            return True
    return False


def find_model(model=None):
    if model is None:
        matches = [path for path in KAGGLE_INPUT.rglob(QWEN_FILE) if path.is_file()]
        if len(matches) != 1:
            raise ValueError(f"Expected one attached {QWEN_FILE}. Attach the Kaggle Qwen 3 GGUF model or set MODEL_PATH.")
        model = matches[0]
    if model.suffix.lower() != ".gguf" or not model.is_file():
        raise ValueError(f"MODEL_PATH must point to a GGUF file. Found {model}")
    return model


def generate(cases, personas, prompts, *, batch_size, journeys, output, model=None):
    if batch_size < 1 or journeys is not None and not 1 <= journeys <= len(cases):
        raise ValueError("Set a positive BATCH_SIZE and a valid JOURNEYS count, or use None for the full input.")
    cases = cases[:journeys]
    if not cases:
        raise ValueError("The attached blueprints are empty.")

    model = find_model(model)
    gpus = gpu_pair()
    output.mkdir(parents=True, exist_ok=True)
    slots = min(4, batch_size, len(cases))
    batch_count = (len(cases) + batch_size - 1) // batch_size
    passed = 0
    lock = Lock()
    with TemporaryDirectory() as directory:
        scratch = Path(directory)
        runtime = load_runtime(scratch)
        with (model_server(runtime, model, gpus, scratch / "writer.log", slots) as url,
              (output / "candidates.jsonl").open("w", encoding="utf-8") as file,
              ThreadPoolExecutor(max_workers=slots) as pool):
            def save(value):
                with lock:
                    write_row(file, value)

            def write_journey(case):
                return generate_journey(case, personas, prompts, url, model.name, save)

            for start in range(0, len(cases), batch_size):
                batch = cases[start:start + batch_size]
                print(f"Batch {start // batch_size + 1}/{batch_count} · {len(batch)} journeys", flush=True)
                passed += sum(pool.map(write_journey, batch))
    print(f"{passed}/{len(cases)} journeys passed format checks. {output / 'candidates.jsonl'}")
