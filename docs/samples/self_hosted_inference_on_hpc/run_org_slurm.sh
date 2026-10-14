#!/bin/bash
#SBATCH -p YOUR_PARTITION
#SBATCH -N 1
#SBATCH --exclusive
#SBATCH --gpus-per-node=4
#SBATCH -t 01:00:00
#SBATCH -J vchpc_org
#SBATCH -o vchpc_org_%j.out
# Add your site's account directive here if it needs one (#SBATCH -A ...).
#
# Slurm skeleton of run_org_pbs.sh (same job body, org_job.sh). Not tested
# on a Slurm site yet; check the GPU request syntax of your site.
#
#   cd docs/samples/self_hosted_inference_on_hpc
#   V=VCHPC_RUN_DIR=/path/to/run,VCHPC_INPUT_DIR=/path/to/inputs,VCHPC_WALL_SEC=3600
#   V=$V,LLM_MODEL=/path/to/model,LLM_TOOL_PARSER=<parser>
#   sbatch --export="ALL,$V" run_org_slurm.sh
JOB_ID=$SLURM_JOB_ID
KIT=${VCHPC_KIT:-$SLURM_SUBMIT_DIR}
export VCHPC_SCHEDULER=slurm
# shellcheck source=org_job.sh
source "$KIT/org_job.sh"
