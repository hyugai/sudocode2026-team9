"""Extractive, source-backed knowledge repair. No business mutations."""
import time
from self_agent.models import digest, redact, sanitize, shared_question


class KnowledgeGapLoop:
    def __init__(self, memory, model, search):
        self.memory, self.model, self.search = memory, model, search

    async def process(self, job_id, snapshot):
        started = time.perf_counter()
        before = dict(getattr(self.model, "usage", {}))
        detected = await self.model.json(
            'Find unanswered business questions AND incorrect/confident unsupported answers. '
            'Compare each answer with its own turn_evidence: price, SKU, dates, conditions, tool success. '
            'Detect wrong context, contradictions with sources, fabricated action success and claims without evidence. '
            'Output {"gaps":[{"message_id": integer customer message_id, "turn_id": integer evidence turn_id, '
            '"reason":"missing_knowledge|retrieval_failure|reasoning_failure|tool_failure|unsupported_claim|context_mismatch"}]}. '
            'Reference real IDs; do not rewrite questions. Missing evidence means unverified, not proven false. '
            'Do not infer missing policies from preferences. Exclude personal data.', snapshot)
        customer_messages = {m.get("message_id", i): m["content"] for i, m in enumerate(snapshot["messages"])
                             if m["role"] in {"user", "customer"}}
        questions = {redact(m["content"]) for m in snapshot["messages"] if m["role"] in {"user", "customer"}}
        questions.update(snapshot["open_questions"])
        candidates = detected.get("gaps", [])
        if not isinstance(candidates, list) or any(not isinstance(item, dict) for item in candidates):
            raise ValueError("Detector gaps must be an array of objects")
        skipped_unmatched = 0
        results = []
        for item in candidates[:20]:
            message_id = item.get("message_id")
            question = customer_messages.get(message_id) if type(message_id) is int else None
            question = question or redact(item.get("question", "")).strip()
            # Ground gap detection in a real question, not a model-invented fact.
            if not question or question not in questions:
                skipped_unmatched += 1
                continue
            reason = item.get("reason")
            if reason not in {"missing_knowledge", "retrieval_failure", "reasoning_failure", "tool_failure", "unsupported_claim", "context_mismatch"}:
                reason = "missing_knowledge"
            generic_question = shared_question(question)
            key = digest([generic_question, reason])
            try:
                gap = self.memory.read("gaps", key)
            except FileNotFoundError:
                gap = {"id": key, "question": generic_question, "occurrences": []}
            if job_id not in gap["occurrences"]:
                gap["occurrences"].append(job_id)
            gap.update(reason=reason, status="pending_evidence")
            if reason in {"reasoning_failure", "tool_failure", "unsupported_claim", "context_mismatch"}:
                evidence = next((e for e in snapshot.get("turn_evidence", [])
                                 if type(item.get("turn_id")) is int and e["turn_id"] == item["turn_id"]), None)
                if evidence is not None:
                    checked = await self.model.json(
                        'Verify the alleged issue against this exact turn evidence and conversation. '
                        'Return {"valid":true} only for a supported contradiction, wrong context or unverified claim; '
                        'never treat absent evidence as proof a fact is false.',
                        {"reason": reason, "question": question, "evidence": evidence,
                         "conversation": snapshot["messages"]})
                    if checked.get("valid") is True:
                        patterns = {
                            "reasoning_failure": "Đối chiếu câu trả lời với nguồn và kết quả tool; không bỏ điều kiện quan trọng.",
                            "tool_failure": "Chỉ xác nhận hành động thành công khi tool trả kết quả thành công.",
                            "unsupported_claim": "Chưa có bằng chứng thì nêu rõ chưa xác minh; không khẳng định như sự thật.",
                            "context_mismatch": "Đối chiếu sản phẩm và nhu cầu hiện tại trước khi dùng thông tin đã nhớ."}
                        pattern = {"id": key, "reason": reason, "pattern": patterns[reason],
                                   "status": "approved", "scope": "general",
                                   "criterion": patterns[reason]}
                        self.memory.write("patterns", key, pattern)
                        self.memory.write("regression_cases", key, pattern)
                        gap.update(status="pending_remediation", pattern_ref=key, test_refs=[key])
            else:
                source = await self.search(question)
                # Resolver selects full chunks; it cannot author a new policy.
                chunks = [c for c in source.get("chunks", []) if c.get("source_file") and c.get("content")
                          and c.get("is_expired", False) is False and c.get("audience", "customer") == "customer"
                          and sanitize(c["content"]) == c["content"]]
                chosen = await self.model.json(
                    'Select a source chunk that fully answers the question, including all conditions. '
                    'Return {"index": integer or null, "safe_to_publish": boolean}. '
                    'False for ambiguous/conflicting sources, personal data, new policy, prices or promotions.',
                    {"question": question, "chunks": chunks}) if chunks else {}
                index = chosen.get("index")
                if chosen.get("safe_to_publish") is True and type(index) is int and 0 <= index < len(chunks):
                    chunk = chunks[index]
                    # Second pass checks entailment; output is still the complete original evidence.
                    verdict = await self.model.json(
                        'Independently check if the complete source answers the question without inventing facts, '
                        'has no PII and is appropriate for customers. Return {"valid": boolean}.',
                        {"question": question, "source": chunk})
                    if verdict.get("valid") is True:
                        case = {"id": key, "question": generic_question, "expected_content": chunk["content"],
                                "source_file": chunk["source_file"], "chunk_id": chunk.get("chunk_id", ""),
                                "source_hash": digest(chunk), "status": "approved"}
                        from .regression import check_case
                        if not check_case(case, chunk):
                            raise ValueError("Generated regression source contract failed")
                        self.memory.write("knowledge", key, case)
                        self.memory.write("regression_cases", key, {**case, "criterion": "answer supported by full source"})
                        self.memory.write("releases", key, {"id": key, "knowledge_id": key, "source_hash": digest(chunk)})
                        gap.update(status="resolved", resolution_ref=key, test_refs=[key])
            self.memory.write("gaps", key, gap)
            results.append({"id": key, "status": gap["status"]})
        report = {"job_id": job_id, "gaps": results,
                  "detection": {"candidate_count": len(candidates),
                                "processed_count": len(results),
                                "skipped_unmatched_question": skipped_unmatched,
                                "skipped_over_limit": max(0, len(candidates) - 20)},
                  "outcome": ("no_candidates" if not candidates else
                              "all_candidates_filtered" if not results else "gaps_processed"),
                  "learning_duration_ms": round((time.perf_counter() - started) * 1000),
                  "learning_usage": {k: v - before.get(k, 0) for k, v in getattr(self.model, "usage", {}).items()}}
        self.memory.write("reports", job_id, report)
        return report
