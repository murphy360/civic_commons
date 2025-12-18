# Civic Commons Roadmap

**Generated:** December 18, 2025  
**Based on:** Persona analysis of 11 user types

This roadmap is derived from analyzing the project against the personas in `/personas/`. Each feature gap is mapped to specific user needs.

---

## ✅ RECENTLY COMPLETED

### Cascading Summary System (December 2025)
Replaced static newsletters with a dynamic, living summary system:

```
Document Added → Event Summary → Daily Summary → Weekly → Monthly → Quarterly → Annual
```

**Key Changes:**
- `newsletters` table replaced with `summaries` table
- Summaries auto-regenerate when new documents arrive
- Completeness tracking shows data availability (0-100%)
- Version history tracks how summaries evolve
- `/newsletters` route now queries `summaries` table
- New `/summaries` route with enhanced UI

**Files Created/Modified:**
- `scripts/init-db.sql` - New `summaries` + `summary_triggers` tables
- `scraper/pipeline/ai/summary.py` - Summary generation logic
- `scraper/pipeline/ai/cascade.py` - Cascade manager
- `scraper/main.py` - Uses cascade system instead of newsletters
- `web/app/newsletters/` - Updated to use summaries table
- `web/app/summaries/` - New dedicated summaries UI

---

## 🔴 CRITICAL: Blocking Issues (Fix Now)

| # | Issue | Personas Affected | Effort | Status |
|---|-------|-------------------|--------|--------|
| 1 | **Worker unhealthy containers** | All (Derek) | Low | ✅ Done |
| 2 | **No CONTRIBUTING.md** | Alex (Developer) | Low | ✅ Done |
| 3 | **No CI/CD pipeline** | Alex, Derek | Medium | ✅ Done |

---

## 🟠 HIGH PRIORITY: Core Value Gaps

| # | Feature Gap | Personas Requesting | Impact | Effort | Status |
|---|-------------|---------------------|--------|--------|--------|
| 4 | **Vote/Roll Call Tracking** | Hal, Maria, Keisha | High | High | ⬜ Todo |
| 5 | **Notification/Alert System** | Sarah, Maria, Keisha, Mike | High | High | ⬜ Todo |
| 6 | **Topic/Issue Tagging** | Keisha, Maria, Hal | High | Medium | ⬜ Todo |
| 7 | **Calendar Export (iCal)** | Sarah, Jordan | Medium | Low | ⬜ Todo |
| 8 | **Print-Friendly Views** | Hal, Dot | Medium | Low | ⬜ Todo |

### Details

