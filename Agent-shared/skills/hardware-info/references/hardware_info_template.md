# hardware_info.md Template

```markdown
# [Hardware Name] Hardware Specifications
Last updated: [UTC time]
Collected by: [SE ID]
Verified by: [PG ID] (signed)

## CPU
- Model: [Processor name]
- Cores: [Cores per socket] per socket × [Socket count] = [Total cores]
- Frequency: [Base frequency] (base), [Boost frequency] (turbo)
- SIMD: [Instruction sets]
- **Theoretical compute performance**: [Value] GFLOPS (FP64)
  Formula: [Cores] × [Frequency] × 2 (FMA) × [SIMD width]

## Memory
- Capacity: [Capacity]
- Type: [Type]
- **Theoretical bandwidth**: [Value] GB/s

## GPU (if applicable)
- Model: [GPU name]
- GPU count: [Count] per node
- **GPU interconnect**: [NVLink/PCIe/etc.]
- **Theoretical compute performance**: [Value] TFLOPS (FP64)

## Performance Metrics Summary
- B/F ratio: [Value] Byte/FLOP (determines memory-bound vs. compute-bound)
```
