# Civic Commons Personas

This directory contains user personas for reviewing and validating the Civic Commons project from multiple perspectives.

## Persona Index

| # | Persona | Role | Key Concern |
|---|---------|------|-------------|
| 01 | [Busy Parent](01_busy_parent.md) | Sarah Chen | Time efficiency, kid-relevant filtering |
| 02 | [Retired Civic Watchdog](02_retired_civic_watchdog.md) | Hal Morrison | Full documents, historical search, accuracy |
| 03 | [City Council Member](03_city_council_member.md) | Marcus Thompson | Cross-entity awareness, constituent queries |
| 04 | [New Resident](04_new_resident.md) | Jordan Rivera | Orientation, discovery, modern UX |
| 05 | [System Administrator](05_system_administrator.md) | Derek Okonkwo | Deployment, maintenance, operations |
| 06 | [Local Journalist](06_local_journalist.md) | Maria Santos | Research, quotes, multi-city coverage |
| 07 | [Senior Citizen](07_senior_citizen.md) | Dot Williams | Accessibility, simplicity, print-friendly |
| 08 | [Small Business Owner](08_small_business_owner.md) | Mike Patel | Business impact, deadlines, quick access |
| 09 | [Community Activist](09_community_activist.md) | Keisha Washington | Accountability, vote tracking, mobilization |
| 10 | [City Staff Member](10_city_staff_member.md) | Amanda Foster | Accuracy, data freshness, workload reduction |
| 11 | [Developer / Contributor](11_developer_contributor.md) | Alex Kim | Documentation, contribution guide, DX |

## How to Use These Personas

### For Design Review
Ask: "How would [Persona] react to this feature?"

### For Prioritization
Consider which personas represent the largest or most important user groups.

### For Testing
Create test scenarios based on each persona's use cases.

### For LLM Review
Prompt: "Review this design from the perspective of [Persona Name] — a [brief description]. Focus on their specific concerns from the persona document."

## Common Themes Across Personas

### High Priority (Multiple Personas)
- **Notifications/Alerts** — Sarah, Maria, Keisha, Mike all want to be notified
- **Full-text Search** — Hal, Maria, Keisha need to find specific information
- **Accessibility** — Dot, but benefits everyone
- **Mobile Access** — Sarah, Mike, Jordan expect mobile-first
- **Data Freshness Transparency** — Amanda, Hal, Maria need to trust the data

### Feature Requests by Frequency
| Feature | Personas Requesting |
|---------|---------------------|
| Keyword/topic alerts | Sarah, Maria, Keisha, Mike |
| Vote/roll call tracking | Hal, Maria, Keisha |
| Permanent shareable links | Hal, Maria, Keisha |
| Calendar export (iCal) | Sarah, Jordan |
| Print-friendly views | Hal, Dot |
| Accessibility (WCAG) | Dot (critical), all |
| Geographic filtering | Mike, Sarah |
| "New resident" onboarding | Jordan, (benefits all) |

### Concerns by Category

**Trust & Accuracy**
- Is it the full document or just a summary?
- How do I verify against the original?
- What if information is wrong?

**Discovery & Onboarding**
- How do people find out this exists?
- How do newcomers understand local government?
- Is it intimidating or approachable?

**Operations & Maintenance**
- What happens when source websites change?
- How quickly do updates appear?
- Who is responsible when something breaks?

## Gaps Identified

Based on persona analysis, these areas need attention in PROJECT_CONTEXT.md:

1. **Notification System** — Not currently designed
2. **Vote Tracking** — Schema has events, not votes
3. **Accessibility Requirements** — Not specified
4. **Topic/Issue Tracking** — No persistent topic tagging
5. **Contribution Guide** — No CONTRIBUTING.md
6. **Data Freshness SLAs** — Not documented
7. **Error Correction Process** — No workflow for fixing incorrect data
