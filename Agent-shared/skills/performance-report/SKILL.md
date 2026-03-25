---
name: performance-report
description: "3-tier report hierarchy for VibeCodeHPC. Use when creating performance reports or organizing deliverables."
---

# Report Hierarchy

## Three Tiers

| Tier | Format | Author | Location |
|------|--------|--------|----------|
| Primary | ChangeLog.md | PG (auto) | Each PG directory |
| Secondary | Markdown + graphs | SE (semi-auto) | User-shared/reports/ |
| Final | Executive summary | PM | User-shared/final_report.md |

## Directory Layout
```
Agent-shared/     # Technical tools (agents only)
User-shared/      # Deliverables (user-facing)
├── final_report.md
├── reports/
└── visualizations/
```

## Timing
- **Primary**: PG records after every code change
- **Secondary**: SE generates at milestones
- **Final**: PM creates at project end (includes ROI, budget summary, recommendations)

## Rules
- Update existing reports — never create duplicates
- Final report must state achievement as % of theoretical peak
