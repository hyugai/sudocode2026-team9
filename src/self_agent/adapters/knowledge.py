"""Validate releases and delegate writes to the existing retrieval backend."""


def build_release(memory, corpus, *, build=None):
    """Corpus is JSON customer-safe chunks, exported/approved by the operator.

    The caller supplies a publisher for its existing backend. No database or
    embedding model is created here, and retrieval environment is never changed.
    """
    from self_agent.models import digest
    chunks = [dict(c) for c in corpus]
    for c in chunks:
        if (not c.get("content") or not c.get("source_file") or c.get("audience") != "customer"
                or c.get("is_expired") is not False):
            raise ValueError("Corpus requires explicit current customer-safe sources")
    by_source = {c["source_file"] for c in chunks}
    for case in memory.records("knowledge"):
        if case["status"] != "approved" or case["source_file"] not in by_source:
            continue
        # Check source content again at release time; withdrawn evidence is excluded.
        if not any(c["source_file"] == case["source_file"] and c["content"] == case["expected_content"] for c in chunks):
            continue
        chunks.append({"content": case["question"] + "\n" + case["expected_content"],
                       "source_file": case["source_file"], "chunk_id": case["chunk_id"],
                       "audience": "customer", "is_expired": False})
    version = digest(chunks)
    path = (memory.root / "releases" / version).resolve()
    marker = path.parent / "ready"
    if not marker.exists():
        if build is None:
            raise ValueError("Provide a publisher for the existing DB/Pinecone backend")
        build(chunks, path)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(version, encoding="utf-8")
    return {"version": version, "path": str(path), "count": len(chunks)}


def publish_pinecone(chunks, index, *, namespace):
    """Write through an existing integrated-embedding index supplied by caller.

    This is an explicit publication operation, never called by benchmark or
    run_turn. Pinecone embeds chunk_text with the index's existing model.
    """
    from self_agent.models import digest
    if not namespace or not namespace.strip():
        raise ValueError("An explicit target namespace is required")
    records = [{"_id": "self-agent-" + digest(c), "chunk_text": c["content"],
                "source_file": c["source_file"], "chunk_id": c.get("chunk_id", ""),
                "audience": "customer", "is_expired": False} for c in chunks]
    for start in range(0, len(records), 50):
        index.upsert_records(namespace=namespace, records=records[start:start + 50])
    return {"status": "submitted", "count": len(records), "namespace": namespace}
