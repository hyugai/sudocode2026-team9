"""
telesale_agent/tools package

Contains all BTC-standard tool implementations, organized by domain.
Each domain module exposes a TOOLS dict mapping BTC tool name → callable.

To add a new tool:
  1. Add your function to the appropriate domain module (or create a new one).
  2. Add it to that module's TOOLS dict.
  3. It will automatically appear in the registry.

To swap mock → real implementation for a domain:
  Change the import in registry.py for that domain's TOOLS dict.
"""
