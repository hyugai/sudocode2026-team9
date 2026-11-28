#!/usr/bin/env python3
"""Judge generated customer journeys with Gemma and DeepEval."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from importlib.util import find_spec
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
from tempfile import TemporaryDirectory
import venv


PHASE = Path(__file__).resolve().parents[1]
GEMMA_FILE = "gemma-4-12b-it-qat-q4_0.gguf"
DEEPEVAL_REQUIREMENT = "deepeval==4.3.4"
sys.path.insert(0, str(PHASE / "src"))
from judge_runtime import gpu_pair, load_runtime, model_server


def read_jsonl(path):
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def load_inputs(directory, candidate_file=None):
    cases = {row["scenario_id"]: row for row in read_jsonl(directory / "blueprints.jsonl")}
    personas = {row["persona_id"]: row for row in json.loads(
        (directory / "personas.json").read_text(encoding="utf-8"))["personas"]}
    rubrics = json.loads((directory / "prompts.json").read_text(encoding="utf-8"))["deepeval_rubrics"]

    attempts = {}
    for row in read_jsonl(candidate_file or directory / "candidates.jsonl"):
        attempts.setdefault(row["scenario_id"], []).append(row)
    if not attempts:
        raise ValueError("The candidates file is empty.")
    if unknown := attempts.keys() - cases.keys():
        raise ValueError(f"Candidates missing from the blueprints: {', '.join(sorted(unknown))}")

    selected = []
    for scenario_id, case in cases.items():
        if scenario_id in attempts:
            rows = sorted(attempts[scenario_id], key=lambda row: row["attempt"])
            candidate = next((row for row in rows if not row["format_errors"]), rows[-1])
            selected.append((case, candidate))
    return selected, personas, rubrics


def find_model():
    files = list(Path("/kaggle/input").rglob(GEMMA_FILE))
    if len(files) != 1:
        raise ValueError("Attach Gemma 4 12B IT QAT Q4_0 GGUF or set MODEL_PATH to its file.")
    return files[0]


@contextmanager
def load_judges(model, rubrics, count):
    if not count:
        yield []
        return

    model = model or find_model()
    gpus = gpu_pair()[:count]
    os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"
    os.environ["DEEPEVAL_DISABLE_DOTENV"] = "1"
    from judge_metric import Gemma, JourneyCheck

    with TemporaryDirectory() as directory, ExitStack() as servers:
        scratch = Path(directory)
        runtime = load_runtime(scratch)
        judges = []
        for index, gpu in enumerate(gpus):
            url = servers.enter_context(model_server(runtime, model, gpu, scratch / f"judge-{index}.log"))
            judges.append(JourneyCheck(Gemma(url, model.name), rubrics))
        yield judges


def judge_batch(batch, judges, pool, personas):
    reports = {}
    eligible = []
    for case, candidate in batch:
        sid = case["scenario_id"]
        errors = candidate["format_errors"]
        sessions = candidate["sessions"]
        if not errors and (not isinstance(sessions, dict) or sessions.keys() != case["sessions"].keys()):
            errors = ["Candidate sessions differ from the blueprint."]
        if errors:
            reports[sid] = {"outcome": "format_fail", "reason": "; ".join(errors)}
        else:
            eligible.append((case, candidate))

    def judge_group(judge, group):
        result = {}
        for case, candidate in group:
            try:
                report = judge.judge(case, candidate["sessions"], personas[case["persona_id"]])
            except (OSError, ValueError) as error:
                report = {"outcome": "review", "reason": str(error)}
            result[case["scenario_id"]] = report
        return result

    jobs = [pool.submit(judge_group, judge, eligible[index::len(judges)])
            for index, judge in enumerate(judges[:len(eligible)])]
    for job in jobs:
        reports.update(job.result())
    return reports


def write_row(file, row):
    file.write(json.dumps(row, ensure_ascii=False) + "\n")


def validate(selected, personas, rubrics, *, batch_size, journeys, output, model=None):
    if batch_size < 1 or journeys is not None and journeys < 1:
        raise ValueError("BATCH_SIZE and JOURNEYS must be positive. Use None for all journeys.")
    selected = selected[:journeys]
    num_batches = (len(selected) + batch_size - 1) // batch_size
    eligible = sum(not row["format_errors"] for _, row in selected)
    num_judges = min(2, batch_size, eligible)

    output.mkdir(parents=True, exist_ok=True)
    passed = 0
    with (load_judges(model, rubrics, num_judges) as judges,
          ThreadPoolExecutor(max_workers=max(1, num_judges)) as pool,
          (output / "transcripts.jsonl").open("w", encoding="utf-8") as transcripts,
          (output / "judge-report.jsonl").open("w", encoding="utf-8") as report_file):
        for offset in range(0, len(selected), batch_size):
            batch = selected[offset:offset + batch_size]
            print(f"Batch {offset // batch_size + 1}/{num_batches} · {len(batch)} journeys", flush=True)
            reports = judge_batch(batch, judges, pool, personas)
            for case, candidate in batch:
                sid = case["scenario_id"]
                report = reports[sid]
                write_row(report_file, {"scenario_id": sid, "attempt": candidate["attempt"], **report})
                if report["outcome"] == "pass":
                    write_row(transcripts, {"scenario_id": sid, **{
                        key: {"channel": case["sessions"][key]["channel"], "customer_turns": turns}
                        for key, turns in candidate["sessions"].items()
                    }})
                    passed += 1
            transcripts.flush()
            report_file.flush()
    print(f"{passed}/{len(selected)} journeys passed. {output}")


def prepare_environment(directory: str | Path) -> Path:
    venv.create(directory, with_pip=False)
    python = Path(directory) / "bin/python"
    packages = Path(sysconfig.get_path("purelib", scheme="venv", vars={"base": str(directory)}))
    # Kaggle puts sitecustomize on the standard library path, where a venv can still see it.
    (packages / "stage2_isolated.pth").write_text('import sys; sys.modules["sitecustomize"] = None\n', encoding="utf-8")
    pip = [sys.executable, "-I", "-m", "pip", "--isolated", "--python", str(python)]
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    subprocess.run([*pip, "install", "-q", DEEPEVAL_REQUIREMENT], check=True, env=env)
    print("Checking DeepEval dependencies...", flush=True)
    subprocess.run([*pip, "check"], check=True, env=env)
    return python


def run_validator(python: Path, arguments: list[str]) -> None:
    subprocess.run([str(python), "-I", "-B", "-u", str(Path(__file__).resolve()), *arguments], check=True)


def run_isolated(arguments: list[str]) -> None:
    with TemporaryDirectory(prefix="stage2-deepeval-") as directory:
        run_validator(prepare_environment(directory), arguments)


def main(arguments=None):
    arguments = sys.argv[1:] if arguments is None else arguments
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=PHASE / "input")
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--output-dir", type=Path, default=PHASE / "output")
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--isolated", action="store_true", help="Run DeepEval in a temporary Python environment.")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--journeys", type=int, default=5)
    selection.add_argument("--all", action="store_true", help="Validate every journey in the candidates file.")
    args = parser.parse_args(arguments)
    inputs = load_inputs(args.input_dir, args.candidates)
    journeys = None if args.all else args.journeys
    needs_judge = any(not row["format_errors"] for _, row in inputs[0][:journeys])
    if needs_judge and (args.isolated or find_spec("deepeval") is None):
        run_isolated([argument for argument in arguments if argument != "--isolated"])
        return
    validate(*inputs, batch_size=args.batch_size, journeys=journeys, output=args.output_dir, model=args.model)


if __name__ == "__main__":
    main()
