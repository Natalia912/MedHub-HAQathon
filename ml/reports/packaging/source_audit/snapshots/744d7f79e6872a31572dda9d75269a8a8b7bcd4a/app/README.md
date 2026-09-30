# Green Clinic questionnaire draft

Run from the repository root using `run-windows.sh` (Git Bash on Windows),
then open http://localhost:8000. The existing launcher installs the repository's
dependencies, so its installation step may need internet access.
The form itself uses only local assets and the local `/fields` endpoint.

This draft ends with an editable answer review, as requested. It does not call
prediction services, persist answers, or produce medical recommendations.
Refreshing the page clears the answers. The backend serves `/`, `/static`,
`/fields`, and `/health`. The old prediction route and offline recording/cache
implementation have been removed. The model contract must be updated before
integrating checkup results. The root launcher still prints `DEMO_MODE`, but
this form no longer uses it.

## Extending the form

Edit `app/config/fields.py`. Each field has a contract key, Russian label, type,
and zero-based step (0–5). Supported types: `number`, `date`, `text`, `select`, `boolean`, and
`multiselect`. Options are `[contract_value, display_label]` pairs. Use `required`,
`min`, `max`, `hint`, `default`, and `show_if` for validation and presentation.
Dot-separated keys serialize to nested objects, such as `last_screening.scr_breast`.
`collectInput()` in `app/static/app.js` builds the future integration payload.
Only values defined in `spec/CONTRACT.md` are included; broader questionnaire
suggestions without contract values are not added.

Urgent symptoms stop progression immediately. The triggering answer remains
editable. Conditional pregnancy and screening answers are removed when they
no longer apply. Optional questions can remain blank; skipping the last step
clears that step's answers. Steps 3–5 can each be skipped independently.

## Contract update (30 September 2026)

- The required `birth_date` replaces the year-only input; `birth_year` is derived
  from its ISO date string. The 1920–2025 birth-year limits remain in effect.
- `conditions`, free-text health history, smoking, work exposure, expanded family
  history, reproductive health, and preparation questions are included.
- `complaints` has been removed. `urgent` remains required and stops the flow.
- With user approval, `registered` stays a separate explicit diagnosis checklist;
  broad conditions do not automatically imply a registered diagnosis.
- With user approval, `discharge`, `dysuria`, `anesthesia_reaction`,
  `blood_thinners`, `allergy`, and `companion` use `yes` / `no` / `unsure`.
- Optional numbers and booleans preserve explicit `0` and `false` values.
- Sex-specific answers are cleared when sex changes. Smoking and screening
  inputs serialize as nested objects. Text is escaped on the review screen.

## Assets and checks

- Colors and typography follow the supplied palette and https://greenclinic.kz/ru/.
- Local logo: https://greenclinic.kz/wp-content/uploads/2024/01/logo-footer.svg.
- Geologica: https://github.com/google/fonts/tree/main/ofl/geologica;
  license included in `static/fonts/OFL.txt`.
- `preview-desktop.png` and `preview-mobile.png` show the initial screen.
- Verified with the existing installed Playwright/Chromium: six-step female/male
  flows, required dates and derived year, numeric bounds and decimal smoking
  values, urgent symptoms, independent conditions/diagnoses, conditional cleanup,
  nested serialization, explicit zero/false values, editing, per-step skip/reset,
  child flow, escaped free text, mobile overflow, schema-load failure/retry,
  removed prediction route, no prediction requests, and no JavaScript errors.
- `node --check app/static/app.js`, `python contract/predict_contract.py`, and
  `git diff --check` passed.
