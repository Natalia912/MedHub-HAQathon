# Происхождение данных переносного модуля

`reference/` содержит исторические материалы для проверки происхождения, а не второй движок или актуальный публичный контракт. Действующий контракт упаковки описан в [docs/CONTRACT.md](../docs/CONTRACT.md); нормализация — в [docs/INPUT_CONTRACT.md](../docs/INPUT_CONTRACT.md).

## Закреплённые источники

| Назначение | Версия и локальный материал |
| --- | --- |
| Состав PRIME, семь правил скрининга, порядок дня и базовая подготовка | `df733c43d5ab655ef08036366a44bae04e59182f`: [исходный rules.json](df733c4/spec/rules.json), [описание пакетов](df733c4/clinical/prime_checkup_packages.md) |
| Старый импорт анкеты и экранные примеры | Тот же SHA: [27 полей](df733c4/app/config/fields.py), [sample_inputs.json](df733c4/ml/sample_inputs.json), [исторический README](df733c4/ml/README.md) |
| Current-анкета, сценарный источник | `744d7f79e6872a31572dda9d75269a8a8b7bcd4a`: [30 полей](../reports/scenarios/sources/744d7f79e6872a31572dda9d75269a8a8b7bcd4a/app/config/fields.py), [правила](../reports/scenarios/sources/744d7f79e6872a31572dda9d75269a8a8b7bcd4a/spec/rules.json) |
| Исходный документ проверки | [Scenarios.docx 1.1](../tests/fixtures/Scenarios.docx), [зафиксированные 48 состояний](../tests/fixtures/prime_scenarios.json) |
| Исторические доказательства и новая сверка веток | [Отчёт исходного прогона](../reports/scenarios/REPORT.md), [аудит упаковки](../reports/packaging/source_audit/source_audit.md) |

Main `d52847ad1cfcfab54fcdaec7061bffc93496d283` совпадает деревом со снимком сценариев. Его составы, скрининги, `day_route_order` и `prime_prep` структурно совпадают с `df733c4`. Ветки engine и packages-logic содержат другие реализации; они не включены в runtime. Полный перечень прочитанных SHA, Git blob ID и контрольных сумм находится в [source_audit.json](../reports/packaging/source_audit/source_audit.json).

Пять исторических `fields.py` оставлены как декларативные источники вопросов. Runtime их не импортирует и не строит из них удалённый интерфейс. Исторические `sample_inputs[].screen` и `spec/examples[].expect` описывают ожидаемый экран/подбор той версии, **не результаты анализов и не безошибочный oracle**. Сценарный runner использует отдельно зафиксированные утверждения DOCX и исходные составы пакетов.

## Старые пути внутри неизменённых JSON

Поля `source`, `source_path`, `source_sha`, результаты прежних запусков и их контрольные суммы сохранены. Старый путь — ссылка на происхождение, не команда загрузить файл из соседнего приложения. Пути ниже даны относительно корня переносного `ml/`.

| Историческое обозначение | Где находится материал или реализация сейчас |
| --- | --- |
| `app/engine.py`, `app/intake.py`, `app/selection.py` и другие процедурные модули | [prime_checkup/](../prime_checkup/) — перенесённая реализация; исторические SHA относятся к старым файлам и не пересчитываются под новое размещение |
| `app/data/*.json` | [prime_checkup/data/](../prime_checkup/data/) — активный нормализованный каталог, правила, тестовые слоты и статические fixture |
| `app/config/clinic_fields.py` | [prime_checkup/config/clinic_fields.py](../prime_checkup/config/clinic_fields.py) — необходимые локальные определения вопросов |
| `reference/df733c4/spec/rules.json` или `spec/rules.json:packages/screening` со старым SHA | [reference/df733c4/spec/rules.json](df733c4/spec/rules.json); нормализованный runtime-каталог остаётся отдельным файлом |
| `reference/df733c4/app/config/fields.py:urgent/pregnant` | [историческая схема](df733c4/app/config/fields.py), не обработчик HTTP |
| `spec/CONTRACT.md` без нового двухэтапного дополнения | [исторический predict-контракт](df733c4/spec/CONTRACT.md); приоритет имеет новый [docs/CONTRACT.md](../docs/CONTRACT.md) |
| `Scenarios.docx` в корне старого проекта | [tests/fixtures/Scenarios.docx](../tests/fixtures/Scenarios.docx), байты документа сохранены |
| `reports/scenarios/local_before/`, старые `app/main.py`, `app/static/*`, альтернативные `ml/engine.py`/`ml/router.py` | Намеренно не являются частью переносного runtime; полные ответы и хеши исходных запусков сохранены в [исторических результатах](../reports/scenarios/results.json). Удалённый код доступен по закреплённым GitHub-ссылкам [аудита](../reports/scenarios/sources/AUDIT.md) |

Для service/action ID используются явные исходные соответствия, сохранённые в [catalog_migration.json](../prime_checkup/data/catalog_migration.json) и карте [prime_scenarios.json](../tests/fixtures/prime_scenarios.json). Нельзя приравнивать похожие названия, скрининг и услугу или подменять текущий каталог 17 черновыми записями `prime_catalog`.

## Границы происхождения

Эти файлы не удостоверяют медицинское одобрение, право на оплату, реальную доступность или назначение. Поправка №75 присутствует в сохранённых источниках; это не доказывает актуальность и юридическую проверку всего набора. `ANAMNESIS_DRAFT` не активируется при копировании, а `medical_validated=false` сохраняется. Отдельная опубликованная лицензия на код и данные проекта в проверенных деревьях main/df733c4 не обнаружена; права на эти материалы не объявляются установленными. Найденная в исходном UI лицензия OFL относится к шрифту, который в этот модуль не переносился.
