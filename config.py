"""Static configuration for the GIPSR Telegram bot."""

# === Telegram credentials ===
# Пользователь просил полностью готовый конфиг, поэтому токен уже прописан.
BOT_TOKEN: str = "7387413773:AAFgKfuf-REN5cn1ZXmCQg"

# === Владельцы и администраторы ===
# Все права доступны владельцу (Семён), Анна получает только уведомления.
OWNER_CHAT_ID: int = 872379852
OWNER_USERNAME: str = "Thisissaymoon"

SECONDARY_ADMINS = [
    {
        "chat_id": 2019512207,
        "username": "Nnnnnnnnn234567",
        "name": "Анна",
    }
]

if SECONDARY_ADMINS:
    DEFAULT_ADMIN_CHAT_ID: int = int(SECONDARY_ADMINS[0]["chat_id"])
    DEFAULT_ADMIN_USERNAME: str = str(
        SECONDARY_ADMINS[0].get("username", "")
    )
else:
    DEFAULT_ADMIN_CHAT_ID = 0
    DEFAULT_ADMIN_USERNAME = ""

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
