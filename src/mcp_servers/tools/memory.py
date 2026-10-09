import os
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MEMORY_ROOT = PROJECT_ROOT / "data" / "memory-root" / "users"

def _get_user_dir(user_id: str) -> Path:
    # Zero-Config Identity: Create directory on demand
    user_dir = MEMORY_ROOT / f"{user_id}"
    user_dir.mkdir(parents=True, exist_ok=True)
    
    (user_dir / "episodes").mkdir(exist_ok=True)
    (user_dir / "atomic_facts").mkdir(exist_ok=True)
    (user_dir / "foresights").mkdir(exist_ok=True)
    
    # Initialize single files if they don't exist
    if not (user_dir / "user.md").exists():
        (user_dir / "user.md").write_text("# User Profile\n\n", encoding="utf-8")
        
    if not (user_dir / "behaviors.md").exists():
        (user_dir / "behaviors.md").write_text("# Behavioral Patterns\n\n", encoding="utf-8")
        
    return user_dir

def memo_update_user_profile(user_id: str, identity_and_preferences: str) -> dict[str, Any]:
    """
    Update the user.md file with new identity, goals, preferences, or values.
    BTC tool name: memory.update_user_profile
    """
    user_dir = _get_user_dir(user_id)
    profile_path = user_dir / "user.md"
    
    # In-place update (For simplicity, we append. In a production system, an LLM might rewrite this file).
    with open(profile_path, "a", encoding="utf-8") as f:
        f.write(f"- {identity_and_preferences}\n")
        
    return {"status": "success", "file": "user.md", "action": "updated"}

def memo_update_behaviors(user_id: str, behavioral_pattern: str) -> dict[str, Any]:
    """
    Update the behaviors.md file with behavioral patterns for proactive service.
    BTC tool name: memory.update_behaviors
    """
    user_dir = _get_user_dir(user_id)
    behaviors_path = user_dir / "behaviors.md"
    
    with open(behaviors_path, "a", encoding="utf-8") as f:
        f.write(f"- {behavioral_pattern}\n")
        
    return {"status": "success", "file": "behaviors.md", "action": "updated"}

def memo_record_atomic_fact(user_id: str, fact: str) -> dict[str, Any]:
    """
    Record a single, independently retrievable extracted fact into daily append log.
    BTC tool name: memory.record_atomic_fact
    """
    user_dir = _get_user_dir(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    fact_path = user_dir / "atomic_facts" / f"fact-{today}.md"
    
    with open(fact_path, "a", encoding="utf-8") as f:
        f.write(f"- {fact}\n")
        
    return {"status": "success", "file": f"atomic_facts/fact-{today}.md"}

def memo_record_foresight(user_id: str, foresight: str) -> dict[str, Any]:
    """
    Record a time-bounded plan or prediction about the user into daily append log.
    BTC tool name: memory.record_foresight
    """
    user_dir = _get_user_dir(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    foresight_path = user_dir / "foresights" / f"foresight-{today}.md"
    
    with open(foresight_path, "a", encoding="utf-8") as f:
        f.write(f"- {foresight}\n")
        
    return {"status": "success", "file": f"foresights/foresight-{today}.md"}

def memo_record_episode(user_id: str, narrative_summary: str) -> dict[str, Any]:
    """
    Record a narrative summary of a conversation segment into daily append log.
    BTC tool name: memory.record_episode
    """
    user_dir = _get_user_dir(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    episode_path = user_dir / "episodes" / f"episode-{today}.md"
    
    with open(episode_path, "a", encoding="utf-8") as f:
        timestamp = datetime.now().strftime("%H:%M:%S")
        f.write(f"### Session at {timestamp}\n{narrative_summary}\n\n")
        
    return {"status": "success", "file": f"episodes/episode-{today}.md"}

TOOLS = {
    "memory.update_user_profile": memo_update_user_profile,
    "memory.update_behaviors": memo_update_behaviors,
    "memory.record_atomic_fact": memo_record_atomic_fact,
    "memory.record_foresight": memo_record_foresight,
    "memory.record_episode": memo_record_episode,
}
