# User info for this run

Copy to `_remote_info/<site>/user_info.md` in your input directory.

- No SSH connection is used: the organisation runs on the compute node itself.
- Working directory: the project root set by the job script (`VCHPC_RUN_DIR`).
- Shared storage: `<path>`. If its file-count quota is tight, append to one file per version instead of creating many small files.
