"""Static configuration for the GIPSR Telegram bot."""

# === Telegram credentials ===
# Пользователь просил полностью готовый конфиг, поэтому токен уже прописан.
BOT_TOKEN: str = "7387413773:AAFgKfuf-REN5cn1ZXmCQg"

# === Администратор по умолчанию ===
# 0 означает, что первый человек, написавший /start, станет админом.
DEFAULT_ADMIN_CHAT_ID: int = 2019512207
DEFAULT_ADMIN_USERNAME: str = "Nnnnnnnnn234567"

# === Базовые настройки проекта ===
PROJECT_NAME: str = "gipsr_bot"
MANAGER_CONTACT_URL: str = "https://t.me/Thisissaymoon"
DEFAULT_PRICING_MODE: str = "light"

# Предопределенные статусы заказа для админ-панели.
ORDER_STATUS_TITLES = {
    "new": "🟡 Новый заказ",
    "in_progress": "🔧 В работе",
    "waiting_payment": "💳 Ожидает оплаты",
    "revision": "🔁 На доработке",
    "done": "✅ Готово к выдаче",
}

# Текст приветствия, дополняющий стандартный /start.
WELCOME_MESSAGE: str = (
    "6 лет помогаем студентам психологии, социальной работы, конфликтологии и логопедии. "
    "Более 4000 проектов для МГУ, СПбГУ, ВШЭ, РАНХиГС и других ведущих вузов. "
    "Срочные заказы выполняем за 24 часа с усиленной поддержкой и возможностью прикреплять любые файлы."
)
