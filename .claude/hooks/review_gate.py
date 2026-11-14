#!/usr/bin/env python3
"""Blocks opening a PR until the code-reviewer agent has passed the commit being proposed.

Two hooks call this (see .claude/settings.json):

- `record`, on SubagentStop: when the code-reviewer agent finishes, note where its transcript
  is. Nothing is parsed yet: Claude Code may still be writing the reviewer's final report to the
  transcript when this hook runs, so reading it here can miss the verdict.
- `check`, on PreToolUse for Bash: for a command that would open a PR, read the final report of
  every recorded review. Each one ends with `VERDICT: READY <sha>` or `VERDICT: FIX FIRST <sha>`,
  naming the commit the reviewer read. The command is allowed only if a review passed HEAD and
  none failed it: a FIX FIRST sticks to its commit, so only a new commit gets a fresh review.

This is a guardrail for a cooperative agent, not a security boundary. It sees only Bash commands
and judges them by their text, so it errs towards blocking: it allows only a plain
`gh pr create`, and blocks any other command that mentions opening a PR. It also blocks when the
branch's remote holds commits HEAD doesn't, since gh would open the PR with those.

Reviews are listed in .git/claude-review/, which is never committed.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REVIEWER = "code-reviewer"
REVIEWS = "reviews.jsonl"

# Anywhere in the command, so prefixes (env, command, a full path, bash -c '...') don't hide it,
# and matched with quotes removed, so `gh pr 'create'` doesn't either. `gh pr new` is an alias of
# `gh pr create`; gh's persistent flags (`-R o/r`) may sit between `pr` and `create`.
# `gh api .../pulls` with fields creates a PR too, and so does the GraphQL createPullRequest
# mutation, which may also come from a file (`gh api graphql --input q.json`).
PR_CREATE = re.compile(r"\bgh\b.*\bpr\b(?:\s+-\S+(?:\s+[^-\s]\S*)?)*\s+(?:create|new)\b", re.DOTALL)
API_CREATE = re.compile(
    # The path and the fields are checked separately, because either may come first.
    r"\bgh\b(?=.*\bapi\b)"
    r"(?:(?=.*/pulls/?(?![/\w]))(?=.*(?:\s-[fFX]|--(?:field|raw-field|method|input)))"
    r"|(?=.*\bcreatePullRequest\b)|(?=.*\bgraphql\b)(?=.*--input\b))",
    re.DOTALL,
)
# The only form the gate can vouch for: `gh pr create` alone, opening a PR for this session's
# HEAD, on one line. Arguments are bare words or single-quoted strings, so nothing in them can
# chain another command, switch branch, change directory, expand a variable or a glob.
PLAIN_CREATE = re.compile(
    r"gh[ \t]+pr[ \t]+(?:create|new)(?:[ \t]+(?:[^\s'\"`$\\;&|<>()*?[~{]+|'[^'\n]*'))*[ \t]*"
)
# Flags that open the PR for another branch or repository. Short flags may be combined (`-dH x`),
# so any single-dash word holding C, H or R counts, even if that blocks a value like `-tHi`.
OTHER_TARGET = re.compile(
    r"(?:^|\s)'?(?:-[A-Za-z]*[CHR]|--head\b|--repo\b|--git-dir\b|--work-tree\b)"
)
# Removed before looking for a PR command, as the shell removes them: line continuations
# (backslash-newline, which joins a word), quotes, backslash escapes and the `$` of `$'...'`.
# A command built from variables or a gh alias still isn't recognised.
SHELL_QUOTING = re.compile(r"\\\n|[\"'\\]|\$(?=')")
ONLY_MENTIONS = (
    " If the command only mentions opening a PR, as a commit message or a search can, move that "
    "text into a file (for example `git commit --file=<path>`) so the command doesn't contain it."
)
VERDICT = re.compile(r"^VERDICT:\s*(READY|FIX FIRST)\s+([0-9a-f]{40})$")

GIT = shutil.which("git") or "/usr/bin/git"


def git(cwd: str, *args: str) -> str:
    # Only fixed git subcommands from this file; nothing from the hook input reaches args.
    return subprocess.run(  # noqa: S603
        [GIT, *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def review_dir(cwd: str) -> Path:
    common = Path(git(cwd, "rev-parse", "--git-common-dir"))
    return (common if common.is_absolute() else Path(cwd) / common) / "claude-review"


def final_reports(transcript: Path) -> list[str]:
    """Every SubagentHandback report, as a resumed reviewer hands back once per run, or else
    the reviewer's last text message."""
    handbacks: list[str] = []
    text = ""
    for line in transcript.read_text().splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = entry.get("message") if isinstance(entry, dict) else None
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "SubagentHandback":
                handbacks.append(str((block.get("input") or {}).get("message", "")))
            elif block.get("type") == "text":
                text = str(block.get("text", "")) or text
    return handbacks or [text]


