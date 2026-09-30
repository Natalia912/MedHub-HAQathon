# PRIME — автономная серверная поставка

Процедурный конструктор: анкета → рекомендация PRIME и отдельные скрининги → окончательный выбор услуг → ограничения, порядок и деморасписание. Python/FastAPI, без GUI, ML/LLM, БД, записи в клинику и отправок. `demo=true`, `medical_validated=false`.

В этой папке находятся все исходники, данные, закреплённые источники, тесты и сценарии. Соседние app/spec/contract и старое окружение не требуются. Основное описание — [techdock.md](techdock.md), [контракт](docs/CONTRACT.md), [интеграция](docs/INTEGRATION.md).

## Установка и запуск (PowerShell)

Проверено с Python 3.12.1. Из указанной папки:

```powershell
Set-Location 'C:\Users\user\Desktop\medhub-app\medhub-app\ml'
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn prime_checkup.main:app --host 127.0.0.1 --port 8000
```

Swagger: http://127.0.0.1:8000/docs. API: POST `/recommend`, `/plan`, `/predict`; GET `/health`. Главной HTML-страницы нет. Если 8000 занят прежним тестером, используйте `--port 8001` и соответствующий URL. Активация venv и изменение ExecutionPolicy не нужны.

Для проверок дополнительно:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m prime_checkup.compat
.venv\Scripts\python.exe -m tools.run_scenarios
.venv\Scripts\python.exe -m tools.verify_package --label local
```

Последняя команда объединяет регрессию, шесть legacy-профилей, все 48 состояний, реальный временный Uvicorn и подключение router к отдельному FastAPI. Она сама выбирает свободный localhost-порт, останавливает только свой процесс и сохраняет результат в `reports/packaging`. Scenario runner использует TestClient; S25 вызывает реальный планировщик отдельно. DOCX разобран стандартными zipfile/XML, дополнительный python-docx не требуется. Нет зависимости от Jinja2/python-multipart.

## Проверка вручную за пять шагов

1. Запустите сервер и откройте `/docs` либо используйте curl.exe ниже.
2. POST `/recommend` из `docs/recommend-request.json`: basic/male, 14 услуг, расписание not_run.
3. POST `/plan` из `docs/preset-request.json`: тот же пресет и полный демомаршрут.
4. POST `/plan` из `docs/plan-request.json`: custom, явное исключение/добавление, выбор сохранён даже при infeasible.
5. POST `/plan` из `docs/empty-request.json`: needs_input без маршрута. Смена catalog_version на устаревшую даёт 409; urgent=chest_pain останавливает подбор.

```powershell
curl.exe --fail-with-body -H "Content-Type: application/json" --data-binary "@docs/recommend-request.json" http://127.0.0.1:8000/recommend
curl.exe --fail-with-body -H "Content-Type: application/json" --data-binary "@docs/preset-request.json" http://127.0.0.1:8000/plan
```

Каталог и стабильные ID: `prime_checkup/data/demo_catalog.json`, миграция ID рядом. Активные правила: `demo_rules.json`, `screening_rules.json`; связи со скринингами — `screening_links.json`; технические длительности/слоты — `prime_slots.json`. Их изменение требует согласования оснований, обновления версий и регрессии. Границы 40 лет, нераскрытые группы, нулевой буфер и демодлительности не являются медицинской валидацией.

В изученных материалах не обнаружены реальные результаты скрининга: годовая история взята из синтетического примера, карта waiting/received/reviewed демонстрирует вымышленные состояния. Её Python-provider и fixture перенесены, HTML-страница исключена. Обычные планы не получают результатов или даты напоминания.

Отдельно сохранены [предыдущий отчёт врачу](reports/scenarios/REPORT.md) и [проверка упаковки](reports/packaging/REPORT.md). Предыдущие результаты не заменяются новым прогоном. Вопросы врачу и выключенный scope S18 остаются открытыми. При упаковке commit/push/deploy не выполняются; содержимое для передачи ограничено этой папкой, `.venv` и кеши исключены.
