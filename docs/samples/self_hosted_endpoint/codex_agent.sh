#!/bin/bash
# Run one agent as a loop of `codex exec` turns against a self-hosted
# server that offers the OpenAI Responses API (for example vLLM).
#
# usage: codex_agent.sh FIRST_PROMPT_FILE NEXT_PROMPT_FILE WORKDIR [MINUTES=25]
#   The first turn starts a thread with FIRST_PROMPT_FILE; every later turn
#   resumes that thread by id with NEXT_PROMPT_FILE (falls back to
#   `resume --last` if no id was printed). The loop ends when WORKDIR/STOP
#   exists or after MINUTES.
#
# Settings (environment, defaults in brackets):
#   LLM_BASE_URL [http://127.0.0.1:8000/v1]  server address, with /v1
#   LLM_NAME [local]                         served model name
#   LLM_MAX_LEN [262144]                     the server's max model length
#   CODEX_BIN [codex]                        Codex CLI executable
#   AGENT_CODEX_HOME [WORKDIR/.codex_home]   separate CODEX_HOME for this agent
#
# Writes CODEX_HOME/config.toml from codex_config.toml next to this script.
# Output: WORKDIR/logs/agent.codex.jsonl (JSON events and turn markers).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
FIRST=$(readlink -f "${1:?usage: codex_agent.sh FIRST_PROMPT NEXT_PROMPT WORKDIR [MINUTES]}")
NEXT=$(readlink -f "${2:?next prompt file}")
WORKDIR=$(readlink -f "${3:?work directory}")
MINUTES=${4:-25}
CODEX=${CODEX_BIN:-codex}

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ftp_proxy FTP_PROXY
export CODEX_HOME=${AGENT_CODEX_HOME:-$WORKDIR/.codex_home}
mkdir -p "$CODEX_HOME" "$WORKDIR/logs"
sed -e "s|@MODEL@|${LLM_NAME:-local}|" \
    -e "s|@BASE_URL@|${LLM_BASE_URL:-http://127.0.0.1:8000/v1}|" \
    -e "s|@CONTEXT@|${LLM_MAX_LEN:-262144}|" \
    "$HERE/codex_config.toml" > "$CODEX_HOME/config.toml"

cd "$WORKDIR" || exit 2
LOG=$WORKDIR/logs/agent.codex.jsonl
END=$(( $(date +%s) + MINUTES * 60 ))
mark() { echo "{\"t\":\"$(date +%T)\",\"kind\":\"$1\"${2:-}}" >> "$LOG"; }

mark start
"$CODEX" exec --skip-git-repo-check --json "$(cat "$FIRST")" >> "$LOG" 2>&1
mark turn_end ",\"turn\":0,\"rc\":$?"
# The first JSON event of a new thread carries its id.
THREAD=$(grep -o '"thread_id": *"[^"]*"' "$LOG" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
n=1
while [ ! -f "$WORKDIR/STOP" ] && [ "$(date +%s)" -lt "$END" ]; do
  if [ -n "$THREAD" ]; then
    "$CODEX" exec --skip-git-repo-check --json resume "$THREAD" "$(cat "$NEXT")" >> "$LOG" 2>&1
  else
    "$CODEX" exec --skip-git-repo-check --json resume --last "$(cat "$NEXT")" >> "$LOG" 2>&1
  fi
  mark turn_end ",\"turn\":$n,\"rc\":$?"
  n=$((n + 1))
  sleep 5
done
mark stop ",\"turns\":$n"