**Vote/Roll Call Tracking (#4)**
- Schema has no `votes` table
- Critical for accountability (Keisha: "How did each council member vote?")
- Maria needs this for journalism research
- Hal wants historical voting records

**Notification/Alert System (#5)**
- 4 personas explicitly request this
- Sarah: "I only find out about things after they've already been decided"
- Mike: Needs business-impact alerts
- No subscription mechanism exists in current schema

**Topic/Issue Tagging (#6)**
- Keisha: "Track an issue across time"
- No way to follow a specific topic (e.g., "Ravenna Road development") across meetings
- Requires persistent topic/tag linking between events and documents

---

## 🟡 MEDIUM PRIORITY: UX & Accessibility

| # | Feature Gap | Personas Requesting | Impact | Effort | Status |
|---|-------------|---------------------|--------|--------|--------|
| 9 | **WCAG Accessibility** | Dot (critical), All | High | Medium | ⬜ Todo |
| 10 | **Simple List View** | Dot, Hal | Medium | Low | ⬜ Todo |
| 11 | **Mobile-First Polish** | Sarah, Mike, Jordan | Medium | Medium | ⬜ Todo |
| 12 | **"Family Mode" Filter** | Sarah | Low | Low | ⬜ Todo |
| 13 | **Data Freshness Display** | Amanda, Hal, Maria | Medium | Low | ⬜ Todo |

### Details

**WCAG Accessibility (#9)**
- Dot: "Text is too small, buttons are too small"
- No accessibility requirements currently documented
- Target: WCAG AA compliance
- Includes: large text mode, high contrast, screen reader support

**Simple List View (#10)**
- Alternative to calendar for seniors and those who prefer simplicity
- "Just a list of upcoming events"

**Data Freshness Display (#13)**
- Amanda (city staff): Needs to trust the data
- Show "last updated" timestamps prominently
- Display source health status

---

## 🟢 NICE TO HAVE: Future Features

| # | Feature | Personas | Notes | Status |
|---|---------|----------|-------|--------|
| 14 | **Weekly Email Digest** | Sarah, Mike | Requires email service integration | ⬜ Todo |
| 15 | **Multi-City Federation** | Maria (journalist) | v2 feature, architectural change | ⬜ Todo |
| 16 | **Entity Extraction** | Maria | Names, addresses, dollar amounts from docs | ⬜ Todo |
| 17 | **Public Comment Deadlines** | Keisha | Highlight opportunities for civic participation | ⬜ Todo |
| 18 | **New Resident Onboarding** | Jordan | "How local government works" guide | ⬜ Todo |
| 19 | **Shareable Quote Links** | Maria, Keisha, Hal | Deep links to specific passages | ⬜ Todo |
| 20 | **Gemini Usage Tracking** | Derek (Admin) | Track API calls, tokens, costs in admin dashboard | ⬜ Todo |

---

## 🛠️ DEVELOPER EXPERIENCE

| # | Issue | Affected | Action | Status |
|---|-------|----------|--------|--------|
| 20 | **No `.github/` directory** | Alex, Derek | Add issue templates, PR template, Actions | ⬜ Todo |
| 21 | **No test examples** | Alex | Add sample pytest and Vitest tests | ⬜ Todo |
| 22 | **Driver test mode missing** | Derek | Add `--dry-run` or `--validate` flag | ⬜ Todo |
| 23 | **No Docker images on registry** | Derek | Publish to Docker Hub or GHCR | ⬜ Todo |
| 24 | **Resource requirements undocumented** | Derek | Add min RAM/CPU/storage to README | ⬜ Todo |
| 25 | **Secrets management unclear** | Derek | Document `.env` vs Docker secrets | ⬜ Todo |

---

## 📋 Recommended Sprints

### Sprint 1: Foundation & Stability
- [ ] Fix web/admin health check issues (#1)
- [ ] Create `CONTRIBUTING.md` (#2)
- [ ] Add basic GitHub Actions (lint + build) (#3)
- [ ] Add iCal export endpoint (#7)
- [ ] Add print CSS styles (#8)

### Sprint 2: Accountability Features
- [ ] Design & add `votes` table schema (#4)
- [ ] Implement vote tracking in scrapers (where available)
- [ ] Add "Last updated" timestamps to UI (#13)
- [ ] Design topic tagging schema (#6)

### Sprint 3: Notifications MVP
- [ ] Design subscription schema (`user_subscriptions` table) (#5)
- [ ] Add keyword watch list per user
- [ ] Implement email digest (weekly) (#14)

### Sprint 4: Accessibility & UX
- [ ] WCAG AA audit and fixes (#9)
- [ ] Simple list view alternative (#10)
- [ ] Large text / high contrast mode toggle
- [ ] Mobile UX polish (#11)

---

## Persona Reference

| Persona | Key Concern | Top Feature Requests |
|---------|-------------|---------------------|
| Sarah Chen (Busy Parent) | Time efficiency | Notifications, filters, iCal export |
| Hal Morrison (Civic Watchdog) | Full documents, accuracy | Vote tracking, full-text search, print |
| Marcus Thompson (Council Member) | Cross-entity awareness | Constituent queries |
| Jordan Rivera (New Resident) | Orientation, discovery | Onboarding guide, modern UX |
| Derek Okonkwo (Sys Admin) | Deployment, maintenance | Docker images, monitoring, docs |
| Maria Santos (Journalist) | Research, multi-city | Alerts, quotes, vote tracking |
| Dot Williams (Senior) | Accessibility | Large text, simple view, print |
| Mike Patel (Business Owner) | Business impact, speed | Alerts, geographic filtering |
| Keisha Washington (Activist) | Accountability | Vote tracking, topic tracking, quotes |
| Amanda Foster (City Staff) | Accuracy, freshness | Data freshness SLAs |
| Alex Kim (Developer) | Documentation, DX | CONTRIBUTING.md, tests, CI/CD |

---

## How to Update This Document

1. Complete a feature → Change status from `⬜ Todo` to `✅ Done`
2. Add new features → Add to appropriate priority section
3. Re-prioritize → Move items between sections as needed
4. Reference personas in `/personas/` for detailed user needs
