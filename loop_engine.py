#!/usr/bin/env python3
"""Self-healing test loop — a worked example of *loop engineering*.

The engineered loop is:

    run tests --> read failures --> ask Claude for a fix --> apply --> re-run

repeated until the suite is green or a budget runs out. The interesting part
isn't the LLM call; it's the *loop* around it. Four knobs make this a
well-engineered loop rather than a while-True with an API call in it, and each
is called out in the code below:

  1. Stopping condition  — terminate on success (all green), never on "looks done".
  2. Budget             — a hard cap on iterations so a stuck loop can't run forever.
  3. Context management — feed only the current failure + source each turn, not
                          the whole history, so the model sees a clean, focused task.
  4. Error handling     — a regression guard: if a patch makes things *worse*,
                          revert it instead of building on a bad edit.

The loop operates on a throwaway copy of ``target_project/`` so the original
buggy files stay pristine and the demo is re-runnable.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...      # or `ant auth login`
    pip install -r requirements.txt
    python loop_engine.py
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import anthropic

# --- Loop-engineering knobs (edit these to change the loop's behaviour) ------

MODEL = "claude-opus-4-8"
MAX_ITERATIONS = 6          # Knob 2: the budget. The loop cannot exceed this.
REGRESSION_GUARD = True     # Knob 4: revert a patch that increases the failure count.
EDITABLE_FILE = "calculator.py"   # The model may only touch this file.
TEST_FILE = "test_calculator.py"  # Read-only ground truth; never edited.

SYSTEM_PROMPT = (
    "You are a debugging agent inside an automated test-fixing loop. "
    f"You may edit ONLY `{EDITABLE_FILE}`. Never edit the tests — they are the "
    "specification. Given the current source and a pytest failure report, work "
    "out the minimal change that makes the failing tests pass, then call "
    "`write_file` with the complete corrected contents of the file. Fix the "
    "code, not the symptoms: make the function actually correct for all inputs."
)

WRITE_FILE_TOOL = {
    "name": "write_file",
    "description": (
        "Overwrite a source file with corrected contents so the failing tests "
        "pass. Provide the FULL new file, not a diff."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": f"The file to overwrite (must be `{EDITABLE_FILE}`).",
            },
            "content": {
                "type": "string",
                "description": "The complete new contents of the file.",
            },
        },
        "required": ["path", "content"],
    },
}


@dataclass
class TestResult:
    passed: bool
    failed_count: int
    output: str


def run_tests(workdir: Path) -> TestResult:
    """Run pytest in ``workdir`` and summarise the outcome.

    The exit code is the loop's success signal (Knob 1): 0 means every test
    passed, and that is the *only* thing that ends the loop successfully.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", TEST_FILE],
        cwd=workdir,
        capture_output=True,
        text=True,
    )
    output = proc.stdout + proc.stderr
    failed_count = _count_failures(output)
    return TestResult(passed=proc.returncode == 0, failed_count=failed_count, output=output)


def _count_failures(pytest_output: str) -> int:
    """Pull the failed-test count out of pytest's summary line.

    Parses the trailing summary (e.g. "3 failed, 2 passed in 0.04s") and returns
    the number before "failed", or 0 if the suite reported no failures.
    """
    for line in reversed(pytest_output.splitlines()):
        if " failed" in line or " passed" in line:
            parts = line.replace("=", " ").replace(",", " ").split()
            for i, tok in enumerate(parts):
                if tok == "failed" and i > 0 and parts[i - 1].isdigit():
                    return int(parts[i - 1])
            return 0
    return 0


def ask_claude_for_fix(
    client: anthropic.Anthropic, source: str, failure_report: str
) -> list[tuple[str, str]]:
    """Ask the model for a fix and return a list of (path, new_content) edits.

    Knob 3 (context management): each call carries only the current file and the
    current failure report — a fresh, focused task. We deliberately do NOT append
    prior turns, so a bad earlier attempt can't pollute the next one.
    """
    user_message = (
        f"Here is the current `{EDITABLE_FILE}`:\n\n```python\n{source}\n```\n\n"
        f"Running the tests produced this failure report:\n\n```\n{failure_report}\n```\n\n"
        "Fix the source file so all tests pass. Call `write_file` with the full "
        "corrected file."
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},   # let Claude decide how hard to think
        system=SYSTEM_PROMPT,
        tools=[WRITE_FILE_TOOL],
        tool_choice={"type": "tool", "name": "write_file"},
        messages=[{"role": "user", "content": user_message}],
    )

    edits: list[tuple[str, str]] = []
    for block in response.content:
        if block.type == "tool_use" and block.name == "write_file":
            edits.append((block.input["path"], block.input["content"]))
    return edits


