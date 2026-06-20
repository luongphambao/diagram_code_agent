# BnK WBS template layout (for reference)

The export clones `data/wbs_template.xlsx` and rebuilds the data sheets. You don't
write Excel yourself — the tools do — but understanding the structure helps you
produce sensible inputs. The deliverable keeps **5 sheets**.

## `0. How to use` — static
Kept verbatim. Explains the file structure + highlights.

## `2. WBS` — the core (formula-driven)
Columns: `# (B) | Ref. Code (C) | Features (D) | Description (E) | Total (F) |
BE Coding (G) | FE/Mobile Coding (H) | Requirement Analysis (I) | Testing (J) |
Project Management (K) | Remark (L)`.

Row types and where text goes:
- **Phase** (I / II / III): name in col C. Roll-up = SUM of its module rows.
- **Module** (I.A / II.A): name in col C. Roll-up = SUM of its leaf block.
- **Sub-module group** (optional, light row): name in col C.
- **Leaf** (a feature): seq# in col B, `Ref.Code` in col C is a formula
  `=CONCATENATE($D$2&"-",B<row>)`, name in col D.

Only **BE (G)** and **FE/Mobile (H)** are hand numbers (plus **RA (I)** for
requirement rows). `Total`, `Requirement Analysis`, `Testing`, `PM` and all roll-ups
are **formulas** that reference `4. Master Data` ratios — Excel recomputes them on
open. `D2` holds the Project Code; `B3` the title `WBS OF <NAME>`.

## `1. Effort` — per-module summary
One row per phase + module, names and role MDs pulled from `2. WBS` via VLOOKUP;
USD columns multiply by the `4. Master Data` rate card. TOTAL row sums the phase rows.
Regenerated to match the actual module set.

## `3. Delivery Plan` — Gantt + resources + milestones (dynamic)
- Header: row 3 = month labels (each spanning 4 week-columns), row 4 = sprints (each
  spanning 2), row 5 = `W1..Wn`. The number of month/sprint/week columns scales to the
  project duration — it never runs short of months.
- One row per phase + module with a Gantt bar across its active weeks
  (waterfall-allocated by effort, or explicit `start_week`/`end_week`).
- Resource Planning rows + the 5-milestone table follow below the module grid.

## `4. Master Data` — ratio drivers (static structure)
`C4` = PM ratio (on dev+ba+qc), `C5` = BA ratio (on dev), `C7` = QC ratio (on dev).
The export writes these from the WBS `ratios` so the live formulas and the summary
agree. Default 0.10 / 0.10 / 0.30 (BnK template ships PM = 0.05).
