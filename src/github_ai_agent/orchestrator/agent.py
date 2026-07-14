from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from github_ai_agent.agent import AgentResult, GitHubToolChoosingAgent
from github_ai_agent.mcp_client import McpTool
from github_ai_agent.orchestrator.prompts import ORCHESTRATOR_SYSTEM_PROMPT


@dataclass(frozen=True)
class DomainAgent:
    """Registration contract for a domain sub-agent.

    Each domain owns its own tools/prompt internally and exposes a single
    `run(question) -> answer` entry point. The orchestrator only sees this
    contract, never the domain's internal tools, so domains can be built and
    changed independently of each other.
    """

    name: str
    description: str
    run: Callable[[str], Awaitable[str]]


class DelegatingToolClient:
    """Exposes each registered DomainAgent as one orchestrator tool call."""

    def __init__(self, domains: list[DomainAgent]) -> None:
        self.domains = {domain.name: domain for domain in domains}

    async def __aenter__(self) -> "DelegatingToolClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def list_tools(self) -> list[McpTool]:
        return [
            McpTool(
                name=f"delegate_to_{name}_agent",
                description=domain.description,
                input_schema={
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The user's question, forwarded to this domain's agent.",
                        }
                    },
                    "required": ["question"],
                    "additionalProperties": False,
                },
            )
            for name, domain in self.domains.items()
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        domain_name = name.removeprefix("delegate_to_").removesuffix("_agent")
        domain = self.domains.get(domain_name)
        if domain is None:
            raise ValueError(f"Unknown domain delegate tool: {name}")
        return await domain.run(str(arguments.get("question", "")))


class OrchestratorAgent:
    """Routes a question to the relevant domain sub-agent(s) and synthesizes an answer."""

    def __init__(
        self,
        domains: list[DomainAgent],
        *,
        model: str | None = None,
        max_tool_rounds: int = 3,
    ) -> None:
        self.domains = domains
        # Reuses the existing tool-calling loop (class name is GitHub-specific
        # for historical reasons only; the loop itself is domain-agnostic).
        self._agent = GitHubToolChoosingAgent(
            model=model,
            system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
            max_tool_rounds=max_tool_rounds,
        )

    async def run(self, question: str) -> AgentResult:
        tool_client = DelegatingToolClient(self.domains)
        async with tool_client as tools:
            return await self._agent.run(question, tools)
