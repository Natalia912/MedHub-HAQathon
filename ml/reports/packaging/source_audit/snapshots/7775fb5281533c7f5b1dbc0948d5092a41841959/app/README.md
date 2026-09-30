# Green Clinic questionnaire draft

Run from the repository root using `run-windows.sh` (Git Bash on Windows),
then open http://localhost:8000. The existing launcher installs the repository's
dependencies, so its installation step may need internet access.
The form itself uses only local assets and the local `/fields` and
`POST /recommendations` endpoints.

After reviewing their answers, users select “Подобрать программу”. The Python
engine reads `spec/rules.json` and returns the package, applicable free screenings,
questionnaire-based additions, exclusions and preparation. This separate endpoint
was authorized without changing the ML contract or calling the model.
Answers are sent to the local server, processed in memory and not persisted.
Responses use `Cache-Control: no-store`; refreshing the page clears the answers.
The root launcher still prints `DEMO_MODE`, but this app does not use it.

The request uses the form's nested JSON shape. Required fields are `sex`,
`birth_date`, and `urgent`; `checkup_year` defaults to the current year. The server
validates fields from `app/config/fields.py`, derives the birth year itself and
discards answers to hidden questions. Invalid requests return HTTP 422 with a
Russian `error` message. Selection follows the age-by-year convention explicitly
defined in the current `rules.json` for package and screening predicates.
The draft `spec/CONTRACT.md` describes a different completed-age convention for
packages; that convention is not used by this separately authorized rules endpoint.
The child's age selects the child package; `for_child` does not override age.
The default child package uses `exams`/`name_mini`; the rules provide no predicate
for automatically selecting the extended child variant.

Urgent symptoms produce a red flag and no package. Possible pregnancy removes
CT, mammography and X-ray and preserves a doctor-review message. Registered
diagnoses, risk factors and repeat intervals control screening eligibility.
Free and paid overlapping services remain visible separately. Additions are
deduplicated, and draft clinic recommendations retain doctor-validation labels.
Prices remain unknown where the rules specify `null`.
The UI disables repeat submissions during loading, times out after 20 seconds,
allows retry without losing answers and clears old results when answers are edited.
Successful selection opens a separate results screen with the same recommendation
contents. “Вернуться к ответам” returns to the editable review with answers intact.
“Продолжить с этим пакетом” opens a separate “Маршрут на один день” screen.
The server groups only the selected package's examinations into an illustrative
day itinerary (`app/itinerary.py`). Times, durations and room numbers are generic
demo data, clearly labeled in the UI; no appointment is booked. Free screenings
and extra services are not silently added to the package itinerary. Users can
return to the recommendation or change answers; resubmission builds a fresh route.
Preparation from the existing rules is displayed in expanded, highlighted cards
beside the relevant itinerary stops. Advance and previous-day preparation also
appears above the itinerary; after-procedure guidance appears at the final stop.
Only instructions matching the selected package are included, preserving answer
conditions such as blood-thinner use. Demo times are not preparation deadlines.

## Extending the form

Edit `app/config/fields.py`. Each field has a contract key, Russian label, type,
and zero-based step (0–5). Supported types: `number`, `date`, `text`, `select`, `boolean`, and
`multiselect`. Options are `[contract_value, display_label]` pairs. Use `required`,
`min`, `max`, `hint`, `default`, and `show_if` for validation and presentation.
Dot-separated keys serialize to nested objects, such as `last_screening.scr_breast`.
`collectInput()` in `app/static/app.js` builds the server request payload.
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
- Engine tests: `python -B -m unittest app.test_recommendations` (synthetic data).
- Browser checks with an existing Playwright installation and running server:
  `node app/check_browser.cjs <path-to-playwright-core>`.
  Covers loading, result rendering, request data, mobile overflow, failure/retry,
  editing, urgent API responses and invalid requests. Writes result screenshots
  to `app/recommendation-desktop.png` and `app/recommendation-mobile.png`.
- `node --check app/static/app.js`, `python contract/predict_contract.py`, and
  `git diff --check` passed.