def apply_edits(workdir: Path, edits: list[tuple[str, str]]) -> dict[Path, str]:
    """Apply edits, returning a snapshot of the prior contents for rollback."""
    snapshot: dict[Path, str] = {}
    for rel_path, content in edits:
        # Guardrail: confine writes to the one editable file, ignore anything else.
        if Path(rel_path).name != EDITABLE_FILE:
            print(f"    ! ignoring attempt to edit {rel_path!r} (only {EDITABLE_FILE} is editable)")
            continue
        target = workdir / EDITABLE_FILE
        snapshot[target] = target.read_text()
        target.write_text(content)
        print(f"    ~ patched {EDITABLE_FILE}")
    return snapshot


def restore(snapshot: dict[Path, str]) -> None:
    for path, content in snapshot.items():
        path.write_text(content)


def _auth_help(exc: Exception) -> None:
    print("\nerror: could not authenticate to the Claude API.", file=sys.stderr)
    print(f"  ({type(exc).__name__}: {exc})", file=sys.stderr)
    print(
        "  Set ANTHROPIC_API_KEY (see .env.example) or run `ant auth login`, "
        "then re-run.",
        file=sys.stderr,
    )


def self_heal(workdir: Path) -> bool:
    """Drive the loop. Returns True if the suite went green within budget."""
    try:
        client = anthropic.Anthropic()
    except Exception as exc:  # missing/invalid credentials at construction time
        _auth_help(exc)
        return False

    for iteration in range(1, MAX_ITERATIONS + 1):
        result = run_tests(workdir)

        # Knob 1: stopping condition — success is the exit code, nothing else.
        if result.passed:
            print(f"[iter {iteration}] all tests pass ✓")
            return True

        print(f"[iter {iteration}] {result.failed_count} test(s) failing — asking Claude for a fix")

        source = (workdir / EDITABLE_FILE).read_text()
        try:
            edits = ask_claude_for_fix(client, source, result.output)
        except (anthropic.AuthenticationError, TypeError) as exc:
            _auth_help(exc)
            return False
        if not edits:
            print("    ! model returned no edit; stopping")
            return False

        snapshot = apply_edits(workdir, edits)
        after = run_tests(workdir)

        # Knob 4: regression guard — never keep a patch that made things worse.
        if REGRESSION_GUARD and after.failed_count > result.failed_count:
            print(
                f"    ↩ patch regressed ({result.failed_count} → {after.failed_count} "
                "failures); reverting"
            )
            restore(snapshot)
        else:
            delta = result.failed_count - after.failed_count
            print(f"    → {after.failed_count} failing now ({delta:+d})")

    # Knob 2: budget exhausted — give up cleanly rather than loop forever.
    print(f"[done] budget of {MAX_ITERATIONS} iterations exhausted; not green")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default=str(Path(__file__).parent / "target_project"),
        help="Directory containing the buggy code + tests to heal.",
    )
    args = parser.parse_args()

    target = Path(args.target).resolve()
    if not target.is_dir():
        print(f"error: target directory not found: {target}", file=sys.stderr)
        return 2

    # Work on a throwaway copy so the original stays pristine and re-runnable.
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp) / "work"
        shutil.copytree(target, workdir)
        print(f"Healing a copy of {target.name}/ in a scratch dir…\n")
        ok = self_heal(workdir)
        if ok:
            print("\nResult: the loop produced a passing test suite.")
            print(f"Final {EDITABLE_FILE}:\n")
            print((workdir / EDITABLE_FILE).read_text())
        else:
            print("\nResult: the loop did not reach a passing state.")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
