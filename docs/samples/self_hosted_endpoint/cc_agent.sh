#!/bin/bash
# Run one agent as a loop of headless Claude Code turns against a
# self-hosted Anthropic-compatible server (for example vLLM's /v1/messages).
#
# usage: cc_agent.sh FIRST_PROMPT_FILE NEXT_PROMPT_FILE WORKDIR [MINUTES=25]
#   The first turn sends FIRST_PROMPT_FILE; every later turn continues the
#   same conversation (--continue) with NEXT_PROMPT_FILE. The loop ends when
#   WORKDIR/STOP exists or after MINUTES.
#
# Settings (environment, defaults in brackets):
#   LLM_BASE_URL [http://127.0.0.1:8000]  server address, without /v1
#   LLM_NAME [local]                      served model name
#   CLAUDE_BIN [claude]                   Claude Code executable
#   AGENT_HOME [WORKDIR/.agent_home]      separate HOME for this agent
#   MAX_TURNS [200]                       tool-use turns per headless call
#
# Output: WORKDIR/logs/agent.cc.jsonl (stream-json, one line per event, plus
# start/turn_end/stop lines) and WORKDIR/logs/agent.cc.err.
set -u
FIRST=$(readlink -f "${1:?usage: cc_agent.sh FIRST_PROMPT NEXT_PROMPT WORKDIR [MINUTES]}")
NEXT=$(readlink -f "${2:?next prompt file}")
WORKDIR=$(readlink -f "${3:?work directory}")
MINUTES=${4:-25}
CLAUDE=${CLAUDE_BIN:-claude}
MODEL=${LLM_NAME:-local}

# Requests to the local server must not go through a proxy.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ftp_proxy FTP_PROXY
export HOME=${AGENT_HOME:-$WORKDIR/.agent_home}
mkdir -p "$HOME" "$WORKDIR/logs"
export ANTHROPIC_BASE_URL=${LLM_BASE_URL:-http://127.0.0.1:8000}
# Headless mode needs a key; the server ignores it unless started with --api-key.
export ANTHROPIC_AUTH_TOKEN=local ANTHROPIC_API_KEY=local
export ANTHROPIC_MODEL=$MODEL ANTHROPIC_SMALL_FAST_MODEL=$MODEL CLAUDE_CODE_SUBAGENT_MODEL=$MODEL
export ANTHROPIC_DEFAULT_OPUS_MODEL=$MODEL ANTHROPIC_DEFAULT_SONNET_MODEL=$MODEL
export ANTHROPIC_DEFAULT_HAIKU_MODEL=$MODEL
export DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1 DISABLE_AUTOUPDATER=1
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

cd "$WORKDIR" || exit 2
LOG=$WORKDIR/logs/agent.cc.jsonl
ERR=$WORKDIR/logs/agent.cc.err
END=$(( $(date +%s) + MINUTES * 60 ))
note() { printf '{"t":"%s","kind":"%s"%s}\n' "$(date +%T)" "$1" "${2:-}" >> "$LOG"; }

turn() {   # turn PROMPT_FILE [extra flags...]
  local prompt=$1; shift
  "$CLAUDE" -p "$(cat "$prompt")" "$@" --dangerously-skip-permissions \
    --output-format stream-json --verbose --max-turns "${MAX_TURNS:-200}" >> "$LOG" 2>> "$ERR"
}

note start
turn "$FIRST"
note turn_end ",\"turn\":0,\"rc\":$?"
n=1
while [ ! -f "$WORKDIR/STOP" ] && [ "$(date +%s)" -lt "$END" ]; do
  turn "$NEXT" --continue
  note turn_end ",\"turn\":$n,\"rc\":$?"
  n=$((n + 1))
  sleep 5
done
note stop ",\"turns\":$n"
