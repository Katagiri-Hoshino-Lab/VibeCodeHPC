#!/bin/bash
# Sample the model server's Prometheus metrics and GPU usage into one JSONL
# file until killed. One line per sample:
#   {"t": <unix s>, "metrics": {"<name{labels}>": value, ...},
#    "gpu_idx_used_total_util_power": [[idx, MiB used, MiB total, %, W], ...]}
#
# usage: org_metrics.sh OUT.jsonl [INTERVAL_S=60] [URL=http://127.0.0.1:8000/metrics]
#
# Kept metrics: token counters, requests, preemptions, KV usage, prefix-cache
# hits (including an offload connector's), all speculative-decoding counters.
set -u
OUT=${1:?usage: org_metrics.sh OUT.jsonl [INTERVAL_S] [URL]}
INTERVAL=${2:-60}
URL=${3:-http://127.0.0.1:8000/metrics}
NAMES=(kv_cache_usage_perc gpu_cache_usage_perc num_requests_running num_requests_waiting
       num_preemptions_total prompt_tokens_total generation_tokens_total request_success_total
       prefix_cache_hits_total prefix_cache_queries_total
       external_prefix_cache_hits_total external_prefix_cache_queries_total spec_decode_)
KEEP="^vllm:($(IFS='|'; echo "${NAMES[*]}"))"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY

while true; do
  ts=$(date +%s)
  m=$(curl -s -m 5 "$URL" 2>/dev/null | grep -E "$KEEP" \
      | awk '$2 ~ /^[-+0-9.eE]+$/ { gsub(/"/, "\\\"", $1);
                                    printf "%s\"%s\":%s", (n++ ? "," : ""), $1, $2 }')
  g=$(nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu,power.draw \
        --format=csv,noheader,nounits 2>/dev/null \
      | awk -F', ' '{ for (i = 1; i <= 5; i++) if ($i !~ /^[-+0-9.]+$/) $i = "null";
                      printf "%s[%s,%s,%s,%s,%s]", (n++ ? "," : ""), $1, $2, $3, $4, $5 }')
  echo "{\"t\":$ts,\"metrics\":{$m},\"gpu_idx_used_total_util_power\":[$g]}" >> "$OUT"
  sleep "$INTERVAL"
done
