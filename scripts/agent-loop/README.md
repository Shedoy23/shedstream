# ShedLink Agent Review Loop

This directory contains an append-only mailbox and a bounded automatic runner
for Claude Code and Codex CLI.

Neither tool can deploy code, restart services, close tasks, or modify
production. Only the owner can close a task.

## Local chat UI

Double-click `scripts/agent-loop/start-chat.cmd`. It starts a localhost-only
chat at `http://127.0.0.1:8765` and opens the default browser.

The chat can create tasks, show the Claude/Codex handoffs as messages, display
live agent status, select a model for each agent, show Codex rate-limit windows,
surface errors, and close owner-ready tasks. While an agent is running, the
conversation shows a live activity feed built from real CLI events: file reads,
searches, commands, checks, handoffs, and completion. Private model reasoning is
never copied into the feed. Claude's exact remaining allowance is linked to
Settings / Usage because its headless CLI does not expose that value
programmatically. The chat is not published to the internet and has no
production credentials.

Each new task has an explicit mode:

- **Авто** (default): the local server resolves permissions from the request
  before starting either model. Mutation verbs select delivery; audit/read
  requests and ambiguous wording select the safer read-only mode.
- **Сделать и проверить**: Claude may edit the worktree, then Codex reviews it
  in a read-only sandbox.
- **Анализ / аудит**: Claude receives only `Read`, `Glob`, and `Grep`; editing,
  shell commands, and web access are denied. Codex also runs read-only. Both
  reports return directly to the owner and no automatic fix cycle starts.

The agents are not assigned static professional roles in their prompts. Their
allowed action is defined by the selected task mode. The mode is fixed when the
task is created; create a new analysis task instead of rerunning an older task.

## One-time setup

Install and authenticate the official standalone CLIs:

```powershell
npm install -g @anthropic-ai/claude-code @openai/codex
claude
codex login
```

Verify both adapters without making a model call:

```powershell
python scripts/agent-loop/orchestrator.py doctor
```

## Automatic workflow

The shortest path creates a task and runs the complete loop in one command:

```powershell
python scripts/agent-loop/orchestrator.py start `
  --title "Fix the vassal lifecycle" `
  --request-file .agent-loop/request.md `
  --mode delivery `
  --max-rounds 2
```

Use `--mode analysis` for a strictly read-only document or code audit.

For separate create, preview, and run steps, create through the mailbox:

```powershell
python scripts/agent-loop/mailbox.py create `
  --title "Fix the vassal lifecycle" `
  --request-file .agent-loop/request.md `
  --to claude `
  --max-rounds 2

python scripts/agent-loop/orchestrator.py run `
  --task SL-YYYYMMDD-XXXXXXXX `
  --dry-run
```

Run the complete bounded loop:

```powershell
python scripts/agent-loop/orchestrator.py run `
  --task SL-YYYYMMDD-XXXXXXXX
```

Routing is deterministic:

- Claude implements and supplies checks.
- Codex performs the first review blind in a read-only sandbox: it sees the
  owner request and current worktree, but not Claude's self-assessment.
- Follow-up verification can see the prior findings and fix handoffs.
- A failed review returns to Claude once while the review budget remains.
- A passing review or exhausted budget returns the task to the owner.
- The process stops immediately when the owner is needed.

Print the final owner-facing report:

```powershell
python scripts/agent-loop/orchestrator.py report `
  --task SL-YYYYMMDD-XXXXXXXX
```

The runner never commits, merges, pushes, deploys, restarts services, or touches
production. Runtime state and run metadata stay under `.agent-loop/`, outside
Git. `runner.json` controls the timeout, step ceiling, and CLI modes. Claude's
turn ceiling defaults to 20; exhaustion produces a short actionable error
instead of exposing the raw SDK result.

## Manual fallback

The GUI-assisted mailbox flow remains available if either CLI is unavailable:

```powershell
python scripts/agent-loop/mailbox.py next --agent claude --ack
python scripts/agent-loop/mailbox.py next --agent codex --ack
```

## Owner gate

Only an explicit owner action closes a task:

```powershell
python scripts/agent-loop/mailbox.py set-status `
  --task SL-YYYYMMDD-XXXXXXXX --by owner --status closed
```

Neither agent is granted production permissions by this protocol.

## Inspection

```powershell
python scripts/agent-loop/mailbox.py inbox --agent codex
python scripts/agent-loop/mailbox.py status
python scripts/agent-loop/mailbox.py status --task SL-YYYYMMDD-XXXXXXXX
```

## Verification

```powershell
python -m unittest scripts/agent-loop/test_mailbox.py -v
python -m unittest scripts/agent-loop/test_orchestrator.py -v
python -m unittest scripts/agent-loop/test_chat_server.py -v
```

The tests use a temporary database and do not touch repository state.
