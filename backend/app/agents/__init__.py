"""Agent framework for WriterAgent loop.

This package provides the core data structures for implementing
an agent-based architecture for the WriterAgent service.
"""

from app.agents.action import AgentAction
from app.agents.state import AgentState

__all__ = [
    "AgentAction",
    "AgentState",
]
