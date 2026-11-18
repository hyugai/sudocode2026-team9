"""Export verified journeys to the repository's nine-field SC-XXX format."""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import date
from pathlib import Path

from .agent import verify_release
from .common import file_hash, fingerprint, new_directory, read, verify_files, write

FIELDS = {"scenario_id", "level", "persona", "hard_case", "customer_phone", "customer_name", "honorific", "notes", "calls"}
PERSONAS = {"hesitant": "khach_do_du_hoi_nguoi_nha", "price_comparison": "khach_so_sanh_gia",
            "exchange": "khach_da_mua_doi_size", "many_questions": "khach_hoi_nhieu_khong_mua",
            "impatient_third_call": "khach_goi_lan_3_het_kien_nhan"}


def export_files(root: Path, *, migrating: bool = False) -> dict:
    excluded = {"manifest.json", ".gitignore"}
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("export must not contain symlinks")
        relative = str(path.relative_to(root))
        if not path.is_file() or relative in excluded or path.suffix == ".partial":
            continue
        if migrating and relative == "seal.json":
            continue
        result[relative] = file_hash(path)
    return result


def save_manifest(root: Path, manifest: dict, *, migrating: bool = False) -> None:
    payload = {k: v for k, v in manifest.items() if k != "integrity"}
    payload["format_version"] = 2
    write(root / "manifest.json", {**payload, "integrity": {
        "algorithm": "sha256", "manifest_payload_sha256": fingerprint(payload),
        "files": export_files(root, migrating=migrating)}})


def migrate_export(root: Path) -> dict:
    """Validate the old seal before consolidating it; retain rollback on failure."""
    manifest_path, seal_path = root / "manifest.json", root / "seal.json"
    manifest = read(manifest_path)
    if manifest.get("format_version") == 2:
        return verify_export(root)
    verify_files(root, read(seal_path)["files"])
    original_manifest, original_seal = manifest_path.read_bytes(), seal_path.read_bytes()
    try:
        save_manifest(root, manifest, migrating=True)
        seal_path.unlink()
        return verify_export(root)
    except Exception:
        manifest_path.write_bytes(original_manifest)
        seal_path.write_bytes(original_seal)
        raise


