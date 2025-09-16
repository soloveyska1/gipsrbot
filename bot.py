from __future__ import annotations

import asyncio
import html
import json
import logging
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import (
    BOT_TOKEN,
    DEFAULT_ADMIN_CHAT_ID as CONFIG_ADMIN_CHAT_ID,
    DEFAULT_ADMIN_USERNAME as CONFIG_ADMIN_USERNAME,
    DEFAULT_PRICING_MODE,
    MANAGER_CONTACT_URL as CONFIG_MANAGER_CONTACT_URL,
    ORDER_STATUS_TITLES,
    OWNER_CHAT_ID as CONFIG_OWNER_CHAT_ID,
    OWNER_USERNAME as CONFIG_OWNER_USERNAME,
    SECONDARY_ADMINS,
    WELCOME_MESSAGE,
)

load_dotenv()

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or BOT_TOKEN or "").strip()

owner_id_env = os.getenv("OWNER_CHAT_ID")
admin_id_env = os.getenv("ADMIN_CHAT_ID")

try:
    OWNER_CHAT_ID_DEFAULT = (
        int(owner_id_env) if owner_id_env is not None else int(CONFIG_OWNER_CHAT_ID or 0)
    )
except ValueError:
    OWNER_CHAT_ID_DEFAULT = int(CONFIG_OWNER_CHAT_ID or 0)

try:
    ADMIN_CHAT_ID_DEFAULT = (
        int(admin_id_env) if admin_id_env is not None else int(CONFIG_ADMIN_CHAT_ID or 0)
    )
except ValueError:
    ADMIN_CHAT_ID_DEFAULT = int(CONFIG_ADMIN_CHAT_ID or 0)

DEFAULT_OWNER_USERNAME = (
    os.getenv("OWNER_USERNAME") or CONFIG_OWNER_USERNAME or ""
).strip()
ADMIN_USERNAME_DEFAULT = (
    os.getenv("ADMIN_USERNAME") or CONFIG_ADMIN_USERNAME or ""
).strip()

MANAGER_CONTACT_LINK = (
    os.getenv("MANAGER_CONTACT") or CONFIG_MANAGER_CONTACT_URL or ""
).strip() or CONFIG_MANAGER_CONTACT_URL

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN is not configured. Проверьте .env или config.py."
    )

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
CLIENTS_DIR = BASE_DIR / "clients"

for directory in (DATA_DIR, LOGS_DIR, CLIENTS_DIR):
    directory.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
file_handler = logging.FileHandler(LOGS_DIR / "bot.log")
file_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger.addHandler(file_handler)

DEFAULT_PRICES: Dict[str, Dict[str, int]] = {
    "self": {"base": 2500, "min": 2500, "max": 4200},
    "course_theory": {"base": 10000, "min": 10000, "max": 16500},
    "course_empirical": {"base": 16500, "min": 15000, "max": 24000},
    "normcontrol": {"base": 5000, "min": 5000, "max": 7000},
    "vkr": {"base": 32000, "min": 30000, "max": 48000},
    "master": {"base": 40000, "min": 40000, "max": 65000},
}

UNIVERSITIES_EXAMPLES = "МГУ, СПбГУ, ВШЭ, РАНХиГС, УрФУ и другие ведущие вузы России"

ORDER_TYPES: Dict[str, Dict[str, object]] = {
    "self": {
        "name": "Самостоятельная работа",
        "icon": "📝",
        "description": "Короткие задания, контрольные, эссе и отчёты. Выполняем точно по методичкам и быстро вовлекаем автора в задачу.",
        "details": "Подходит для работ до 20 страниц, готовим за вечер и дожидаемся подтверждения от преподавателя.",
        "examples": [
            "Эссе по психологии",
            "Контрольная по педагогике",
            "Отчёт по социальной работе",
        ],
    },
    "course_theory": {
        "name": "Курсовая (теория)",
        "icon": "📘",
        "description": "Теоретическая курсовая с понятной логикой, актуальными источниками и акцентом на научную новизну.",
        "details": "Оформляем главы, список литературы и приложения с учётом требований кафедры. Результаты подбираем под вашу задачу.",
        "examples": [
            "Психология развития личности",
            "Современные методики логопедии",
            "Социальная работа с семьёй",
        ],
    },
    "course_empirical": {
        "name": "Курсовая (теория + эмпирика)",
        "icon": "📊",
        "description": "Полный курс с аналитикой: теория, исследование, результаты и выводы. Можем придумать данные или использовать ваши.",
        "details": "Разрабатываем инструментарий, проводим опросы/тесты, оформляем таблицы и графики. Всё готово к защите.",
        "examples": [
            "Диагностика конфликтов в организации",
            "Анализ эффективности соцслужб",
            "Исследование логопедических методик",
        ],
    },
    "normcontrol": {
        "name": "Нормоконтроль",
        "icon": "📏",
        "description": "Проверим оформление, ГОСТ, ссылки и плагины. Всё приведём к стандарту вуза.",
        "details": "Шаблоны, оглавление, списки и приложения — всё выверено под требования преподавателя.",
        "examples": [
            "Проверка диплома перед сдачей",
            "Форматирование курсовой",
            "Адаптация статей под ГОСТ",
        ],
    },
    "vkr": {
        "name": "Дипломная работа (ВКР)",
        "icon": "🎓",
        "description": "Выпускная работа под ключ: план, теория, практическая часть и защита. Сопровождаем до финального отзыва.",
        "details": "Готовим презентацию, речь и сопровождаем консультациями. Опыт — 6 лет, более 4000 успешных проектов в {UNIVERSITIES_EXAMPLES}.",
        "examples": [
            "Психологическое сопровождение персонала",
            "Программа развития соцслужбы",
            "Корпоративные конфликты и их решения",
        ],
    },
    "master": {
        "name": "Магистерская диссертация",
        "icon": "🔍",
        "description": "Исследование уровня магистратуры: глубокая аналитика, научная новизна и публикации.",
        "details": "Согласовываем план, проводим исследования, готовим статьи, презентацию и речь. Сопровождаем до защиты.",
        "examples": [
            "Инновации в социальной сфере",
            "Психологические технологии сопровождения",
            "Программы профилактики конфликтов",
        ],
    },
}

FAQ_ITEMS: List[Dict[str, str]] = [
    {
        "question": "Как оформить заказ?",
        "answer": "Нажмите '📝 Сделать заказ', последовательно выберите тип, срок, объём и требования. Можно прикреплять любые файлы прямо в чат.",
    },
    {
        "question": "С какими сроками работаете?",
        "answer": "Берём срочные заказы от 24 часов с повышающим коэффициентом. Чем раньше обратитесь — тем выгоднее.",
    },
    {
        "question": "Какие скидки и бонусы?",
        "answer": "На первый заказ действует скидка 7% (до 3000 ₽). За каждого приглашённого друга — +300 ₽ на бонусный счёт.",
    },
    {
        "question": "Работаете ли с моим вузом?",
        "answer": f"Да! За 6 лет мы делали работы для {UNIVERSITIES_EXAMPLES}. Подстроимся под ваши методички.",
    },
    {
        "question": "Как передать методички и данные?",
        "answer": "На этапе требований прикрепите файлы любого формата: Word, PDF, фото, аудио. Всё автоматически прилетает администратору.",
    },
    {
        "question": "Что с антиплагиатом?",
        "answer": "Из-за детектора дубликатов Антиплагиат.ру мы не делаем предварительных проверок, но бесплатно переписываем до нужного процента. Для крупных работ правки — 6 месяцев.",
    },
]

UPSELL_OPTIONS: Dict[str, Dict[str, int]] = {
    "presentation_pack": {"title": "Презентация + речь", "price": 3000},
    "mentor": {"title": "Личный куратор с ежедневной связью", "price": 1500},
}

PAGE_OPTIONS: Dict[str, Dict[str, object]] = {
    "20": {"label": "до 20 стр.", "multiplier": 1.0},
    "35": {"label": "до 35 стр.", "multiplier": 1.2},
    "50": {"label": "до 50 стр.", "multiplier": 1.35},
    "70": {"label": "70+ стр.", "multiplier": 1.55},
}

DEADLINE_CHOICES: List[tuple[int, str]] = [
    (1, "🔥 24 часа"),
    (2, "⚡ 2 дня"),
    (3, "⚡ 3 дня"),
    (5, "5 дней"),
    (7, "Неделя"),
    (14, "2 недели"),
    (21, "3 недели"),
    (30, "Месяц"),
]

FIRST_ORDER_DISCOUNT_RATE = 0.07
FIRST_ORDER_DISCOUNT_CAP = 3000
REFERRAL_BONUS_AMOUNT = 300
LOYALTY_REWARD_RATE = 0.02

