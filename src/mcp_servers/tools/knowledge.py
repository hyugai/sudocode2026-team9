"""Customer-safe retrieval over the BTC policy knowledge base."""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from pathlib import Path
from threading import Lock
from typing import Any
from types import SimpleNamespace

logger = logging.getLogger(__name__)

_DEFAULT_EMBEDDING_MODEL = "keepitreal/vietnamese-sbert"
_MAX_K = 5
_store: Any | None = None
_store_key: tuple[str, str] | None = None
_store_lock = Lock()
_pinecone_index: Any | None = None
_pinecone_index_key: tuple[str, str] | None = None
_pinecone_lock = Lock()

# These files are not customer-facing evidence.  The ingest script already
# excludes the two trap documents, but this second boundary also protects a
# database that was built by an older ingest version.
_BLOCKED_SOURCE_MARKERS = (
    "het-hieu-luc",
    "noi-bo",
    "noi-quy-nhan-vien",
)

_STOP_WORDS = {
    "anh",
    "chi",
    "cho",
    "co",
    "cua",
    "em",
    "hien",
    "khong",
    "la",
    "minh",
    "nao",
    "neu",
    "shop",
    "the",
    "thi",
    "tai",
    "va",
    "voi",
}


def _normalized_tokens(value: str) -> set[str]:
    decomposed = unicodedata.normalize("NFD", value.casefold())
    ascii_text = "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    ).replace("đ", "d")
    return {
        token
        for token in re.findall(r"[a-z0-9]+", ascii_text)
        if len(token) > 1 and token not in _STOP_WORDS
    }


def _topic_source_boost(query: str, source_file: str) -> float:
    """Prefer the authoritative document family for an obvious policy topic."""
    query_tokens = _normalized_tokens(query)
    source = source_file.casefold()
    boost = 0.0
    if query_tokens.intersection(
        {"doi", "tra", "size", "mau", "tem", "hop", "hoan"}
    ):
        if "chinh-sach-doi-tra" in source:
            boost += 12.0
        elif "changelog" in source:
            boost += 8.0
        elif "quy-trinh-cod-hoan-hang" in source:
            boost += 4.0
    if query_tokens.intersection(
        {"ship", "giao", "van", "chuyen", "cod", "thanh", "toan"}
    ) and "chinh-sach-van-chuyen-thanh-toan" in source:
        boost += 12.0
    warranty_topic = (
        {"bao", "hanh"}.issubset(query_tokens)
        or "warranty" in query_tokens
    )
    if warranty_topic and "chinh-sach-bao-hanh" in source:
        boost += 12.0
    if query_tokens.intersection(
        {"khuyen", "mai", "voucher", "giam", "promo"}
    ) and "dieu-khoan-khuyen-mai" in source:
        boost += 12.0
    return boost


def _candidate_score(query: str, document: Any, rank: int) -> float:
    metadata = dict(getattr(document, "metadata", {}) or {})
    source = str(metadata.get("source_file") or metadata.get("source") or "")
    heading = " ".join(
        str(metadata.get(key) or "") for key in ("Header 1", "Header 2", "Header 3")
    )
    content = str(getattr(document, "page_content", "") or "")
    query_tokens = _normalized_tokens(query)
    content_tokens = _normalized_tokens(f"{heading} {content}")
    lexical_overlap = len(query_tokens.intersection(content_tokens))
    heading_overlap = len(query_tokens.intersection(_normalized_tokens(heading)))
    return (
        _topic_source_boost(query, source)
        + lexical_overlap * 2.0
        + heading_overlap * 3.0
        + 1.0 / (rank + 1)
    )