def scenario(sid: str, profile: str, plan: dict, transcripts: list[dict]) -> dict:
    calls = {}
    for i, (session, transcript) in enumerate(zip(plan["sessions"], transcripts)):
        facts, event = session["facts"], session["reference_event"]
        product, quote = facts["product"], facts["quote"]
        text = " ".join(u["text"] for u in transcript["utterances"])
        established = {"product_advised": product.get("parent_sku", product["sku"])}
        if str(facts["price_vnd"]) in text:
            established["price_quoted_vnd"] = facts["price_vnd"]
        if str(facts["customer_budget_vnd"]) in text:
            established["budget_vnd"] = facts["customer_budget_vnd"]
        if product.get("variant"):
            established.update(variant_sku=product["sku"], size=product["variant"]["size"], color=product["variant"]["color"])
        truth = {"price_vnd": facts["price_vnd"], "list_price_vnd": quote.get("list_price_vnd", facts["price_vnd"]),
                 "in_stock": facts["inventory"]["in_stock"]}
        for promo in quote.get("applied_promos", []):
            truth[f"promo_{promo['promo_code']}_active"] = True
        for promo in quote.get("expired_promos", []):
            code = promo["promo_code"] if isinstance(promo, dict) else promo
            truth[f"promo_{code}_active"] = False
        action = event["action"]
        if action == "consultation":
            success = {"tool_called": None, "must_not_call_tools": ["order.create", "order.update", "handoff.transfer"]}
            outcome = "hen_goi_lai" if i < len(transcripts) - 1 else "tu_choi"
        else:
            args = {k: v for k, v in event["args"].items() if k != "on"}
            # A fixture address is not automatically a fact spoken by the customer.
            if "address" in args and args["address"] not in text:
                args.pop("address")
            success, outcome = {"tool_called": action, "args_match": args}, "chot_don"
            established["order_id"] = event["result"]["order_id"]
            if action == "order.create":
                established["payment"] = event["args"]["payment"]
                if event["args"]["address"] in text:
                    established["delivery_address"] = event["args"]["address"]
            elif action == "order.update":
                truth.update(exchange_fee_vnd=event["result"]["fee_vnd"],
                             price_diff_vnd=event["result"]["price_diff_vnd"],
                             extra_payment_vnd=event["result"]["extra_payment_vnd"])
        call = {"channel": transcript["channel"], "channel_identity": transcript["customer_id"],
                "call_date": session["date"], "input_mode": "clean", "customer_goal": " ".join(session["goals"]),
                "customer_turns": [u["text"] for u in transcript["utterances"] if u["speaker"] == "customer"],
                "facts_established": established, "expected_outcome": outcome, "success_if": success,
                "ground_truth_facts": truth}
        if i:
            carried = [k for k in ("product_advised", "price_quoted_vnd") if k in calls[f"call_{i}"]["facts_established"]]
            call.update(must_carry_over=carried, must_not_ask=carried,
                        days_later=(date.fromisoformat(session["date"]) - date.fromisoformat(plan["sessions"][i-1]["date"])).days)
        calls[f"call_{i+1}"] = call
    return {"scenario_id": sid, "level": profile, "persona": PERSONAS[plan["persona"]],
            "hard_case": plan["sessions"][0]["hard_case"], "customer_phone": plan["customer_id"],
            "customer_name": "Khách tổng hợp " + plan["customer_id"].removeprefix("SYN-C"), "honorific": "chị",
            "notes": "Kịch bản tổng hợp từ transcript đã qua kiểm tra và same_agent_self_review, không phải trace agent thực tế. "
                     "Tên là nhãn fixture, customer_phone/channel_identity là ID tổng hợp, không phải số điện thoại thật; harness cần hỗ trợ ID này. "
                     "Reset state giữa scenario, giữ state giữa các call. Mã đơn lấy từ mock tham chiếu; lời khách báo nhận hàng không chứng minh backend delivered. "
                     "hen_goi_lai chỉ việc còn trao đổi tiếp, không tự thêm lịch callback. chot_don với order.update nghĩa là ghi nhận yêu cầu đổi, chưa hoàn tất đổi. "
                     "Không gán địa chỉ fixture chưa được nói thành fact khách đã cung cấp; args_match chỉ giữ địa chỉ khi có trong hội thoại. "
                     "Chỉ đưa channel/identity/customer_turns vào agent; giữ ground_truth_facts và success_if riêng để chấm. "
                     "Định dạng đã kiểm tra; chưa chạy benchmark với agent thật.", "calls": calls}


