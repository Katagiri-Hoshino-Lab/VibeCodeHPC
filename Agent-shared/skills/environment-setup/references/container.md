# Container Environment (Singularity / Docker)

## Singularity on Supercomputers

### Advantage
- Modern OS inside container — Claude Code, Gemini CLI, OpenCode all installable
- Independent of host OS constraints (CentOS 7 etc.)

### Limitation
- **Batch job scheduler (PBS/Slurm) not accessible from inside container**
- Network access depends on site policy

### Hybrid Strategy
Use container CLIs for code generation, host CLI for job management:

| Agent | Location | CLI | Role |
|-------|----------|-----|------|
| PM, SE | Container (Singularity) | Claude Code | Orchestration, analysis |
| PG (code gen) | Container | Claude Code / Gemini | Code generation |
| PG (job mgmt) | Host | Codex (musl) | `qsub`, `sbatch`, result retrieval |

Agents communicate via tmux IPC across container boundary.

## Docker (Local Development)
- No restrictions on job scheduler
- `docker compose` for multi-service (e.g., Ollama + vibe-local)
- Full network access
