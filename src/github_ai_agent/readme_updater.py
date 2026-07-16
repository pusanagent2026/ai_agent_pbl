"""LLM logic for the web UI's "README 갱신" tab: judge whether a diff needs a
README update, and rewrite the README when it does. Diff/file-listing is
deliberately left to the caller (GitHub REST API in the web UI).

The "does this need a README update?" judgment is a 3-layer filter, cheapest
first, so the LLM (layer 3) is only called for genuinely ambiguous changes:
  layer1_rule_filter  - file-path rules, no LLM, near-zero cost
  layer2_diff_analysis - regex over the diff text, no LLM, still cheap
  layer3_llm_judge     - gpt-4o-mini yes/no, only for what's left ambiguous
should_update_readme() wires the three together and is what callers use.
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

# Layer 1: paths that can never need a README update on their own. Dependency
# manifests (requirements.txt, pyproject.toml, package.json, ...) are
# deliberately NOT here even though they're "config" - layer 2 treats a
# dependency change as a strong update signal, so hard-skipping them here
# would contradict that.
_TEST_FILE_RE = re.compile(r"(^|/)(test_[^/]*\.py|[^/]*_test\.py)$")
_TOOLING_CONFIG_FILES = {
    ".flake8",
    ".pylintrc",
    "pytest.ini",
    "tox.ini",
    "mypy.ini",
    ".pre-commit-config.yaml",
    ".editorconfig",
    ".gitignore",
    "ruff.toml",
    ".ruff.toml",
    "setup.cfg",
}

# Layer 1: commit-message prefixes are only ever a hint (never a verdict on
# their own) because a developer can write "chore: ..." and still slip in a
# real feature. Layer 2 decides whether the diff backs the hint up.
_SKIP_HINT_PREFIXES = ("docs:", "test:", "chore:", "style:")
_PASS_HINT_MARKERS = ("feat:", "feat!:", "breaking")

# Layer 2: Python-only, since this repo is pure Python (including the
# web.py frontend, which is inline HTML/JS strings, not separate files).
# Extend with more patterns if/when non-Python source is added.
_DEPENDENCY_FILE_RE = re.compile(
    r"(^|/)(requirements[^/]*\.txt|pyproject\.toml|package(-lock)?\.json|poetry\.lock|Pipfile(\.lock)?)$"
)
_ROUTE_DECORATOR_RE = re.compile(r"^\+\s*@(app|router)\.\w+\(")
_DEF_LINE_RE = re.compile(r"^([+-])\s*(?:async\s+)?def\s+(\w+)\s*\((.*?)\)")
_CLASS_OR_DEF_ADDED_RE = re.compile(r"^\+\s*(?:async\s+def|def|class)\s+(\w+)\b")
_CLI_CONFIG_ADDED_RE = re.compile(r"^\+.*(add_argument\(|click\.option\(|@click\.command)")


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


def layer1_rule_filter(changed_files: list[str], commit_messages: list[str]) -> dict:
    """Layer 1: no LLM. File paths can hard-skip on their own (near-zero
    cost, no ambiguity - a docs/test/tooling-only change never needs a
    README update). Commit-message prefixes CANNOT hard-skip or hard-pass on
    their own - a developer can write "chore: ..." and still slip in a real
    feature - so they only produce a `commit_hint` that layer 2 weighs
    against the actual diff.
    """
    if changed_files and all(
        f == "README.md"
        or f.startswith("docs/")
        or f.startswith("tests/")
        or _TEST_FILE_RE.search(f)
        or f in _TOOLING_CONFIG_FILES
        for f in changed_files
    ):
        return {
            "hard_skip": True,
            "commit_hint": "neutral",
            "reason": "changed files are all docs/tests/tooling-config",
        }

    lowered = [m.lower() for m in commit_messages]
    if any(marker in m for m in lowered for marker in _PASS_HINT_MARKERS):
        commit_hint = "pass_likely"
    elif lowered and all(m.startswith(_SKIP_HINT_PREFIXES) for m in lowered):
        commit_hint = "skip_candidate"
    else:
        commit_hint = "neutral"

    return {"hard_skip": False, "commit_hint": commit_hint, "reason": f"commit_hint={commit_hint}"}


def layer2_diff_analysis(diff_text: str, changed_files: list[str], commit_hint: str) -> dict:
    """Layer 2: no LLM, just regex over the diff text (Python-only patterns -
    this repo, including the web.py frontend, is pure Python). Structural
    evidence in the diff outranks the commit-message hint: a clear signal
    (new endpoint, changed function signature, dependency file, new CLI/
    config option) decides "update" regardless of what the hint says, since
    the diff is proof and the commit message is only a claim. Only a genuine
    conflict (no signal at all, but the hint claims a feature change) or a
    signal whose public/private nature is unclear gets punted to layer 3.
    """
    signals: list[str] = []
    weak_signals: list[str] = []

    if any(_DEPENDENCY_FILE_RE.search(f) for f in changed_files):
        signals.append("dependency file changed")

    removed_defs: dict[str, str] = {}
    added_defs: dict[str, str] = {}
    for line in diff_text.splitlines():
        if _ROUTE_DECORATOR_RE.match(line):
            signals.append("new route/endpoint decorator")
            continue
        if _CLI_CONFIG_ADDED_RE.match(line):
            signals.append("CLI argument or config option added")
            continue

        def_match = _DEF_LINE_RE.match(line)
        if def_match:
            sign, name, args = def_match.groups()
            if sign == "-":
                removed_defs[name] = args
            else:
                added_defs[name] = args
                if not name.startswith("_"):
                    # Underscore-prefixed names are internal helpers (no
                    # signal). Anything else could be a public API but a
                    # diff alone can't prove it, so it's a weak/ambiguous
                    # signal - unless it also turns out to be a signature
                    # change below, which promotes it to a strong signal.
                    weak_signals.append(f"new public def: {name}")
            continue

        added_match = _CLASS_OR_DEF_ADDED_RE.match(line)
        if added_match and not added_match.group(1).startswith("_"):
            # Only reached for `class` additions here - `def`/`async def`
            # lines are already handled (and `continue`d past) above.
            weak_signals.append(f"new public def/class: {added_match.group(1)}")

    for name, new_args in added_defs.items():
        old_args = removed_defs.get(name)
        if old_args is not None and old_args.strip() != new_args.strip():
            signals.append(f"function signature changed: {name}")

    if signals:
        return {"verdict": "update", "signals": signals, "reason": "strong structural signal found"}

    if weak_signals:
        return {"verdict": "ambiguous", "signals": weak_signals, "reason": "unclear public-API signal"}

    if commit_hint == "pass_likely":
        return {
            "verdict": "ambiguous",
            "signals": [],
            "reason": "no structural signal but commit message claims a feature change",
        }

    return {"verdict": "skip", "signals": [], "reason": "no structural signal in diff"}


def layer3_llm_judge(
    diff_text: str, changed_files: list[str], layer2_result: dict, client: OpenAI
) -> bool:
    """Layer 3: only reached when layers 1-2 couldn't decide. Same
    yes/no-only prompt shape the old single-layer filter used, plus the
    layer 2 signals so the model has context on why this case was ambiguous
    instead of judging blind.
    """
    signals_text = ", ".join(layer2_result.get("signals", [])) or "없음"
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
                    f"1차 분석에서 발견된 애매한 신호: {signals_text}\n\n"
                    f"diff:\n{diff_text}"
                ),
            },
        ],
    )
    content = (response.choices[0].message.content or "").strip().lower()
    return content.startswith("yes")


def should_update_readme(
    diff_text: str, changed_files: list[str], commit_messages: list[str], client: OpenAI
) -> tuple[bool, dict]:
    """Orchestrates layer1 -> layer2 -> (layer3 only if still ambiguous).
    Returns (should_update, trace); the trace is safe to log as-is since it
    only holds verdicts and matched-signal names, never the full diff or
    README content.
    """
    layer1 = layer1_rule_filter(changed_files, commit_messages)
    trace: dict = {"layer1": layer1, "layer2": None, "layer3": None}
    if layer1["hard_skip"]:
        return False, trace

    layer2 = layer2_diff_analysis(diff_text, changed_files, layer1["commit_hint"])
    trace["layer2"] = layer2
    if layer2["verdict"] == "update":
        return True, trace
    if layer2["verdict"] == "skip":
        return False, trace

    decision = layer3_llm_judge(diff_text, changed_files, layer2, client)
    trace["layer3"] = decision
    return decision, trace


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
