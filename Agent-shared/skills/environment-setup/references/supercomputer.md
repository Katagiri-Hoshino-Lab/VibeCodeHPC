# Supercomputer Known Constraints

## CentOS 7 / RHEL 7
- glibc 2.17 — too old for modern Node.js (v18+)
- **Claude Code, Gemini CLI: native install impossible** (npm/Node 20+ required)
- **Codex: OK** — musl static binary, no glibc dependency
  ```bash
  wget https://github.com/openai/codex/releases/latest/download/codex-x86_64-unknown-linux-musl.tar.gz
  tar xzf codex-x86_64-unknown-linux-musl.tar.gz
  mv codex ~/.local/bin/
  ```
- OpenCode: Go binary, may work if glibc is recent enough

## RHEL 8 / Rocky 8 / AlmaLinux 8
- glibc 2.28 — Node 18/20 may work via module or nvm
- Claude Code / Gemini CLI: possible if Node 20+ available

## SLES 15 (e.g. Fugaku)
- Similar constraints to RHEL 8

## General
- No sudo — install to `~/.local/bin` or `$HOME/.codex/bin`
- No internet on compute nodes — download on login node, transfer
- Batch job scheduler (PBS/Slurm) not accessible from containers (Singularity)
- 2FA — configure ssh-agent on local machine before connecting
