#!/bin/bash
#PBS -q YOUR_QUEUE
#PBS -l select=1
#PBS -l walltime=01:00:00
#PBS -j oe
#PBS -N vchpc_org
# Add your site's accounting directive here if it needs one (e.g. #PBS -A or -W group_list=).
#
# Run a VibeCodeHPC organisation on one GPU node with a local model server.
# Submit from this directory so that PBS_O_WORKDIR points at the kit:
#
#   cd docs/samples/self_hosted_inference_on_hpc
#   V=VCHPC_RUN_DIR=/path/to/run,VCHPC_INPUT_DIR=/path/to/inputs,VCHPC_WALL_SEC=3600
#   V=$V,LLM_MODEL=/path/to/model,LLM_TOOL_PARSER=<parser>
#   qsub -v "$V" run_org_pbs.sh
#
# Submit the same command again for the next job: it resumes the same
# conversations. All settings are described in org_job.sh and serve.sh.
JOB_ID=${PBS_JOBID%%.*}
KIT=${VCHPC_KIT:-$PBS_O_WORKDIR}
export VCHPC_SCHEDULER=pbs
# shellcheck source=org_job.sh
source "$KIT/org_job.sh"
