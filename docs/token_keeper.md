# Token Keeper

Flat-rate CLI subscriptions limit usage per window, typically 5 hours and one week, per account. An organisation of many agents can use up a window in an afternoon. The Token Keeper reads how much of each window is used, records it every few minutes, and closes a gate when a window passes its threshold. While the gate is closed, `vibecodehpc launch` does not start agents, and PM is told once.

It is off unless you configure it. Without `Agent-shared/quota/state.json`, or when that file is older than three reading intervals, nothing is gated.

## What it reads

None of the readers opens a credential file. Only percentages, window names and reset times are stored.

| Source (`type`) | Provider | How |
|---|---|---|
| `codex_rollouts` | Codex CLI | The `rate_limits` Codex writes into its own session logs (`$CODEX_HOME/sessions/**/rollout-*.jsonl`), newest per plan type. As fresh as the last Codex turn on that account |
| `claude_usage` | Claude Code | Opens Claude Code in a private tmux session, shows `/usage`, reads the screen, exits. The CLI uses its own login and makes no model request. Opt-in; needs tmux |
| `command` | any | Runs your command; its stdout is a JSON list of `{"window", "used_pct", "resets_at", "provider", "account"}`. Other fields are dropped |

Windows are named `5h`, `week`, `week:<model>` (Claude Code's per-model weekly window), or `<minutes>m`.

## Configuration

`Agent-shared/quota_config.json`:

```json
{
  "sources": [
    {"type": "codex_rollouts", "account": "personal", "codex_home": "~/.codex"},
    {"type": "claude_usage", "account": "personal"},
    {"type": "claude_usage", "account": "org", "config_dir": "~/.claude-org"}
  ],
  "thresholds": {"claude": {"5h": 90, "week": 90}, "codex/personal": {"week": 85}},
  "notify": "PM",
  "interval_s": 300
}
```

A threshold key is `provider` or `provider/account`; the more specific one wins. A window at or above its threshold closes the gate.

## Running

```bash
# every 5 minutes from cron (preferred: no long-running loop)
*/5 * * * * cd /path/to/project && python3 -m vibecodehpc.monitor.quota --once
# or as a background process, e.g. inside a batch job
python3 -m vibecodehpc.monitor.quota --interval 300 &
```

On Windows, register the `--once` form in the Task Scheduler. The `claude_usage` source needs tmux and is not available there.

## Outputs (`Agent-shared/quota/`)

| File | Content |
|---|---|
| `quota.log` | One line per reading, e.g. `2026-10-14T02:45:08+00:00 claude/personal 5h 9% / week 3% \| codex/personal:pro 5h na / week 52% \| pause_new_seats no` |
| `usage.jsonl` | Every window of every reading, for plotting |
| `state.json` | The latest windows, `pause_new_seats`, the reasons, and `valid_until` |

## The gate

- `vibecodehpc launch` exits with status 3 and the reasons while the gate is closed. `--ignore-quota` overrides it, for the user's explicit request.
- When the gate closes or opens, the keeper sends PM one message (`[TK] [Warning]` or `[TK] [Report]`) with `vibecodehpc send`.
- PM's instructions ("Allocate Agents by Quota") tell it to read `quota.log` before starting or reassigning agents and to move new work to accounts with room.

## Notes

- The Codex value is the last snapshot Codex saw. An account that has not run a turn for hours shows its old value.
- The `/usage` screen layout belongs to Claude Code; if a future version changes it, the reader reports "usage screen not recognised" instead of a wrong number.
- When sending notices by hand into a tmux pane, use the same pattern as `vibecodehpc send`: check the pane is not showing a permission or usage-limit prompt, type the text, send Enter separately, then confirm on the screen that the agent took it.
