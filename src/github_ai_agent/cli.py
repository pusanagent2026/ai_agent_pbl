from __future__ import annotations

import argparse
import asyncio
import json

from dotenv import load_dotenv

from github_ai_agent.agent import GitHubToolChoosingAgent
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
        "--save-to-notion",
        action="store_true",
        help="Allow the agent to create Notion tasks from the answer.",
    )
    args = parser.parse_args()

    github_domain = build_github_domain_agent(
        owner=args.owner,
        repo=args.repo,
        backend=args.backend,
    )
    notion_domain = build_notion_domain_agent()
    orchestrator = OrchestratorAgent(
        domains=[github_domain, notion_domain],
        model=args.model,
    )

    github_client = GitHubMcpClient()
    tool_client = CombinedToolClient([github_client, NotionToolClient()])
    question = args.question
    if args.save_to_notion:
        question += (
            "\n\nNotion auto-save is enabled. If you identify concrete tasks, "
            "create them in Notion using the available Notion task tool."
        )

    result = await orchestrator.run(question)

    if args.debug:
        print("\n[Selected GitHub tools: mcp]")
        print(json.dumps(result.selected_tools, ensure_ascii=False, indent=2))
        print("\n[Answer]")

    print(result.answer)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
