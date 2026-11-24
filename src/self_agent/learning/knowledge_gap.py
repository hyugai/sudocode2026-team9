"""Extractive, source-backed knowledge repair. No business mutations."""
import time
import asyncio
from self_agent.models import digest, redact, sanitize, shared_question
from .candidate_review import (KNOWLEDGE_REASONS, REFLECTION_REASONS, GAP_CRITERION,
    discover, aligned_turns, prior_evidence, evidence_inventory, path_allowed, inventory_audit_valid)
from self_agent.guardrails import VERSION, scan_payload

def evidence_value(payload, path):
    """Resolve a data-only reference, never evaluate model-provided expressions."""
    if not isinstance(path, str) or path.split('.')[0] not in {"evidence", "conversation", 'prior_evidence'}:
        raise ValueError("Invalid evidence path")
    value = payload
    for part in path.split('.'):
        if isinstance(value,list):
            if not part.isdigit(): raise ValueError('Invalid list index')
            value=value[int(part)]
        else:
            value=value[part]
    return value


def issue_format_errors(checked, evidence, payload, mechanism):
    errors = []
    if type(checked.get('valid')) is not bool:
        errors.append('missing_boolean_verdict')
    if (checked.get('valid') is False and checked.get('assessment') == 'unsupported_by_evidence'
            and isinstance(checked.get('claim'),str) and checked['claim'] in evidence['agent_response']
            and not checked.get('decision_reason')):
        return ['inconsistent_issue_verdict']
    if checked.get('valid') is False:
        return ['verifier_rejected_issue']
    expected = 'reflection' if mechanism == 'reflection' else 'business_knowledge'
    if checked.get('issue_scope') != expected:
        errors.append('scope_mismatch')
    claim = checked.get('claim')
    if not isinstance(claim,str) or not claim.strip() or claim not in evidence['agent_response']:
        errors.append('claim_missing_or_not_exact')
    target = payload.get('candidate_claim')
    if (isinstance(target,str) and target in evidence['agent_response'] and
            isinstance(claim,str) and claim not in target):
        errors.append('claim_outside_candidate')
    paths = checked.get('evidence_paths')
    if not isinstance(paths,list) or (not paths and not inventory_audit_valid(checked,payload,mechanism)):
        errors.append('missing_evidence_references')
    else:
        try:
            for path in paths:
                value=evidence_value(payload,path)
                if checked.get('assessment') == 'contradicts_evidence' and (
                        value is None or value == '' or isinstance(value,(list,dict)) and not value):
                    errors.append('empty_contradiction_evidence')
        except (KeyError,IndexError,ValueError,TypeError):
            errors.append('invalid_evidence_reference')
    if checked.get('assessment') not in {'contradicts_evidence','unsupported_by_evidence','context_mismatch'}:
        errors.append('invalid_assessment')
    if (mechanism == 'knowledge_gap' and checked.get('assessment') == 'unsupported_by_evidence'
            and not inventory_audit_valid(checked,payload,mechanism)):
        errors.append('incomplete_evidence_inventory_audit')
    return errors


