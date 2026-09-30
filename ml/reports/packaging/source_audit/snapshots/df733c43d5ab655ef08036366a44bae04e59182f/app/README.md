# Green Clinic questionnaire draft

Run from the repository root using `run-windows.sh` (Git Bash on Windows),
then open http://localhost:8000. The existing launcher installs the repository's
dependencies, so its installation step may need internet access.
The form itself uses only local assets and the local `/fields` endpoint.

The form ends with an editable answer review and then the checkup program
(«Показать программу»). The program is computed in the browser from
`spec/rules.json` (served at `/rules`): free state screening (order ДСМ-174/2020),
the PRIME package by sex and full age (6 packages, as on primegc.kz), extras
based on answers, a one-day route, preparation and a summary for the doctor.
It does not call `/predict` or persist answers; refreshing clears them.

## Extending the form

Edit `app/config/fields.py`: `STEPS` (titles, sidebar, optional steps; `*_m`
variants for men) and `FIELDS`. Types: `number`, `date`, `text`, `textarea`,
`select`, `boolean`, `multiselect`. Options are `[value, label]` or
`[value, label, "F"|"M"]` for sex-specific options. `show_if` supports `sex`,
`age_min`/`age_max` (full years from `birth_date`), `adult` and
`when: [[field, op, value]]` with `eq`, `ne`, `in`, `gt`, `has_any`, `lacks`.
`options_from` shows only options picked in another field, `exclusive` makes a
«none» option clear the others, `stop` stops the questionnaire (call 103),
`contract` + `maps_to` rename and translate a value for the payload.
`collectInput()` in `app/static/app.js` builds the payload (see `spec/CONTRACT.md`).
A step with no visible questions is skipped (e.g. men's health for a child).

## Assets and checks

- Colors and typography follow the supplied palette and https://greenclinic.kz/ru/.
- Local logo: https://greenclinic.kz/wp-content/uploads/2024/01/logo-footer.svg.
- Geologica: https://github.com/google/fonts/tree/main/ofl/geologica;
  license included in `static/fonts/OFL.txt`.
- `preview-desktop.png` and `preview-mobile.png` show the initial screen.
- Verified with the existing installed Playwright/Chromium: required fields,
  numeric bounds, urgent symptoms, pregnancy visibility, conditional cleanup,
  nested serialization, editing, skip/reset, child flow, mobile overflow,
  schema-load failure/retry, no prediction requests, and no JavaScript errors.
- 30.09.2026: all 12 cases in `spec/examples.json` match (free screening and
  package); desktop and 390px mobile checked with Playwright, no errors, no
  horizontal scroll.
- `node --check app/static/app.js`, `python contract/predict_contract.py`, and
  `git diff --check` passed.