def _enabled() -> bool:
    return os.environ.get("ENABLE_VECTOR_RAG", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _db_path() -> Path:
    configured = os.environ.get("CHROMA_DB_DIR", "data/chroma_db").strip()
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = _project_root() / path
    return path.resolve()


def _embedding_model() -> str:
    return os.environ.get(
        "CHROMA_EMBEDDING_MODEL", _DEFAULT_EMBEDDING_MODEL
    ).strip()


def _backend() -> str:
    return os.environ.get("KNOWLEDGE_BACKEND", "chroma").strip().lower()


def _get_pinecone_index() -> Any:
    """Reuse the remote index handle without loading local embedding models."""
    global _pinecone_index, _pinecone_index_key

    api_key = os.environ.get("PINECONE_API_KEY", "").strip()
    index_name = os.environ.get("PINECONE_INDEX_NAME", "btc-policy").strip()
    if not api_key:
        raise ValueError("PINECONE_API_KEY is required for Pinecone knowledge search")
    if not index_name:
        raise ValueError("PINECONE_INDEX_NAME is required for Pinecone knowledge search")

    key = (api_key, index_name)
    if _pinecone_index is not None and _pinecone_index_key == key:
        return _pinecone_index

    with _pinecone_lock:
        if _pinecone_index is not None and _pinecone_index_key == key:
            return _pinecone_index
        from pinecone import Pinecone

        _pinecone_index = Pinecone(api_key=api_key).index(index_name)
        _pinecone_index_key = key
        logger.info("Connected to Pinecone policy index %s", index_name)
        return _pinecone_index


def _get_store() -> Any:
    """Initialize Chroma and the embedding model only on the first query."""
    global _store, _store_key

    db_path = _db_path()
    model_name = _embedding_model()
    key = (str(db_path), model_name)
    if _store is not None and _store_key == key:
        return _store

    with _store_lock:
        if _store is not None and _store_key == key:
            return _store
        if not db_path.is_dir():
            raise FileNotFoundError(f"Chroma directory does not exist: {db_path}")

        # Delayed imports keep MCP startup light.  In particular, the main
        # agent process no longer needs to load a second sentence-transformer.
        from langchain_chroma import Chroma
        from langchain_huggingface import HuggingFaceEmbeddings

        logger.info("Loading BTC knowledge base from %s", db_path)
        embeddings = HuggingFaceEmbeddings(model_name=model_name)
        _store = Chroma(
            persist_directory=str(db_path),
            embedding_function=embeddings,
        )
        _store_key = key
        return _store


def _customer_safe_source(metadata: dict[str, Any]) -> bool:
    source = str(metadata.get("source_file") or metadata.get("source") or "")
    normalized = source.casefold()
    return (
        bool(source)
        and not any(marker in normalized for marker in _BLOCKED_SOURCE_MARKERS)
        and metadata.get("audience", "customer") == "customer"
        and metadata.get("is_expired", False) is False
    )


def _chunk_id(metadata: dict[str, Any], section: str) -> str:
    stored = str(metadata.get("chunk_id") or "").strip()
    if re.fullmatch(r"[A-Za-z]{1,12}-\d{1,5}", stored):
        return stored.upper()
    match = re.search(r"\[([A-Za-z]{1,12}-\d{1,5})\]", section)
    return match.group(1).upper() if match else ""


def _pinecone_documents(query: str, candidate_k: int) -> list[Any]:
    namespace = os.environ.get("PINECONE_NAMESPACE", "btc-policy-prod").strip()
    if not namespace:
        raise ValueError("PINECONE_NAMESPACE is required for Pinecone knowledge search")

    response = _get_pinecone_index().search(
        namespace=namespace,
        inputs={"text": query},
        top_k=candidate_k,
        filter={
            "$and": [
                {"audience": {"$eq": "customer"}},
                {"is_expired": {"$eq": False}},
            ]
        },
        fields=["chunk_text", "source_file", "section", "chunk_id", "audience", "is_expired"],
    )
    hits = getattr(getattr(response, "result", None), "hits", []) or []
    documents = []
    for hit in hits:
        fields = dict(getattr(hit, "fields", {}) or {})
        documents.append(
            SimpleNamespace(
                page_content=fields.get("chunk_text", ""),
                metadata={
                    "source_file": fields.get("source_file", ""),
                    "Header 2": fields.get("section", ""),
                    "chunk_id": fields.get("chunk_id", ""),
                    "audience": fields.get("audience"),
                    "is_expired": fields.get("is_expired"),
                },
            )
        )
    return documents


def knowledge_search(
    query: str,
    k: int = 3,
    product_sku: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Find current customer-facing policy, shipping and store-rule evidence.

    ``product_sku`` and ``as_of`` are returned as provenance, not treated as
    policy facts or mixed into the semantic query. Results from expired or
    internal documents are always filtered before reaching the agent.
    """
    clean_query = " ".join(str(query or "").split())
    if not clean_query:
        return {"error": "query_required", "chunks": []}
    if not _enabled():
        return {"error": "knowledge_search_disabled", "chunks": []}

    try:
        requested_k = max(1, min(int(k), _MAX_K))
    except (TypeError, ValueError):
        requested_k = 3

    try:
        # Search broadly, then hybrid-rerank. Product SKU/date hints are useful
        # provenance but can degrade semantic ranking when appended to a
        # natural-language policy question.
        backend = _backend()
        if backend not in {"chroma", "pinecone"}:
            raise ValueError(f"Unsupported KNOWLEDGE_BACKEND: {backend!r}")
        default_candidates = "20" if backend == "pinecone" else "60"
        try:
            configured_candidates = int(
                os.environ.get("KNOWLEDGE_CANDIDATE_K", default_candidates)
            )
        except ValueError:
            configured_candidates = int(default_candidates)
        candidate_k = min(
            max(requested_k * 4, configured_candidates, 8),
            100,
        )
        if backend == "pinecone":
            documents = _pinecone_documents(clean_query, candidate_k)
        else:
            documents = _get_store().similarity_search(clean_query, k=candidate_k)
    except Exception as exc:
        logger.exception("Knowledge search failed")
        return {"error": f"knowledge_search_failed: {exc}", "chunks": []}

    safe_documents = [
        (rank, document)
        for rank, document in enumerate(documents)
        if _customer_safe_source(
            dict(getattr(document, "metadata", {}) or {})
        )
    ]
    safe_documents.sort(
        key=lambda item: _candidate_score(clean_query, item[1], item[0]),
        reverse=True,
    )

    chunks: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for _, document in safe_documents:
        metadata = dict(getattr(document, "metadata", {}) or {})
        content = " ".join(
            str(getattr(document, "page_content", "") or "").split()
        )
        source_file = str(
            metadata.get("source_file") or metadata.get("source") or "unknown"
        )
        dedupe_key = (source_file, content)
        if not content or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        section = (
            metadata.get("Header 3")
            or metadata.get("Header 2")
            or metadata.get("Header 1")
            or ""
        )
        chunks.append(
            {
                "chunk_id": _chunk_id(metadata, str(section)),
                "content": content,
                "source_file": source_file,
                "section": str(section),
            }
        )
        if len(chunks) >= requested_k:
            break

    if not chunks:
        return {
            "error": "no_customer_safe_knowledge_found",
            "query": clean_query,
            "chunks": [],
        }
    return {
        "query": clean_query,
        "as_of": as_of,
        "product_sku": product_sku,
        "count": len(chunks),
        "chunks": chunks,
    }


TOOLS = {
    "policy.search": knowledge_search,
    # Preserve internal dispatch for older traces/callers; new traces use policy.search.
    "knowledge.search": knowledge_search,
}

