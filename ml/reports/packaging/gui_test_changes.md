# Перенос регрессии без локального HTML-интерфейса

Исходные **156** тестов локального demo-3 перенесены в `ml/tests`. Получилось **154** теста: 131 сохранён, 22 заменены проверками JSON/общего движка/Python-провайдера карты, три проверки только GUI исключены, один тест монтирования `APIRouter` добавлен. Сопоставление всех идентификаторов и SHA-256 файлов находится в [gui_test_changes.json](gui_test_changes.json).

Медицинские ожидаемые исходы не менялись. Для 131 сохранённого метода подтверждено равенство AST после замены пространства имён `app` → `prime_checkup` и пути рабочих данных. Fixture `prime_scenarios.json` совпадает с исходным побайтово. Исходный проект `MedHub-HAQathon` не редактировался.

Фактически выполнено из каталога `medhub-app/ml`:

```powershell
C:\Users\user\Desktop\medhub-app\MedHub-HAQathon\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

**154 теста, 0 ошибок, 0 провалов, 0 пропусков; exit code 0.** Это Python и FastAPI `TestClient`, включая монтирование роутера под `/prime`. Это не проверка запущенного Uvicorn или браузера. Прогон в отдельном окружении упакованного модуля фиксируется отдельно. Воспроизводимая команда с установленными зависимостями: `python -m unittest discover -s tests -v` из `ml`.

## Исключены только три проверки представления

| Исходный тест | Причина и сохранённая проверка |
| --- | --- |
| `test_http.HTTPTests.test_html_escapes_input_catalog_and_result_json` | HTML-рендерера в модуле нет. Структурные ошибки входа и точная передача свободного текста проверяются JSON-тестами |
| `test_clinic_integration.ClinicIntegrationTests.test_form_has_six_sections_profiles_and_css_without_javascript` | Секции формы, ссылки готовых профилей и CSS относятся к удалённому GUI. Все девять импортированных входов продолжают проверяться через оба API |
| `test_completed.CompletedTests.test_result_text_and_serialized_fixture_are_html_escaped` | Карта возвращает данные, не HTML. Состояния, точные тексты, даты и независимость копий сохранены; экранирование выполняет подключаемый интерфейс |

## Замены смешанных GUI/бизнес-тестов

Имена классов и файлов сохранены, кроме отдельно указанного нового теста. Здесь перечислены все 22 замены; полный квалифицированный идентификатор каждого метода есть в JSON.

### `test_http.HTTPTests` — четыре замены

| Старый метод | Новый метод / сохранённый смысл |
| --- | --- |
| `test_normal_rejection_and_json_html_parity` | `test_normal_rejection_and_json_engine_parity`: все профили, остановка подбора и занятый день через `/predict` и общий движок |
| `test_form_error_keeps_values_and_matches_api` | `test_field_errors_match_engine_without_mutating_input`: ошибки полей 422 и неизменность данных вызывающего кода |
| `test_profiles_health_and_whitelisted_debug_pages` | `test_profiles_health_and_native_scheduler_whitelist`: `/health`, профили и пять технических fixture; неизвестный fixture запрещён |
| `test_completed_is_a_fixed_synthetic_fixture` | `test_completed_provider_is_a_fixed_synthetic_fixture`: карта и неназначенное/неотправленное напоминание не меняются после нового расчёта |

### `test_completed.CompletedTests` — пять замен транспорта

Имена методов сохранены. Вместо `/demo/completed` вызывается `cards.get_completed_case()`:

- `test_three_states_have_only_their_fixed_events_and_reminders`: все точные ожидания waiting/received/reviewed, событий, результатов и напоминаний сохранены.
- `test_history_preserves_only_known_year_and_unknown_outcomes`: 2025 остаётся годом, полная дата отсутствует, результат и просмотр неизвестны.
- `test_default_and_switching_do_not_mutate_shared_fixture`: переключение не меняет fixture; дополнительно проверено изменение вложенной возвращённой копии.
- `test_unknown_case_is_rejected_before_loading_a_file`: Python `ValueError` заменяет HTTP 404 удалённой страницы; загрузчик по-прежнему не вызывается.
- `test_history_and_result_states_never_change_the_new_plan`: вызовы провайдера между настоящими запросами `/predict` не меняют состав, карту и напоминание.

### `test_clinic_integration.ClinicIntegrationTests` — шесть замен

| Старый метод | Новый метод / сохранённый смысл |
| --- | --- |
| `test_pregnant_mammography_html_row_keeps_both_independent_annotations` | `test_pregnant_mammography_json_keeps_both_independent_annotations`: клиническое ограничение и совпадение со скринингом присутствуют одновременно |
| `test_html_and_json_share_normalized_business_result` | `test_engine_and_json_share_normalized_business_result`: полный бизнес-результат Python и `/predict` совпадает |
| `test_nine_rendered_imported_forms_submit_their_actual_successful_controls` | `test_nine_imported_recommendations_match_the_shared_engine`: девять неизменённых input через `/recommend`; формат df733c4 сохраняется |
| `test_form_errors_preserve_values_and_free_text_is_escaped` | `test_json_preserves_free_text_and_reports_field_errors`: свободный текст остаётся данными, невозможная дата даёт 422, исходный запрос не изменяется |
| `test_new_answers_never_generate_results_or_mutate_fixed_cards` | То же имя: три карты проверяются Python-провайдером, новые анкеты не создают результаты или даты напоминания |
| `test_unknown_checkbox_value_is_preserved_and_escaped_on_error` | `test_unknown_answer_code_is_rejected_by_json`: неизвестный код не исчезает молча и получает ошибку поля |

### `test_two_step_http.TwoStepHTTPTests` — семь замен

| Старый метод | Новый метод / сохранённый смысл |
| --- | --- |
| `test_recommendation_does_not_search_and_preserves_json_html_parity` | `test_recommendation_does_not_search_and_preserves_json_engine_parity`: поиск слотов запрещён на первом этапе, каталог и варианты возвращаются |
| `test_actual_preset_and_custom_forms_submit_validated_hidden_patient` | `test_preset_and_custom_json_revalidate_patient_and_reconstruct_composition`: оба режима восстанавливают состав и повторно валидируют пациента |
| `test_custom_removal_and_addition_have_html_json_parity` | `test_custom_removal_and_addition_have_json_engine_parity`: окончательный выбор, дедупликация, разница с рекомендацией и неизвестная цена сохранены |
| `test_empty_unknown_and_stale_selection_preserve_checkboxes_and_errors` | `test_empty_unknown_and_stale_selection_preserve_input_and_errors`: пустой выбор, неизвестные ID и устаревшая версия дают прежние бизнес-исходы и 422/409 |
| `test_service_review_is_editable_but_global_urgent_has_no_editor` | `test_service_review_can_be_removed_but_global_urgent_still_stops`: удаление услуги снимает только её ограничение; urgent по-прежнему останавливает план |
| `test_hidden_metadata_is_not_trusted_and_html_stays_escaped` | `test_client_metadata_is_not_trusted_and_free_text_stays_data`: клиентский status не принимается, текст остаётся данными JSON |
| `test_wrong_hidden_context_and_patient_types_are_errors_not_template_failures` | `test_wrong_context_and_patient_types_are_structured_errors`: неправильные типы пациента и контекста дают общий ответ 422 |

Сохранённая фабрика `clinic()` вынесена в `tests/helpers.py`; зависимости от HTML-parser и старого обработчика формы больше нет. Пути `reference` и рабочих данных разрешаются внутри `ml`.

Новый `test_router_mount.RouterMountTests.test_prefixed_mount_matches_standalone_without_changing_host_routes` проверяет включение роутера под `/prime`, сохранение маршрута приложения-хозяина, совпадение обоих этапов со standalone API и общий формат 422 при повреждённом JSON.