class KnowledgeGapLoop:
    def __init__(self, memory, model, search):
        self.memory, self.model, self.search = memory, model, search

    async def process(self, job_id, snapshot):
        started = time.perf_counter()
        before = dict(getattr(self.model, "usage", {}))
        guardrails = {'version':VERSION,'input_findings':scan_payload(snapshot),
                      'blocked_lessons':[],'blocked_sources':[]}
        detector_error = None
        candidates, detection_scan = await discover(self.model,snapshot)
        if detection_scan['errors']:
            detector_error = 'DetectorScanFailure'
        turns = aligned_turns(snapshot)
        by_message = {t['message_id']:t for t in turns}
        by_turn = {t['turn_id']:t for t in turns}
        customer_messages = {m.get("message_id", i): m["content"] for i, m in enumerate(snapshot["messages"])
                             if m["role"] in {"user", "customer"}}
        questions = {redact(m["content"]) for m in snapshot["messages"] if m["role"] in {"user", "customer"}}
        questions.update(snapshot["open_questions"])
        if not isinstance(candidates, list) or any(not isinstance(item, dict) for item in candidates):
            raise ValueError("Detector gaps must be an array of objects")
        detector_candidate_count = len(candidates)
        # Authoritative unresolved questions must survive empty/failed detection.
        # Process them first so the model candidate cap cannot drop the backlog.
        forced = [{"question": q, "reason": "missing_knowledge", "origin": "open_questions"}
                  for q in dict.fromkeys(snapshot["open_questions"]) if isinstance(q, str) and q.strip()]
        candidates = forced + candidates
        skipped_unmatched = 0
        seen = set()
        reviews = []
        results = []
        evaluation_cases = []
        out_of_scope = []
        alignment_rejections = []
        evaluation_seen = set()
        for item in candidates:
            message_id = item.get("message_id")
            aligned = by_message.get(message_id) if type(message_id) is int else None
            if aligned is None and type(item.get('turn_id')) is int:
                aligned = by_turn.get(item['turn_id'])
                if aligned: message_id = aligned['message_id']
            question = aligned['question'] if aligned else None
            question = question or redact(item.get("question", "")).strip()
            # Ground gap detection in a real question, not a model-invented fact.
            if not question or question not in questions:
                skipped_unmatched += 1
                alignment_rejections.append({'message_id':item.get('message_id'),'turn_id':item.get('turn_id'),
                                             'reason':'no_matching_question'})
                continue
            turn_index = aligned['turn_id'] if aligned else next((i for i, content in enumerate(customer_messages.values(), 1) if content == question), None)
            if type(item.get('turn_id')) is int and turn_index is not None and item['turn_id'] != turn_index:
                skipped_unmatched += 1
                alignment_rejections.append({'message_id':message_id,'turn_id':item.get('turn_id'),
                                             'reason':'conflicting_question_and_turn'})
                continue
            reason = item.get("reason")
            if reason not in KNOWLEDGE_REASONS | REFLECTION_REASONS:
                out_of_scope.append({'message_id': message_id, 'reason': reason})
                continue
            mechanism = 'reflection' if reason in REFLECTION_REASONS else 'knowledge_gap'
            generic_question = shared_question(question)
            atomic_claim = item.get('claim') if isinstance(item.get('claim'),str) else None
            key = digest([generic_question, reason, atomic_claim]) if atomic_claim else digest([generic_question, reason])
            occurrence = (key, turn_index, question)
            if occurrence in seen:
                continue
            seen.add(occurrence)
            try:
                gap = await asyncio.to_thread(self.memory.read, "gaps", key)
            except FileNotFoundError:
                gap = {"id": key, "question": generic_question, "occurrences": []}
            if job_id not in gap["occurrences"]:
                gap["occurrences"].append(job_id)
            gap.update(reason=reason, mechanism=mechanism, status="pending_evidence")
            gap.setdefault("evidence_refs", [])
            reference = {"job_id": job_id, "message_id": message_id if type(message_id) is int else
                         next((i for i, content in customer_messages.items() if content == question), None),
                         "turn_id": turn_index,
                         "origin": item.get("origin", "detector")}
            if reference not in gap["evidence_refs"]:
                gap["evidence_refs"].append(reference)
            if turn_index is not None and mechanism == 'knowledge_gap' and turn_index not in evaluation_seen:
                evaluation_seen.add(turn_index)
                evaluation_cases.append({'id': digest([job_id, turn_index]), 'gap_id': key,
                    'turn_id': turn_index, 'question': question, 'reason': reason, 'criterion': GAP_CRITERION})
            if reason == 'unsupported_claim' or mechanism == 'reflection':
                evidence = next((e for e in snapshot.get("turn_evidence", [])
                                 if e["turn_id"] == turn_index), None)
                if evidence is not None:
                    evidence = {**evidence,'tool_calls':evidence.get('tool_calls',[]),
                                'sources':evidence.get('sources',[]),'promotions':evidence.get('promotions',[])}
                    payload = {"reason": reason, "question": question, "evidence": evidence,
                               'candidate_claim':atomic_claim, 'required_fact':item.get('required_fact'),
                               'prior_evidence':prior_evidence(snapshot,turn_index),
                               "conversation": snapshot["messages"][:next((i for i,m in enumerate(snapshot['messages'])
                                   if m.get('message_id',i)==message_id),len(snapshot['messages']))]}
                    payload['evidence_inventory'] = evidence_inventory(payload)
                    scope_instruction = (
                        'This is a reflection issue: verify context use, reasoning or action execution, '
                        'not business policy. Conversation evidence must be an earlier explicit customer '
                        'statement, never the agent claim itself; tool outcomes may verify executed actions. '
                        'Approve issue_scope=reflection only for a specific demonstrated mistake.'
                        if mechanism == 'reflection' else
                        'This is a knowledge issue. Exclude conversation-management, reasoning and execution '
                        'failures. Approve issue_scope=business_knowledge only using tool-result or knowledge '
                        'sources, including earlier tool/source facts only if still applicable; conversation '
                        'is not authoritative business policy. Judge only candidate_claim when present, '
                        'not the whole answer. Check dates, amounts, conditions and other claims independently. '
                        'For unsupported_by_evidence, valid=true means this claim is NOT ESTABLISHED by '
                        'the supplied evidence, not that the business fact is proven false. Do not reject '
                        'such an issue merely because no source explicitly refutes it. An inventory audit '
                        'may establish lack of support only within the supplied evidence, never global falsehood.')
                    checked = await self.model.json(
                        'Verify the alleged issue against this exact turn evidence and conversation. '
                        'Return {"valid":boolean,"issue_scope":"business_knowledge|reflection|out_of_scope",'
                        '"claim":"exact substring of evidence.agent_response",'
                        '"assessment":"contradicts_evidence|unsupported_by_evidence|context_mismatch",'
                        '"evidence_paths":["evidence.tool_calls.0.result.status"],'
                        '"decision_reason":"brief justification",'
                        '"audit":{"support_status":"supported|contradicted|not_established",'
                        '"coverage":"complete|partial|unknown","checked_paths":["inventory.path"]}}. '
                        'valid means the ISSUE is verified, never that the claim is correct. '
                        'For a knowledge claim lacking support, inspect ALL evidence_inventory entries '
                        'and return their exact paths with not_established/complete. Then evidence_paths '
                        'may be empty; do not invent a citation. Otherwise cite the concrete evidence '
                        'showing the issue. State decision_reason when rejecting; partial/unknown coverage '
                        'cannot verify an absence-of-support claim. '
                        'Reference actual data paths under evidence or conversation. Only approve with a concrete claim '
                        'and evidence. Never treat absent evidence as proof a fact is false. '
                        + scope_instruction, payload)
                    format_errors = issue_format_errors(checked,evidence,payload,mechanism)
                    retried_format = bool(format_errors and (checked.get('valid') is not False or
                                                              'inconsistent_issue_verdict' in format_errors))
                    if retried_format:
                        checked = await self.model.json(
                            'Correct the verifier response format using exact text spans and existing data paths. '
                            'Return {"valid":boolean,"issue_scope":"business_knowledge|reflection|out_of_scope",'
                            '"claim":"exact substring of evidence.agent_response",'
                            '"assessment":"contradicts_evidence|unsupported_by_evidence|context_mismatch",'
                            '"evidence_paths":["data.path"],"decision_reason":"why",'
                            '"audit":{"support_status":"supported|contradicted|not_established",'
                            '"coverage":"complete|partial|unknown","checked_paths":["inventory.path"]}}. '
                            'valid refers to the alleged ISSUE, not the truth of the claim. Do not paraphrase the claim. '
                            'This is not a request to approve: return valid=false if evidence is insufficient. '
                            + scope_instruction,
                            {'input':payload,'previous_output':checked,'format_errors':format_errors})
                    final_errors = issue_format_errors(checked,evidence,payload,mechanism)
                    claim = checked.get("claim")
                    paths = checked.get("evidence_paths")
                    assessment = checked.get("assessment")
                    audited = inventory_audit_valid(checked,payload,mechanism)
                    verified = (checked.get("valid") is True and checked.get('issue_scope') == (
                                    'reflection' if mechanism == 'reflection' else 'business_knowledge')
                                and isinstance(claim, str) and bool(claim.strip())
                                and claim in evidence["agent_response"] and isinstance(paths, list) and (bool(paths) or audited)
                                and (not atomic_claim or atomic_claim not in evidence['agent_response'] or claim in atomic_claim)
                                and (mechanism != 'knowledge_gap' or assessment != 'unsupported_by_evidence' or audited)
                                and assessment in ({"contradicts_evidence", "unsupported_by_evidence", "context_mismatch"}
                                                   if mechanism == 'reflection' else {"contradicts_evidence", "unsupported_by_evidence"}))
                    if verified:
                        try:
                            if not all(path_allowed(p,mechanism) for p in paths):
                                verified = False  # The disputed claim cannot be its own evidence.
                            for path in paths:
                                value=evidence_value(payload, path)
                                if assessment == 'contradicts_evidence' and (
                                        value is None or value == '' or isinstance(value,(list,dict)) and not value):
                                    verified=False
                                if path.startswith('conversation.'):
                                    prior = payload['conversation'][int(path.split('.')[1])]
                                    if prior['role'] not in {'user', 'customer'} or prior.get('message_id', 0) >= message_id:
                                        verified = False
                        except (KeyError, IndexError, ValueError, TypeError):
                            verified = False
                    # Exact claim stays in runtime report; shared memory gets only IDs and general patterns.
                    reviews.append({**reference, 'mechanism': mechanism, "verified": bool(verified), "claim": claim if isinstance(claim, str)
                                    and claim in evidence["agent_response"] else None,
                                    "assessment": assessment if verified else None,
                                    "evidence_paths": paths if verified else [],
                                    "rejection": None if verified else "missing_or_invalid_claim_evidence",
                                    'rejection_reasons': [] if verified else (final_errors or ['evidence_authority_or_scope_not_verified']),
                                    'format_retry': retried_format,
                                    'verifier_output': sanitize(checked)})
                    reviews[-1].update(candidate_claim=atomic_claim,
                        verification_basis='evidence_inventory_audit' if verified and audited else
                                           'referenced_evidence' if verified else None,
                        evidence_inventory=payload['evidence_inventory'])
                    if verified:
                        patterns = {'unsupported_claim': 'Do not state an unverified claim as a fact.',
                                    'reasoning_failure': 'Check the answer against evidence and preserve all applicable conditions.',
                                    'tool_failure': 'Confirm an action only after its tool reports success.',
                                    'context_mismatch': 'Check the current product and customer intent before reusing remembered information.'}
                        from self_agent.lessons import generate_lesson
                        lesson = await generate_lesson(self.model, {**payload, 'verified_issue': checked}, reference, key,
                                                       mechanism=mechanism,existing=await asyncio.to_thread(self.memory.load_lessons),
                                                       security_audit=guardrails['blocked_lessons'])
                        pattern = {"id": key, "reason": reason, "pattern": patterns[reason],
                                   "status": "approved" if lesson else "pending_lesson", "scope": "general", 'mechanism': mechanism,
                                   "criterion": patterns[reason], "evidence_refs": gap["evidence_refs"],
                                   "assessment": assessment, "report_ref": job_id}
                        if lesson:
                            pattern.update(lesson=lesson, lesson_path=await asyncio.to_thread(self.memory.write_lesson, lesson), lesson_hash=digest(lesson))
                        reviews[-1]['lesson_status'] = pattern['status']
                        await asyncio.to_thread(self.memory.write, "patterns", key, pattern)
                        await asyncio.to_thread(self.memory.write, "regression_cases", key, pattern)
                        gap.update(status="pending_remediation", pattern_ref=key, test_refs=[key])
            elif any(term in question.casefold() for term in ("sê-ri", "serial", "từng chiếc", "chiếc sẽ giao")):
                gap["required_source"] = "unit_specific_evidence"
            else:
                source = await self.search(question)
                safe_chunks = []
                for chunk_index, chunk in enumerate(source.get('chunks', [])):
                    findings = scan_payload(chunk)
                    if findings:
                        guardrails['blocked_sources'].append({'chunk_index':chunk_index,'findings':findings})
                    else:
                        safe_chunks.append(chunk)
                # Resolver selects full chunks; it cannot author a new policy.
                chunks = [c for c in safe_chunks if c.get("source_file") and c.get("content")
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
                        await asyncio.to_thread(self.memory.write, "knowledge", key, case)
                        await asyncio.to_thread(self.memory.write, "regression_cases", key, {**case, "criterion": "answer supported by full source"})
                        await asyncio.to_thread(self.memory.write, "releases", key, {"id": key, "knowledge_id": key, "source_hash": digest(chunk)})
                        gap.update(status="pending_application", resolution_ref=key, test_refs=[key])
            await asyncio.to_thread(self.memory.write, "gaps", key, gap)
            results.append({"id": key, "status": gap["status"]})
        report = {"job_id": job_id, "gaps": results, 'scope': 'knowledge_gap_and_reflection_v1',
                  'evaluation_cases': evaluation_cases, 'out_of_scope': out_of_scope,
                  "issue_reviews": reviews, "detector_error": detector_error, 'guardrails':guardrails,
                  "detection": {"candidate_count": detector_candidate_count,
                                "open_question_count": len(forced),
                                "processed_count": len(results),
                                "skipped_unmatched_question": skipped_unmatched,
                                "skipped_over_limit": detection_scan['skipped_over_limit'],
                                'scan':detection_scan, 'alignment_rejections':alignment_rejections},
                  "outcome": ("detector_failed" if detector_error else "no_candidates" if not candidates else
                              "all_candidates_filtered" if not results else "gaps_processed"),
                  "learning_duration_ms": round((time.perf_counter() - started) * 1000),
                  "learning_usage": {k: v - before.get(k, 0) for k, v in getattr(self.model, "usage", {}).items()}}
        await asyncio.to_thread(self.memory.write, "reports", job_id, report)
        return report
