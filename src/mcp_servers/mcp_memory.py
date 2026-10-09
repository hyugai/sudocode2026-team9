import os
from datetime import datetime
from pathlib import Path
from typing import Any
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP Server
mcp = FastMCP("Memory-Server")

# Setup Paths
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

@mcp.tool()
def memory_update_user_profile(user_id: str, identity_and_preferences: str) -> str:
    """
    Update the user.md file with new identity, goals, preferences, or values.
    """
    user_dir = _get_user_dir(user_id)
    profile_path = user_dir / "user.md"
    
    with open(profile_path, "a", encoding="utf-8") as f:
        f.write(f"- {identity_and_preferences}\n")
        
    return "Profile updated successfully."

@mcp.tool()
def memory_update_behaviors(user_id: str, behavioral_pattern: str) -> str:
    """
    Update the behaviors.md file with behavioral patterns for proactive service.
    """
    user_dir = _get_user_dir(user_id)
    behaviors_path = user_dir / "behaviors.md"
    
    with open(behaviors_path, "a", encoding="utf-8") as f:
        f.write(f"- {behavioral_pattern}\n")
        
    return "Behaviors updated successfully."

@mcp.tool()
def memory_record_atomic_fact(user_id: str, fact: str) -> str:
    """
    Record a single, independently retrievable extracted fact into daily append log.
    """
    user_dir = _get_user_dir(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    fact_path = user_dir / "atomic_facts" / f"fact-{today}.md"
    
    with open(fact_path, "a", encoding="utf-8") as f:
        f.write(f"- {fact}\n")
        
    return f"Fact recorded in fact-{today}.md."

@mcp.tool()
def memory_record_foresight(user_id: str, foresight: str) -> str:
    """
    Record a time-bounded plan or prediction about the user into daily append log.
    """
    user_dir = _get_user_dir(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    foresight_path = user_dir / "foresights" / f"foresight-{today}.md"
    
    with open(foresight_path, "a", encoding="utf-8") as f:
        f.write(f"- {foresight}\n")
        
    return f"Foresight recorded in foresight-{today}.md."

@mcp.tool()
def memory_record_episode(user_id: str, narrative_summary: str) -> str:
    """
    Record a narrative summary of a conversation segment into daily append log.
    """
    user_dir = _get_user_dir(user_id)
    today = datetime.now().strftime("%Y-%m-%d")
    episode_path = user_dir / "episodes" / f"episode-{today}.md"
    
    with open(episode_path, "a", encoding="utf-8") as f:
        timestamp = datetime.now().strftime("%H:%M:%S")
        f.write(f"### Session at {timestamp}\n{narrative_summary}\n\n")
        
    return f"Episode recorded in episode-{today}.md."

if __name__ == "__main__":
    mcp.run()
