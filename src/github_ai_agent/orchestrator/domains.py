"""Domain registration point.

To add a new domain (code review, meeting, calendar, ...):
1. Build your domain's own agent/tool logic in your own module(s) — do not
   edit this file's existing entries.
2. Add one `build_<domain>_domain_agent()` function here that returns a
   `DomainAgent` (name, description, async run(question) -> str).
3. Append it to the list passed into `OrchestratorAgent(domains=[...])` in
   cli.py / web.py.

The orchestrator only ever calls `DomainAgent.run(question)` — your domain's
internal tools, prompts, and backends stay private to your module.
"""

from __future__ import annotations

import os

from github_ai_agent.agent import GitHubToolChoosingAgent
from github_ai_agent.github_api_client import DirectGitHubToolClient
from github_ai_agent.mcp_client import GitHubMcpClient
from github_ai_agent.notion_client import NotionToolClient
from github_ai_agent.orchestrator.agent import DomainAgent


def build_github_domain_agent(
    *,
    owner: str | None = None,
    repo: str | None = None,
    backend: str | None = None,
) -> DomainAgent:
    """Wraps the existing GitHub tool-calling flow as one delegate tool."""

    async def run(question: str) -> str:
        agent = GitHubToolChoosingAgent(owner=owner, repo=repo)
        resolved_backend = backend or os.environ.get("GITHUB_TOOL_BACKEND", "github-api")
        github_client = (
            GitHubMcpClient()
            if resolved_backend == "mcp"
            else DirectGitHubToolClient(owner=owner, repo=repo)
        )
        async with github_client as tools:
            result = await agent.run(question, tools)
        return result.answer

    return DomainAgent(
        name="github",
        description=(
            "Answers questions about this GitHub repository: issues, pull "
            "requests, commits, and workflow runs."
        ),
        run=run,
    )


NOTION_DOMAIN_SYSTEM_PROMPT = """
You create tasks in a connected Notion database using the create_notion_task
tool. Read the question, extract concrete action items, and call
create_notion_task once per task with a short action-oriented title,
priority, source, and a brief evidence-based reason. Do not dump raw JSON.
If there is nothing concrete to save, say so without calling any tool.

Answer in Korean unless the user asks for another language.
""".strip()


def build_notion_domain_agent() -> DomainAgent:
    """Wraps the existing Notion task-creation tool as its own delegate."""

    async def run(question: str) -> str:
        tool_client = NotionToolClient()
        if not tool_client.enabled:
            return "Notion 연동이 설정되어 있지 않습니다 (NOTION_API_KEY / NOTION_DATABASE_ID 필요)."

        agent = GitHubToolChoosingAgent(
            system_prompt=NOTION_DOMAIN_SYSTEM_PROMPT,
            max_tool_rounds=4,
        )
        async with tool_client as tools:
            result = await agent.run(question, tools)
        return result.answer

    return DomainAgent(
        name="notion",
        description=(
            "Creates tasks in the connected Notion database. Use only when "
            "the user explicitly asks to save/record/add tasks, or Notion "
            "auto-save is enabled and there are concrete action items to save."
        ),
        run=run,
    )
