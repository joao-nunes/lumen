#!/usr/bin/env python3
"""Blocks `gh pr create` until the code-reviewer agent has passed the commit being proposed.

Two hooks call this (see .claude/settings.json):

- `record`, on SubagentStop: when the code-reviewer agent finishes, read its last line,
  `VERDICT: READY` or `VERDICT: FIX FIRST`, and store it for the current HEAD.
- `check`, on PreToolUse for Bash: deny any command that runs `gh pr create` unless HEAD's
  stored verdict is READY. A new commit has a new SHA, so every fix needs a fresh review.

Verdicts live in .git/claude-review/, which is never committed.
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
# Only where a command starts (beginning, or after ; & | ( or a newline, then optional VAR=value
# prefixes), so a commit message or echo that mentions the phrase isn't blocked.
PR_CREATE = re.compile(r"(?:^|[;&|(\n])\s*(?:\w+=\S*\s+)*gh\s+pr\s+create\b")
VERDICT = re.compile(r"VERDICT:\s*(READY|FIX FIRST)\s*\**\s*$", re.IGNORECASE)


GIT = shutil.which("git") or "/usr/bin/git"


def git(cwd: str, *args: str) -> str:
    # Only fixed git subcommands from this file; nothing from the hook input reaches args.
    return subprocess.run(  # noqa: S603
        [GIT, *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def review_dir(cwd: str) -> Path:
    common = Path(git(cwd, "rev-parse", "--git-common-dir"))
    return (common if common.is_absolute() else Path(cwd) / common) / "claude-review"


def last_assistant_text(data: dict[str, Any]) -> str:
    """The reviewer's final message, from the hook input or else from its transcript."""
    text = data.get("last_assistant_message")
    if isinstance(text, str) and text:
        return text
    transcript = data.get("agent_transcript_path") or data.get("transcript_path")
    if not transcript or not Path(transcript).is_file():
        return ""
    last = ""
    for line in Path(transcript).read_text().splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = entry.get("message") or {}
        if entry.get("type") != "assistant" and message.get("role") != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str):
            last = content or last
        elif isinstance(content, list):
            parts = [c.get("text", "") for c in content if c.get("type") == "text"]
            last = "\n".join(p for p in parts if p) or last
    return last


def record(data: dict[str, Any]) -> int:
    cwd = data.get("cwd") or "."
    directory = review_dir(cwd)
    directory.mkdir(exist_ok=True)
    # Field names only, never content: shows what this Claude Code version sends.
    (directory / "last-subagent-stop-keys.json").write_text(json.dumps(sorted(data)))

    agent = data.get("agent_type") or data.get("subagent_type")
    if agent != REVIEWER:
        return 0
    match = VERDICT.search(last_assistant_text(data).rstrip())
    verdict = match.group(1).upper() if match else "NONE"
    head = git(cwd, "rev-parse", "HEAD")
    (directory / head).write_text(verdict + "\n")
    return 0


def check(data: dict[str, Any]) -> int:
    command = (data.get("tool_input") or {}).get("command", "")
    if not PR_CREATE.search(command):
        return 0
    cwd = data.get("cwd") or "."
    head = git(cwd, "rev-parse", "HEAD")
    marker = review_dir(cwd) / head
    verdict = marker.read_text().strip() if marker.is_file() else "none"
    if verdict == "READY":
        return 0
    reason = (
        f"Blocked: the code-reviewer agent hasn't passed commit {head[:7]} "
        f"(its verdict: {verdict}). Run the code-reviewer agent on this branch, fix what it "
        "reports, commit, and run it again until it ends with VERDICT: READY."
    )
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


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    payload = json.load(sys.stdin)
    if mode == "record":
        sys.exit(record(payload))
    if mode == "check":
        sys.exit(check(payload))
    sys.exit(f"usage: review_gate.py record|check (got {mode!r})")