SETTINGS_FILE = DATA_DIR / "settings.json"
PRICES_FILE = DATA_DIR / "prices.json"
REFERRALS_FILE = DATA_DIR / "referrals.json"
ORDERS_FILE = DATA_DIR / "orders.json"
FEEDBACKS_FILE = DATA_DIR / "feedbacks.json"
USER_LOGS_FILE = DATA_DIR / "user_logs.json"
BONUSES_FILE = DATA_DIR / "bonuses.json"


@dataclass
class OrderRecord:
    order_id: int
    type_key: str
    topic: str
    deadline_days: int
    deadline_date: str
    page_plan: str
    requirements: str
    attachments: List[Dict[str, str]] = field(default_factory=list)
    upsells: List[str]
    status_key: str
    base_price: int
    discount: int
    price: int
    status: str
    created_at: str


class DataStore:
    def __init__(self) -> None:
        default_notification_ids: List[int] = []
        if OWNER_CHAT_ID_DEFAULT:
            default_notification_ids.append(int(OWNER_CHAT_ID_DEFAULT))
        if ADMIN_CHAT_ID_DEFAULT and ADMIN_CHAT_ID_DEFAULT not in default_notification_ids:
            default_notification_ids.append(int(ADMIN_CHAT_ID_DEFAULT))
        for entry in SECONDARY_ADMINS or []:
            try:
                extra_id = int(entry.get("chat_id", 0))
            except (TypeError, ValueError):
                continue
            if extra_id and extra_id not in default_notification_ids:
                default_notification_ids.append(extra_id)
        default_settings = {
            "pricing_mode": DEFAULT_PRICING_MODE,
            "owner_chat_id": OWNER_CHAT_ID_DEFAULT,
            "owner_username": DEFAULT_OWNER_USERNAME,
            "admin_chat_id": ADMIN_CHAT_ID_DEFAULT,
            "admin_username": ADMIN_USERNAME_DEFAULT,
            "manager_contact_url": MANAGER_CONTACT_LINK,
            "notification_chat_ids": default_notification_ids,
        }
        loaded_settings = self._load_json(SETTINGS_FILE, default_settings)
        changed = False
        for key, value in default_settings.items():
            if key not in loaded_settings:
                loaded_settings[key] = value
                changed = True
        if (
            int(default_settings.get("owner_chat_id", 0))
            and int(loaded_settings.get("owner_chat_id", 0)) == 0
        ):
            loaded_settings["owner_chat_id"] = default_settings["owner_chat_id"]
            changed = True
        if (
            default_settings.get("owner_username")
            and not loaded_settings.get("owner_username")
        ):
            loaded_settings["owner_username"] = default_settings["owner_username"]
            changed = True
        if (
            int(default_settings.get("admin_chat_id", 0))
            and int(loaded_settings.get("admin_chat_id", 0)) == 0
        ):
            loaded_settings["admin_chat_id"] = default_settings["admin_chat_id"]
            changed = True
        if (
            default_settings.get("admin_username")
            and not loaded_settings.get("admin_username")
        ):
            loaded_settings["admin_username"] = default_settings["admin_username"]
            changed = True
        notifications = loaded_settings.get("notification_chat_ids")
        if not isinstance(notifications, list):
            notifications = []
            changed = True
        for value in default_notification_ids:
            if value and value not in notifications:
                notifications.append(value)
                changed = True
        loaded_settings["notification_chat_ids"] = notifications
        if changed:
            self._save_json(SETTINGS_FILE, loaded_settings)
        self.settings: Dict[str, object] = loaded_settings
        self.prices: Dict[str, Dict[str, int]] = self._load_json(PRICES_FILE, DEFAULT_PRICES)
        self.referrals: Dict[str, List[int]] = self._load_json(REFERRALS_FILE, {})
        self.orders: Dict[str, List[Dict[str, object]]] = self._load_json(ORDERS_FILE, {})
        self.feedbacks: Dict[str, List[str]] = self._load_json(FEEDBACKS_FILE, {})
        self.user_logs: Dict[str, List[Dict[str, str]]] = self._load_json(USER_LOGS_FILE, {})
        self.bonuses: Dict[str, Dict[str, object]] = self._load_json(BONUSES_FILE, {})

    @staticmethod
    def _load_json(path: Path, default) -> object:
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as fh:
                    return json.load(fh)
            except json.JSONDecodeError as exc:
                logger.warning("Failed to decode %s (%s). Restoring defaults.", path, exc)
        DataStore._save_json(path, default)
        return json.loads(json.dumps(default))

    @staticmethod
    def _save_json(path: Path, data) -> None:
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)

    def get_pricing_mode(self) -> str:
        return self.settings.get("pricing_mode", DEFAULT_PRICING_MODE)

    def set_pricing_mode(self, mode: str) -> None:
        self.settings["pricing_mode"] = mode
        self._save_json(SETTINGS_FILE, self.settings)

    def get_owner_chat_id(self) -> int:
        try:
            return int(self.settings.get("owner_chat_id", 0))
        except (TypeError, ValueError):
            return 0

    def set_owner_chat_id(self, chat_id: int, username: Optional[str] = None) -> None:
        try:
            normalized = int(chat_id)
        except (TypeError, ValueError):
            normalized = 0
        self.settings["owner_chat_id"] = normalized
        if username is not None:
            self.settings["owner_username"] = username or ""
        notifications = self.settings.get("notification_chat_ids")
        if not isinstance(notifications, list):
            notifications = []
        if normalized and normalized not in notifications:
            notifications.append(normalized)
        self.settings["notification_chat_ids"] = notifications
        self._save_json(SETTINGS_FILE, self.settings)

    def get_admin_chat_id(self) -> int:
        try:
            return int(self.settings.get("admin_chat_id", 0))
        except (TypeError, ValueError):
            return 0

    def set_admin_chat_id(self, chat_id: int, username: Optional[str] = None) -> None:
        try:
            normalized = int(chat_id)
        except (TypeError, ValueError):
            normalized = 0
        self.settings["admin_chat_id"] = normalized
        if username is not None:
            self.settings["admin_username"] = username or ""
        notifications = self.settings.get("notification_chat_ids")
        if not isinstance(notifications, list):
            notifications = []
        if normalized and normalized not in notifications:
            notifications.append(normalized)
        self.settings["notification_chat_ids"] = notifications
        self._save_json(SETTINGS_FILE, self.settings)

    def get_admin_username(self) -> str:
        return str(self.settings.get("admin_username", "") or "")

    def get_notification_chat_ids(self) -> List[int]:
        recipients: List[int] = []
        owner_id = self.get_owner_chat_id()
        if owner_id:
            recipients.append(owner_id)
        try:
            admin_id = int(self.settings.get("admin_chat_id", 0))
        except (TypeError, ValueError):
            admin_id = 0
        if admin_id and admin_id not in recipients:
            recipients.append(admin_id)
        extras = self.settings.get("notification_chat_ids", [])
        if isinstance(extras, list):
            for value in extras:
                try:
                    candidate = int(value)
                except (TypeError, ValueError):
                    continue
                if candidate and candidate not in recipients:
                    recipients.append(candidate)
        return recipients

    def get_manager_contact(self) -> str:
        return str(self.settings.get("manager_contact_url", MANAGER_CONTACT_LINK))

    def add_referral(self, referrer_id: int, new_user_id: int) -> bool:
        referrer_key = str(referrer_id)
        referred_list = self.referrals.setdefault(referrer_key, [])
        if new_user_id in referred_list:
            return False
        referred_list.append(new_user_id)
        self._save_json(REFERRALS_FILE, self.referrals)
        self.add_bonus(referrer_id, REFERRAL_BONUS_AMOUNT, f"Реферал {new_user_id}")
        return True

    def add_bonus(self, user_id: int, amount: int, reason: str) -> None:
        if not amount:
            return
        user_key = str(user_id)
        entry = self.bonuses.setdefault(user_key, {"balance": 0, "history": []})
        entry["balance"] = int(entry.get("balance", 0)) + int(amount)
        history = entry.setdefault("history", [])
        history.append(
            {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "amount": int(amount),
                "reason": reason,
            }
        )
        self._save_json(BONUSES_FILE, self.bonuses)

    def get_bonus_info(self, user_id: int) -> Dict[str, object]:
        entry = self.bonuses.get(str(user_id), {})
        return {
            "balance": int(entry.get("balance", 0)),
            "history": list(entry.get("history", [])),
        }

    def list_referral_stats(self) -> List[Dict[str, object]]:
        stats: List[Dict[str, object]] = []
        for user_id, referred in self.referrals.items():
            info = self.get_bonus_info(int(user_id))
            stats.append(
                {
                    "user_id": int(user_id),
                    "count": len(referred),
                    "bonus": int(info.get("balance", 0)),
                }
            )
        stats.sort(key=lambda item: (item["bonus"], item["count"]), reverse=True)
        return stats

    def log_action(self, user_id: int, username: Optional[str], action: str) -> None:
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "action": action,
            "username": username or "",
        }
        user_key = str(user_id)
        self.user_logs.setdefault(user_key, []).append(entry)
        self._save_json(USER_LOGS_FILE, self.user_logs)

    def add_feedback(self, user_id: int, feedback: str) -> None:
        user_key = str(user_id)
        self.feedbacks.setdefault(user_key, []).append(feedback)
        self._save_json(FEEDBACKS_FILE, self.feedbacks)

    def next_order_id(self, user_id: int) -> int:
        user_key = str(user_id)
        orders = self.orders.get(user_key, [])
        if not orders:
            return 1
        last_id = max(int(order.get("order_id", 0)) for order in orders)
        return last_id + 1

    def add_order(self, user_id: int, order: OrderRecord) -> OrderRecord:
        user_key = str(user_id)
        orders = self.orders.setdefault(user_key, [])
        orders.append(asdict(order))
        self._save_json(ORDERS_FILE, self.orders)
        return order

    def get_orders(self, user_id: int) -> List[Dict[str, object]]:
        return self.orders.get(str(user_id), [])

    def get_order(self, user_id: int, order_id: int) -> Optional[Dict[str, object]]:
        orders = self.orders.get(str(user_id))
        if not orders:
            return None
        for order in orders:
            if int(order.get("order_id", 0)) == int(order_id):
                return order
        return None

    def list_recent_orders(self, limit: int = 10) -> List[Dict[str, object]]:
        entries: List[Dict[str, object]] = []
        for user_id, orders in self.orders.items():
            for order in orders:
                combined = {"user_id": int(user_id)}
                combined.update(order)
                entries.append(combined)
        entries.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return entries[:limit]

    def total_spent(self, user_id: int) -> int:
        return int(sum(int(order.get("price", 0)) for order in self.get_orders(user_id)))

    def get_referrals(self, user_id: int) -> List[int]:
        return self.referrals.get(str(user_id), [])

    def export_orders(self) -> Optional[Path]:
        records: List[Dict[str, object]] = []
        for user_id, orders in self.orders.items():
            for order in orders:
                records.append({"user_id": user_id, **order})
        if not records:
            return None
        df = pd.DataFrame(records)
        export_path = DATA_DIR / "orders_export.xlsx"
        df.to_excel(export_path, index=False)
        return export_path

    def get_statistics(self) -> Dict[str, int]:
        orders_flat = [order for orders in self.orders.values() for order in orders]
        total_orders = len(orders_flat)
        total_revenue = int(sum(int(order.get("price", 0)) for order in orders_flat))
        active_orders = 0
        for order in orders_flat:
            status_key = str(order.get("status_key", "")).lower()
            status_text = str(order.get("status", "")).lower()
            if status_key in {"done"}:
                continue
            if any(word in status_text for word in ("готов", "заверш")):
                continue
            active_orders += 1
        unique_users = len(self.orders)
        total_referrals = sum(len(refs) for refs in self.referrals.values())
        total_bonuses = int(
            sum(int(info.get("balance", 0)) for info in self.bonuses.values())
        )
        return {
            "orders": total_orders,
            "revenue": total_revenue,
            "active": active_orders,
            "users": unique_users,
            "referrals": total_referrals,
            "bonuses": total_bonuses,
        }

    def update_order_status(
        self, user_id: int, order_id: int, status_key: str, status_title: str
    ) -> Optional[Dict[str, object]]:
        orders = self.orders.get(str(user_id))
        if not orders:
            return None
        for order in orders:
            if int(order.get("order_id", 0)) == int(order_id):
                order["status_key"] = status_key
                order["status"] = status_title
                self._save_json(ORDERS_FILE, self.orders)
                return order
        return None


