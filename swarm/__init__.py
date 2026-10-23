"""Swarm — multi-agent coordination for SparkAgent.

Agents cooperate through typed messages (mailbox), shared state
(blackboard), and structured topologies (sequential/parallel/star).
Specialized roles — planner, worker, critic, synthesizer — are composed
by the orchestrator rather than hardcoded.
"""

from swarm.protocols import AgentMessage, MessageKind, Sender
from swarm.mailbox import Mailbox

__all__ = ["AgentMessage", "MessageKind", "Sender", "Mailbox"]
