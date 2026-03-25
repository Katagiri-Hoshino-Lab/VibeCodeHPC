# _remote_info

Site-specific connection info and project settings for the target compute environment.

⚠️ **This directory is gitignored.** Never commit credentials or private keys.

## Example structure

```
_remote_info/
├── flow/                        # e.g. Supercomputer "Flow"
│   ├── user_info.md             # SSH connection, remote working directory
│   ├── command_list.md          # Site-specific commands (qsub, pjsub, etc.)
│   ├── sample_bash.sh           # Job script sample
│   ├── load_custom_module.md    # Module loading instructions
│   └── node_resource_groups.md  # Resource group specs (required)
│
└── miyabi/                      # Another site
    └── (same structure)
```

## Required: `node_resource_groups.md`

Markdown table with resource group details for budget tracking:
- Group name (cx-small, fx-large, etc.)
- Min/max nodes, CPU/GPU cores, memory
- Max walltime (default and limit)
- Rate (points/sec)

### How to obtain
1. Copy from the site's official documentation
2. Convert to markdown table
3. Include the billing formula (e.g. `rate × GPU_count × seconds`)

### Used by
- **PM**: Resource allocation strategy
- **PG**: Job submission (selecting the right resource group)
- **Budget tracking**: Cost estimation from ChangeLog.md

## Example: `user_info.md`

```markdown
- **SSH**: username@supercomputer.example.jp
- **Working directory**: /data/username/VibeCodeHPC/project_name/
```

## Security
- File permissions: `chmod 600`
- Private keys managed via ssh-agent (never stored here)
