# Budget Phase Details

## Per-Agent Responsibilities

### PM (Central Budget Manager)
- Check budget status every 5-10 minutes
- Immediately notify all agents on phase transitions
- Reallocate resources based on efficiency scores

### SE (Budget Efficiency Analysis)
- Periodically calculate budget efficiency (points/performance gain)
- Identify inefficient PGs and propose improvements
- Generate budget consumption forecast graphs

### PG (Budget-Aware Implementation)
- Always check budget phase before submitting jobs
- No new implementations allowed from Phase 3 onward
- Consult PM before running long-duration jobs

### CD (Artifact Preservation)
- Immediately back up SOTA code regardless of budget status
- Perform final sync when Phase 4 is reached

## Budget Efficiency Metrics
```
Efficiency Score = (Performance Improvement Rate) / (Points Consumed)

Criteria:
- High Efficiency: Score > 0.1
- Normal: 0.01 < Score < 0.1
- Low Efficiency: Score < 0.01
```

## Emergency Procedures on Budget Exhaustion

1. **Immediate**: Stop all running jobs, terminate SSH/SFTP sessions
2. **Complete within 5 minutes**: Final update of each agent's ChangeLog.md, generate final_report.md
3. **Cleanup**: Delete large files on the supercomputer (optional)
