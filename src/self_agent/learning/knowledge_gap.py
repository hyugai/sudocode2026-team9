"""Extractive, source-backed knowledge repair. No business mutations."""
import time
from self_agent.models import digest, redact, sanitize, shared_question


def evidence_value(payload, path):
    """Resolve a data-only reference, never evaluate model-provided expressions."""
    if not isinstance(path, str) or path.split('.')[0] not in {"evidence", "conversation"}:
        raise ValueError("Invalid evidence path")
    value = payload
    for part in path.split('.'):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


class KnowledgeGapLoop:
    def __init__(self, memory, model, search):
        self.memory, self.model, self.search = memory, model, search

    async def process(self, job_id, snapshot):
        started = time.perf_counter()
        before = dict(getattr(self.model, "usage", {}))
        detector_error = None
        try:
            detected = await self.model.json(
            'Find unanswered business questions AND incorrect/confident unsupported answers. '
            'Compare each answer with its own turn_evidence: price, SKU, dates, conditions, tool success. '
            'Detect wrong context, contradictions with sources, fabricated action success and claims without evidence. '
            'Output {"gaps":[{"message_id": integer customer message_id, "turn_id": integer evidence turn_id, '
            '"reason":"missing_knowledge|retrieval_failure|reasoning_failure|tool_failure|unsupported_claim|context_mismatch"}]}. '
            'Reference real IDs; do not rewrite questions. Missing evidence means unverified, not proven false. '
                'Do not infer missing policies from preferences. An honest admission of missing information '
                'is still an unresolved knowledge gap. Include open_questions. Exclude personal data.', snapshot)
        except Exception as exc:
            detector_error = type(exc).__name__
            detected = {"gaps": []}
        if not isinstance(detected, dict) or not isinstance(detected.get("gaps"), list) or any(
                not isinstance(c, dict) for c in detected.get("gaps", [])):
            detector_error = "InvalidDetectorSchema"
            detected = {"gaps": []}
        customer_messages = {m.get("message_id", i): m["content"] for i, m in enumerate(snapshot["messages"])
                             if m["role"] in {"user", "customer"}}
        questions = {redact(m["content"]) for m in snapshot["messages"] if m["role"] in {"user", "customer"}}
        questions.update(snapshot["open_questions"])
        candidates = detected.get("gaps", [])
        if not isinstance(candidates, list) or any(not isinstance(item, dict) for item in candidates):
            raise ValueError("Detector gaps must be an array of objects")
        detector_candidate_count = len(candidates)
        # Authoritative unresolved questions must survive empty/failed detection.
        # Process them first so the model candidate cap cannot drop the backlog.
        forced = [{"question": q, "reason": "missing_knowledge", "origin": "open_questions"}
                  for q in dict.fromkeys(snapshot["open_questions"]) if isinstance(q, str) and q.strip()]
        candidates = forced + candidates[:20]
        skipped_unmatched = 0
        seen = set()
        reviews = []
        results = []
        for item in candidates:
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
            if key in seen:
                continue
            seen.add(key)
            try:
                gap = self.memory.read("gaps", key)
            except FileNotFoundError:
                gap = {"id": key, "question": generic_question, "occurrences": []}
            if job_id not in gap["occurrences"]:
                gap["occurrences"].append(job_id)
            gap.update(reason=reason, status="pending_evidence")
            gap.setdefault("evidence_refs", [])
            reference = {"job_id": job_id, "message_id": message_id if type(message_id) is int else
                         next((i for i, content in customer_messages.items() if content == question), None),
                         "turn_id": item.get("turn_id") if type(item.get("turn_id")) is int else None,
                         "origin": item.get("origin", "detector")}
            if reference not in gap["evidence_refs"]:
                gap["evidence_refs"].append(reference)
            if reason in {"reasoning_failure", "tool_failure", "unsupported_claim", "context_mismatch"}:
                evidence = next((e for e in snapshot.get("turn_evidence", [])
                                 if type(item.get("turn_id")) is int and e["turn_id"] == item["turn_id"]), None)
                if evidence is not None:
                    payload = {"reason": reason, "question": question, "evidence": evidence,
                               "conversation": snapshot["messages"]}
                    checked = await self.model.json(
                        'Verify the alleged issue against this exact turn evidence and conversation. '
                        'Return {"valid":boolean,"claim":"exact substring of evidence.agent_response",'
                        '"assessment":"contradicts_evidence|unsupported_by_evidence|context_mismatch",'
                        '"evidence_paths":["evidence.tool_calls.0.result.status"]}. '
                        'Reference actual data paths under evidence or conversation. Only approve with a concrete claim '
                        'and evidence. Never treat absent evidence as proof a fact is false.', payload)
                    claim = checked.get("claim")
                    paths = checked.get("evidence_paths")
                    assessment = checked.get("assessment")
                    verified = (checked.get("valid") is True and isinstance(claim, str) and bool(claim.strip())
                                and claim in evidence["agent_response"] and isinstance(paths, list) and bool(paths)
                                and assessment in {"contradicts_evidence", "unsupported_by_evidence", "context_mismatch"})
                    if verified:
                        try:
                            if not any(isinstance(p, str) and p.startswith(('evidence.tool_calls', 'evidence.sources', 'conversation.')) for p in paths):
                                verified = False  # The disputed claim cannot be its own evidence.
                            for path in paths:
                                evidence_value(payload, path)
                        except (KeyError, IndexError, ValueError, TypeError):
                            verified = False
                    # Exact claim stays in runtime report; shared memory gets only IDs and general patterns.
                    reviews.append({**reference, "verified": bool(verified), "claim": claim if isinstance(claim, str)
                                    and claim in evidence["agent_response"] else None,
                                    "assessment": assessment if verified else None,
                                    "evidence_paths": paths if verified else [],
                                    "rejection": None if verified else "missing_or_invalid_claim_evidence"})
                    if verified:
                        patterns = {
                            "reasoning_failure": "Check the answer against evidence and preserve all applicable conditions.",
                            "tool_failure": "Confirm an action only after its tool reports success.",
                            "unsupported_claim": "Do not state an unverified claim as a fact.",
                            "context_mismatch": "Check the current product and customer intent before reusing remembered information."}
                        from self_agent.lessons import generate_lesson
                        lesson = await generate_lesson(self.model, {**payload, 'verified_issue': checked}, reference, key)
                        pattern = {"id": key, "reason": reason, "pattern": patterns[reason],
                                   "status": "approved" if lesson else "pending_lesson", "scope": "general",
                                   "criterion": patterns[reason], "evidence_refs": gap["evidence_refs"],
                                   "assessment": assessment, "report_ref": job_id}
                        if lesson:
                            pattern.update(lesson=lesson, lesson_path=self.memory.write_lesson(lesson), lesson_hash=digest(lesson))
                        reviews[-1]['lesson_status'] = pattern['status']
                        self.memory.write("patterns", key, pattern)
                        self.memory.write("regression_cases", key, pattern)
                        gap.update(status="pending_remediation", pattern_ref=key, test_refs=[key])
            elif any(term in question.casefold() for term in ("sê-ri", "serial", "từng chiếc", "chiếc sẽ giao")):
                gap["required_source"] = "unit_specific_evidence"
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
                  "issue_reviews": reviews, "detector_error": detector_error,
                  "detection": {"candidate_count": detector_candidate_count,
                                "open_question_count": len(forced),
                                "processed_count": len(results),
                                "skipped_unmatched_question": skipped_unmatched,
                                "skipped_over_limit": max(0, detector_candidate_count - 20)},
                  "outcome": ("detector_failed" if detector_error else "no_candidates" if not candidates else
                              "all_candidates_filtered" if not results else "gaps_processed"),
                  "learning_duration_ms": round((time.perf_counter() - started) * 1000),
                  "learning_usage": {k: v - before.get(k, 0) for k, v in getattr(self.model, "usage", {}).items()}}
        self.memory.write("reports", job_id, report)
        return report
