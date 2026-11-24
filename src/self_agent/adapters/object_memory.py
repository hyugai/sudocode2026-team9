"""S3-compatible agent lessons and diagnostic artifacts, separate from users/."""
import json
import os
import re

from self_agent.lessons import compact_context, markdown, parse_lesson

GROUPS = frozenset({"gaps", "knowledge", "patterns", "regression_cases", "reports", "releases"})


class ObjectStorageAgentMemory:
    def __init__(self, *, bucket=None, prefix=None, runtime_prefix=None, client=None):
        self.bucket = bucket or os.environ.get("AGENT_MEMORY_BUCKET") or os.environ.get("CUSTOMER_MEMORY_BUCKET", "")
        if not self.bucket:
            raise ValueError("AGENT_MEMORY_BUCKET (hoặc CUSTOMER_MEMORY_BUCKET) is required")
        self.prefix = self._prefix(prefix if prefix is not None else os.environ.get(
            "AGENT_MEMORY_PREFIX", "agents/telesales_agent/knowledge_gap_loop"))
        self.runtime_prefix = self._prefix(runtime_prefix if runtime_prefix is not None else os.environ.get(
            "AGENT_LEARNING_RUNTIME_PREFIX", "learning-runtime/telesales_agent"))
        if self.prefix == self.runtime_prefix or self.prefix.startswith(self.runtime_prefix + "/") or self.runtime_prefix.startswith(self.prefix + "/"):
            raise ValueError("Agent memory and runtime prefixes must be separate")
        customer_prefix = os.environ.get("CUSTOMER_MEMORY_PREFIX", "users").strip("/")
        if not customer_prefix or any(p == customer_prefix or p.startswith(customer_prefix + "/")
                                      or customer_prefix.startswith(p + "/")
                                      for p in (self.prefix, self.runtime_prefix)):
            raise ValueError("Agent prefixes must not overlap customer memory")
        if client is None:
            import boto3
            from botocore.config import Config
            client = boto3.client(
                "s3", endpoint_url=os.environ.get("AWS_ENDPOINT_URL_S3") or None,
                region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or None,
                config=Config(s3={"addressing_style": "path"}, connect_timeout=3, read_timeout=5,
                              retries={"mode": "standard", "total_max_attempts": 2}))
        self.client = client

    @staticmethod
    def _prefix(value):
        value = value.strip("/")
        if not value or not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", value):
            raise ValueError("Invalid agent storage prefix")
        return value

    @staticmethod
    def _id(key):
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]+", key):
            raise ValueError("Artifact key must be a hex digest")
        return key

    def _key(self, group, key):
        if group not in GROUPS:
            raise ValueError("Unknown artifact group")
        return f"{self.runtime_prefix}/{group}/{self._id(key)}.json"

    def _read(self, key):
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        except Exception as exc:
            if getattr(exc, "response", {}).get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
                raise FileNotFoundError(key) from None
            raise
        try:
            return body.read().decode("utf-8")
        finally:
            body.close()

    def _put(self, key, text, content_type):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=text.encode("utf-8"), ContentType=content_type)

    def _keys(self, prefix):
        token = None
        while True:
            args = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                args["ContinuationToken"] = token
            page = self.client.list_objects_v2(**args)
            yield from (item["Key"] for item in page.get("Contents", []))
            if not page.get("IsTruncated"):
                break
            token = page["NextContinuationToken"]

    def read(self, group, key):
        return json.loads(self._read(self._key(group, key)))

    def write(self, group, key, value):
        self._put(self._key(group, key), json.dumps(value, ensure_ascii=False, allow_nan=False),
                  "application/json; charset=utf-8")

    def records(self, group):
        self._key(group, "a")
        return [json.loads(self._read(key)) for key in sorted(self._keys(f"{self.runtime_prefix}/{group}/"))
                if key.endswith(".json")]

    def write_lesson(self, lesson):
        relative = f"lessons/approved/{self._id(lesson['id'])}.md"
        self._put(f"{self.prefix}/{relative}", markdown(lesson), "text/markdown; charset=utf-8")
        return relative

    def load_lessons(self):
        result, seen = [], set()
        for key in sorted(self._keys(f"{self.prefix}/lessons/approved/")):
            if not key.endswith(".md"):
                continue
            try:
                lesson = parse_lesson(self._read(key))
            except (ValueError, TypeError, KeyError):
                continue
            normalized = " ".join(compact_context(lesson).casefold().split())
            if normalized not in seen:
                result.append(lesson)
                seen.add(normalized)
        return result