store = DataStore()


STATE_NAVIGATION, STATE_ORDER_TOPIC, STATE_ORDER_PAGES, STATE_ORDER_REQUIREMENTS, STATE_FEEDBACK, STATE_ADMIN = range(6)


def schedule_restart(delay: float = 1.5) -> None:
    loop = asyncio.get_running_loop()

    def _shutdown() -> None:
        logger.warning("Stopping bot process by admin request")
        os._exit(0)

    loop.call_later(delay, _shutdown)


def log_user_action(update: Update, action: str) -> None:
    user = update.effective_user
    if not user:
        return
    store.log_action(user.id, user.username, action)


async def ensure_owner_access(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    user = update.effective_user
    owner_id = store.get_owner_chat_id()
    if not user or user.id != owner_id:
        if update.message:
            await update.message.reply_text(
                "Админ-панель доступна только владельцу бота."
            )
        elif update.callback_query:
            await update.callback_query.answer("Нет доступа", show_alert=True)
        return False
    return True


def calculate_price(
    order_type: str,
    days_left: int,
    page_multiplier: float = 1.0,
    upsells: Iterable[str] = (),
) -> int:
    price_info = store.prices.get(order_type) or DEFAULT_PRICES.get(order_type)
    if not price_info:
        logger.warning("Unknown order type for pricing: %s", order_type)
        return 0
    base_price = int(price_info.get("base", 0))
    subtotal = int(base_price * page_multiplier)
    mode = store.get_pricing_mode()
    if days_left <= 1:
        subtotal = int(subtotal * (1.8 if mode == "hard" else 1.65))
    elif days_left <= 2:
        subtotal = int(subtotal * (1.6 if mode == "hard" else 1.45))
    elif days_left <= 3:
        subtotal = int(subtotal * (1.35 if mode == "hard" else 1.25))
    elif days_left <= 5:
        subtotal = int(subtotal * (1.2 if mode == "hard" else 1.15))
    elif days_left <= 7:
        subtotal = int(subtotal * (1.15 if mode == "hard" else 1.1))
    elif days_left <= 14 and mode == "hard":
        subtotal = int(subtotal * 1.05)
    total = subtotal
    for upsell in upsells:
        option = UPSELL_OPTIONS.get(upsell)
        if option:
            total += option["price"]
    return total


def build_main_menu_keyboard() -> InlineKeyboardMarkup:
    contact_url = store.get_manager_contact()
    keyboard = [
        [InlineKeyboardButton("📝 Сделать заказ", callback_data="main:order")],
        [
            InlineKeyboardButton("💲 Прайс-лист", callback_data="main:prices"),
            InlineKeyboardButton("🧮 Калькулятор", callback_data="main:calculator"),
        ],
        [
            InlineKeyboardButton("👤 Профиль", callback_data="main:profile"),
            InlineKeyboardButton("❓ FAQ", callback_data="main:faq"),
        ],
        [InlineKeyboardButton("📞 Администратор", url=contact_url)],
    ]
    return InlineKeyboardMarkup(keyboard)


def order_type_name_from_key(type_key: Optional[str]) -> str:
    if type_key and type_key in ORDER_TYPES:
        return ORDER_TYPES[type_key]["name"]
    return str(type_key or "Неизвестный тип")


def order_type_name_from_record(order: Dict[str, object]) -> str:
    type_key = order.get("type_key")
    if type_key in ORDER_TYPES:
        return ORDER_TYPES[type_key]["name"]
    legacy_name = order.get("type")
    if legacy_name:
        return str(legacy_name)
    return order_type_name_from_key(type_key if isinstance(type_key, str) else None)


def format_order_summary(
    draft: Dict[str, object], base_price: int, final_price: int, discount_value: int
) -> str:
    order_type = ORDER_TYPES.get(draft.get("type_key")) or {}
    upsells = draft.get("upsells", [])
    upsell_lines = []
    for upsell in upsells:
        info = UPSELL_OPTIONS.get(upsell)
        if info:
            upsell_lines.append(f"• {info['title']} (+{info['price']} ₽)")
    upsell_text = "\n".join(upsell_lines) if upsell_lines else "—"
    deadline_days = int(draft.get("deadline_days", 0))
    deadline_date = (datetime.now() + timedelta(days=deadline_days)).strftime("%d.%m.%Y")
    page_label = draft.get("page_label") or get_page_option(str(draft.get("page_key"))).get("label")
    attachments = draft.get("attachments", [])
    attachments_text = (
        f"{len(attachments)} файл(ов)" if attachments else "можно прикрепить позже"
    )
    discount_line = (
        f"Скидка новичка: −{discount_value} ₽\n" if discount_value else ""
    )
    return (
        f"<b>Проверим данные перед оформлением:</b>\n\n"
        f"Тип: {order_type.get('icon', '')} {order_type.get('name', 'Неизвестно')}\n"
        f"Тема: {html.escape(str(draft.get('topic', 'не указана')))}\n"
        f"Срок: {deadline_days} дн. (до {deadline_date})\n"
        f"Объём: {page_label}\n"
        f"Требования: {html.escape(str(draft.get('requirements', 'не указаны')))}\n"
        f"Файлы: {attachments_text}\n"
        f"Доп. услуги: {upsell_text}\n\n"
        f"Базовая стоимость: {base_price} ₽\n"
        f"{discount_line}Итого к оплате: <b>{final_price} ₽</b>"
    )


async def get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    username = context.application.bot_data.get("bot_username")
    if username:
        return username
    me = await context.bot.get_me()
    username = me.username or ""
    context.application.bot_data["bot_username"] = username
    return username


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: Optional[str] = None) -> int:
    markup = build_main_menu_keyboard()
    message_text = text or (
        "Выберите нужный раздел 👇\n"
        "Срочный заказ за 24 часа? Просто прикрепите задание — мы возьмёмся сразу."
    )
    if update.callback_query:
        query = update.callback_query
        try:
            await query.edit_message_text(message_text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except BadRequest as exc:
            if "message is not modified" not in str(exc):
                raise
    elif update.message:
        await update.message.reply_text(message_text, reply_markup=markup, parse_mode=ParseMode.HTML)
    return STATE_NAVIGATION

def get_order_draft(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, object]:
    draft = context.user_data.setdefault("order_draft", {})
    draft.setdefault("upsells", set())
    return draft


def get_page_option(key: Optional[str]) -> Dict[str, object]:
    if key and key in PAGE_OPTIONS:
        return PAGE_OPTIONS[key]
    return PAGE_OPTIONS["20"]


def ensure_requirement_buckets(draft: Dict[str, object]) -> None:
    draft.setdefault("requirements_texts", [])
    draft.setdefault("attachments", [])


async def show_order_types(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    log_user_action(update, "open_order_types")
    keyboard = [
        [
            InlineKeyboardButton(
                f"{info['icon']} {info['name']}", callback_data=f"order:type:{key}"
            )
        ]
        for key, info in ORDER_TYPES.items()
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="main:root")])
    markup = InlineKeyboardMarkup(keyboard)
    text = "Выберите тип работы. Можно оформить несколько заказов подряд — будет дополнительная скидка!"
    query = update.callback_query
    try:
        await query.edit_message_text(text, reply_markup=markup)
    except BadRequest as exc:
        if "message is not modified" not in str(exc):
            raise
    return STATE_NAVIGATION


