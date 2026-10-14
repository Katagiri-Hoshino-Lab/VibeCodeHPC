#!/bin/bash
# Body of the organisation job, sourced by run_org_pbs.sh or run_org_slurm.sh
# after they set JOB_ID and KIT (this directory). Everything runs on the one
# allocated node: the model server, VibeCodeHPC and all agents.
#
# Required (environment):
#   VCHPC_RUN_DIR     project root. Keep the same path in every job: Claude
#                     Code stores conversations per directory path.
#   VCHPC_INPUT_DIR   copied over the project root at every job start:
#                     requirement_definition.md, BaseCode/, _remote_info/
#   LLM_MODEL         model path given to serve.sh
#
# Optional (defaults in brackets):
#   VCHPC_SRC [KIT/../../..]    VibeCodeHPC checkout copied into a new project root
#   VCHPC_NAME [org]            project name (tmux sessions NAME_PM, NAME_Workers1)
#   VCHPC_WORKERS [8]           worker panes
#   VCHPC_WALL_SEC [3600]       the job's walltime in seconds (match the header)
#   VCHPC_ORG_MIN               fixed organisation window in minutes from server ready
#   VCHPC_SAVE_SEC [360]        seconds kept at the end for saving state
#   VCHPC_STOP_MARGIN_MIN [5]   agents stop new work this long before the window ends
#   VCHPC_READY_WAIT [2400]     seconds to wait for the server
#   VCHPC_LOG_DIR [RUN/../joblogs/JOB_ID]
#   VCHPC_LOCAL_DIR [${TMPDIR:-/tmp}/vchpc_JOB_ID]  node-local scratch, holds HOME
#   VCHPC_PYTHON [python3]      Python >= 3.10 for v2 and its hooks
#   VCHPC_CLAUDE_BIN            Claude Code executable if not on PATH
#   VCHPC_EFFORT                effort level for every agent
#   VCHPC_MAX_OUTPUT_TOKENS [32000]  keep prompt + output under LLM_MAX_LEN
#   VCHPC_NEW_AGENTS            JSONL of agents joining in this job (resume_sessions.py)
#   VCHPC_ASSIGNMENTS           JSON {agent_id: text} for the first messages (init_send.py)
#   VCHPC_VERIFY_CMD            independent checker, run every VCHPC_VERIFY_INTERVAL [120] s
#   VCHPC_DIGEST_CMD            digest command, run every VCHPC_DIGEST_INTERVAL [600] s
#                               (both run with bash -c in the project root; KIT is exported)
#   VCHPC_MEASURE_QUEUE         enables `measure_submit` for the agents (measure_submit.sh)
#   VCHPC_RUN_BASE_TAR          start from this tar of a project root (for A/B runs);
#                               the current root is saved to RUN/../snap/ first
#   LLM_SPEC [none]             speculative decoding (serve.sh SPEC)
#   LLM_NAME [local], LLM_PORT [8000], other LLM_*: see serve.sh
set -u
: "${JOB_ID:?set by the wrapper}" "${KIT:?set by the wrapper}"
RUN=${VCHPC_RUN_DIR:?set VCHPC_RUN_DIR}
INPUT=${VCHPC_INPUT_DIR:?set VCHPC_INPUT_DIR}
: "${LLM_MODEL:?set LLM_MODEL}"
SRC=${VCHPC_SRC:-$(cd "$KIT/../../.." && pwd)}
NAME=${VCHPC_NAME:-org}
export LLM_NAME=${LLM_NAME:-local} LLM_PORT=${LLM_PORT:-8000}
SPEC=${LLM_SPEC:-none}
LOG=${VCHPC_LOG_DIR:-$(dirname "$RUN")/joblogs/$JOB_ID}
LOCAL=${VCHPC_LOCAL_DIR:-${TMPDIR:-/tmp}/vchpc_$JOB_ID}
PY=$(command -v "${VCHPC_PYTHON:-python3}") || { echo "python not found"; exit 2; }
ME=$(id -un)
mkdir -p "$LOG" "$LOCAL/bin" "$RUN"
T0=$(date +%s)
END=$((T0 + ${VCHPC_WALL_SEC:-3600}))
# Compute nodes often export a proxy; requests to the local server must not use it.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ftp_proxy FTP_PROXY
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost

