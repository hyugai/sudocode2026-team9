from typing import Any

from telesale_agent.adapters.memory import FileCustomerMemoryRepository


memory_repository = FileCustomerMemoryRepository()

def memo_update_user_profile(user_id: str, identity_and_preferences: str) -> dict[str, Any]:
    """
    Update user.md with new identity, goals, preferences, or values.
    BTC tool name: memory.update_user_profile
    """
    return memory_repository.update_profile(user_id, identity_and_preferences)

def memo_update_behaviors(user_id: str, behavioral_pattern: str) -> dict[str, Any]:
    """
    Update behaviors.md with behavioral patterns for proactive service.
    BTC tool name: memory.update_behaviors
    """
    return memory_repository.update_behaviors(user_id, behavioral_pattern)

def memo_record_atomic_fact(user_id: str, fact: str) -> dict[str, Any]:
    """
    Record a single, independently retrievable extracted fact into daily append log.
    BTC tool name: memory.record_atomic_fact
    """
    return memory_repository.record_atomic_fact(user_id, fact)

def memo_record_foresight(user_id: str, foresight: str) -> dict[str, Any]:
    """
    Record a time-bounded plan or prediction about the user into daily append log.
    BTC tool name: memory.record_foresight
    """
    return memory_repository.record_foresight(user_id, foresight)

def memo_record_episode(user_id: str, narrative_summary: str) -> dict[str, Any]:
    """
    Record a narrative summary of a conversation segment into daily append log.
    BTC tool name: memory.record_episode
    """
    return memory_repository.record_episode(user_id, narrative_summary)

TOOLS = {
    "memory.update_user_profile": memo_update_user_profile,
    "memory.update_behaviors": memo_update_behaviors,
    "memory.record_atomic_fact": memo_record_atomic_fact,
    "memory.record_foresight": memo_record_foresight,
    "memory.record_episode": memo_record_episode,
}
