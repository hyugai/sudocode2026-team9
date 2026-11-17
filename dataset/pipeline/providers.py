from __future__ import annotations

import importlib.metadata
import os
from pathlib import Path

from .common import fingerprint, read, write


class ProviderFailure(RuntimeError):
    pass


class OpenAIProvider:
    def __init__(self, model: str, max_output_tokens: int, *, client=None):
        if not model or model == "SET_OPENAI_MODEL":
            raise ValueError("choose an explicit OpenAI model using --model or config")
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise ValueError("OPENAI_API_KEY is required for live generation")
            from openai import OpenAI
            client = OpenAI(timeout=60, max_retries=0)
        self.client = client
        self.model = model
        self.max_output_tokens = max_output_tokens
        try:
            sdk = importlib.metadata.version("openai")
        except importlib.metadata.PackageNotFoundError:
            sdk = None
        self.metadata = {"provider": "openai", "model": model, "sdk_version": sdk,
                         "max_output_tokens": max_output_tokens, "sdk_max_retries": 0,
                         "seed": None, "temperature": None, "store": False}

    def request(self, request: dict) -> dict:
        try:
            response = self.client.responses.create(
                model=self.model, input=request["messages"], max_output_tokens=self.max_output_tokens,
                text={"format": {"type": "json_schema", "name": request["schema_name"],
                                 "strict": True, "schema": request["schema"]}}, store=False)
        except Exception as exc:
            raise ProviderFailure(f"OpenAI request failed: {type(exc).__name__}; status={getattr(exc, 'status_code', None)}") from None
        data = response.model_dump(mode="json")
        return {"text": response.output_text, "raw": data,
                "completed": response.status == "completed" and bool(response.output_text),
                "metadata": {"response_id": response.id, "model": response.model,
                             "status": response.status, "usage": data.get("usage")}}


class ReplayProvider:
    def __init__(self, run: Path):
        self.records = [read(p) for p in sorted((run / "calls").glob("*.json"))]
        self.position = 0
        self.metadata = {"provider": "offline_replay", "original": read(run / "run.json")["provider"]}

    def request(self, request: dict) -> dict:
        if self.position >= len(self.records):
            raise ProviderFailure("replay ended before the next required response")
        record = self.records[self.position]
        if record["request_sha256"] != fingerprint(request) or record["request"] != request:
            raise ProviderFailure("replay request differs from the archived request")
        self.position += 1
        if "response" not in record:
            raise ProviderFailure("archived call did not finish; cannot invent its response")
        return record["response"]

    def finish(self) -> None:
        if self.position != len(self.records):
            raise ProviderFailure("replay left archived calls unconsumed; execution diverged")


class RoutedProvider:
    """Use an independently configured client for judging, with one audit stream."""

    def __init__(self, generator, reviewer):
        self.generator, self.reviewer = generator, reviewer
        self.metadata = {"provider": "openai_routed", "generation": generator.metadata,
                         "automated_review": reviewer.metadata}

    def request(self, request: dict) -> dict:
        return (self.generator if request["kind"] == "generate" else self.reviewer).request(request)


class Recorder:
    def __init__(self, provider, output: Path, budget: int):
        self.provider, self.output, self.budget = provider, output, budget
        self.count = 0

    def request(self, request: dict) -> dict:
        if self.count >= self.budget:
            raise ProviderFailure("configured model-call budget exhausted")
        self.count += 1
        path = self.output / "calls" / f"{self.count:06d}.json"
        record = {"request_sha256": fingerprint(request), "request": request}
        write(path, record)
        try:
            response = self.provider.request(request)
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            write(path, record)
            raise
        record["response"] = response
        write(path, record)
        return response