timing() { echo "$1" >> "$LOG/timing.jsonl"; }
# every SECONDS LOGFILE COMMAND: run COMMAND repeatedly until RUN/STOP exists
every() {
  ( while [ ! -f "$RUN/STOP" ]; do bash -c "$3" >> "$2" 2>&1; sleep "$1"; done ) &
}
stop_server() {
  pkill -u "$ME" -f "vllm serve $LLM_MODEL" 2>/dev/null; sleep 10
  pkill -9 -u "$ME" -f "vllm serve $LLM_MODEL" 2>/dev/null
}
start_server() {
  LLM_CACHE_DIR=$LOCAL/llm_cache bash "$KIT/serve.sh" "$LLM_MODEL" "$SPEC" \
    > "$LOG/server.log" 2>&1 &
  SERVER_PID=$!
}

{ echo "host $(hostname) job $JOB_ID start $(date -Is) end $(date -d @$END -Is)"
  nvidia-smi --query-gpu=index,name,memory.total --format=csv
  tmux -V; } > "$LOG/env.txt" 2>&1

# 0. Optional: the same starting point for every run of a comparison.
if [ -n "${VCHPC_RUN_BASE_TAR:-}" ]; then
  SNAP=$(dirname "$RUN")/snap; mkdir -p "$SNAP"
  if [ ! -f "$RUN/CLAUDE.md" ] || tar -cf "$SNAP/replaced_$JOB_ID.tar" -C "$RUN" .; then
    find "$RUN" -mindepth 1 -delete && tar -xf "$VCHPC_RUN_BASE_TAR" -C "$RUN" \
      && timing "{\"restored\":\"$VCHPC_RUN_BASE_TAR\"}"
  fi
fi

# 1. Model server and its metrics (loading a large model takes many minutes).
bash "$KIT/org_metrics.sh" "$LOG/org_metrics.jsonl" 60 "http://127.0.0.1:$LLM_PORT/metrics" &
start_server
timing "{\"spec\":\"$SPEC\",\"t0\":$T0}"

# 2. Project tree: VibeCodeHPC on the first job, the user's inputs on every job.
if [ ! -f "$RUN/CLAUDE.md" ]; then
  if [ -e "$SRC/.git" ]; then      # a directory, or a file in a git worktree
    git -C "$SRC" archive HEAD | tar -x -C "$RUN"
  else
    tar -C "$SRC" --exclude=.git -cf - . | tar -x -C "$RUN"
  fi
fi
cp -a "$INPUT"/. "$RUN"/
mkdir -p "$RUN/state" "$RUN/Agent-shared" "$RUN/User-shared"
rm -f "$RUN/STOP"
NEW_ORG=0
[ -s "$RUN/state/sessions_latest.jsonl" ] || NEW_ORG=1

# 3. Node-local HOME holding the previous job's conversations; agent environment.
export HOME=$LOCAL/home
mkdir -p "$HOME"
[ -f "$RUN/state/home_latest.tar" ] && tar -xf "$RUN/state/home_latest.tar" -C "$HOME"
ln -sf "$PY" "$LOCAL/bin/python3"          # v2 hooks call python3
[ -n "${VCHPC_CLAUDE_BIN:-}" ] && ln -sf "$VCHPC_CLAUDE_BIN" "$LOCAL/bin/claude"
if [ -n "${VCHPC_MEASURE_QUEUE:-}" ]; then
  printf '#!/bin/bash\nexec bash %q "$@"\n' "$KIT/measure_submit.sh" > "$LOCAL/bin/measure_submit"
  chmod +x "$LOCAL/bin/measure_submit"
  export VCHPC_RUN_DIR=$RUN VCHPC_ORG_JOB=$JOB_ID VCHPC_MEASURE_QUEUE
fi
export PATH=$LOCAL/bin:$PATH
SEED=(--plain-shell --max-output-tokens "${VCHPC_MAX_OUTPUT_TOKENS:-32000}")
[ "${LLM_TEXT_ONLY:-1}" = 1 ] && SEED+=(--text-only)
[ -n "${VCHPC_EFFORT:-}" ] && SEED+=(--effort "$VCHPC_EFFORT")
"$PY" "$RUN/vibecodehpc/scripts/seed_claude_home.py" "$HOME" "$RUN" "${SEED[@]}" \
  >> "$LOG/env.txt" 2>&1

