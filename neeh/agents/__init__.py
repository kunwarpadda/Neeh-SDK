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
from neeh.agents.iai import (
    IAI_VERSION,
    PERCEPTION_POLICIES,
    InkAgentInterface,
    PerceptionBudget,
    build_observation_workspace,
)
from neeh.agents.timeline import (
    TIMELINE_VERSION,
    TimelineConfig,
    build_ink_timeline,
    find_ink_moments,
    inspect_ink_moment,
)
from neeh.agents.analyzers import ANALYSIS_OPERATIONS, ANALYSIS_VERSION, analyze_ink
from neeh.agents.reducers import REDUCER_TASKS, reduce_ink

__all__ = [
    "ModelUnavailableError",
    "agent_input_preview",
    "run_claude",
    "run_codex_cli",
    "run_mock",
    "IAI_VERSION",
    "PERCEPTION_POLICIES",
    "InkAgentInterface",
    "PerceptionBudget",
    "build_observation_workspace",
    "TIMELINE_VERSION",
    "TimelineConfig",
    "build_ink_timeline",
    "find_ink_moments",
    "inspect_ink_moment",
    "ANALYSIS_OPERATIONS",
    "ANALYSIS_VERSION",
    "analyze_ink",
    "REDUCER_TASKS",
    "reduce_ink",
]
