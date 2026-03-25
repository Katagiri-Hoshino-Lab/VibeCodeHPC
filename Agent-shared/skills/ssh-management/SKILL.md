---
name: ssh-management
description: "SSH/SFTP session management for remote HPC execution. Use when connecting to supercomputers. Not needed when running directly on supercomputer."
---

# SSH/SFTP Management

## Prerequisites
- User has configured SSH keys and ssh-agent before project start
- Connection details provided in `_remote_info/`

## Session Tracking
Manage sessions in `ssh_sftp_sessions.json` (PID, host, purpose). Update on create/destroy.

## Best Practices
1. Redirect large output to files, inspect with `tail`/`head`
2. Maintain same directory structure on remote as local
3. Close all sessions at project end

> Details: `references/session_management.md`
