# Loop-Engineering

A worked example of **loop engineering** — the practice of designing and tuning
the *loop* an AI agent runs in, not just the prompt it runs once.

This repo implements a **self-healing test loop**: point it at a project with
failing tests, and it runs

```
run tests ──▶ read failures ──▶ ask Claude for a fix ──▶ apply ──▶ re-run
```

over and over until the suite is green or a budget runs out. The LLM call is the
easy part. The engineering is in the loop around it.

## Why this is "loop engineering"

A `while True:` with an API call inside is not an engineered loop. Four knobs
turn it into one — each is a labelled, tunable constant/step in
[`loop_engine.py`](loop_engine.py):

| # | Knob | What it does | Where |
|---|------|--------------|-------|
| 1 | **Stopping condition** | Terminate on a real success signal — pytest's exit code — never on "looks done". | `run_tests` / `self_heal` |
| 2 | **Budget** | A hard cap (`MAX_ITERATIONS`) so a stuck loop can't run forever. | `MAX_ITERATIONS` |
| 3 | **Context management** | Feed only the *current* file + *current* failure each turn — a fresh, focused task — instead of piling up history. | `ask_claude_for_fix` |
| 4 | **Error handling** | A regression guard: if a patch increases the failure count, revert it instead of building on a bad edit. | `REGRESSION_GUARD` |

Change any knob and the loop behaves differently — that's the point.

## Layout

| File | Purpose |
|------|---------|
| `loop_engine.py` | The loop harness — the actual demonstration. |
| `target_project/calculator.py` | Five functions, each with an intentional bug. The loop edits this. |
| `target_project/test_calculator.py` | The spec, as tests. Read-only ground truth — the loop never edits it. |
| `requirements.txt` | `anthropic` + `pytest`. |

## Run it

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...        # or: ant auth login
python loop_engine.py
```

You'll see something like:

```
[iter 1] 5 test(s) failing — asking Claude for a fix
    ~ patched calculator.py
    → 0 failing now (+5)
[iter 2] all tests pass ✓

Result: the loop produced a passing test suite.
```

The loop works on a **throwaway copy** of `target_project/`, so the original
buggy files stay intact and every run starts fresh.

## Design choices worth noting

- **Uses Claude** (`claude-opus-4-8`) via the official `anthropic` SDK, with
  adaptive thinking so the model decides how hard to reason per fix.
- **A single tool, `write_file`** — the model returns the full corrected file,
  which the harness applies. A path guardrail confines edits to `calculator.py`;
  the tests can't be "fixed" by rewriting them.
- **A manual loop, not the SDK tool-runner** — deliberately, so the loop's
  control flow (the thing being taught) is visible in code rather than hidden
  inside a helper.

## Make it your own

- Point it at your own code: `python loop_engine.py --target path/to/project`
  (expects a `test_*.py` suite runnable with pytest).
- Flip `REGRESSION_GUARD` off and watch a bad patch compound — the failure mode
  the guard exists to prevent.
- Lower `MAX_ITERATIONS` to 1 to see the budget stop the loop before it's green.
