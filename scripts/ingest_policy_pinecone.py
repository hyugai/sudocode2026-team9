r"""Ingest the BTC Markdown policy corpus into Pinecone.

This script uses a Pinecone index with integrated embedding, so policy text is
sent as text records and no local sentence-transformer is loaded.

Examples (PowerShell):

    .\.venv\Scripts\python.exe scripts\ingest_policy_pinecone.py --dry-run
    .\.venv\Scripts\python.exe scripts\ingest_policy_pinecone.py
    .\.venv\Scripts\python.exe scripts\ingest_policy_pinecone.py `
        --namespace btc-policy-staging `
        --verify-query "chính sách đổi trả"

The command is intentionally non-destructive: it never deletes an index or a
namespace. Deterministic record IDs make repeated runs update the same chunks.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_DIR = (
    PROJECT_ROOT / "dataset" / "BTC-Data-Vong1-TEAMS" / "policy"
)

# Do not upload expired or internal-only material. Keeping this boundary at
# ingestion time prevents unsafe records from ever entering the customer KB.
EXCLUDED_FILES = {
    "chinh-sach-doi-tra-v2026-06-HET-HIEU-LUC.md",
    "ghi-chu-nhap-hang-NOI-BO.md",
    "noi-quy-nhan-vien.md",
}

DEFAULT_INDEX_NAME = "btc-policy"
DEFAULT_NAMESPACE = "btc-policy-prod"
DEFAULT_MODEL = "multilingual-e5-large"
DEFAULT_CLOUD = "aws"
DEFAULT_REGION = "us-east-1"
TEXT_FIELD = "chunk_text"

CHUNK_ID_PATTERN = re.compile(r"\[([A-Za-z]{1,12}-\d{1,5})\]")


def _env(name: str, fallback: str) -> str:
    return os.environ.get(name, fallback).strip() or fallback


def _slug(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_value = decomposed.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    return slug or "chunk"


def _section(metadata: dict[str, Any]) -> str:
    return str(
        metadata.get("Header 3")
        or metadata.get("Header 2")
        or metadata.get("Header 1")
        or ""
    ).strip()


def _chunk_id(section: str, content: str) -> str:
    match = CHUNK_ID_PATTERN.search(section) or CHUNK_ID_PATTERN.search(content)
    return match.group(1).upper() if match else ""


def load_policy_chunks(policy_dir: Path) -> list[Document]:
    """Read safe Markdown files and split them like the local Chroma ingest."""
    if not policy_dir.is_dir():
        raise FileNotFoundError(f"Policy directory does not exist: {policy_dir}")

    markdown_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "Header 1"),
            ("##", "Header 2"),
            ("###", "Header 3"),
        ]
    )
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
        separators=["\n\n", "\n", ".", " ", ""],
    )

    heading_chunks: list[Document] = []
    loaded_files = 0
    for file_path in sorted(policy_dir.glob("*.md")):
        if file_path.name in EXCLUDED_FILES:
            print(f"[skip] {file_path.name} (expired/internal)")
            continue

        content = file_path.read_text(encoding="utf-8")
        splits = markdown_splitter.split_text(content)
        for split in splits:
            split.metadata["source_file"] = file_path.name
        heading_chunks.extend(splits)
        loaded_files += 1
        print(f"[load] {file_path.name}")

    if not heading_chunks:
        raise RuntimeError(f"No customer-safe Markdown documents found in {policy_dir}")

    chunks = text_splitter.split_documents(heading_chunks)
    print(f"Prepared {len(chunks)} chunks from {loaded_files} policy files.")
    return chunks


def build_records(chunks: Iterable[Document]) -> list[dict[str, Any]]:
    """Convert chunks to idempotent Pinecone text records."""
    occurrences: defaultdict[tuple[str, str], int] = defaultdict(int)
    records: list[dict[str, Any]] = []

    for chunk in chunks:
        content = chunk.page_content.strip()
        if not content:
            continue

        metadata = dict(chunk.metadata or {})
        source_file = str(metadata.get("source_file") or "unknown.md")
        section = _section(metadata)
        labelled_id = _chunk_id(section, content)
        identity = labelled_id or section or "unlabelled"
        occurrence_key = (source_file, identity)
        occurrences[occurrence_key] += 1
        part = occurrences[occurrence_key]

        source_slug = _slug(Path(source_file).stem)
        identity_slug = _slug(identity)
        record_id = f"{source_slug}-{identity_slug}-{part:02d}"
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

        records.append(
            {
                "_id": record_id,
                TEXT_FIELD: content,
                "source_file": source_file,
                "section": section,
                "chunk_id": labelled_id,
                "audience": "customer",
                "is_expired": False,
                "content_sha256": digest,
            }
        )

    ids = [str(record["_id"]) for record in records]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Generated duplicate Pinecone record IDs")
    return records


def _batches(records: list[dict[str, Any]], size: int):
    for start in range(0, len(records), size):
        yield records[start : start + size]


def _existing_model(index_description: Any) -> str | None:
    schema = getattr(index_description, "schema", None)
    fields = getattr(schema, "fields", None)
    if not fields:
        return None
    field = fields.get(TEXT_FIELD)
    if field is None:
        return None
    model = getattr(field, "model", None)
    return str(model) if model else None


def ensure_index(
    pc: Any,
    *,
    index_name: str,
    model: str,
    cloud: str,
    region: str,
) -> None:
    """Create an integrated-embedding index, or validate the existing one."""
    if not pc.indexes.exists(index_name):
        from pinecone import EmbedConfig

        print(
            f"Creating Pinecone index {index_name!r} with model {model!r} "
            f"in {cloud}/{region}..."
        )
        pc.indexes.create_for_model(
            name=index_name,
            cloud=cloud,
            region=region,
            embed=EmbedConfig(
                model=model,
                field_map={"text": TEXT_FIELD},
                write_parameters={"input_type": "passage"},
                read_parameters={"input_type": "query"},
            ),
            tags={"application": "telesale-agent", "corpus": "btc-policy"},
        )
        return

    description = pc.indexes.describe(index_name)
    existing_model = _existing_model(description)
    if existing_model is None:
        raise RuntimeError(
            f"Index {index_name!r} exists but has no integrated text field "
            f"{TEXT_FIELD!r}. Use another index name or recreate it with "
            "Pinecone integrated embedding."
        )
    if existing_model != model:
        raise RuntimeError(
            f"Index {index_name!r} uses model {existing_model!r}, not {model!r}. "
            "The embedding model of an existing index cannot be changed."
        )
    print(f"Using existing Pinecone index {index_name!r} ({existing_model}).")


def upload_records(args: argparse.Namespace, records: list[dict[str, Any]]) -> None:
    api_key = os.environ.get("PINECONE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "PINECONE_API_KEY is missing. Add it to .env or the process environment."
        )

    try:
        from pinecone import Pinecone
    except ImportError as exc:
        raise RuntimeError(
            'Pinecone SDK is not installed. Run: pip install "pinecone>=10,<11"'
        ) from exc

    pc = Pinecone(api_key=api_key)
    ensure_index(
        pc,
        index_name=args.index_name,
        model=args.model,
        cloud=args.cloud,
        region=args.region,
    )

    index = pc.index(args.index_name)
    accepted = 0
    for number, batch in enumerate(_batches(records, args.batch_size), start=1):
        response = index.upsert_records(
            namespace=args.namespace,
            records=batch,
            timeout=args.timeout,
        )
        accepted += int(getattr(response, "record_count", len(batch)))
        print(f"[upsert {number}] submitted {len(batch)} records")

    print(
        f"Submitted {accepted} records to index={args.index_name!r}, "
        f"namespace={args.namespace!r}."
    )
    print("Pinecone writes are asynchronous; search freshness may take a moment.")

    if args.verify_query:
        response = index.search(
            namespace=args.namespace,
            inputs={"text": args.verify_query},
            top_k=3,
        )
        hits = list(getattr(getattr(response, "result", None), "hits", []) or [])
        print(f"Verification query returned {len(hits)} hit(s):")
        for hit in hits:
            fields = dict(getattr(hit, "fields", {}) or {})
            print(
                f"  - {getattr(hit, 'id', 'unknown')} "
                f"score={getattr(hit, 'score', 'n/a')} "
                f"source={fields.get('source_file', 'unknown')} "
                f"section={fields.get('section', '')}"
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Chunk BTC policy Markdown and upload text records to a Pinecone "
            "integrated-embedding index."
        )
    )
    parser.add_argument(
        "--policy-dir",
        type=Path,
        default=DEFAULT_POLICY_DIR,
        help=f"Markdown directory (default: {DEFAULT_POLICY_DIR})",
    )
    parser.add_argument(
        "--index-name",
        default=_env("PINECONE_INDEX_NAME", DEFAULT_INDEX_NAME),
    )
    parser.add_argument(
        "--namespace",
        default=_env("PINECONE_NAMESPACE", DEFAULT_NAMESPACE),
    )
    parser.add_argument(
        "--model",
        default=_env("PINECONE_EMBEDDING_MODEL", DEFAULT_MODEL),
    )
    parser.add_argument(
        "--cloud",
        default=_env("PINECONE_CLOUD", DEFAULT_CLOUD),
    )
    parser.add_argument(
        "--region",
        default=_env("PINECONE_REGION", DEFAULT_REGION),
    )
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--verify-query",
        default="",
        help="Optional semantic query to run after upsert.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and inspect records without connecting to Pinecone.",
    )
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    if not args.index_name.strip():
        parser.error("--index-name must not be empty")
    if not args.namespace.strip():
        parser.error("--namespace must not be empty")
    return args


def main(argv: list[str] | None = None) -> int:
    # Windows PowerShell can expose a legacy cp1258 stream even when policy
    # files are UTF-8. Reconfigure only the CLI streams so Vietnamese headings
    # can be printed without changing the text sent to Pinecone.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")

    load_dotenv(PROJECT_ROOT / ".env")
    args = parse_args(argv)
    policy_dir = args.policy_dir.expanduser()
    if not policy_dir.is_absolute():
        policy_dir = (PROJECT_ROOT / policy_dir).resolve()

    chunks = load_policy_chunks(policy_dir)
    records = build_records(chunks)
    if not records:
        raise RuntimeError("Chunking produced no Pinecone records")

    if args.dry_run:
        print(
            f"Dry run: {len(records)} records would be uploaded to "
            f"index={args.index_name!r}, namespace={args.namespace!r}."
        )
        for record in records[:5]:
            print(
                f"  - {record['_id']}: {record['source_file']} / "
                f"{record['section']}"
            )
        return 0

    upload_records(args, records)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
