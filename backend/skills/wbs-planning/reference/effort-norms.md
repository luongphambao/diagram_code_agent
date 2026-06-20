# WBS effort norms (dev man-days)

Benchmark ranges distilled from ~50 real BnK WBS files. Values are **dev man-days**
(BE + FE/Mobile); the total per leaf ≈ 1.54 × dev under the 10/30/10 ratio model.
Estimate the dev columns only — BA/QC/PM are derived. The live `get_effort_norms()`
tool returns the same table as JSON.

| Feature type | BE | FE/Mobile | phase_type | notes |
|---|---|---|---|---|
| Login / Authentication (web) | 0.5–2 | 0.5–2 | development | login/logout, forgot pw, OTP |
| Login (mobile) | 0–0.5 | 1–2 | development | |
| Registration / Onboarding | 3–4 | 4–5 | development | multi-step, validation |
| Dashboard | 1.5–2 | 1.5–3 | development | |
| CRUD list (sort/filter/export) | 0.75–1.5 | 0.75–3 | development | |
| CRUD detail screen | 2–3.5 | 2–3 | development | |
| RBAC / roles / permissions | 2–4 | 0–2 | development | |
| KYC | 3 | 5 | development | |
| File upload / attachments | 3–4 | 1 | development | |
| Notification framework/adapter | 2 | 0 | development | one-time |
| Notification channel (each) | 1 | 0 | development | email / sms / in-app / whatsapp |
| Real-time chat | 1 | 3 | development | |
| Report / Export / Analytics | 5–11 | 0–8 | development | |
| Payment integration | 1–5 | 0–1 | development | gateway / wallet / deposit |
| 3rd-party / SSO / public API | 1–14 | 0–2 | development | scales with API complexity |
| Admin / user management | 2.5 | 3 | development | |
| Search / filter / builder | 4–6 | 1–4 | development | |
| Workflow / approval engine | 6 | 4 | development | |
| Rule / calculation engine (per rule) | 3–9 | 1–3 | development | |
| Audit trail / change history | 3–3.5 | 1–2 | development | |
| Database design | 1–6 | 0 | design | BE-only, no BA/QC |
| System / architecture / HLA design | 5 | 0 | design | |
| UI/UX design | 0 | 5–20 | uiux | FE/Mobile + PM only |
| Code base / repo setup | 2 | 0–2 | design | |
| Deployment setup (infra/CI-CD) | 3–5 | 0 | design | |
| Monitoring setup (each) | 2 | 0 | design | infra / error / APM |
| Production deploy / app-store / migration (each) | 1 | 0 | deployment | PM = 0 |
| Requirement workshop / BRD | (ba 3–14) | — | requirement | put MD in `ba`; BA + PM only |
| AI: dataset prep | 15 | 0 | development | AI MD ≈ dev |
| AI: fine-tune (SFT) | 15 | 0 | development | |
| AI: model serving / vLLM | 5–6 | 0 | development | |

## Reconciliation examples (verified to the cent)

- Login `BE 0.5, FE 0.5` → dev 1.0 → BA 0.1, QC 0.3, PM 0.14, **total 1.54**
- Feature `BE 2` (dev) → BA 0.2, QC 0.6, PM 0.28, **total 3.08**
- Registration `BE 3.5, FE 5` → dev 8.5 → BA 0.85, QC 2.55, PM 1.19, **total 13.09**
- Setup `BE 3` (design) → PM 0.3, **total 3.3** (no BA/QC)
- Workshop `BA 5` (requirement) → PM 0.5, **total 5.5**
- UI/UX `Mobile 5` (uiux) → PM 0.5, **total 5.5**
- Prod deploy `BE 1` (deployment) → **total 1.0** (PM 0)
