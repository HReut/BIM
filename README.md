# BIM — Model Health Board

The first module of a BIM SaaS platform: automated QA/coordination checks on
Revit models, reflected in a Health Board available on the web, scoped by
role — **project → discipline → model**, with permissions on top.

**Live demo (sample data):** https://claude.ai/artifact/91AbAkYzd5euPEGZbUxuvY
— use the "מציג כ" (viewing as) selector in the header to see the same
project through each of the four roles.

## Why this shape

No ACC/Forma license is available — only Revit 2027 locally — so there is no
cloud API to pull model data from. The pipeline is built around that
constraint, and around two things a real project actually needs that a
single-model demo doesn't:

1. A project is a set of **disciplines** (architecture, structure, HVAC,
   electrical, plumbing, landscape, ...), each of which can hold several
   **models** — not one model.
2. Different people need different slices of the same data — a designer
   shouldn't see every discipline's coordination detail, a PM doesn't need
   per-check drill-down. This is meant to become a real multi-tenant SaaS
   platform, so the **role/permission model is designed into the schema now**
   rather than bolted onto a dashboard later — see [Roles & permissions](#roles--permissions).

```
Revit 2027 (local, one button per model)         Web
┌───────────────────┐   JSON   ┌────────────┐   fetch   ┌──────────────────┐
│ pyRevit script      │ ──────▶ │  project    │ ──────▶  │  Health Board     │
│ (one per model,     │  merge  │  tree file  │          │  dashboard        │
│  DISCIPLINE_ID/     │         │  (all       │          │  (role-scoped     │
│  MODEL_ID set)       │        │  models,    │          │  drill-down:      │
└───────────────────┘          │  roles,     │          │  project→disc→   │
                                 │  config)    │          │  model)           │
                                 └────────────┘           └──────────────────┘
```

- **Extraction** (`extraction/pyrevit/qa_extract.py`) — runs inside pyRevit
  against the open document, computes as many of the 28 QA checks as it can
  for *that* model, and merges one run into its place in the shared tree
  file (keyed by `DISCIPLINE_ID` / `MODEL_ID`, set per model deployment at
  the top of the script).
- **Schema** (`schema/health-report.schema.json`) — the contract between the
  extraction script and the dashboard: one project (with its BEP `config`),
  `roles[]`, `checkDefinitions[]`, and `disciplines[]` → `models[]` → each
  model's chronological `history[]`.
- **Sample data** (`sample-data/health-history.json`) — a synthetic project
  ("Sample Tower") with 6 disciplines and 7 models, 14 runs each, with
  deliberately varied trajectories — including a few planted failures
  (a wrongly-named HVAC model file, a missing link, a Base Point moved
  mid-project) so the checks that catch real problems have something to
  catch.
- **Dashboard** (`dashboard/health-board.html`) — published as a Claude
  Artifact (see link above). Three drill-down levels, each with a hero
  score + meter, a status-breakdown strip, a card grid (grouped by category
  at the model level), and a trend chart with hover tooltip and a table
  fallback — all filtered by the active role.

## Roles & permissions

There's no real authentication yet — the dashboard's role switcher
simulates what the SaaS platform's login would enforce, so the permission
*model* can be designed and demoed now without building auth infrastructure
first. Four roles, defined in `roles[]` in the schema:

| Role | Scope | Detail |
|---|---|---|
| מנהל BIM (BIM Manager) | every discipline | every check |
| מתאם מערכות (Systems Coordinator) | every discipline | coordination checks only |
| מנהל פרויקט (Project Manager) | every discipline | scores/status only, no per-check drill-down |
| מתכנן (Designer) | their assigned discipline only | every check, for that discipline |

`scope` controls which disciplines a role can reach at all (a designer
switching roles lands directly on their assigned discipline — there's no
project-wide view for them). `detail` controls what a model page shows:
`full` (everything, grouped by category), `coordination` (only
`categoryGroup: "coordination"` checks), or `summary` (hero score only, no
check grid). Both are enforced client-side in `dashboard/health-board.html`
— real enforcement belongs in a backend once one exists; this is the UX and
data model that backend would sit behind.

## Project config

BEP-derived rules that config-driven checks are evaluated against live in
`project.config` in the schema (naming patterns, expected worksets, expected
links per discipline, the reference discipline for levels/grids/coordinates).
Today it's authored by hand once per project, both in the sample data and
mirrored in `PROJECT_CONFIG` at the top of `qa_extract.py`. In the SaaS
platform this becomes a settings page a BIM Manager edits per project instead
of a constant a developer edits per deployment.

## Check catalog (28 checks)

| Category | Checks |
|---|---|
| קואורדינציה והקמה (Coordination & Setup) | ACC/Forma access\*, model in cloud\*, all models in cloud\*, model naming, coordinates acquired, Copy/Monitor levels + match, Copy/Monitor grids + match, worksets per BEP, links loaded, links on correct workset, shared coordinates, base point integrity, units consistency |
| התקדמות מידול (Modeling Progress) | modeling progress %, duplicate/overlapping elements, days since last sync, worksharing display name set |
| Model Cleanliness / Worksharing / Rooms & Spaces / Families / Views & Sheets | the original 8 model-hygiene checks (warnings, workset1 elements, unplaced rooms, duplicate family types, view template coverage, views not on sheets, model groups) |
| תיעוד (Documentation) | sheet naming compliance |
| Performance | central file size |

\* Marked `status: "coming_soon"` — needs the ACC/Forma API, which there's
no license to verify against yet. These render as a muted "בקרוב" badge
instead of a scored card, and are never counted toward the health score, so
adding real ACC access later is additive rather than a rescoring event.

Coordination checks that only make sense for a *non-reference* discipline
(coordinates acquired, both Copy/Monitor pairs, both match checks) are
tagged `excludeReference: true` and skipped entirely for models in
`project.config.referenceDiscipline` (architecture, here) — they'd be
comparing that model against itself.

### Implementation status in `qa_extract.py`

Not every check has real Revit API code behind it yet:

- **Implemented**: the original 8, plus naming convention, worksets-per-BEP,
  sheet naming, duplicate elements (bounding-box heuristic, capped to a few
  clash-prone categories), modeling progress (element count vs. a
  placeholder target), sync recency (file mtime proxy), worksharing display
  name (presence check), units consistency, links loaded, links on correct
  workset.
- **Stubbed** (`return None` — the check simply doesn't appear on the
  dashboard until implemented): `coordinates_acquired`,
  `copy_monitor_levels`, `levels_match`, `copy_monitor_grids`,
  `grids_match`, `shared_coordinates`, `base_point_integrity`. Each needs
  either the linked reference model opened via
  `RevitLinkInstance.GetLinkDocument()` and its Levels/Grids compared, or
  (for base point integrity specifically) a persisted baseline from an
  earlier run — none of this has been run against a live Revit session, so
  it's left honest rather than guessed at.

Thresholds (`good`/`warn`/`crit`, or `goodMin=warnMin=critMin=1` for a
boolean pass/fail) live in `checkDefinitions` inside the schema and are
duplicated in `qa_extract.py` — keep the two in sync when tuning.

## Score aggregation

- **Model score** — the average of its available checks' individual 0–100
  scores (`coming_soon` and unimplemented-stub checks are excluded, not
  counted as failures).
- **Discipline score** — the average of its models' *latest* score.
- **Project score** — the average of its disciplines' scores (each
  discipline weighted equally, regardless of how many models it has).