def verdict_of(report: str) -> tuple[str, str] | None:
    """(verdict, sha) from the report's last line, or None if it doesn't end with one."""
    lines = report.strip().splitlines()
    match = VERDICT.match(lines[-1].strip().strip("*`").strip()) if lines else None
    return (match.group(1).upper(), match.group(2)) if match else None


def record(data: dict[str, Any]) -> int:
    if data.get("agent_type") != REVIEWER:
        return 0
    transcript = data.get("agent_transcript_path")
    if not isinstance(transcript, str) or not transcript:
        return 0
    directory = review_dir(data.get("cwd") or ".")
    directory.mkdir(exist_ok=True)
    with (directory / REVIEWS).open("a") as reviews:
        reviews.write(json.dumps({"transcript": transcript}) + "\n")
    return 0


def verdicts_for(directory: Path, head: str) -> set[str]:
    reviews = directory / REVIEWS
    found: set[str] = set()
    for line in reviews.read_text().splitlines() if reviews.is_file() else []:
        try:
            transcript = Path(json.loads(line)["transcript"])
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
        for report in final_reports(transcript) if transcript.is_file() else []:
            result = verdict_of(report)
            if result and result[1] == head:
                found.add(result[0])
    return found


def deny(reason: str) -> int:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    return 0


def pushed_elsewhere(cwd: str, head: str) -> bool:
    """Whether the branch's push ref holds commits HEAD doesn't, which gh would open the PR with."""
    pushed = subprocess.run(  # noqa: S603
        [GIT, "rev-parse", "--verify", "--quiet", "@{push}"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if not pushed:
        return False
    ancestor = subprocess.run(  # noqa: S603
        [GIT, "merge-base", "--is-ancestor", pushed, head], cwd=cwd, check=False
    )
    return ancestor.returncode != 0


def check(data: dict[str, Any]) -> int:
    command = str((data.get("tool_input") or {}).get("command", ""))
    unquoted = SHELL_QUOTING.sub("", command)
    if not (PR_CREATE.search(unquoted) or API_CREATE.search(unquoted)):
        return 0
    if not PLAIN_CREATE.fullmatch(command.strip()) or OTHER_TARGET.search(command):
        return deny(
            "Blocked: the review gate can only vouch for a PR opened by `gh pr create` on its "
            "own, from the reviewed branch. Run it alone (no other commands, directory changes, "
            "--head, --repo or gh api), with any values in single quotes or a --body-file."
            + ONLY_MENTIONS
        )
    cwd = data.get("cwd") or "."
    head = git(cwd, "rev-parse", "HEAD")
    if pushed_elsewhere(cwd, head):
        return deny(
            f"Blocked: this branch's remote has commits that {head[:7]} doesn't, and gh would "
            "open the PR with them rather than the reviewed commit. Push HEAD to the branch "
            "(after checking those commits should go) before opening the PR."
        )
    verdicts = verdicts_for(review_dir(cwd), head)
    if verdicts == {"READY"}:
        return 0
    found = " and ".join(sorted(verdicts)) or "none"
    return deny(
        f"Blocked: the code-reviewer agent hasn't passed commit {head[:7]} (verdicts for it: "
        f"{found}). Run the code-reviewer agent on this branch, fix what it reports, commit, "
        "and review the new commit until it ends with VERDICT: READY." + ONLY_MENTIONS
    )


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = json.load(sys.stdin)
    if mode == "record":
        sys.exit(record(payload))
    if mode == "check":
        sys.exit(check(payload))
    sys.exit(f"usage: review_gate.py record|check (got {mode!r})")
