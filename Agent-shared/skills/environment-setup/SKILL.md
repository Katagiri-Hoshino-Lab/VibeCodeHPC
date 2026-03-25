---
name: environment-setup
description: "CLI and dependency installation guidance. Use when setting up VibeCodeHPC on a new environment — local PC, supercomputer, container, etc."
---

# Environment Setup

## Decision Flow

1. Check available tools: `which node npm cargo python3 module`
2. Check constraints: container restrictions, network access, admin privileges
3. Select CLI based on environment (see references/)
4. Install and authenticate

## CLI Selection Guide

| Constraint | Recommended CLI |
|-----------|----------------|
| No npm/node | Codex (Rust binary) |
| No network (air-gapped) | vibe-local (Ollama, pre-downloaded models) |
| Supercomputer (batch jobs) | Claude Code or Codex |
| Container (no job scheduler) | Any, but verify batch job access |
| Free tier only | OpenCode (Nemotron, keyless) |

## References

Environment-specific guides in `references/`:
- `references/local_pc.md` — WSL, macOS, Linux desktop
- `references/supercomputer.md` — module system, batch jobs, SSH
- `references/container.md` — Singularity, Docker constraints
