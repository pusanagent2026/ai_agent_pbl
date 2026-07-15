"""LLM logic shared by scripts/update_readme.py (GitHub Actions) and the web
UI's "README 갱신" tab: judge whether a diff needs a README update, and
rewrite the README when it does. Diff/file-listing is deliberately left to
the caller (local git in the Actions script, GitHub REST API in the web UI).
"""

from __future__ import annotations

import os
import re
import time

from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError

MAX_DIFF_CHARS = 12000
MAX_RETRIES = 3

FILTER_MODEL = os.environ.get("README_FILTER_MODEL", "gpt-4o-mini")
REWRITE_MODEL = os.environ.get("README_REWRITE_MODEL", "gpt-4o")

RELEVANCE_CRITERIA = """\
다음 기준으로만 판단하세요:
- yes: 새로운 기능, API, 실행 명령어, 의존성, 설정값(.env 등), 폴더 구조, \
외부 연동, 권한 요구사항이 바뀌었다.
- no: 오타 수정, 주석 변경, 내부 리팩토링, 테스트 변경 등 사용자에게 보이지 \
않는 변화만 있다.
"""


def is_doc_only_change(changed_files: list[str]) -> bool:
    return all(f == "README.md" or f.startswith("docs/") for f in changed_files)


def call_openai_with_retry(client: OpenAI, **create_kwargs: object):
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            return client.chat.completions.create(**create_kwargs)
        except (RateLimitError, APITimeoutError, APIConnectionError, APIError) as error:
            last_error = error
            if attempt < MAX_RETRIES - 1:
                time.sleep(2**attempt)
    raise RuntimeError(f"OpenAI request failed after {MAX_RETRIES} attempts") from last_error


def is_relevant(diff_text: str, changed_files: list[str], client: OpenAI) -> bool:
    response = call_openai_with_retry(
        client,
        model=FILTER_MODEL,
        temperature=0,
        max_tokens=5,
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 이 변경이 README.md 갱신을 필요로 하는지 판단하는 "
                    f"필터입니다. {RELEVANCE_CRITERIA}\n"
                    "답변은 반드시 정확히 'yes' 또는 'no' 한 단어만 출력하세요. "
                    "다른 설명은 절대 추가하지 마세요."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"변경된 파일:\n{chr(10).join(changed_files)}\n\n"
                    f"diff:\n{diff_text}"
                ),
            },
        ],
    )
    content = (response.choices[0].message.content or "").strip().lower()
    return content.startswith("yes")


def rewrite_readme(
    diff_text: str, changed_files: list[str], current_readme: str, client: OpenAI
) -> tuple[str, str]:
    response = call_openai_with_retry(
        client,
        model=REWRITE_MODEL,
        temperature=0.2,
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 이 저장소의 README.md를 유지보수하는 기술 문서 작성자입니다.\n"
                    "규칙:\n"
                    "1. 기존 README를 통째로 새로 쓰지 말고, 변경이 필요한 섹션만 수정하세요. "
                    "나머지 내용은 원문 그대로 보존하세요.\n"
                    "2. diff에 실제로 나타난 변경만 반영하세요. 없는 내용을 지어내지 마세요.\n"
                    "3. 갱신이 필요 없다면 기존 README를 그대로 반환하세요.\n"
                    "4. 반드시 아래 형식으로만 출력하세요(다른 텍스트 금지, 마크다운 코드펜스 금지):\n"
                    "<<<README_START>>>\n(전체 README.md 내용)\n<<<README_END>>>\n"
                    "<<<SUMMARY_START>>>\n(무엇이 왜 바뀌었는지 한국어로 짧게 요약, PR 본문용)\n"
                    "<<<SUMMARY_END>>>"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"현재 README.md:\n{current_readme}\n\n"
                    f"변경된 파일:\n{chr(10).join(changed_files)}\n\n"
                    f"diff:\n{diff_text}"
                ),
            },
        ],
    )
    content = response.choices[0].message.content or ""

    readme_match = re.search(r"<<<README_START>>>\n(.*?)\n<<<README_END>>>", content, re.DOTALL)
    summary_match = re.search(r"<<<SUMMARY_START>>>\n(.*?)\n<<<SUMMARY_END>>>", content, re.DOTALL)
    if not readme_match:
        # Model didn't follow the format: fail safe by keeping the README untouched.
        return current_readme, ""

    new_readme = readme_match.group(1).strip("\n")
    new_readme = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", new_readme)
    summary = summary_match.group(1).strip() if summary_match else ""
    return new_readme, summary
