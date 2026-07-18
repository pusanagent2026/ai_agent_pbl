from __future__ import annotations

import argparse
import asyncio
import json
import os

from dotenv import load_dotenv

from github_ai_agent.agent import GitHubToolChoosingAgent
from github_ai_agent.github_api_client import DirectGitHubToolClient
from github_ai_agent.mcp_client import GitHubMcpClient
from github_ai_agent.notion_client import NotionToolClient
from github_ai_agent.tool_client import CombinedToolClient


async def async_main() -> None:
    load_dotenv(encoding="utf-8-sig")

    parser = argparse.ArgumentParser(
        description="Ask an AI agent to choose and call GitHub MCP tools."
    )
    parser.add_argument("question", help="Natural language question about the project.")
    parser.add_argument("--owner", help="GitHub owner/org. Defaults to GITHUB_OWNER.")
    parser.add_argument("--repo", help="GitHub repo. Defaults to GITHUB_REPO.")
    parser.add_argument("--model", help="OpenAI model. Defaults to OPENAI_MODEL.")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print selected GitHub tools and arguments.",
    )
    parser.add_argument(
        "--backend",
        choices=["github-api", "mcp"],
        default=os.environ.get("GITHUB_TOOL_BACKEND", "github-api"),
        help="Use github-api now, or mcp later with Docker/local MCP server.",
    )
    parser.add_argument(
        "--save-to-notion",
        action="store_true",
        help="Allow the agent to create Notion tasks from the answer.",
    )
    args = parser.parse_args()

    agent = GitHubToolChoosingAgent(
        model=args.model,
        owner=args.owner,
        repo=args.repo,
        approved_tools={"create_notion_task"} if args.save_to_notion else set(),
    )

    if args.backend == "mcp":
        github_client = GitHubMcpClient()
    else:
        github_client = DirectGitHubToolClient(owner=args.owner, repo=args.repo)

    tool_client = CombinedToolClient([github_client, NotionToolClient()])
    question = args.question
    if args.save_to_notion:
        question += (
            "\n\nNotion auto-save is enabled. If you identify concrete tasks, "
            "create them in Notion using the available Notion task tool."
        )

    async with tool_client as github_tools:
        result = await agent.run(question, github_tools)

    if args.debug:
        print(f"\n[Selected GitHub tools: {args.backend}]")
        print(json.dumps(result.selected_tools, ensure_ascii=False, indent=2))
        if result.blocked_actions:
            print("\n[Blocked actions: approval required]")
            print(json.dumps(result.blocked_actions, ensure_ascii=False, indent=2))
        if result.failures:
            print("\n[Tool failures]")
            print(json.dumps(result.failures, ensure_ascii=False, indent=2))
        print("\n[Answer]")

    print(result.answer)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
