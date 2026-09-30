# Подключение PRIME без переноса GUI

Канонические JSON-операции: [CONTRACT.md](CONTRACT.md). Входные ответы и происхождение: [INPUT_CONTRACT.md](INPUT_CONTRACT.md). Вся серверная реализация находится в этой папке `ml`; соседние `app`, `spec`, `contract` не нужны.

## Самостоятельный процесс

Из `ml`, после установки зависимостей по [README](../README.md):

```powershell
.venv\Scripts\python.exe -m uvicorn prime_checkup.main:app --host 127.0.0.1 --port 8000
```

Адреса: `http://127.0.0.1:8000/recommend`, `/plan`, `/predict`, `/health`. Swagger: `http://127.0.0.1:8000/docs`. `/` возвращает 404: HTML-тестер намеренно не перенесён. Занятый порт можно заменить, например на 8001, не останавливая другой процесс.

## Router в существующем FastAPI

В корне общего репозитория должна лежать целиком эта папка `ml`, включая `__init__.py`, данные и `prime_checkup`. Установите зависимости из `ml/requirements.txt` в окружение общего приложения. Пример его HTTP-оболочки:

```python
from fastapi import FastAPI
from ml.prime_checkup.router import router as prime_router

app = FastAPI()
app.include_router(prime_router, prefix="/prime")

@app.get("/health")
def health():
    return {"host": True}
```

Получатся `POST /prime/recommend`, `/prime/plan`, `/prime/predict`. Убрать prefix можно только если таких операций ещё нет: не регистрируйте два одинаковых method/path. Router не импортирует самостоятельный main, не запускает второй сервер, не монтирует static и не меняет health владельца. Общая форма ошибок 422 работает и при подключении с prefix — не требуется глобальный exception handler хозяина. Неожиданные ошибки остаются ошибками.

Этот фрагмент реально проверяется отдельным процессом из родительской папки через `python -m ml.tools.smoke_api --mounted-child`; основной запуск проверки — `python -m tools.smoke_api` из ml. Внешний `app/main.py` при упаковке не редактировался. Само подключение к общему GUI ещё не выполнено.

## Что должен сделать frontend Натальи

1. Отправить исходную анкету с явным `input_version=clinic_v2` и context в `/recommend`. Не преобразовывать широкие ответы в диагнозы и неизвестные числа в нули. H0 «никогда» передавать явно по каждому screening_id.
2. Показать рекомендованный package/items, отдельно screening. Редактор заполнить из catalog и package_options; пользователю доступны ID услуг, не внутренние action_id. Сохранить анкету, контекст и `versions.catalog` на клиенте.
3. Отправить в `/plan` patient/context, mode, base_package_id, variant_id, catalog_version; для custom — окончательный selected_procedure_ids, включая пустой массив при пустом выборе. Изменение анкеты требует новой рекомендации.
4. Показать selected_items, разницу с рекомендацией, warnings и клинические пометки независимо от screening_matches. Учитывать status и schedule.status; 200 не всегда означает готовое расписание. При 409 повторить рекомендации и предложить проверить выбор.
5. Показать route как порядок, schedule.route — как тестовые интервалы, after_results — отдельно. Не выводить дату следующего визита, результат анализа или цену, если их нет. Не выдавать candidate скрининга за подтверждение оплаты.

Полные готовые запросы/ответы лежат рядом: [рекомендация](recommend-request.json), [пресет](preset-request.json), [custom](plan-request.json), [пустой выбор](empty-request.json). Там настоящие ID каталога demo-2. Пример custom удаляет `prime_lipids_glucose_group` и добавляет `prime_hepatitis_bc_group`; нехватка слотов не меняет выбор.

Ветка `packages-logic` (`7775fb5`) предлагает иной `POST /recommendations` и иллюстративный маршрут. Это **не алиас** `/recommend`. Ветка `engine` (`c2f3968`) принимает другой выбор по названиям и содержит другую логику. Не подключайте их как замену или второй медицинский движок. Нужна переделка транспортных вызовов frontend по этому контракту либо отдельно согласованный адаптер; в этой поставке такого frontend нет. Сверка веток: [отчёт](../reports/packaging/source_audit/source_audit.md).

## Python API

Из `ml`: `from prime_checkup.selection import recommend_request, plan_request`; обе функции принимают ровно JSON-объект соответствующего HTTP-запроса и возвращают dict. `response_http_status(result)` в том же модуле определяет 200/422/409. Низкоуровневые `recommend(patient, context=None)` и `plan_selection(patient, selection, context=None)` используют тот же движок.

Совместимость: `from prime_checkup.compat import predict`; из корня репозитория — `from ml import predict`. Для фиксированной вымышленной карты: `from prime_checkup.cards import get_completed_case` (waiting/received/reviewed). Эти импорты не запускают тесты, сервер или сеть. В Python-коде владельца используйте единый namespace `ml.prime_checkup`, не смешивайте его с standalone `prime_checkup` в одном процессе.

## Данные и эксплуатационные границы

Данные читаются относительно `prime_checkup/__file__`, без PYTHONPATH и соседних файлов. Нет сессий, хранилища пациентов, AI API, задач отправки, бронирования или расчёта цен. Все поставляемые анкеты и результаты вымышленные. Постоянное `medical_validated=false` сохраняется. Реальная дата следующего визита требует источника назначения/правила; технический fixture карты не назначает её другим пациентам.
