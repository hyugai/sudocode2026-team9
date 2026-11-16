"""Opt-in, post-session learning. Importing this package starts no services."""
from .config import LearningConfig
from .harness import SelfAgentHarness

__all__ = ["LearningConfig", "SelfAgentHarness"]