# Point every Claude Code model slot at the local server (docs/self_hosted_inference.md).
export ANTHROPIC_BASE_URL=http://127.0.0.1:$LLM_PORT ANTHROPIC_AUTH_TOKEN=local
unset ANTHROPIC_API_KEY
export ANTHROPIC_MODEL=$LLM_NAME ANTHROPIC_SMALL_FAST_MODEL=$LLM_NAME
export ANTHROPIC_DEFAULT_OPUS_MODEL=$LLM_NAME ANTHROPIC_DEFAULT_SONNET_MODEL=$LLM_NAME
export ANTHROPIC_DEFAULT_HAIKU_MODEL=$LLM_NAME CLAUDE_CODE_SUBAGENT_MODEL=$LLM_NAME
export DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
export DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1
{ command -v python3 claude tmux; python3 --version; claude --version; } >> "$LOG/env.txt" 2>&1

# 4. Wait for the server. If it died with the KV offload on, retry once without it.
ready=0
WAIT_TO=$((T0 + ${VCHPC_READY_WAIT:-2400}))
while [ "$(date +%s)" -lt "$WAIT_TO" ]; do
  curl -s -m 3 "http://127.0.0.1:$LLM_PORT/health" > /dev/null 2>&1 && { ready=1; break; }
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    [ "${LLM_CPU_OFFLOAD_GB:-0}" -gt 0 ] || break
    cp "$LOG/server.log" "$LOG/server_offload_failed.log"
    stop_server
    export LLM_CPU_OFFLOAD_GB=0
    timing "{\"fallback\":\"no_offload\",\"seconds\":$(( $(date +%s) - T0 ))}"
    start_server
  fi
  sleep 10
done
timing "{\"server_ready\":$ready,\"seconds\":$(( $(date +%s) - T0 ))}"
KV_LINES="non-default args|retention|KV cache size|Maximum concurrency|Turning off hybrid"
grep -E "$KV_LINES|[Ss]peculative" "$LOG/server.log" | head -40 > "$LOG/kv_summary.txt"

if [ "$ready" = 1 ]; then
  # 5. The organisation's window, and the end time the agents are told.
  T_READY=$(date +%s)
  ORG_END=$((END - ${VCHPC_SAVE_SEC:-360}))
  CUT=0
  if [ -n "${VCHPC_ORG_MIN:-}" ]; then
    PLANNED=$((T_READY + VCHPC_ORG_MIN * 60))
    if [ "$PLANNED" -le "$ORG_END" ]; then ORG_END=$PLANNED; else CUT=1; fi
  fi
  STOP_AT=$(date -d @$((ORG_END - ${VCHPC_STOP_MARGIN_MIN:-5} * 60)) +%H:%M)
  # requirement_definition.md may contain @JOB_END@ and @STOP_NEW_WORK@.
  [ -f "$RUN/requirement_definition.md" ] && sed -i \
    -e "s/@JOB_END@/$(date -d @$ORG_END +%H:%M)/g" -e "s/@STOP_NEW_WORK@/$STOP_AT/g" \
    "$RUN/requirement_definition.md"
  "$PY" - "$RUN/Agent-shared/periodic_monitor_config.json" $(( (ORG_END - T_READY) / 60 )) <<'PY'
import json, sys
path, minutes = sys.argv[1], int(sys.argv[2])
try:
    config = json.load(open(path))
except (OSError, ValueError):
    config = {}