async def show_order_details(update: Update, key: str) -> int:
    query = update.callback_query
    info = ORDER_TYPES.get(key)
    if not info:
        await query.edit_message_text("Неизвестный тип работы. Попробуйте снова.")
        return STATE_NAVIGATION
    examples = ", ".join(info.get("examples", []))
    text = (
        f"{info['icon']} <b>{info['name']}</b>\n\n"
        f"{info['description']}\n\n"
        f"<b>Что включено:</b> {info['details']}\n"
        f"<b>Примеры:</b> {html.escape(examples)}"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Выбрать", callback_data=f"order:new:{key}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="order:list")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return STATE_NAVIGATION


async def prompt_order_topic(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str) -> int:
    draft = get_order_draft(context)
    draft.clear()
    draft.update({"type_key": key, "upsells": set()})
    query = update.callback_query
    await query.edit_message_text(
        "Напишите тему работы сообщением. Можно прикрепить требования позже. Для отмены /cancel",
        parse_mode=ParseMode.HTML,
    )
    return STATE_ORDER_TOPIC


async def receive_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = get_order_draft(context)
    topic = update.message.text.strip()
    if not topic:
        await update.message.reply_text("Пожалуйста, отправьте тему текстом.")
        return STATE_ORDER_TOPIC
    draft["topic"] = topic
    log_user_action(update, f"order_topic:{topic}")
    return await prompt_deadline(update, context)


async def prompt_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (
        "Выберите срок сдачи. Срочные заказы (до 24 часов) выполняем с приоритетом — "
        "это дороже, но экономит вам время."
    )
    today = datetime.now()
    keyboard: List[List[InlineKeyboardButton]] = []
    for days, label in DEADLINE_CHOICES:
        deadline = today + timedelta(days=days)
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{label} · до {deadline:%d.%m}",
                    callback_data=f"order:deadline:{days}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton("⬅️ Отмена", callback_data="order:cancel")])
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=markup)
    return STATE_NAVIGATION


async def handle_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE, days: int) -> int:
    draft = get_order_draft(context)
    draft["deadline_days"] = days
    return await prompt_page_selection(update, context)


async def prompt_page_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = get_order_draft(context)
    query = update.callback_query
    text = (
        "Сколько примерно страниц или слайдов нужно оформить? Чем больше объём, тем тщательнее подбор автора."
    )
    keyboard = [
        [InlineKeyboardButton(option["label"], callback_data=f"order:pages:{key}")]
        for key, option in PAGE_OPTIONS.items()
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Отмена", callback_data="order:cancel")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return STATE_ORDER_PAGES


async def prompt_requirements_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = get_order_draft(context)
    ensure_requirement_buckets(draft)
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Готово, дальше", callback_data="order:req_finish")],
            [InlineKeyboardButton("⬅️ Отменить", callback_data="order:cancel")],
        ]
    )
    await update.callback_query.edit_message_text(
        (
            "Отправьте требования сообщениями и прикрепите файлы (Word, PDF, фото, аудио — всё принимаем).\n"
            "Для самостоятельных работ приложите задание, для курсовых/ВКР/магистерских — методические рекомендации.\n"
            "Когда закончите, нажмите кнопку ниже или отправьте команду /done."
        ),
        reply_markup=keyboard,
    )
    return STATE_ORDER_REQUIREMENTS


async def handle_page_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str) -> int:
    draft = get_order_draft(context)
    option = get_page_option(key)
    draft["page_key"] = key
    draft["page_label"] = option["label"]
    draft["page_multiplier"] = float(option.get("multiplier", 1.0))
    ensure_requirement_buckets(draft)
    return await prompt_requirements_input(update, context)


async def receive_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = get_order_draft(context)
    ensure_requirement_buckets(draft)
    message_text = update.message.text.strip()
    if not message_text:
        await update.message.reply_text("Пожалуйста, опишите требования текстом или отправьте /skip, если их нет.")
        return STATE_ORDER_REQUIREMENTS
    draft.setdefault("requirements_texts", []).append(message_text)
    draft["requirements"] = "\n\n".join(draft["requirements_texts"])
    log_user_action(update, "order_requirements_note")
    await update.message.reply_text(
        "Приняли. Можно добавить ещё комментариев или прикрепить файлы. Когда всё готово — /done."
    )
    return STATE_ORDER_REQUIREMENTS


async def skip_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = get_order_draft(context)
    ensure_requirement_buckets(draft)
    draft["requirements_texts"] = []
    draft["requirements"] = "Нет дополнительных требований"
    return await finish_requirements(update, context)


def finalize_requirement_text(draft: Dict[str, object]) -> str:
    notes = [note.strip() for note in draft.get("requirements_texts", []) if note.strip()]
    if notes:
        combined = "\n\n".join(notes)
    else:
        combined = str(draft.get("requirements", "Нет дополнительных требований"))
    draft["requirements"] = combined
    return combined


async def finish_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = get_order_draft(context)
    ensure_requirement_buckets(draft)
    finalize_requirement_text(draft)
    attachments = draft.get("attachments", [])
    log_user_action(update, f"order_requirements_done:{len(draft['requirements_texts'])}:{len(attachments)}")
    if update.message:
        return await show_upsell_menu(update, context)
    if update.callback_query:
        await update.callback_query.answer("Требования сохранены", show_alert=False)
    return await show_upsell_menu(update, context)


async def handle_requirement_attachment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = get_order_draft(context)
    ensure_requirement_buckets(draft)
    message = update.message
    attachment_entry: Dict[str, str]
    label = "Файл"
    attachment_type = "attachment"
    if message.document:
        doc = message.document
        label = doc.file_name or (doc.mime_type or "Документ")
        attachment_entry = {
            "type": "document",
            "file_id": doc.file_id,
            "name": label,
        }
    elif message.photo:
        photo = message.photo[-1]
        label = message.caption or "Фото задания"
        attachment_entry = {
            "type": "photo",
            "file_id": photo.file_id,
            "name": label,
        }
    elif message.audio:
        audio = message.audio
        label = audio.title or audio.file_name or "Аудиофайл"
        attachment_entry = {
            "type": "audio",
            "file_id": audio.file_id,
            "name": label,
        }
    elif message.voice:
        label = "Голосовое сообщение"
        attachment_entry = {
            "type": "voice",
            "file_id": message.voice.file_id,
            "name": label,
        }
    elif message.video:
        video = message.video
        label = video.file_name or "Видеофайл"
        attachment_entry = {
            "type": "video",
            "file_id": video.file_id,
            "name": label,
        }
    elif message.video_note:
        label = "Круглое видео"
        attachment_entry = {
            "type": "video_note",
            "file_id": message.video_note.file_id,
            "name": label,
        }
    else:
        label = "Файл"
        attachment_entry = {"type": attachment_type, "file_id": "", "name": label}
    attachments = draft.setdefault("attachments", [])
    if attachment_entry.get("file_id"):
        attachments.append(attachment_entry)
        attachment_type = attachment_entry.get("type", attachment_type)
    caption = message.caption
    if caption:
        draft.setdefault("requirements_texts", []).append(caption.strip())
        finalize_requirement_text(draft)
    log_user_action(update, f"order_attachment:{attachment_type}")
    for admin_chat_id in store.get_notification_chat_ids():
        try:
            await message.forward(admin_chat_id)
        except Exception as exc:  # pragma: no cover - зависит от Telegram API
            logger.warning("Не удалось переслать вложение админу %s: %s", admin_chat_id, exc)
    await message.reply_text(
        f"Добавили: {label}. Можно прикрепить ещё или нажать /done, когда всё готово.")
    return STATE_ORDER_REQUIREMENTS