Trend lines at the discipline/project level average their children's scores
**by run index**, not by date — it assumes every model in a discipline is
checked on roughly the same cadence (true for the sample data). A real
deployment with staggered run schedules per model would need date-bucketed
aggregation instead.

## Running the extraction script

1. Install pyRevit and confirm it supports Revit 2027 against the current
   [pyRevit release notes](https://github.com/pyrevitlabs/pyRevit) — that
   compatibility isn't verified here.
2. Edit `PROJECT_CONFIG` at the top of `extraction/pyrevit/qa_extract.py`
   once per project (naming patterns, expected worksets/links, reference
   discipline), then set `DISCIPLINE_ID` / `DISCIPLINE_LABEL` / `MODEL_ID` /
   `MODEL_LABEL` per model (a copy of the script per model, or read them
   from a config/parameter if you want one script shared across buttons).
3. Wire it into a pyRevit extension button (or run it once via pyRevit's
   Script Executor / RevitPythonShell) with that model open.
4. It merges a run into `sample-data/health-history.json` next to this repo,
   creating the discipline/model entry the first time that model reports in.
   Commit that file, or point `tree_path` in the script at wherever the
   dashboard reads from.

## Status

- [x] Schema + roles/permissions + project config + 28-check catalog +
      multi-discipline sample data + role-scoped drill-down dashboard
- [ ] Real extraction run against a Revit 2027 model (needs local testing —
      not something this environment can do)
- [ ] Cross-model checks (Copy/Monitor, levels/grids match, shared
      coordinates, base point integrity) — needs verifying the linked-document
      API against a live Revit session
- [ ] ACC/Forma-dependent checks — needs a license
- [ ] Real authentication behind the role switcher
- [ ] Live updates: wire the dashboard to a shared data store (e.g. an
      Artifact runtime capability) so a new pyRevit run updates the board
      without a manual republish
- [ ] Discipline-specific checks beyond the shared 28 (duct/pipe clash
      counts for HVAC/plumbing, panel schedule completeness for electrical, ...)
- [ ] Multi-project support (today's schema is one project per tree file)

## Repo layout

```
schema/health-report.schema.json     JSON Schema: project(+config) → roles[] → checkDefinitions[] → disciplines[] → models[] → history[]
sample-data/health-history.json      Synthetic 6-discipline, 7-model, 28-check demo dataset
extraction/pyrevit/qa_extract.py     pyRevit extraction script (one model per deployment)
dashboard/health-board.html          Dashboard source (published as an Artifact)
```
