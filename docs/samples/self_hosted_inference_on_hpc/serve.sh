#!/bin/bash
# Start a vLLM server that Claude Code (Anthropic /v1/messages) and
# OpenAI-compatible CLIs (/v1/chat/completions, /v1/responses) can use.
#
# usage: serve.sh MODEL_PATH [SPEC]
#   SPEC  speculative decoding, default none:
#           none             no speculative decoding
#           mtp:K            the model's own multi-token-prediction heads, K tokens
#           ngram:K          prompt lookup, K tokens (n-gram key of 2..K tokens)
#           METHOD:K:PATH    a separate draft model (e.g. eagle3:4:/models/draft)
#
# Settings (environment, defaults in brackets):
#   LLM_NAME [local]          served model name; agents use it as --model
#   LLM_HOST [127.0.0.1]  LLM_PORT [8000]
#   LLM_TP [4]                tensor-parallel size (GPUs per server)
#   LLM_EP [0]                1: expert parallelism for MoE models
#   LLM_MAX_LEN [262144]      max model length (prompt + output)
#   LLM_MAX_SEQS [48]         concurrent sequences; >= number of agents
#   LLM_GPU_UTIL [0.92]
#   LLM_KV_DTYPE [auto]       e.g. fp8
#   LLM_TOOL_PARSER           tool-call parser for the model (required for agents)
#   LLM_REASONING_PARSER      reasoning parser for the model, if it has one
#   LLM_TEXT_ONLY [1]         1: refuse image/video/audio inputs
#   LLM_CPU_OFFLOAD_GB [0]    >0: vLLM's own KV offload to host memory
#   LLM_PREFIX_RETENTION [0]  >0: --prefix-cache-retention-interval (tokens,
#                             multiple of the block size); see
#                             docs/self_hosted_inference.md for hybrid models
#   LLM_TRUST_REMOTE_CODE [0] 1: --trust-remote-code
#   LLM_EXTRA_ARGS            appended to the vllm serve command (word-split),
#                             e.g. "--generation-config vllm"
#   LLM_CONTAINER             Singularity/Apptainer image; empty runs vllm directly
#   LLM_BIND                  extra bind paths for the container (comma separated)
#   LLM_CACHE_DIR [${TMPDIR:-/tmp}/vllm_$USER]  node-local caches
#
# The script execs the server, so its PID is the server's PID.
set -u
MODEL=${1:?usage: serve.sh MODEL_PATH [SPEC]}
SPEC=${2:-none}

CACHE=${LLM_CACHE_DIR:-${TMPDIR:-/tmp}/vllm_$(id -un)}
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1
export VLLM_CACHE_ROOT=$CACHE/vllm HF_HOME=$CACHE/hf
export XDG_CACHE_HOME=$CACHE/xdg TRITON_CACHE_DIR=$CACHE/triton
mkdir -p "$VLLM_CACHE_ROOT" "$HF_HOME" "$XDG_CACHE_HOME" "$TRITON_CACHE_DIR"
# Compute nodes often export a proxy; requests to localhost must not use it.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ftp_proxy FTP_PROXY

ARGS=(--served-model-name "${LLM_NAME:-local}"
      --host "${LLM_HOST:-127.0.0.1}" --port "${LLM_PORT:-8000}"
      --tensor-parallel-size "${LLM_TP:-4}"
      --max-model-len "${LLM_MAX_LEN:-262144}"
      --max-num-seqs "${LLM_MAX_SEQS:-48}"
      --gpu-memory-utilization "${LLM_GPU_UTIL:-0.92}"
      --kv-cache-dtype "${LLM_KV_DTYPE:-auto}")
[ "${LLM_EP:-0}" = 1 ] && ARGS+=(--enable-expert-parallel)
[ "${LLM_TRUST_REMOTE_CODE:-0}" = 1 ] && ARGS+=(--trust-remote-code)
if [ -n "${LLM_TOOL_PARSER:-}" ]; then
  ARGS+=(--enable-auto-tool-choice --tool-call-parser "$LLM_TOOL_PARSER")
else
  echo "warning: LLM_TOOL_PARSER is not set; agents need tool calls" >&2
fi
[ -n "${LLM_REASONING_PARSER:-}" ] && ARGS+=(--reasoning-parser "$LLM_REASONING_PARSER")
[ "${LLM_TEXT_ONLY:-1}" = 1 ] && ARGS+=(--limit-mm-per-prompt '{"image":0,"video":0,"audio":0}')

OFFLOAD_GB=${LLM_CPU_OFFLOAD_GB:-0}
if [ "$OFFLOAD_GB" -gt 0 ]; then
  # vLLM's own connector; check server.log for "Turning off hybrid" with other connectors.
  printf -v KV '{"kv_connector":"%s","kv_role":"kv_both","kv_connector_extra_config":%s}' \
    SimpleCPUOffloadConnector \
    "{\"kv_offload_backend\":\"cpu\",\"cpu_bytes_to_use\":$((OFFLOAD_GB * 1000000000))}"
  ARGS+=(--kv-transfer-config "$KV")
fi
RETENTION=${LLM_PREFIX_RETENTION:-0}
[ "$RETENTION" -gt 0 ] && ARGS+=(--prefix-cache-retention-interval "$RETENTION")

case "$SPEC" in
  none) ;;
  ngram:*)
    k=${SPEC#ngram:}
    printf -v SC '{"method":"ngram","num_speculative_tokens":%s,%s}' "$k" \
      "\"prompt_lookup_max\":$k,\"prompt_lookup_min\":2"
    ARGS+=(--speculative-config "$SC") ;;
  *:*:*)
    method=${SPEC%%:*}; rest=${SPEC#*:}; k=${rest%%:*}; draft=${rest#*:}
    printf -v SC '{"method":"%s","num_speculative_tokens":%s,"model":"%s"}' "$method" "$k" "$draft"
    ARGS+=(--speculative-config "$SC") ;;
  *:*)
    method=${SPEC%%:*}; k=${SPEC#*:}
    printf -v SC '{"method":"%s","num_speculative_tokens":%s}' "$method" "$k"
    ARGS+=(--speculative-config "$SC") ;;
  *) echo "unknown SPEC '$SPEC'" >&2; exit 2 ;;
esac

# shellcheck disable=SC2206  # LLM_EXTRA_ARGS is meant to be word-split
[ -n "${LLM_EXTRA_ARGS:-}" ] && ARGS+=($LLM_EXTRA_ARGS)

echo "serve spec=$SPEC: vllm serve $MODEL ${ARGS[*]}"
if [ -n "${LLM_CONTAINER:-}" ]; then
  RUNTIME=$(command -v apptainer || command -v singularity) \
    || { echo "apptainer/singularity not found" >&2; exit 2; }
  BINDS=(-B "$CACHE" -B "$(dirname "$MODEL")")
  [ -n "${LLM_BIND:-}" ] && BINDS+=(-B "$LLM_BIND")
  exec "$RUNTIME" exec --nv "${BINDS[@]}" "$LLM_CONTAINER" vllm serve "$MODEL" "${ARGS[@]}"
fi
exec vllm serve "$MODEL" "${ARGS[@]}"
