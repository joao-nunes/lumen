"""The review gate (.claude/hooks/review_gate.py) blocks opening a PR until the code-reviewer
agent has passed the exact commit being proposed. Driven as Claude Code drives it: the script
run with hook JSON on stdin, in a real git repository.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "review_gate.py"
GIT = shutil.which("git") or "/usr/bin/git"


def run(repo: Path, mode: str, payload: dict[str, object]) -> str:
    # This interpreter, the gate script and a fixed mode: nothing untrusted runs.
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(GATE), mode],
        input=json.dumps(payload),
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def git(repo: Path, *args: str) -> str:
    # Fixed git subcommands from this file, in a temporary repository.
    return subprocess.run(  # noqa: S603
        [GIT, *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def commit(repo: Path) -> str:
    git(repo, "commit", "--allow-empty", "-q", "-m", "change")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "Test")
    git(path, "config", "commit.gpgsign", "false")  # a global signing setup can't break the tests
    (path / "sub").mkdir()
    commit(path)
    return path


def handback(report: str) -> str:
    """A transcript line for the reviewer's final turn: a SubagentHandback tool call, no text."""
    block = {"type": "tool_use", "name": "SubagentHandback", "input": {"message": report}}
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [block]}})


def reading() -> str:
    message = {"role": "assistant", "content": [{"type": "text", "text": "Reading the diff."}]}
    return json.dumps({"type": "assistant", "message": message})


def review(repo: Path, report: str, agent: str = "code-reviewer") -> None:
    """A finished review, recorded as SubagentStop does: before its final turn is written."""
    transcript = repo.parent / f"agent-{len(list(repo.parent.glob('agent-*')))}.jsonl"
    transcript.write_text(reading() + "\n")
    stop = {"agent_type": agent, "agent_transcript_path": str(transcript), "cwd": str(repo)}
    run(repo, "record", stop)
    with transcript.open("a") as file:
        file.write(handback(report) + "\n")


def allowed(repo: Path, command: str = "gh pr create --fill", cwd: Path | None = None) -> bool:
    payload = {"tool_input": {"command": command}, "cwd": str(cwd or repo)}
    out = run(repo, "check", payload)
    if not out:
        return True
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    return False


def test_a_passed_commit_may_open_a_pr(repo: Path) -> None:
    head = git(repo, "rev-parse", "HEAD")
    review(repo, f"No findings.\n\nVERDICT: READY {head}")
    assert allowed(repo)
    assert allowed(repo, cwd=repo / "sub")  # relative --git-common-dir resolves
    assert allowed(repo, "gh pr create --title 'Add a gate' --body-file /tmp/b.md --base master")


@pytest.mark.parametrize(
    "case",
    [
        "no review",
        "fix first",
        "fix first, then ready on the same commit",
        "fix first, then ready when the same review is resumed",
        "ready for an earlier commit",
        "ready for the commit only in a quote, not the last line",
        "ready from another agent",
        "ready without the commit",
    ],
)
def test_otherwise_opening_a_pr_is_blocked(repo: Path, case: str) -> None:
    head = git(repo, "rev-parse", "HEAD")
    if case == "fix first":
        review(repo, f"VERDICT: FIX FIRST {head}")
    elif case == "fix first, then ready on the same commit":
        review(repo, f"VERDICT: FIX FIRST {head}")
        review(repo, f"VERDICT: READY {head}")
    elif case == "fix first, then ready when the same review is resumed":
        review(repo, f"VERDICT: FIX FIRST {head}")
        (transcript,) = repo.parent.glob("agent-*.jsonl")
        with transcript.open("a") as file:
            file.write(reading() + "\n" + handback(f"VERDICT: READY {head}") + "\n")
    elif case == "ready for an earlier commit":
        review(repo, f"VERDICT: READY {head}")
        commit(repo)
    elif case == "ready for the commit only in a quote, not the last line":
        review(repo, f"It must end with:\nVERDICT: READY {head}\nIt doesn't yet.")
    elif case == "ready from another agent":
        review(repo, f"VERDICT: READY {head}", agent="general-purpose")
    elif case == "ready without the commit":
        review(repo, "VERDICT: READY")
    assert not allowed(repo)


