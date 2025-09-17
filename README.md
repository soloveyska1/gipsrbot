# GIPSR Telegram Bot

Этот репозиторий содержит Telegram-бота и вспомогательные скрипты для автоматического деплоя на сервере с Ubuntu.

## Файлы и директории

- `bot.py` — основной код Telegram-бота.
- `requirements.txt` — список зависимостей Python.
- `scripts/autodeploy.sh` — сценарий, который устанавливает зависимости, мигрирует данные и перезапускает сервис бота.
- `scripts/gipsrbot-bot.service` — unit-файл systemd для постоянной работы бота.
- `deploy/cloud-config.yaml` — пример конфигурации cloud-init для автоматической настройки сервера.
- Все данные бота (`orders.json`, `prices.json`, логи и т.д.) автоматически перемещаются в `/root/gipsr_bot/data`.

## Подготовка сервера через cloud-init

Если вы разворачиваете новую виртуальную машину, используйте `deploy/cloud-config.yaml` в качестве user-data. Конфигурация:

1. Устанавливает Python, pip и systemd.
2. Включает systemd-путь `gipsrbot-autodeploy.path`, который следит за изменениями файлов бота.
3. При любом изменении `.env`, `bot.py`, `requirements.txt` или сценариев в `scripts/` запускает `scripts/autodeploy.sh`.

## Как обновить бота без доступа к консоли

1. Сформируйте архив/папку с содержимым репозитория и загрузите его на сервер в `/root/gipsr_bot` (замена существующих файлов).
2. Убедитесь, что рядом лежит `.env` со следующими переменными:
   ```env
   TELEGRAM_BOT_TOKEN=ваш_токен
   ADMIN_CHAT_ID=123456789
   ```
3. После загрузки файлов systemd автоматически выполнит `scripts/autodeploy.sh`:
   - создаст виртуальное окружение `.venv` (если его ещё нет);
   - установит зависимости из `requirements.txt`;
   - перенесёт `orders.json`, `prices.json`, `orders.xlsx`, `user_logs.json` в `/root/gipsr_bot/data/`, чтобы бот видел сохранённые данные;
   - установит unit-файл `gipsrbot-bot.service` и перезапустит Telegram-бота.
4. Логи автодеплоя можно смотреть через `journalctl -u gipsrbot-autodeploy.service`, а логи бота — в `/root/gipsr_bot/logs/bot.log`.

После этого бот должен автоматически перезапуститься с обновлённым кодом.
