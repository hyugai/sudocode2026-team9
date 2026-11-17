"""Deterministic duplicate triage, independent of the generation model."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass


def normalized(transcript: dict, entities: list[str] | None = None) -> str:
    text = " ".join(f"{u['speaker']} {u['text']}" for u in transcript["utterances"])
    text = unicodedata.normalize("NFC", text).casefold()
    # Local comparison only: this never changes the model request or exported text.
    for entity in sorted(set(entities or []), key=lambda s: (-len(s), s)):
        if entity:
            text = re.sub(r"(?<!\w)" + re.escape(entity.casefold()) + r"(?!\w)", " entity ", text)
    text = re.sub(r"\b(?:syn-c\d+|j\d+-s\d+|od\d+)\b", " identifier ", text)
    text = re.sub(r"\d+(?:[.,]\d+)*", " number ", text)
    return " ".join(re.findall(r"\w+", text))


def shingles(text: str) -> set[tuple]:
    words = text.split()
    return {tuple(words[i:i+3]) for i in range(max(1, len(words)-2))}


@dataclass
class Entry:
    transcript: dict
    normalized_text: str
    grams: set
    exact_hash: str
    source: str


class DuplicateIndex:
    def __init__(self):
        self.entries: list[Entry] = []

    def add(self, transcript: dict, entities: list[str], source: str) -> None:
        text = normalized(transcript, entities)
        dialogue = {"transcript_id": transcript["transcript_id"], "utterances": transcript["utterances"]}
        self.entries.append(Entry(dialogue, text, shingles(text), hashlib.sha256(text.encode()).hexdigest(), source))

    def compare(self, candidate: dict, entities: list[str], config: dict) -> dict:
        text = normalized(candidate, entities)
        exact = hashlib.sha256(text.encode()).hexdigest()
        grams = shingles(text)
        matches = []
        for e in self.entries:
            score = len(grams & e.grams) / max(1, len(grams | e.grams))
            if exact == e.exact_hash or score >= config["review_threshold"]:
                matches.append({"transcript_id": e.transcript["transcript_id"], "source": e.source,
                                "score": round(score, 8), "exact": exact == e.exact_hash,
                                "reference": e.transcript})
        matches.sort(key=lambda m: (-m["score"], m["source"], m["transcript_id"]))
        reject = any(m["exact"] or m["score"] >= config["reject_threshold"] for m in matches)
        return {"decision": "reject" if reject else "review" if matches else "clear",
                "matches": matches[:3], "algorithm": "nfc_casefold_entity_number_normalized_word_trigram_jaccard_v1"}

    def copy(self) -> "DuplicateIndex":
        other = DuplicateIndex()
        other.entries = list(self.entries)
        return other