@pytest.mark.parametrize(
    "command",
    [
        "gh pr new --fill",
        "gh -R owner/repo pr create",
        "env gh pr create",
        "/opt/homebrew/bin/gh pr create",
        "bash -c 'gh pr create --fill'",
        "if true; then gh pr create; fi",
        "gh pr -R o/r create",
        "gh pr 'create'",
        'gh "pr" create',
        "gh pr cr\\eate --fill",
        "gh pr $'create'",
        "gh pr cre\\\nate --fill",
        "gh api repos/o/r/pulls/ -f head=x -f base=master",
        "gh api graphql --input mutation.json",
        "gh api repos/o/r/pulls -f head=x -f base=master",
        "gh api -f head=x -f base=master -f title=t repos/o/r/pulls",
        "gh api graphql -f query='mutation { createPullRequest(input: {}) { clientMutationId } }'",
    ],
)
def test_every_way_of_opening_a_pr_is_gated(repo: Path, command: str) -> None:
    assert not allowed(repo, command)


@pytest.mark.parametrize(
    "command",
    [
        "cd ../other-worktree && gh pr create --fill",
        "gh pr create --head other-branch",
        "gh pr create -R someone/fork",
        "gh pr create -Hother-branch",
        "gh pr create -Ro/fork",
        "gh pr create -dH other",
        "gh pr create -fR o/fork",
        "gh pr create *",
        "GH_REPO=o/r gh pr create",
        "git checkout other && gh pr create --fill",
        "git switch other; gh pr create",
        'gh pr create --title "$(git switch other)"',
        "gh api repos/o/r/pulls -f head=unreviewed -f base=master",
        "gh api graphql -f query='mutation { createPullRequest(input: {}) { clientMutationId } }'",
    ],
)
def test_a_pr_for_another_commit_is_blocked_even_after_a_pass(repo: Path, command: str) -> None:
    head = git(repo, "rev-parse", "HEAD")
    review(repo, f"VERDICT: READY {head}")
    assert not allowed(repo, command)


def test_a_remote_ahead_of_the_passed_commit_is_blocked(repo: Path, tmp_path: Path) -> None:
    """gh skips pushing when the remote branch already contains HEAD, and opens the PR with the
    remote's commits: say a failed commit was pushed, then reset away locally."""
    git(tmp_path, "init", "-q", "--bare", "remote.git")
    git(repo, "remote", "add", "origin", str(tmp_path / "remote.git"))
    passed = git(repo, "rev-parse", "HEAD")
    commit(repo)
    git(repo, "push", "-q", "-u", "origin", "HEAD")
    git(repo, "reset", "-q", "--hard", passed)
    review(repo, f"VERDICT: READY {passed}")
    assert not allowed(repo)
    git(repo, "push", "-q", "--force", "origin", "HEAD")
    assert allowed(repo)


def test_the_configured_hooks_work_when_claude_code_starts_in_a_subdirectory(repo: Path) -> None:
    """There CLAUDE_PROJECT_DIR has no .claude/: the hooks must still find the gate, or a
    missing script lets every PR through."""
    (repo / ".claude" / "hooks").mkdir(parents=True)
    shutil.copy(GATE, repo / ".claude" / "hooks")
    hooks = json.loads((GATE.parents[1] / "settings.json").read_text())["hooks"]
    sub = repo / "sub"
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(sub)}

    def hook(event: str, payload: dict[str, object]) -> str:
        command = hooks[event][0]["hooks"][0]["command"]
        # The command from this repository's settings, in a temporary repository.
        return subprocess.run(  # noqa: S603
            ["bash", "-c", command],  # noqa: S607
            input=json.dumps(payload),
            cwd=sub,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    create = {"tool_input": {"command": "gh pr create --fill"}, "cwd": str(sub)}
    assert (
        json.loads(hook("PreToolUse", create))["hookSpecificOutput"]["permissionDecision"] == "deny"
    )
    head = git(repo, "rev-parse", "HEAD")
    transcript = repo.parent / "agent-sub.jsonl"
    transcript.write_text(handback(f"VERDICT: READY {head}") + "\n")
    stop = {
        "agent_type": "code-reviewer",
        "agent_transcript_path": str(transcript),
        "cwd": str(sub),
    }
    hook("SubagentStop", stop)
    assert hook("PreToolUse", create) == ""


@pytest.mark.parametrize(
    "command",
    ["gh pr view 58", "gh pr list", "gh api repos/o/r/pulls/58/comments", "git status"],
)
def test_other_commands_are_not_gated(repo: Path, command: str) -> None:
    assert allowed(repo, command)
