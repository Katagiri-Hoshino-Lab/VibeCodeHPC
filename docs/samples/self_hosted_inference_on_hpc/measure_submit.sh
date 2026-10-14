#!/bin/bash
# Submit DIR/run.sh as a short measurement job from inside the organisation's
# own job, with limits enforced here rather than by the agents' instructions.
#
# The organisation's node keeps its GPUs for the model server, so GPU
# measurements run as separate small jobs. Agents call this script (on PATH
# as `measure_submit`) instead of qsub/sbatch.
#
# usage: measure_submit.sh DIR "PURPOSE" [MINUTES]
#   run from the agent's own Agent-workdir/<AGENT_ID>; DIR must contain run.sh
#
# Limits, counted per team (SE<n> and PG<n>.* share team n):
#   - at most VCHPC_MEASURE_MAX_ACTIVE jobs running or queued [2]
#   - at most VCHPC_MEASURE_MAX_PER_ORG submissions per organisation job [10]
#   - walltime clamped to 1..VCHPC_MEASURE_MAX_MIN minutes [15]
# Over a limit the script refuses with exit code 3.
#
# Environment (set by the organisation's job script):
#   VCHPC_RUN_DIR             project root (log: Agent-shared/measure_jobs.jsonl)
#   VCHPC_ORG_JOB             id of the organisation's job
#   VCHPC_SCHEDULER [pbs]     pbs | slurm
#   VCHPC_MEASURE_QUEUE       queue (PBS) or partition (Slurm) for measurements
#   VCHPC_MEASURE_RESOURCES   PBS: [select=1:ngpus=1]  Slurm: [--gpus=1]
#   VCHPC_MEASURE_ACCOUNT     optional account/group to charge
#   VCHPC_MEASURE_PREAMBLE    optional shell lines run first (e.g. "module load cuda")
#
# Output: DIR/measure_<job number>.out. Read that file (not qstat in a loop).
set -u
DIR=$(readlink -f "${1:?usage: measure_submit.sh DIR PURPOSE [MINUTES]}")
PURPOSE=${2:?usage: measure_submit.sh DIR PURPOSE [MINUTES] (PURPOSE: one line)}
MIN=${3:-10}
RUN=${VCHPC_RUN_DIR:?VCHPC_RUN_DIR is set by the job script}
QUEUE=${VCHPC_MEASURE_QUEUE:?VCHPC_MEASURE_QUEUE is set by the job script}
SCHED=${VCHPC_SCHEDULER:-pbs}
ORG_JOB=${VCHPC_ORG_JOB:-unknown}
MAX_ACTIVE=${VCHPC_MEASURE_MAX_ACTIVE:-2}
MAX_PER_ORG=${VCHPC_MEASURE_MAX_PER_ORG:-10}
MAX_MIN=${VCHPC_MEASURE_MAX_MIN:-15}
LOG=$RUN/Agent-shared/measure_jobs.jsonl

AGENT=$(basename "$PWD")
case "$AGENT" in
  SE[0-9]*) TEAM=${AGENT#SE} ;;
  PG[0-9]*.*) TEAM=${AGENT#PG}; TEAM=${TEAM%%.*} ;;
  *) echo "refused: run this from your own Agent-workdir/<SE n or PG n.m>"; exit 2 ;;
esac
JOB_NAME=m${TEAM}_$(printf %s "$AGENT" | tr -c 'A-Za-z0-9_\n' '_')

[ -f "$DIR/run.sh" ] || { echo "refused: $DIR/run.sh does not exist"; exit 2; }
case "$MIN" in ''|*[!0-9]*) MIN=10 ;; esac
[ "$MIN" -gt "$MAX_MIN" ] && MIN=$MAX_MIN
[ "$MIN" -lt 1 ] && MIN=1

# Job ids of this team in this organisation job, from the log.
team_jobs() {
  python3 - "$LOG" "$ORG_JOB" "$TEAM" <<'PY'
import json, sys
path, org_job, team = sys.argv[1:]
try:
    lines = open(path, encoding="utf-8").read().splitlines()
except OSError:
    lines = []
for line in lines:
    try:
        r = json.loads(line)
    except ValueError:
        continue
    if r.get("org_job") == org_job and r.get("team") == team:
        print(str(r.get("job", "")).split(".")[0])
PY
}