config["max_runtime_min"] = minutes
json.dump(config, open(path, "w"), indent=2)
PY
  printf '{"t0":%s,"t_ready":%s,"org_end":%s,"cut":%s,"stop_new_work":"%s","spec":"%s"}\n' \
    "$T0" "$T_READY" "$ORG_END" "$CUT" "$STOP_AT" "$SPEC" > "$LOG/org_window.json"

  cd "$RUN" || exit 2
  export PYTHONPATH=$RUN KIT
  python3 "$KIT/org_summary.py" snap "$RUN" "$LOG/org_before.json" >> "$LOG/env.txt" 2>&1

  # 6. v2: a new organisation, or the previous one with the same conversations.
  if [ "$NEW_ORG" = 1 ]; then
    python3 -m vibecodehpc setup --name "$NAME" --workers "${VCHPC_WORKERS:-8}" \
      --cli claude --model "$LLM_NAME" > "$LOG/v2_setup.log" 2>&1
  else
    RESUME=(--name "$NAME" --model "$LLM_NAME" --workers "${VCHPC_WORKERS:-8}"
            --end-time "$STOP_AT")
    [ -n "${VCHPC_NEW_AGENTS:-}" ] && RESUME+=(--new-agents "$VCHPC_NEW_AGENTS")
    python3 "$KIT/resume_sessions.py" "${RESUME[@]}" > "$LOG/v2_resume.log" 2>&1
    python3 -m vibecodehpc.monitor.periodic_monitor "$RUN" --foreground \
      --project-name "$NAME" > "$LOG/periodic_monitor.log" 2>&1 &
  fi
  T_V2=$(date +%s)
  timing "{\"v2_started\":$T_V2,\"new_org\":$NEW_ORG}"
  python3 -m vibecodehpc.monitor.periodic_enter "$NAME" > "$LOG/periodic_enter.log" 2>&1 &
  INIT=(--wait-min 30 --end-time "$STOP_AT")
  [ "$NEW_ORG" = 1 ] || INIT+=(--tag "$JOB_ID")
  [ -n "${VCHPC_ASSIGNMENTS:-}" ] && INIT+=(--assignments "$VCHPC_ASSIGNMENTS")
  python3 "$KIT/init_send.py" "${INIT[@]}" > "$LOG/init_send.log" 2>&1 &

  # 7. Optional: independent checker and digest (read-only towards the agents).
  if [ -n "${VCHPC_VERIFY_CMD:-}" ]; then
    every "${VCHPC_VERIFY_INTERVAL:-120}" "$LOG/verify.log" "$VCHPC_VERIFY_CMD"
  fi
  if [ -n "${VCHPC_DIGEST_CMD:-}" ]; then
    every "${VCHPC_DIGEST_INTERVAL:-600}" "$LOG/digest.log" "$VCHPC_DIGEST_CMD"
  fi

  # 8. The organisation runs. If PM's tmux session disappears, resume PM once.
  relaunched=0
  while [ "$(date +%s)" -lt "$ORG_END" ]; do
    if [ "$relaunched" = 0 ] && ! tmux has-session -t "${NAME}_PM" 2>/dev/null; then
      python3 "$KIT/resume_sessions.py" --name "$NAME" --model "$LLM_NAME" --pm-only \
        > "$LOG/pm_relaunch.log" 2>&1
      relaunched=1
    fi
    sleep 30
  done
  python3 "$KIT/org_summary.py" final "$RUN" "$LOG" "$T_V2" "$(date +%s)" --label "$SPEC" \
    > "$LOG/org_summary.log" 2>&1

  # 9. State for the next job: the registry (session ids) and one tar of HOME.
  cp "$RUN/Agent-shared/agent_and_pane_id_table.jsonl" "$RUN/state/sessions_$JOB_ID.jsonl" \
    && cp "$RUN/state/sessions_$JOB_ID.jsonl" "$RUN/state/sessions_latest.jsonl"
  # Keep the newest previous HOME tar as a fallback, delete older ones.
  find "$RUN/state" -maxdepth 1 -name 'home_*.tar' ! -name home_latest.tar -printf '%T@ %p\n' \
    | sort -rn | tail -n +2 | cut -d' ' -f2- | xargs -r -d '\n' rm -f
  tar -cf "$RUN/state/home_$JOB_ID.tar" -C "$HOME" . \
    && cp "$RUN/state/home_$JOB_ID.tar" "$RUN/state/home_latest.tar"
  touch "$RUN/STOP"
fi

# Shut down this run only: its tmux sessions, monitors, helpers and the server.
tmux list-sessions -F '#{session_name}' 2>/dev/null | grep "^${NAME}_" \
  | xargs -r -n 1 tmux kill-session -t
pkill -u "$ME" -f "periodic_monitor $RUN" 2>/dev/null
jobs -p | xargs -r kill 2>/dev/null
stop_server
echo "end $(date -Is) elapsed $(( $(date +%s) - T0 )) s" >> "$LOG/env.txt"
