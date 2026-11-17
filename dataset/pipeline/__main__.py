from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .common import code_hashes, read, verify_files
from .providers import OpenAIProvider, ReplayProvider, RoutedProvider
from .runner import generate_run, plan_run, verify_plan, verify_run


def main() -> int:
    parser = argparse.ArgumentParser(description="Sinh transcript JSON độc lập từ cấu hình và dữ liệu nghiệp vụ.")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="đóng băng nguồn và tạo kế hoạch, không gọi API")
    plan.add_argument("--config", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    plan.add_argument("--reference-dir", type=Path, action="append", default=[])
    gen = sub.add_parser("generate", help="gọi OpenAI; mặc định chỉ một hành trình")
    gen.add_argument("--plan", type=Path, required=True)
    gen.add_argument("--output", type=Path, required=True)
    gen.add_argument("--model", help="model ID OpenAI hỗ trợ Structured Outputs")
    gen.add_argument("--review-model", help="model kiểm định; mặc định dùng model sinh trong lượt gọi riêng")
    group = gen.add_mutually_exclusive_group()
    group.add_argument("--limit", type=int, default=1)
    group.add_argument("--all", action="store_true")
    replay = sub.add_parser("replay", help="kiểm tra lại bằng response đã lưu; không API")
    replay.add_argument("--run", type=Path, required=True)
    replay.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify", help="kiểm tra checksum, schema JSON, review và liên kết phiên")
    verify.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            report = plan_run(args.config, args.output, args.reference_dir)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["transcript_requirements_met"] else 3
        if args.command == "generate":
            config, _, _ = verify_plan(args.plan)
            model = args.model or os.environ.get("OPENAI_MODEL") or config["generation"]["model"]
            review_model = args.review_model or config["review"]["model"]
            if review_model == "SAME_AS_GENERATOR":
                review_model = model
            provider = RoutedProvider(OpenAIProvider(model, config["generation"]["max_output_tokens"]),
                                      OpenAIProvider(review_model, config["review"]["max_output_tokens"]))
            result = generate_run(args.plan, args.output, provider, limit=None if args.all else args.limit)
        elif args.command == "replay":
            verify_files(args.run, read(args.run / "seal.json")["files"])
            original = read(args.run / "run.json")
            if original["kind"] != "generation" or original["code_sha256"] != code_hashes():
                raise ValueError("replay needs a generation run made with identical pipeline code/prompts/schema")
            provider = ReplayProvider(args.run)
            result = generate_run(args.run / "plan", args.output, provider, limit=original["limit"])
        else:
            print(json.dumps(verify_run(args.run), ensure_ascii=False, indent=2))
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] in {"provider_stopped", "quarantined"}:
            return 2
        return 0 if result["coverage"]["transcript_requirements_met"] else 3
    except ImportError:
        print("Install the OpenAI SDK for live generation: python -m pip install 'openai>=2,<3'", file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        # SDK errors may include request content; avoid displaying credential-bearing errors.
        if type(exc).__module__.startswith("openai"):
            print(f"OpenAI setup failed: {type(exc).__name__}", file=sys.stderr)
        else:
            print(f"Stopped: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