def build_upsell_keyboard(selected: Iterable[str]) -> InlineKeyboardMarkup:
    keyboard: List[List[InlineKeyboardButton]] = []
    selected_set = set(selected)
    for key, info in UPSELL_OPTIONS.items():
        prefix = "✅" if key in selected_set else "➕"
        keyboard.append(
            [InlineKeyboardButton(f"{prefix} {info['title']} (+{info['price']} ₽)", callback_data=f"order:upsell:{key}")]
        )
    keyboard.append([InlineKeyboardButton("Продолжить", callback_data="order:summary")])
    keyboard.append([InlineKeyboardButton("Отменить", callback_data="order:cancel")])
    return InlineKeyboardMarkup(keyboard)


async def show_upsell_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = get_order_draft(context)
    raw_selected = draft.get("upsells", set())
    selected = raw_selected if isinstance(raw_selected, set) else set(raw_selected)
    draft["upsells"] = selected
    if update.message:
        await update.message.reply_text(
            "Добавьте дополнительные услуги: презентацию с речью или личного куратора с ежедневной связью."
            " Можно сразу перейти к подтверждению.",
            reply_markup=build_upsell_keyboard(selected),
        )
    else:
        query = update.callback_query
        await query.edit_message_text(
            "Выберите дополнительные услуги или переходите к подтверждению заказа.",
            reply_markup=build_upsell_keyboard(selected),
        )
    return STATE_NAVIGATION


async def toggle_upsell(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str) -> int:
    draft = get_order_draft(context)
    selected_raw = draft.get("upsells", set())
    selected = selected_raw if isinstance(selected_raw, set) else set(selected_raw)
    if key in selected:
        selected.remove(key)
    else:
        selected.add(key)
    draft["upsells"] = selected
    query = update.callback_query
    await query.edit_message_text(
        "Отлично! Можно добавить еще или перейти к подтверждению.",
        reply_markup=build_upsell_keyboard(selected),
    )
    return STATE_NAVIGATION


async def show_order_summary_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = get_order_draft(context)
    user = update.effective_user
    if "topic" not in draft or "deadline_days" not in draft:
        return await show_main_menu(update, context, "Начните оформление заказа заново.")
    upsells = list(draft.get("upsells", set()))
    draft["upsells"] = upsells
    page_multiplier = float(draft.get("page_multiplier", get_page_option(str(draft.get("page_key"))).get("multiplier", 1.0)))
    base_price = calculate_price(
        draft["type_key"],
        int(draft["deadline_days"]),
        page_multiplier,
        upsells,
    )
    existing_orders = store.get_orders(user.id) if user else []
    discount_value = 0
    if user and not existing_orders:
        discount_value = min(int(base_price * FIRST_ORDER_DISCOUNT_RATE), FIRST_ORDER_DISCOUNT_CAP)
    final_price = max(base_price - discount_value, 0)
    draft["base_price"] = base_price
    draft["discount_value"] = discount_value
    draft["price"] = final_price
    text = format_order_summary(draft, base_price, final_price, discount_value)
    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить заказ", callback_data="order:confirm")],
        [InlineKeyboardButton("✏️ Изменить допы", callback_data="order:upsell")],
        [InlineKeyboardButton("❌ Отменить", callback_data="order:cancel")],
    ]
    query = update.callback_query
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    return STATE_NAVIGATION


async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("order_draft", None)
    if update.callback_query:
        await update.callback_query.edit_message_text("Оформление отменено. Можно начать заново из меню.")
        return await show_main_menu(update, context)
    if update.message:
        await update.message.reply_text("Оформление заказа отменено.")
    return await show_main_menu(update, context)


async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user:
        return STATE_NAVIGATION
    draft = get_order_draft(context)
    if not draft:
        return await show_main_menu(update, context, "Корзина пуста. Попробуйте оформить заказ заново.")
    order_id = store.next_order_id(user.id)
    deadline_days = int(draft.get("deadline_days", 0))
    deadline_date = (datetime.now() + timedelta(days=deadline_days)).strftime("%d.%m.%Y")
    page_plan = draft.get("page_label") or get_page_option(str(draft.get("page_key"))).get("label")
    attachments = list(draft.get("attachments", []))
    base_price = int(draft.get("base_price", draft.get("price", 0)))
    discount_value = int(draft.get("discount_value", 0))
    final_price = int(draft.get("price", base_price))
    order = OrderRecord(
        order_id=order_id,
        type_key=str(draft.get("type_key")),
        topic=str(draft.get("topic", "")),
        deadline_days=deadline_days,
        deadline_date=deadline_date,
        page_plan=str(page_plan),
        requirements=str(draft.get("requirements", "")),
        attachments=attachments,
        upsells=list(draft.get("upsells", [])),
        status_key="new",
        base_price=base_price,
        discount=discount_value,
        price=final_price,
        status=ORDER_STATUS_TITLES.get("new", "новый"),
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    store.add_order(user.id, order)
    log_user_action(update, f"order_confirmed:{order.order_id}")
    context.user_data.pop("order_draft", None)
    loyalty_bonus = int(final_price * LOYALTY_REWARD_RATE)
    if loyalty_bonus:
        store.add_bonus(user.id, loyalty_bonus, f"Бонус за заказ #{order.order_id}")
    bonus_info = store.get_bonus_info(user.id)
    bonus_balance = int(bonus_info.get("balance", 0))
    text = (
        f"Спасибо! Заказ #{order.order_id} оформлен.\n"
        f"Менеджер свяжется с вами в ближайшее время. Статус можно отслеживать в профиле.\n\n"
        f"Текущий бонусный баланс: {bonus_balance} ₽."
    )
    if loyalty_bonus:
        text += f"\nНачислили +{loyalty_bonus} ₽ за заказ — их можно тратить на следующие работы."
    query = update.callback_query
    await query.edit_message_text(text)
    notification_ids = store.get_notification_chat_ids()
    if notification_ids:
        order_type = order_type_name_from_key(order.type_key)
        upsell_titles = [UPSELL_OPTIONS.get(u, {}).get("title", u) for u in order.upsells]
        admin_text = (
            f"Новый заказ #{order.order_id}\n"
            f"Пользователь: {user.id} ({user.username or user.full_name})\n"
            f"Тип: {order_type}\n"
            f"Тема: {order.topic}\n"
            f"Срок: {order.deadline_days} дн. (до {order.deadline_date})\n"
            f"Объём: {page_plan}\n"
            f"Опции: {', '.join(upsell_titles) if upsell_titles else 'нет'}\n"
            f"Базовая сумма: {base_price} ₽\n"
            f"Скидка: {discount_value} ₽\n"
            f"Итого: {final_price} ₽\n"
            f"Файлы: {len(attachments)} (пересланы отдельными сообщениями)"
        )
        for admin_chat_id in notification_ids:
            try:
                await context.bot.send_message(admin_chat_id, admin_text)
            except Exception as exc:  # pragma: no cover - depends on Telegram API
                logger.error("Failed to notify admin %s: %s", admin_chat_id, exc)
    return await show_main_menu(update, context, "Хотите оформить еще одну работу?")

async def show_price_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    log_user_action(update, "open_price_list")
    rows = []
    for key, info in ORDER_TYPES.items():
        price_info = store.prices.get(key, DEFAULT_PRICES[key])
        rows.append(f"{info['icon']} <b>{info['name']}</b> — от {price_info['base']} ₽")
    text = (
        "💰 <b>Прайс-лист</b>\n"
        "6 лет опыта и 4000+ работ для {UNIVERSITIES_EXAMPLES}.\n"
        "Срочные заказы (до 24 часов) выполняем с коэффициентом — это быстрее и выгоднее, чем переделывать в последний день.\n\n"
    ).format(UNIVERSITIES_EXAMPLES=UNIVERSITIES_EXAMPLES) + "\n".join(rows)
    keyboard = [
        [
            InlineKeyboardButton(f"Подробнее: {info['name']}", callback_data=f"prices:detail:{key}")
        ]
        for key, info in ORDER_TYPES.items()
    ]
    keyboard.append([InlineKeyboardButton("🧮 Калькулятор", callback_data="main:calculator")])
    keyboard.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="main:root")])
    query = update.callback_query
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return STATE_NAVIGATION


