"""Optional model adapters for turning page context into Neeh tool actions.

Importing this package does not import the OpenAI or Anthropic SDKs. Those
dependencies are loaded only when their corresponding runner is called.
"""

from neeh.agents.assistant import (
    ModelUnavailableError,
    agent_input_preview,
    run_claude,
    run_codex_cli,
    run_mock,
)

__all__ = [
    "ModelUnavailableError",
    "agent_input_preview",
    "run_claude",
    "run_codex_cli",
    "run_mock",
]