def export(runs: list[Path], output: Path, start: int = 1) -> dict:
    if not runs or type(start) is not int or start < 1:
        raise ValueError("provide finalized runs and a positive start ID")
    sources, seen_runs, seen_customers, rows = [], set(), set(), []
    for root in runs:
        root = root.resolve()
        verify_release(root)
        settings, report = read(root / "settings.json"), read(root / "final_report.json")
        if settings["run_id"] in seen_runs or report["status"] not in {"completed", "partial_coverage"}:
            raise ValueError("runs must be distinct, finalized and free of quarantined journeys")
        seen_runs.add(settings["run_id"])
        sources.append({"run_id": settings["run_id"], "path": str(root), "seal_sha256": file_hash(root / "final.seal.json")})
        provenance = root / "generation/provenance.json"
        if provenance.is_file():
            sources[-1]["provenance"] = read(provenance)
        plans = {p["journey_id"]: p for p in read(root / "generation/plan/plans.json")}
        grouped = {}
        for item in read(root / "generation/manifest.json"):
            grouped.setdefault(item["journey_id"], []).append(item)
        for jid, items in grouped.items():
            plan = plans[jid]
            if plan["customer_id"] in seen_customers:
                raise ValueError("duplicate customer across scenarios; select additional distinct journeys")
            seen_customers.add(plan["customer_id"])
            items.sort(key=lambda r: read(root / "generation" / r["path"])["session_index"])
            transcripts = [read(root / "generation" / item["path"]) for item in items]
            rows.append((root, settings, plan, items, transcripts))
    output = new_directory(output)
    manifest = {"format_version": 2, "scope": "partial M1/M2 sample; not full dataset coverage",
                "sources": sources, "scenarios": []}
    for number, (root, settings, plan, items, transcripts) in enumerate(rows, start):
        sid = f"SC-{number:03d}"
        path = output / "scenarios_complete" / f"{sid}.json"
        write(path, scenario(sid, settings["profile"], plan, transcripts))
        links = []
        for item in items:
            relative = "transcripts/" + Path(item["path"]).name
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / "generation" / item["path"], destination)
            links.append({"transcript_id": item["transcript_id"], "path": relative, "sha256": file_hash(destination)})
        manifest["scenarios"].append({"scenario_id": sid, "path": str(path.relative_to(output)), "sha256": file_hash(path),
                                      "source_run_id": settings["run_id"], "source_journey_id": plan["journey_id"], "transcripts": links})
    manifest.update(scenario_count=len(rows), transcript_count=sum(len(row[3]) for row in rows))
    lines = ["# Bộ mẫu scenario M1", "", f"Có {manifest['scenario_count']} scenario, gồm {manifest['transcript_count']} transcript. Mỗi SC là một hành trình hoàn chỉnh.", "",
             "| Scenario | Hành trình nguồn | Số phiên |", "| --- | --- | --- |"]
    lines += [f"| [{r['scenario_id']}]({r['path']}) | {r['source_journey_id']} | {len(r['transcripts'])} |" for r in manifest["scenarios"]]
    lines += ["", "JSON theo chín trường của scenarios_complete; chỉ chứa lượt khách và điều kiện chấm. Đối thoại đầy đủ giữ nguyên byte trong `transcripts/`.",
              "Tên/định danh đều là fixture tổng hợp, không sao chép tên/số điện thoại từ bộ M1 cũ. Không có audio hoặc kết quả benchmark thật.",
              "Ground truth và tool expectations lấy từ plan đóng băng; không tự biến facts ẩn thành lời khách đã cung cấp. Một số transcript cũ không đọc đủ địa chỉ: không chấm địa chỉ đó như thông tin đã nói; harness cần bổ sung luồng xác nhận nếu cần.",
              "Same-agent self-review không phải đánh giá độc lập. Đây là bộ mẫu, chưa đạt toàn bộ coverage M1.",
              "", "[Manifest, checksum và liên kết run nguồn](manifest.json). Giữ các run nguồn để replay đầy đủ.", ""]
    (output / "README.md").write_text("\n".join(lines), encoding="utf-8")
    save_manifest(output, manifest)
    return verify_export(output)


def verify_export(root: Path) -> dict:
    manifest = read(root / "manifest.json")
    if manifest.get("format_version") != 2:
        raise ValueError("legacy export: run --migrate-manifest before verification")
    integrity = manifest.get("integrity", {})
    payload = {k: v for k, v in manifest.items() if k != "integrity"}
    if integrity.get("algorithm") != "sha256" or integrity.get("manifest_payload_sha256") != fingerprint(payload):
        raise ValueError("manifest integrity mismatch")
    if integrity.get("files") != export_files(root):
        raise ValueError("export files/checksums changed")
    if len(manifest["scenarios"]) != manifest["scenario_count"]:
        raise ValueError("scenario count differs from manifest")
    count = 0
    for row in manifest["scenarios"]:
        obj = read(root / row["path"])
        if set(obj) != FIELDS or obj["scenario_id"] != row["scenario_id"] or Path(row["path"]).name != obj["scenario_id"] + ".json":
            raise ValueError("scenario format/name mismatch")
        if file_hash(root / row["path"]) != row["sha256"] or len(obj["calls"]) != len(row["transcripts"]):
            raise ValueError("scenario checksum/session count mismatch")
        for i, link in enumerate(row["transcripts"], 1):
            t = read(root / link["path"])
            call = obj["calls"][f"call_{i}"]
            if file_hash(root / link["path"]) != link["sha256"] or call["customer_turns"] != [u["text"] for u in t["utterances"] if u["speaker"] == "customer"]:
                raise ValueError("scenario customer turns differ from source transcript")
            if call["channel"] != t["channel"] or call["call_date"] != t["date"] or obj["customer_phone"] != t["customer_id"]:
                raise ValueError("scenario identity/channel/date changed")
            count += 1
    if count != manifest["transcript_count"]:
        raise ValueError("transcript count mismatch")
    return {"status": "verified_scenario_export", "scenarios": len(manifest["scenarios"]), "transcripts": count,
            "output": str(root.resolve()), "system_benchmark_run": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-id", type=int, default=1)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--migrate-manifest", action="store_true", help="consolidate a verified legacy export seal into manifest v2")
    args = parser.parse_args()
    try:
        result = migrate_export(args.output) if args.migrate_manifest else verify_export(args.output) if args.verify else export(args.run, args.output, args.start_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "detail": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