async def show_price_detail(update: Update, key: str) -> int:
    info = ORDER_TYPES.get(key)
    price_info = store.prices.get(key, DEFAULT_PRICES.get(key, {}))
    if not info:
        await update.callback_query.edit_message_text("Неизвестный тип работы.")
        return STATE_NAVIGATION
    text = (
        f"{info['icon']} <b>{info['name']}</b>\n\n"
        f"{info['description']}\n\n"
        f"<b>Диапазон цен:</b> {price_info.get('min', price_info.get('base', 0))}–{price_info.get('max', price_info.get('base', 0))} ₽\n"
        f"<b>Что входит:</b> {info['details']}\n"
        f"<b>Примеры:</b> {html.escape(', '.join(info.get('examples', [])))}\n"
        "<b>Срочно?</b> Сделаем за 24 часа с надбавкой и постоянной обратной связью.\n"
        "<b>Файлы:</b> прикрепляйте методички, задания и данные прямо сюда — всё сразу уйдет в работу."
    )
    keyboard = [
        [InlineKeyboardButton("📝 Оформить", callback_data=f"order:type:{key}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main:prices")],
    ]
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    return STATE_NAVIGATION


async def show_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    log_user_action(update, "open_calculator")
    keyboard = [
        [InlineKeyboardButton(f"{info['icon']} {info['name']}", callback_data=f"calc:type:{key}")]
        for key, info in ORDER_TYPES.items()
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="main:root")])
    await update.callback_query.edit_message_text(
        "Выберите тип работы для расчета стоимости:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return STATE_NAVIGATION


async def calculator_select_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str) -> int:
    context.user_data.setdefault("calculator", {})["type"] = key
    keyboard = []
    for days, label in DEADLINE_CHOICES:
        keyboard.append([InlineKeyboardButton(label, callback_data=f"calc:deadline:{days}")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="main:calculator")])
    await update.callback_query.edit_message_text(
        "Выберите срок выполнения:", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return STATE_NAVIGATION


async def calculator_select_pages(update: Update, context: ContextTypes.DEFAULT_TYPE, days: int) -> int:
    context.user_data.setdefault("calculator", {})["deadline"] = days
    keyboard = [
        [InlineKeyboardButton(option["label"], callback_data=f"calc:pages:{key}")]
        for key, option in PAGE_OPTIONS.items()
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="main:calculator")])
    await update.callback_query.edit_message_text(
        "Оцените объём работы:", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return STATE_NAVIGATION


async def show_calculation_result(update: Update, context: ContextTypes.DEFAULT_TYPE, page_key: str) -> int:
    data = context.user_data.get("calculator", {})
    type_key = data.get("type")
    days = int(data.get("deadline", 14))
    if not type_key:
        return await show_calculator(update, context)
    page_option = get_page_option(page_key)
    data["page_key"] = page_key
    multiplier = float(page_option.get("multiplier", 1.0))
    price = calculate_price(type_key, days, multiplier)
    info = ORDER_TYPES.get(type_key, {})
    user = update.effective_user
    discount_value = 0
    if user and not store.get_orders(user.id):
        discount_value = min(int(price * FIRST_ORDER_DISCOUNT_RATE), FIRST_ORDER_DISCOUNT_CAP)
    final_price = max(price - discount_value, 0)
    text = (
        f"Расчет для {info.get('icon', '')} <b>{info.get('name', 'работы')}</b>\n"
        f"Срок: {days} дней\n"
        f"Объём: {page_option['label']}\n\n"
        f"Примерная стоимость: <b>{price} ₽</b>\n"
    )
    if discount_value:
        text += f"Скидка новичка: −{discount_value} ₽\nИтого: <b>{final_price} ₽</b>\n"
    text += "\nХотите оформить заказ прямо сейчас?"
    keyboard = [
        [InlineKeyboardButton("📝 Сделать заказ", callback_data=f"order:type:{type_key}")],
        [InlineKeyboardButton("🔁 Пересчитать", callback_data="main:calculator")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="main:root")],
    ]
    await update.callback_query.edit_message_text(
        text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return STATE_NAVIGATION


async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user:
        return STATE_NAVIGATION
    log_user_action(update, "open_profile")
    orders = store.get_orders(user.id)
    total_orders = len(orders)
    total_spent = store.total_spent(user.id)
    referrals = store.get_referrals(user.id)
    bonus_info = store.get_bonus_info(user.id)
    bonus_balance = int(bonus_info.get("balance", 0))
    bot_username = await get_bot_username(context)
    ref_link = f"https://t.me/{bot_username}?start={user.id}" if bot_username else "—"
    last_order = orders[-1] if orders else None
    discount_status = (
        "Доступна скидка 7% на первый заказ (до 3000 ₽)"
        if total_orders == 0
        else "Скидка новичка уже использована — теперь копим бонусы"
    )
    profile_lines = [
        f"👤 <b>Профиль {html.escape(user.first_name or user.full_name or '')}</b>",
        "",
        f"Статус: {'Новичок' if total_orders == 0 else 'Постоянный клиент'}",
        f"Заказов: {total_orders} на {total_spent} ₽",
        f"Бонусный счёт: {bonus_balance} ₽",
        f"Рефералов: {len(referrals)} (по {REFERRAL_BONUS_AMOUNT} ₽ за каждого)",
        discount_status,
    ]
    if last_order:
        profile_lines.extend(
            [
                "",
                f"Последний заказ #{last_order.get('order_id')}: {order_type_name_from_record(last_order)}",
                f"Статус: {last_order.get('status', 'в работе')}",
                f"Срок: {last_order.get('deadline_date', '—')}",
            ]
        )
    profile_lines.extend(
        [
            "",
            f"Реферальная ссылка: {ref_link}",
            "Поделитесь ею — бонусы накапливаются автоматически.",
        ]
    )
    text = "\n".join(profile_lines)
    keyboard = [
        [InlineKeyboardButton("📋 Мои заказы", callback_data="profile:orders")],
        [InlineKeyboardButton("⭐ Оставить отзыв", callback_data="profile:feedback")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="main:root")],
    ]
    await update.callback_query.edit_message_text(
        text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return STATE_NAVIGATION


async def show_user_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not user:
        return STATE_NAVIGATION
    orders = store.get_orders(user.id)
    if not orders:
        text = "Пока нет заказов. Самое время оформить первый!"
    else:
        lines = []
        for order in orders[-10:]:
            name = order_type_name_from_record(order)
            attachments_count = len(order.get("attachments", []))
            discount_amount = int(order.get("discount", 0))
            lines.append(
                f"#{order.get('order_id')} — {name}\n"
                f"Тема: {order.get('topic')}\n"
                f"Срок: {order.get('deadline_date')}\n"
                f"Объём: {order.get('page_plan', '—')}\n"
                f"Статус: {order.get('status', 'в работе')}\n"
                f"Сумма: {order.get('price', 0)} ₽ (скидка {discount_amount} ₽)\n"
                f"Файлов: {attachments_count}\n"
            )
        text = "\n".join(lines) + "\nЕсли появились новые файлы или вопросы — ответьте на это сообщение, и менеджер свяжется."
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="main:profile")]]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return STATE_NAVIGATION


async def request_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.edit_message_text(
        "Поделитесь впечатлениями о нашей работе. Отзыв увидит администратор и подарит бонусы!"
    )
    return STATE_FEEDBACK


async def receive_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    feedback = update.message.text.strip()
    user = update.effective_user
    if not feedback:
        await update.message.reply_text("Отзыв не может быть пустым. Попробуйте еще раз.")
        return STATE_FEEDBACK
    store.add_feedback(user.id, feedback)
    log_user_action(update, "feedback_left")
    await update.message.reply_text("Спасибо! Мы ценим обратную связь — менеджер ответит в ближайшее время.")
    for admin_chat_id in store.get_notification_chat_ids():
        try:
            await context.bot.send_message(
                admin_chat_id,
                f"Новый отзыв от {user.id} ({user.username or user.full_name}):\n{feedback}",
            )
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to send feedback to admin %s: %s", admin_chat_id, exc)
    return await show_main_menu(update, context)


