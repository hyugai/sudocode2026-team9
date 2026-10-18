"""Current customer memory plus dated Markdown archives on object storage."""

from __future__ import annotations

import os
import re
import tempfile
import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Any

from telesale_agent.application.memory.snapshot import (
    empty_snapshot,
    parse_snapshot,
    render_snapshot,
)


_SAFE_CUSTOMER_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_DAILY_SOURCE = {
    "atomic_facts": re.compile(r"^fact-(\d{4}-\d{2}-\d{2})\.md$"),
    "episodes": re.compile(r"^episode-(\d{4}-\d{2}-\d{2})\.md$"),
    "foresights": re.compile(r"^foresight-(\d{4}-\d{2}-\d{2})\.md$"),
}


class ObjectStorageCustomerMemoryRepository:
    """GET current.md; publish changed Markdown files before committing it."""

    def __init__(
        self,
        *,
        bucket: str | None = None,
        prefix: str | None = None,
        client: Any = None,
    ) -> None:
        self.bucket = bucket or os.environ.get("CUSTOMER_MEMORY_BUCKET", "")
        if not self.bucket:
            raise ValueError("CUSTOMER_MEMORY_BUCKET is required for object storage")
        configured_prefix = (
            prefix if prefix is not None else os.environ.get("CUSTOMER_MEMORY_PREFIX", "users")
        )
        self.prefix = configured_prefix.strip("/")
        if self.prefix and any(
            not _SAFE_CUSTOMER_ID.fullmatch(part) for part in self.prefix.split("/")
        ):
            raise ValueError("CUSTOMER_MEMORY_PREFIX contains unsupported path characters")
        if client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as exc:
                raise RuntimeError("Install boto3 to use object-storage memory") from exc
            self.client = boto3.client(
                "s3",
                endpoint_url=os.environ.get("AWS_ENDPOINT_URL_S3") or None,
                config=Config(s3={"addressing_style": "path"}),
            )
        else:
            self.client = client

    def _customer_prefix(self, customer_id: str) -> str:
        if not customer_id or not _SAFE_CUSTOMER_ID.fullmatch(customer_id):
            raise ValueError("customer_id contains unsupported path characters")
        return f"{self.prefix}/{customer_id}" if self.prefix else customer_id

    def _key(self, customer_id: str) -> str:
        return f"{self._customer_prefix(customer_id)}/current.md"

    def _legacy_key(self, customer_id: str) -> str:
        self._customer_prefix(customer_id)
        return f"customer-memory/{customer_id}.md"

    def _read_object(self, key: str) -> str | None:
        try:
            result = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise
        body = result["Body"]
        try:
            return body.read().decode("utf-8")
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()

    def load(self, customer_id: str) -> dict[str, Any]:
        document = self._read_object(self._key(customer_id))
        if document is None:
            # Read an earlier deployment's single-object format without deleting it.
            document = self._read_object(self._legacy_key(customer_id))
        if document is None:
            return empty_snapshot(customer_id)
        return parse_snapshot(document, customer_id)

    def has_current(self, customer_id: str) -> bool:
        """Check whether the new canonical key exists (migration only)."""
        return self._read_object(self._key(customer_id)) is not None

    def load_archive(self, customer_id: str, collection: str, day: str) -> str | None:
        """Fetch one old daily Markdown file only when the caller needs it."""
        pattern = _DAILY_SOURCE.get(collection)
        if pattern is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("Invalid memory archive location")
        prefix = {"episodes": "episode", "atomic_facts": "fact", "foresights": "foresight"}[collection]
        name = f"{prefix}-{day}.md"
        return self._read_object(f"{self._customer_prefix(customer_id)}/{collection}/{name}")

    def search_archive(
        self,
        customer_id: str,
        query: str,
        *,
        section: str = "episodes",
        day: str | None = None,
    ) -> dict[str, Any]:
        """Search current detail and a bounded set of cold files on demand."""
        customer_prefix = self._customer_prefix(customer_id)
        current = self.load(customer_id)
        if section in {"user", "behaviors", "facts"}:
            if day:
                raise ValueError("A static archive section has no day")
            content = self._individual_files(current)[f"{section}.md"]
            return {"section": section, "hits": [{"source": f"{section}.md", "content": content[:1200]}] if content else []}
        if section not in _DAILY_SOURCE:
            raise ValueError("Unsupported memory archive section")
        live_items = {
            f"{section}/{item['source']}": str(item.get("content", ""))
            for item in current.get(section, [])
            if isinstance(item, dict) and item.get("source")
        }
        if day:
            prefix_name = {"episodes": "episode", "atomic_facts": "fact", "foresights": "foresight"}[section]
            relative_key = f"{section}/{prefix_name}-{day}.md"
            content = live_items.get(relative_key)
            if content is None:
                content = self.load_archive(customer_id, section, day)
            return {"section": section, "hits": [{"source": day, "content": content[:1200]}] if content else []}
        prefix = f"{customer_prefix}/{section}/"
        keys: list[str] = []
        continuation: str | None = None
        for _ in range(5):
            request: dict[str, Any] = {"Bucket": self.bucket, "Prefix": prefix, "MaxKeys": 1000}
            if continuation:
                request["ContinuationToken"] = continuation
            page = self.client.list_objects_v2(**request)
            keys.extend(
                item["Key"] for item in page.get("Contents", [])
                if _DAILY_SOURCE[section].fullmatch(item["Key"].removeprefix(prefix))
            )
            continuation = page.get("NextContinuationToken")
            if not continuation:
                break
        terms = [word for word in re.findall(r"\w+", query.casefold()) if len(word) >= 3]
        candidates = [
            {"source": source, "content": content[:900], "score": sum(term in content.casefold() for term in terms)}
            for source, content in live_items.items()
        ]
        for key in sorted(keys, reverse=True)[:12]:
            if key.removeprefix(customer_prefix + "/") in live_items:
                continue  # Current copy is fresher than its archive object.
            content = self._read_object(key) or ""
            score = sum(term in content.casefold() for term in terms)
            candidates.append({"source": key.removeprefix(customer_prefix + "/"), "content": content[:900], "score": score})
        candidates.sort(key=lambda item: item["score"], reverse=True)
        return {"section": section, "hits": candidates[:3]}

    @staticmethod
    def _active_days(snapshot: dict[str, Any]) -> list[str]:
        return sorted({
            match.group(1)
            for collection, pattern in _DAILY_SOURCE.items()
            for item in snapshot.get(collection, [])
            if isinstance(item, dict)
            for match in [pattern.fullmatch(str(item.get("source", "")))]
            if match
        })

    @classmethod
    def _split_recent(cls, snapshot: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[str, str]]]:
        """Keep two latest active dates; return files to archive first."""
        days = cls._active_days(snapshot)
        recent = set(days[-2:])
        current = deepcopy(snapshot)
        archives: list[tuple[str, str]] = []
        for collection, pattern in _DAILY_SOURCE.items():
            retained = []
            for item in snapshot.get(collection, []):
                source = str(item.get("source", ""))
                match = pattern.fullmatch(source)
                if match and match.group(1) not in recent:
                    archives.append((f"{collection}/{source}", str(item.get("content", ""))))
                else:
                    retained.append(item)
            current[collection] = retained
        return current, archives

    def _put_markdown(self, key: str, content: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=BytesIO(content.encode("utf-8")),
            ContentType="text/markdown; charset=utf-8",
        )

    @staticmethod
    def _individual_files(snapshot: dict[str, Any]) -> dict[str, str]:
        """Export the same visible tree as FileCustomerMemoryRepository."""
        facts = snapshot.get("facts", {})
        if not isinstance(facts, dict):
            raise ValueError("Customer facts must be a mapping")
        files = {
            "user.md": str(snapshot.get("profile") or "# User Profile\n\n"),
            "behaviors.md": str(snapshot.get("behaviors") or "# Behavioral Patterns\n\n"),
            "facts.md": "# Customer Facts\n\n" + "".join(
                f"- {key}: {json.dumps(value, ensure_ascii=False)}\n"
                for key, value in facts.items()
            ),
        }
        for collection, pattern in _DAILY_SOURCE.items():
            items = snapshot.get(collection, [])
            if not items:
                # Object stores have no physical empty directories.
                files[f"{collection}/.keep"] = ""
            for item in items:
                source = str(item.get("source", ""))
                if not pattern.fullmatch(source):
                    continue  # Legacy undated entries remain in current.md.
                files[f"{collection}/{source}"] = str(item.get("content", ""))
        return files

    def save_snapshot(
        self,
        customer_id: str,
        snapshot: dict[str, Any],
        *,
        previous_snapshot: dict[str, Any] | None = None,
    ) -> None:
        if snapshot.get("customer_id") != customer_id:
            raise ValueError("Cannot save another customer's memory snapshot")
        current, archives = self._split_recent(snapshot)
        customer_prefix = self._customer_prefix(customer_id)
        files = self._individual_files(snapshot)
        evicted_keys = {key for key, _ in archives}
        initial_export = previous_snapshot is None or previous_snapshot == empty_snapshot(customer_id)
        previous_days = self._active_days(previous_snapshot) if previous_snapshot else []
        current_days = self._active_days(snapshot)
        advanced_day = bool(previous_days and current_days and current_days[-1] > previous_days[-1])
        closed_day = previous_days[-1] if advanced_day else None
        # Routine turns only PUT current.md. Export the visible tree when the
        # customer is first created; on a new activity day, flush the prior
        # day's complete files and static mirrors. Evicted dates are forced
        # durable before current.md drops them.
        for relative_key, content in files.items():
            static_sync = (
                (advanced_day or bool(evicted_keys))
                and relative_key in {"user.md", "behaviors.md", "facts.md"}
            )
            closed_file = bool(
                closed_day
                and any(
                    relative_key.startswith(f"{collection}/")
                    and pattern.fullmatch(relative_key.removeprefix(f"{collection}/"))
                    and relative_key.endswith(f"-{closed_day}.md")
                    for collection, pattern in _DAILY_SOURCE.items()
                )
            )
            if initial_export or relative_key in evicted_keys or closed_file or static_sync:
                self._put_markdown(f"{customer_prefix}/{relative_key}", content)
        key = self._key(customer_id)
        # TemporaryDirectory removes the local draft after a successful PUT
        # and also when serialization/upload raises. Render disk is never the
        # durable copy.
        with tempfile.TemporaryDirectory(prefix="telesale-memory-") as directory:
            draft = Path(directory) / "current.md"
            with draft.open("w", encoding="utf-8", newline="\n") as output:
                output.write(render_snapshot(current))
            with draft.open("rb") as body:
                self.client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=body,
                    ContentType="text/markdown; charset=utf-8",
                )

    def backfill_files(
        self,
        customer_id: str,
        local_snapshot: dict[str, Any] | None = None,
    ) -> int:
        """Repair missing per-file objects without replacing an existing current.md."""
        current = self.load(customer_id)
        files = self._individual_files(local_snapshot or empty_snapshot(customer_id))
        files.update(self._individual_files(current))  # Current wins on overlap.
        customer_prefix = self._customer_prefix(customer_id)
        uploaded = 0
        for relative_key, content in files.items():
            key = f"{customer_prefix}/{relative_key}"
            if self._read_object(key) is None:
                self._put_markdown(key, content)
                uploaded += 1
        return uploaded
