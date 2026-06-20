# Condensed WBS skeletons (few-shot, from real BnK projects)

Use these as shape references — phase/module breakdown + how leaves map to phase_type.
Numbers are dev man-days (BE/FE); BA/QC/PM are derived.

## Example A — Clinic Management (Web + Mobile), ~82 MD

```
I  SET UP & INSTALLATION
   I.A Solution Design
       - Odoo Deployment Setup            design   BE 3
   I.B Requirement Gathering & UI-UX
       - Detailed Requirement Analysis    requirement  BA 5
       - UI/UX Design                     uiux     Mobile 5
II DEVELOPMENT
   II.A Web Development
       - Login and authentication         development  BE 2
       - Manage patients/records (×3)      development  BE 1–5
       - Director comprehensive view      development  BE 5
   II.B Mobile Development
       - Login and authentication         development  BE 0.5 / Mobile 2
       - Manage sale orders               development  BE 0.5 / Mobile 3
       - Director view                    development  BE 1 / Mobile 5
III TESTING & DEPLOYMENT SUPPORT
   III.A Solution Qualification
       - Fix SIT/UAT Issues               support  BE 5 / Mobile 2.5
   III.B Deployment & Maintenance
       - Production Deployment            deployment  BE 1
       - Mobile App Deployment            deployment  BE 1
       - Post Golive Support              design   BE 5
```

## Example B — Lending platform (template), ~132 MD

```
I  SET UP & INSTALLATION
   I.A Solution Design: Database Design, System Design, Data Security,
       UI/UX Design (uiux), Code Base Setup        (mostly design, BE 1–10)
   I.B System Operation: Deployment Setup, Infra/FE/APM Monitoring  (design, BE 2–5)
II DEVELOPMENT
   II.A Web Portal  → groups: Common Module, Account Module, ...
   II.B Mobile Application → groups: Common Module, ...
   II.C Core Service → groups: Notification (adapter + per-channel), 3rd-party
        Integration (SSO, Payment Gateway, IDP, chat)
III TESTING & DEPLOYMENT SUPPORT
   III.A Solution Qualification: Fix SIT/UAT (support)
   III.B Deployment & Maintenance: Prod deploy/app-store (deployment), Post Go-live
```

## Example C — AI build (e.g. detection/voicebot)

Add an AI/Models module under DEVELOPMENT with leaves like Dataset Preparation (15),
Fine-tuning/SFT (15), Prompt Optimization (10), Model Serving/vLLM (5–6), per-rule
detection engines (3–6 BE each) — all `phase_type=development` (AI MD counts as dev).
