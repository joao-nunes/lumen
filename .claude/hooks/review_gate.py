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
and judges them by their text, so it errs towards blocking: a command that merely mentions
opening a PR, or that may target another branch or repository, is blocked too.

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

# Anywhere in the command, so prefixes (env, command, a full path, bash -c '...') don't hide it.
# `gh pr new` is an alias of `gh pr create`. `gh api .../pulls` with fields creates a PR too,
# and so does the GraphQL createPullRequest mutation.
# gh's persistent flags (`-R o/r`) may sit between `pr` and `create`.
PR_CREATE = re.compile(r"\bgh\b.*\bpr\b(?:\s+-\S+(?:\s+[^-\s]\S*)?)*\s+(?:create|new)\b", re.DOTALL)
API_CREATE = re.compile(
    # The path and the fields are checked separately, because either may come first.
    r"\bgh\b(?=.*\bapi\b)"
    r"(?:(?=.*/pulls(?![/\w]))(?=.*(?:\s-[fFX]|--(?:field|raw-field|method|input)))"
    r"|(?=.*\bcreatePullRequest\b))",
    re.DOTALL,
)
# Anything that may make the PR's commit differ from this session's HEAD.
OTHER_TARGET = re.compile(
    r"(?:^|[\s;&|(])(?:cd|pushd)\s"
    # A short flag's value may be attached (`-Hbranch`), so nothing is required after it.
    r"|(?:^|\s)(?:-[CHR]|--head\b|--repo\b|--git-dir\b|--work-tree\b)"
    r"|\b(?:GH_REPO|GIT_DIR|GIT_WORK_TREE)="
)
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


def final_report(transcript: Path) -> str:
    """The reviewer's last SubagentHandback report, or else its last text message."""
    handback = text = ""
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
                handback = str((block.get("input") or {}).get("message", "")) or handback
            elif block.get("type") == "text":
                text = str(block.get("text", "")) or text
    return handback or text


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
        result = verdict_of(final_report(transcript)) if transcript.is_file() else None
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


def check(data: dict[str, Any]) -> int:
    command = str((data.get("tool_input") or {}).get("command", ""))
    if not (PR_CREATE.search(command) or API_CREATE.search(command)):
        return 0
    if OTHER_TARGET.search(command):
        return deny(
            "Blocked: this command may open a PR for a commit other than this session's HEAD "
            "(it changes directory or names a branch, repository or git dir), so the review "
            "gate can't check it. Run `gh pr create` on its own from the reviewed branch."
            + ONLY_MENTIONS
        )
    cwd = data.get("cwd") or "."
    head = git(cwd, "rev-parse", "HEAD")
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
