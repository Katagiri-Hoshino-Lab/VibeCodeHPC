# SSH/SFTP Session Management Details

## Session State File

Each agent manages session state via `ssh_sftp_sessions.json`:
```json
{
  "last_updated": "2025-01-30T12:34:56Z",
  "sessions": [
    {
      "type": "ssh",
      "pid": 37681,
      "host": "hpc.example.jp",
      "purpose": "main_commands",
      "created": "2025-01-30T10:23:45Z"
    },
    {
      "type": "sftp",
      "pid": 37682,
      "host": "hpc.example.jp",
      "purpose": "file_transfer",
      "created": "2025-01-30T10:25:12Z"
    }
  ]
}
```

## Command Examples by Purpose

### Compilation
```bash
cd /project/path && make 2>&1 | tee compile_v1.2.3.log
```

### Batch Job Submission
```bash
# Create and submit job script (sbatch/pjsub/etc. depending on the system)
sbatch job.sh

# Check job status (squeue/pjstat/etc. depending on the system)
squeue -u $USER
```

### File Transfer (SFTP)
```bash
# Upload / Download
put optimized_code.c
get job_12345.out
mget *.log
```

### Environment Survey (for SE — hardware_info.md creation)
**Important**: Hardware information must be collected on compute nodes.
Login nodes may have different CPU/GPU configurations, so use a batch job or interactive job to access a compute node before running collection commands.

## Error Handling

### On Connection Failure
1. Check SSH configuration (ssh-agent, keys)
2. Re-verify connection information in `_remote_info/`
3. Try alternative connection methods (direct Bash tool)
4. Report to PM

### On Session Disconnect
1. Remove stale PIDs from `ssh_sftp_sessions.json`
2. Establish a new session
3. Update the JSON file