# Job numbers of this user that are queued or running.
active_jobs() {
  if [ "$SCHED" = slurm ]; then
    squeue -h -u "$(id -un)" -t PENDING,RUNNING -o %i 2>/dev/null
  else
    # `qstat -u` columns: job id first, state (Q/R/...) tenth.
    qstat -u "$(id -un)" 2>/dev/null \
      | awk '$10 == "Q" || $10 == "R" { split($1, a, "."); print a[1] }'
  fi
}

submitted=$(team_jobs)
n_org=$(printf '%s\n' "$submitted" | grep -c . || true)
if [ "$n_org" -ge "$MAX_PER_ORG" ]; then
  echo "refused: team $TEAM already submitted $n_org jobs in this organisation job" \
       "(limit $MAX_PER_ORG); ask your SE / PM"
  exit 3
fi
n_active=0
if [ -n "$submitted" ]; then
  n_active=$(active_jobs | grep -cxF -f <(printf '%s\n' "$submitted") || true)
fi
if [ "${n_active:-0}" -ge "$MAX_ACTIVE" ]; then
  echo "refused: $n_active measurement jobs of team $TEAM are running or queued" \
       "(limit $MAX_ACTIVE); wait for one to finish"
  exit 3
fi

JOB_FILE=$DIR/measure_job.sh
WALLTIME=$(printf '%02d:%02d:00' $((MIN / 60)) $((MIN % 60)))
{
  echo "#!/bin/bash"
  if [ "$SCHED" = slurm ]; then
    printf '#SBATCH %s\n' "-p $QUEUE" "${VCHPC_MEASURE_RESOURCES:---gpus=1}" \
      "-t $WALLTIME" "-J $JOB_NAME" "-o $DIR/measure_%j.log"
    [ -n "${VCHPC_MEASURE_ACCOUNT:-}" ] && echo "#SBATCH -A $VCHPC_MEASURE_ACCOUNT"
  else
    printf '#PBS %s\n' "-q $QUEUE" "-l ${VCHPC_MEASURE_RESOURCES:-select=1:ngpus=1}" \
      "-l walltime=$WALLTIME" "-N $JOB_NAME" "-j oe" "-o $DIR/"
    [ -n "${VCHPC_MEASURE_ACCOUNT:-}" ] && echo "#PBS -A $VCHPC_MEASURE_ACCOUNT"
  fi
  printf 'DIR=%q\n' "$DIR"
  printf '%s\n' "${VCHPC_MEASURE_PREAMBLE:-}"
  cat <<'BODY'
JOBNUM=${SLURM_JOB_ID:-${PBS_JOBID%%.*}}
cd "$DIR" || exit 1
{ echo "host $(hostname) job $JOBNUM start $(date -Is)"
  command -v nvidia-smi > /dev/null && nvidia-smi \
    --query-gpu=name,clocks.sm,clocks.max.sm,temperature.gpu --format=csv,noheader
  bash run.sh
  echo "exit $? end $(date -Is)"; } > "$DIR/measure_$JOBNUM.out" 2>&1
BODY
} > "$JOB_FILE"

if [ "$SCHED" = slurm ]; then
  SUBMIT=(sbatch --parsable "$JOB_FILE")
else
  SUBMIT=(qsub "$JOB_FILE")
fi
jid=$("${SUBMIT[@]}") || { echo "submission failed"; exit 1; }
jid=${jid%%;*}    # sbatch --parsable may append ";cluster"
python3 -c 'import json, sys, time
keys = ("agent", "team", "job", "purpose", "dir", "minutes", "org_job")
row = dict(zip(keys, sys.argv[1:]), time=time.strftime("%Y-%m-%dT%H:%M:%S"))
row["minutes"] = int(row["minutes"])
print(json.dumps(row, ensure_ascii=False))' \
  "$AGENT" "$TEAM" "$jid" "$PURPOSE" "$DIR" "$MIN" "$ORG_JOB" >> "$LOG"
echo "submitted $jid (limit $MIN min); output: $DIR/measure_${jid%%.*}.out"
