# Hardware Information Collection Commands

## CPU Information [Cross-check with Multiple Commands]
```bash
# Basic information
lscpu | grep -E "Model name|CPU\(s\)|Thread|Core|Socket|MHz|cache|Flags"
cat /proc/cpuinfo | grep -E "model name|cpu cores|siblings|cpu MHz|flags" | head -20

# Check SIMD instruction sets
grep -o 'avx[^ ]*\|sse[^ ]*\|fma' /proc/cpuinfo | sort -u

# NUMA information
numactl --hardware 2>/dev/null || echo "NUMA not available"
```

## Memory Information
```bash
free -h
cat /proc/meminfo | grep -E "MemTotal|MemAvailable"
```

## GPU Information

### NVIDIA
```bash
nvidia-smi -q | grep -E "Product Name|Memory|Compute|Clock"
nvidia-smi topo -m          # GPU interconnect topology
nvidia-smi nvlink -s         # NVLink status
```

### AMD
```bash
rocm-smi --showproductname 2>/dev/null
rocm-smi --showtopology 2>/dev/null
```

## Network Information
```bash
ibstat  # InfiniBand
ip link show
```
