# Task: global-error-handler

- Дата: 2026-10-06
- Проект: content-fabric
- Ветка: feature/content-fabric
- Статус: done

## Задача
Добавить глобальный обработчик ошибок бота: исключения из хендлеров команд
должны логироваться, фиксироваться в БД (видно в /status) и получать короткий
ответ пользователю вместо дефолтного поведения aiogram.

## Требования
- Единая точка обработки через `dp.errors` (aiogram 3.28), без try/except в каждом хендлере
- Лог с полным traceback; детали события в БД обрезаны до 300 символов (секреты не утекают)
- Короткий ответ пользователю (текст на английском, как остальные ответы бота)
- Обработчик сам не поднимает исключений (запись в БД и ответ — под try/except)
- `CancelledError` не перехватывается (shutdown не ломается)
- Scheduler-циклы не трогать — они обрабатывают ошибки самостоятельно
- Рассылку админам через TelegramAlerter НЕ добавлять (решение пользователя: минимальный вариант)

## Ограничения
- aiogram можно импортить только вне `core/` (test_architecture.py: запреты для core/pipeline.py и core/factory.py)
- Новый модуль — в `news_bot/bot/`

## Acceptance criteria
- [x] Исключение в любом хендлере команды: лог `unhandled_error` + traceback, событие `error` в `bot_stats`, ответ пользователю, `return True`
- [x] Отказ БД или Telegram при обработке ошибки не поднимает исключение из обработчика
- [x] Апдейт без message/callback_query обрабатывается без падения
- [x] Детали события в БД ≤ 300 символов
- [x] Тесты покрывают все ветки обработчика
- [x] `uv run pytest` (эквивалент `.venv/bin/python -m pytest`) — новые тесты зелёные

## Изменяемые файлы
- `news_bot/bot/error_handler.py` (новый)
- `news_bot/main.py` (регистрация обработчика)
- `news_bot/tests/test_error_handler.py` (новый, 7 тестов)
- `ARCHITECTURE.md` (подраздел «Глобальный обработчик ошибок бота»)

## Итог
Сделано по плану (режим plan mode, план одобрен пользователем; выбран минимальный
вариант уведомлений — без рассылки админам). `dp.errors`-обработчик в
`bot/error_handler.py`, регистрация в `main.py` после `include_router`.

Отличия от плана: тестовое построение апдейта — через `Update.model_construct`
(план предполагал MagicMock; `ErrorEvent` в aiogram — pydantic-модель и валидирует
`update` как настоящий `Update`). Ожидание в тесте обрезки учитывает префикс
`ValueError: ` в деталях.

Прогон: 232 passed, 1 skipped, 1 deselected; 1 предсуществующий провал
`test_loader.py::test_factory_defaults_from_yaml` — падает и на чистом дереве
(локальный env `FACTORY_ENABLED=true` протекает в тест), к задаче не относится.
`uv run pytest` в текущем окружении падает «Failed to spawn: pytest» — использован
эквивалент `.venv/bin/python -m pytest`.

Известные долги: изолировать env в `test_factory_defaults_from_yaml` (отдельная
задача); разобраться, почему uv не подхватывает dev-группу.

Коммит: feat: add global error handler for bot commands (feature/content-fabric).
