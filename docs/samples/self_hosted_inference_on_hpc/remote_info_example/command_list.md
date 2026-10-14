# Commands for this run

Copy to `_remote_info/<site>/command_list.md` in your input directory.

- You are already on the compute node, inside a batch job. Run work directly in your working directory.
- Do not use `qsub`, `qstat`, `qdel`, `sbatch`, `squeue` or `ssh`.
- GPU measurements: `measure_submit <dir with run.sh> "<purpose, one line>" [minutes]`. It refuses when your team is at its limit; wait for a running measurement to finish. Read `<dir>/measure_<job number>.out` at most once a minute.
- The GPUs of this node serve the language model you run on. Do not use them.
- `python3` is Python `<version>` with `<packages>`. No pip, no downloads: the node has no internet access.
- Limit threads per run: `OMP_NUM_THREADS=<n>`.