async def show_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton(item["question"], callback_data=f"faq:item:{idx}")]
        for idx, item in enumerate(FAQ_ITEMS)
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="main:root")])
    await update.callback_query.edit_message_text(
        "Частые вопросы. Выберите интересующий пункт:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return STATE_NAVIGATION


async def show_faq_item(update: Update, idx: int) -> int:
    if idx < 0 or idx >= len(FAQ_ITEMS):
        await update.callback_query.edit_message_text("Вопрос не найден.")
        return STATE_NAVIGATION
    item = FAQ_ITEMS[idx]
    keyboard = [
        [InlineKeyboardButton("⬅️ Назад", callback_data="main:faq")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="main:root")],
    ]
    await update.callback_query.edit_message_text(
        f"❓ <b>{item['question']}</b>\n\n{item['answer']}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return STATE_NAVIGATION

async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await ensure_owner_access(update, context):
        return STATE_NAVIGATION
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton("📋 Последние заказы", callback_data="admin:orders")],
        [InlineKeyboardButton("💰 Режим ценообразования", callback_data="admin:pricing")],
        [InlineKeyboardButton("🎁 Бонусы и рефералы", callback_data="admin:bonuses")],
        [InlineKeyboardButton("📤 Экспорт в Excel", callback_data="admin:export")],
        [InlineKeyboardButton("♻️ Обновить статус", callback_data="admin:status_list")],
        [InlineKeyboardButton("🗂 Последние действия", callback_data="admin:logs")],
        [InlineKeyboardButton("🔄 Перезапустить бота", callback_data="admin:restart")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="main:root")],
    ]
    text = "🔐 Админ-панель. Выберите действие:"
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return STATE_NAVIGATION


async def restart_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await ensure_owner_access(update, context):
        return STATE_NAVIGATION
    user = update.effective_user
    source = "callback" if update.callback_query else "command"
    notify_text = "Перезапускаю бота. Он вернётся через несколько секунд."
    if update.callback_query:
        await update.callback_query.answer("Перезапускаю…")
        await context.bot.send_message(chat_id=user.id, text=notify_text)
    elif update.message:
        await update.message.reply_text(notify_text)
    logger.warning("Restart requested by admin %s via %s", user.id, source)
    schedule_restart()
    return STATE_NAVIGATION


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    log_user_action(update, "admin_command")
    return await show_admin_menu(update, context)


async def admin_show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await ensure_owner_access(update, context):
        return STATE_NAVIGATION
    stats = store.get_statistics()
    text = (
        "📊 <b>Сводка по заказам</b>\n\n"
        f"Всего заказов: {stats['orders']}\n"
        f"Активных заказов: {stats['active']}\n"
        f"Выручка: {stats['revenue']} ₽\n"
        f"Клиентов: {stats['users']}\n"
        f"Рефералов: {stats['referrals']}\n"
        f"Начислено бонусов: {stats['bonuses']} ₽"
    )
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin:menu")]]))
    return STATE_NAVIGATION


async def admin_show_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await ensure_owner_access(update, context):
        return STATE_NAVIGATION
    records = [order for orders in store.orders.values() for order in orders]
    records = sorted(records, key=lambda item: item.get("created_at", ""), reverse=True)[:10]
    if not records:
        text = "Заказов пока нет."
    else:
        lines = []
        for record in records:
            name = order_type_name_from_record(record)
            base_amount = int(record.get("base_price", record.get("price", 0)))
            discount_amount = int(record.get("discount", 0))
            final_amount = int(record.get("price", 0))
            attachments_count = len(record.get("attachments", []))
            upsell_titles = [
                UPSELL_OPTIONS.get(key, {}).get("title", key)
                for key in record.get("upsells", [])
            ]
            lines.append(
                f"#{record.get('order_id')} — {name}\n"
                f"Тема: {record.get('topic')}\n"
                f"Объём: {record.get('page_plan', '—')}\n"
                f"Опции: {', '.join(upsell_titles) if upsell_titles else 'нет'}\n"
                f"Статус: {record.get('status', 'в работе')}\n"
                f"Сумма: {final_amount} ₽ (база {base_amount} ₽, скидка {discount_amount} ₽)\n"
                f"Файлы: {attachments_count}\n"
            )
        text = "\n".join(lines)
    await update.callback_query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin:menu")]])
    )
    return STATE_NAVIGATION


async def admin_request_pricing_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await ensure_owner_access(update, context):
        return STATE_NAVIGATION
    context.user_data["admin_state"] = "pricing_mode"
    await update.callback_query.edit_message_text(
        f"Текущий режим: {store.get_pricing_mode()}. Введите hard или light:",
    )
    return STATE_ADMIN


async def admin_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await ensure_owner_access(update, context):
        return STATE_NAVIGATION
    path = store.export_orders()
    if not path:
        await update.callback_query.edit_message_text(
            "Нет данных для экспорта.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin:menu")]])
        )
        return STATE_NAVIGATION
    await update.callback_query.edit_message_text("Отправляю файл с заказами…")
    try:
        owner_chat_id = store.get_owner_chat_id()
        if owner_chat_id:
            await context.bot.send_document(owner_chat_id, document=path.open("rb"))
    finally:
        path.unlink(missing_ok=True)
    await update.callback_query.edit_message_text(
        "Экспорт заказов успешно отправлен ✅",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin:menu")]]),
    )
    return STATE_NAVIGATION


async def admin_show_bonuses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await ensure_owner_access(update, context):
        return STATE_NAVIGATION
    stats = store.list_referral_stats()
    if not stats:
        text = "Бонусов пока нет. Делитесь реферальной ссылкой из профиля клиентов."
    else:
        lines = [
            f"{entry['user_id']}: приглашений {entry['count']}, бонусов {entry['bonus']} ₽"
            for entry in stats[:10]
        ]
        text = "\n".join(lines)
        text += f"\n\nБонус за реферала: {REFERRAL_BONUS_AMOUNT} ₽."
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin:menu")]]),
    )
    return STATE_NAVIGATION


async def admin_show_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await ensure_owner_access(update, context):
        return STATE_NAVIGATION
    last_logs = []
    for user_id, logs in store.user_logs.items():
        if logs:
            last_logs.append((user_id, logs[-1]))
    if not last_logs:
        text = "Логи пока пусты."
    else:
        lines = [
            f"{user_id}: {entry['action']} ({entry['timestamp']})"
            for user_id, entry in last_logs[-10:]
        ]
        text = "\n".join(lines)
    await update.callback_query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin:menu")]])
    )
    return STATE_NAVIGATION


async def admin_list_status_targets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await ensure_owner_access(update, context):
        return STATE_NAVIGATION
    records = store.list_recent_orders(limit=12)
    if not records:
        await update.callback_query.edit_message_text(
            "Заказов пока нет.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin:menu")]]),
        )
        return STATE_NAVIGATION
    keyboard: List[List[InlineKeyboardButton]] = []
    for record in records:
        order_id = int(record.get("order_id", 0))
        user_id = int(record.get("user_id", 0))
        name = order_type_name_from_record(record)
        status_key = str(record.get("status_key", "")) or "new"
        status_label = record.get("status") or ORDER_STATUS_TITLES.get(status_key, "—")
        label = f"#{order_id} — {name} ({status_label})"
        if len(label) > 60:
            label = label[:57] + "…"
        callback = f"admin:status_select:{user_id}:{order_id}"
        keyboard.append([InlineKeyboardButton(label, callback_data=callback)])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin:menu")])
    await update.callback_query.edit_message_text(
        "Выберите заказ, чтобы обновить статус:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return STATE_NAVIGATION


async def admin_select_status(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, order_id: int
) -> int:
    if not await ensure_owner_access(update, context):
        return STATE_NAVIGATION
    context.user_data["admin_status_target"] = {"user_id": user_id, "order_id": order_id}
    record = store.get_order(user_id, order_id)
    if record is None:
        # Запросили несуществующий заказ, возвращаемся к списку.
        context.user_data.pop("admin_status_target", None)
        await update.callback_query.edit_message_text(
            "Заказ не найден. Возможно, он был удален.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin:status_list")]]),
        )
        return STATE_NAVIGATION
    original_status_key = str(record.get("status_key", "new") or "new")
    original_status_title = record.get("status") or ORDER_STATUS_TITLES.get(original_status_key, "—")
    order_name = order_type_name_from_record(record)
    keyboard = [
        [InlineKeyboardButton(title, callback_data=f"admin:status_apply:{key}")]
        for key, title in ORDER_STATUS_TITLES.items()
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin:status_list")])
    text = (
        f"Заказ #{order_id} — {order_name}\n"
        f"Текущий статус: {original_status_title}\n"
        "Выберите новый статус:"
    )
    await update.callback_query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return STATE_NAVIGATION


async def admin_apply_status(
    update: Update, context: ContextTypes.DEFAULT_TYPE, status_key: str
) -> int:
    if not await ensure_owner_access(update, context):
        return STATE_NAVIGATION
    target = context.user_data.get("admin_status_target")
    if not target:
        return await admin_list_status_targets(update, context)
    user_id = int(target.get("user_id", 0))
    order_id = int(target.get("order_id", 0))
    status_title = ORDER_STATUS_TITLES.get(status_key, status_key)
    record = store.update_order_status(user_id, order_id, status_key, status_title)
    if not record:
        await update.callback_query.edit_message_text(
            "Не удалось обновить статус (заказ не найден).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin:status_list")]]),
        )
        return STATE_NAVIGATION
    log_user_action(update, f"admin_status:{order_id}:{status_key}")
    await update.callback_query.edit_message_text(
        f"Статус заказа #{order_id} обновлен: {status_title}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ В меню", callback_data="admin:menu")]]),
    )
    try:
        await context.bot.send_message(
            user_id,
            (
                f"Статус вашего заказа #{order_id}: {status_title}.\n"
                f"Если нужно обсудить детали — ответьте на это сообщение или пишите {MANAGER_CONTACT_LINK}."
            ),
        )
    except Exception as exc:  # pragma: no cover - зависит от Telegram API
        logger.warning("Could not notify user %s about status change: %s", user_id, exc)
    context.user_data.pop("admin_status_target", None)
    return STATE_NAVIGATION


