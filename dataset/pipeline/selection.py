"""Select complete journeys deterministically, without truncating sessions."""
from __future__ import annotations


def select_plans(plans: list[dict], *, limit: int | None = None, samples: int | None = None,
                 journey_ids: list[str] | None = None) -> list[dict]:
    if sum(x is not None for x in (limit, samples, journey_ids)) > 1:
        raise ValueError("choose one of journey limit, sample count or explicit journey IDs")
    if journey_ids is not None:
        if not journey_ids or any(not isinstance(x, str) for x in journey_ids) or len(set(journey_ids)) != len(journey_ids):
            raise ValueError("journey IDs must be distinct nonempty strings")
        selected = [p for p in plans if p["journey_id"] in journey_ids]
        if len(selected) != len(journey_ids):
            raise ValueError("requested journey is absent from the frozen plan")
        return selected
    for name, value in (("limit", limit), ("samples", samples)):
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError(f"{name} must be a positive integer")
    if samples is None:
        return plans if limit is None else plans[:limit]
    if samples > sum(len(plan["sessions"]) for plan in plans):
        raise ValueError("sample count exceeds the frozen plan")
    # Prefer fewer journeys, then the earliest indices in the frozen plan.
    choices = {0: ()}
    for index, plan in enumerate(plans):
        size = len(plan["sessions"])
        for total, selected in list(choices.items()):
            target = total + size
            if target > samples:
                continue
            candidate = selected + (index,)
            previous = choices.get(target)
            if previous is None or (len(candidate), candidate) < (len(previous), previous):
                choices[target] = candidate
    if samples not in choices:
        raise ValueError("exact sample count cannot be formed from complete journeys; choose another count")
    return [plans[index] for index in choices[samples]]
