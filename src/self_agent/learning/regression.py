"""Deterministic source contract for generated, data-only regression cases."""
from self_agent.models import digest


def check_case(case, source):
    return (case["expected_content"] == source["content"]
            and case["source_file"] == source["source_file"]
            and case["source_hash"] == digest(source)
            and bool(case["question"].strip()))
