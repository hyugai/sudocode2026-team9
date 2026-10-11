import os
import sys
from mcp.server.fastmcp import FastMCP

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from telesale_agent.adapters.memory import FileCustomerMemoryRepository

# Initialize FastMCP Server
mcp = FastMCP("Memory-Server")

memory_repository = FileCustomerMemoryRepository()

@mcp.tool()
def memory_update_user_profile(user_id: str, identity_and_preferences: str) -> str:
    """
    Update user.md with new identity, goals, preferences, or values.
    """
    result = memory_repository.update_profile(user_id, identity_and_preferences)
    return f"Profile updated in {result['file']}."

@mcp.tool()
def memory_update_behaviors(user_id: str, behavioral_pattern: str) -> str:
    """
    Update behaviors.md with behavioral patterns for proactive service.
    """
    result = memory_repository.update_behaviors(user_id, behavioral_pattern)
    return f"Behaviors updated in {result['file']}."

@mcp.tool()
def memory_record_atomic_fact(user_id: str, fact: str) -> str:
    """
    Record a single, independently retrievable extracted fact into daily append log.
    """
    result = memory_repository.record_atomic_fact(user_id, fact)
    return f"Fact recorded in {result['file']}."

@mcp.tool()
def memory_record_foresight(user_id: str, foresight: str) -> str:
    """
    Record a time-bounded plan or prediction about the user into daily append log.
    """
    result = memory_repository.record_foresight(user_id, foresight)
    return f"Foresight recorded in {result['file']}."

@mcp.tool()
def memory_record_episode(user_id: str, narrative_summary: str) -> str:
    """
    Record a narrative summary of a conversation segment into daily append log.
    """
    result = memory_repository.record_episode(user_id, narrative_summary)
    return f"Episode recorded in {result['file']}."

if __name__ == "__main__":
    mcp.run()