async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await ensure_owner_access(update, context):
        return STATE_NAVIGATION
    state = context.user_data.pop("admin_state", None)
    if state == "pricing_mode":
        choice = update.message.text.strip().lower()
        if choice not in {"hard", "light"}:
            context.user_data["admin_state"] = "pricing_mode"
            await update.message.reply_text("Пожалуйста, введите hard или light.")
            return STATE_ADMIN
        store.set_pricing_mode(choice)
        await update.message.reply_text(f"Режим установлен: {choice}")
        return await show_admin_menu(update, context)
    await update.message.reply_text("Команда не распознана. Используйте кнопки в меню.")
    return STATE_ADMIN

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    log_user_action(update, f"callback:{data}")
    if data == "main:root":
        return await show_main_menu(update, context)
    if data == "main:order" or data == "order:list":
        return await show_order_types(update, context)
    if data.startswith("order:type:"):
        key = data.split(":", maxsplit=2)[2]
        return await show_order_details(update, key)
    if data.startswith("order:new:"):
        key = data.split(":", maxsplit=2)[2]
        return await prompt_order_topic(update, context, key)
    if data.startswith("order:deadline:"):
        days = int(data.split(":", maxsplit=2)[2])
        return await handle_deadline(update, context, days)
    if data.startswith("order:pages:"):
        key = data.split(":", maxsplit=2)[2]
        return await handle_page_selection(update, context, key)
    if data.startswith("order:upsell:"):
        key = data.split(":", maxsplit=2)[2]
        if key:
            return await toggle_upsell(update, context, key)
    if data == "order:upsell":
        return await show_upsell_menu(update, context)
    if data == "order:summary":
        return await show_order_summary_step(update, context)
    if data == "order:req_finish":
        return await finish_requirements(update, context)
    if data == "order:confirm":
        return await confirm_order(update, context)
    if data == "order:cancel":
        return await cancel_order(update, context)
    if data == "main:prices":
        return await show_price_list(update, context)
    if data.startswith("prices:detail:"):
        key = data.split(":", maxsplit=2)[2]
        return await show_price_detail(update, key)
    if data == "main:calculator":
        return await show_calculator(update, context)
    if data.startswith("calc:type:"):
        key = data.split(":", maxsplit=2)[2]
        return await calculator_select_deadline(update, context, key)
    if data.startswith("calc:deadline:"):
        days = int(data.split(":", maxsplit=2)[2])
        return await calculator_select_pages(update, context, days)
    if data.startswith("calc:pages:"):
        key = data.split(":", maxsplit=2)[2]
        return await show_calculation_result(update, context, key)
    if data == "main:profile" or data == "profile:back":
        return await show_profile(update, context)
    if data == "profile:orders":
        return await show_user_orders(update, context)
    if data == "profile:feedback":
        return await request_feedback(update, context)
    if data == "main:faq":
        return await show_faq(update, context)
    if data.startswith("faq:item:"):
        idx = int(data.split(":", maxsplit=2)[2])
        return await show_faq_item(update, idx)
    if data == "admin:menu":
        return await show_admin_menu(update, context)
    if data == "admin:stats":
        return await admin_show_stats(update, context)
    if data == "admin:orders":
        return await admin_show_orders(update, context)
    if data == "admin:pricing":
        return await admin_request_pricing_mode(update, context)
    if data == "admin:export":
        return await admin_export(update, context)
    if data == "admin:bonuses":
        return await admin_show_bonuses(update, context)
    if data == "admin:logs":
        return await admin_show_logs(update, context)
    if data == "admin:restart":
        return await restart_bot(update, context)
    if data == "admin:status_list":
        return await admin_list_status_targets(update, context)
    if data.startswith("admin:status_select:"):
        try:
            _, _, user_str, order_str = data.split(":", maxsplit=3)
            return await admin_select_status(update, context, int(user_str), int(order_str))
        except (ValueError, IndexError):
            await update.callback_query.answer("Не удалось распознать заказ", show_alert=True)
            return STATE_NAVIGATION
    if data.startswith("admin:status_apply:"):
        status_key = data.split(":", maxsplit=2)[2]
        return await admin_apply_status(update, context, status_key)
    await query.edit_message_text("Команда не распознана. Возвращаюсь в меню.")
    return await show_main_menu(update, context)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    log_user_action(update, "start")
    user = update.effective_user
    context.user_data.pop("order_draft", None)
    promoted_text = ""
    owner_chat_id = store.get_owner_chat_id()
    if user and owner_chat_id == 0:
        store.set_owner_chat_id(user.id, user.username or user.full_name or "")
        owner_chat_id = user.id
        promoted_text = (
            "\n\nВы назначены администратором бота. Используйте /admin для управления заказами."
        )
    if context.args:
        payload = context.args[0]
        if payload.isdigit():
            referrer_id = int(payload)
            if referrer_id != user.id and store.add_referral(referrer_id, user.id):
                for admin_id in store.get_notification_chat_ids():
                    try:
                        await context.bot.send_message(
                            admin_id,
                            f"Новый реферал: {user.id} (пригласил {referrer_id})",
                        )
                    except Exception as exc:  # pragma: no cover
                        logger.error(
                            "Failed to notify admin %s about referral: %s",
                            admin_id,
                            exc,
                        )
                try:
                    bonus_info = store.get_bonus_info(referrer_id)
                    await context.bot.send_message(
                        referrer_id,
                        (
                            f"🔥 Ваша ссылка сработала! +{REFERRAL_BONUS_AMOUNT} ₽ на бонусный счёт.\n"
                            f"Баланс: {bonus_info.get('balance', 0)} ₽."
                        ),
                    )
                except Exception as exc:  # pragma: no cover
                    logger.warning("Не удалось уведомить реферера %s: %s", referrer_id, exc)
    greeting = (
        f"👋 Привет, {html.escape(user.first_name or user.full_name or 'друг')}!\n\n"
        "Я помогу оформить любую учебную работу: от самостоятельной до магистерской."
    )
    if WELCOME_MESSAGE:
        greeting += f"\n{WELCOME_MESSAGE}"
    existing_orders = store.get_orders(user.id)
    if not existing_orders:
        greeting += "\n🎁 На первый заказ действует скидка 7% (до 3000 ₽)."
    if promoted_text:
        greeting += promoted_text
    if update.message:
        await update.message.reply_text(greeting)
    return await show_main_menu(update, context, "Готовы сделать заказ?")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Используйте /start для перехода к главному меню.\n"
        "Кнопка '📝 Сделать заказ' запустит пошаговое оформление с возможностью прикреплять файлы.\n"
        "Команды /done и /skip доступны на этапе требований.\n"
        "Команда /cancel завершит текущий процесс."
    )
    await update.message.reply_text(text)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await cancel_order(update, context)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error: %s", context.error)
    for admin_chat_id in store.get_notification_chat_ids():
        try:
            await context.bot.send_message(admin_chat_id, f"Ошибка в боте: {context.error}")
        except Exception:  # pragma: no cover
            pass


def build_application():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            STATE_NAVIGATION: [CallbackQueryHandler(handle_callback)],
            STATE_ORDER_TOPIC: [
                CallbackQueryHandler(handle_callback),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_topic),
            ],
            STATE_ORDER_PAGES: [CallbackQueryHandler(handle_callback)],
            STATE_ORDER_REQUIREMENTS: [
                CallbackQueryHandler(handle_callback),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_requirements),
                 MessageHandler(filters.ATTACHMENT, handle_requirement_attachment),
                CommandHandler("skip", skip_requirements),
                CommandHandler("done", finish_requirements),
            ],
            STATE_FEEDBACK: [
                CallbackQueryHandler(handle_callback),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_feedback),
            ],
            STATE_ADMIN: [
                CallbackQueryHandler(handle_callback),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command), CommandHandler("start", start)],
        allow_reentry=True,
    )
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("restart_bot", restart_bot))
    application.add_error_handler(error_handler)
    return application


def main() -> None:
    application = build_application()
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
