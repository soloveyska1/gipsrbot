from __future__ import annotations

import asyncio
import html
import json
import logging
import os
from dataclasses import dataclass, asdict
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
    DEFAULT_ADMIN_USERNAME,
    DEFAULT_PRICING_MODE,
    MANAGER_CONTACT_URL as CONFIG_MANAGER_CONTACT_URL,
    ORDER_STATUS_TITLES,
    WELCOME_MESSAGE,
)

load_dotenv()

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or BOT_TOKEN or "").strip()

admin_id_env = os.getenv("ADMIN_CHAT_ID")
try:
    ADMIN_CHAT_ID_DEFAULT = (
        int(admin_id_env) if admin_id_env is not None else int(CONFIG_ADMIN_CHAT_ID)
    )
except ValueError:
    ADMIN_CHAT_ID_DEFAULT = int(CONFIG_ADMIN_CHAT_ID)

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
    "self": {"base": 1500, "min": 1500, "max": 3500},
    "course_theory": {"base": 7000, "min": 6000, "max": 11000},
    "course_empirical": {"base": 11000, "min": 9500, "max": 16000},
    "vkr": {"base": 32000, "min": 28000, "max": 45000},
    "master": {"base": 42000, "min": 36000, "max": 60000},
}

ORDER_TYPES: Dict[str, Dict[str, object]] = {
    "self": {
        "name": "Самостоятельная работа",
        "icon": "📝",
        "description": "Быстрые задания: эссе, контрольные, отчеты. Выполняем качественно и в срок.",
        "details": "Лучший выбор для работ до 20 страниц. Подбираем автора по предмету и требованиям.",
        "examples": [
            "Эссе по философии",
            "Контрольная по экономике",
            "Реферат по истории",
        ],
    },
    "course_theory": {
        "name": "Курсовая (теория)",
        "icon": "📘",
        "description": "Теоретическая курсовая с глубоким обзором литературы и четкой структурой.",
        "details": "Формируем оглавление, методологию и источники по стандартам вашего вуза.",
        "examples": [
            "История экономических учений",
            "Методики преподавания",
            "Психология личности",
        ],
    },
    "course_empirical": {
        "name": "Курсовая (теория + эмпирика)",
        "icon": "📊",
        "description": "Курсовая с практической частью, опросами, анализом данных и выводами.",
        "details": "Подготовим инструментарий, соберем данные и оформим аналитическую главу.",
        "examples": [
            "Опрос удовлетворенности клиентов",
            "Анализ HR-процессов",
            "Исследование маркетинговых стратегий",
        ],
    },
    "vkr": {
        "name": "Дипломная работа (ВКР)",
        "icon": "🎓",
        "description": "Полный цикл подготовки выпускной квалификационной работы.",
        "details": "План, теория, эмпирика, презентация и речь. Поддержка до защиты.",
        "examples": [
            "Социально-психологическая адаптация",
            "Бизнес-план компании",
            "Маркетинговая стратегия бренда",
        ],
    },
    "master": {
        "name": "Магистерская диссертация",
        "icon": "🔍",
        "description": "Продвинутое исследование с научной новизной и публикациями.",
        "details": "Разработаем методологию, проведем исследование, подготовим статьи и презентацию.",
        "examples": [
            "Data-driven подходы в образовании",
            "Инновации в социальной работе",
            "Комплексные исследования экологии",
        ],
    },
}

FAQ_ITEMS: List[Dict[str, str]] = [
    {
        "question": "Как сделать заказ?",
        "answer": "Выберите '📝 Сделать заказ', укажите тип работы, тему, срок и требования. Менеджер свяжется для подтверждения.",
    },
    {
        "question": "Как рассчитывается стоимость?",
        "answer": "Стоимость зависит от типа, срочности и сложности. Воспользуйтесь разделом '🧮 Калькулятор' для точного расчета.",
    },
    {
        "question": "Какие гарантии предоставляете?",
        "answer": "Проверяем работы на антиплагиат, делаем бесплатные правки 14 дней и сопровождаем до успешной защиты.",
    },
    {
        "question": "Есть ли скидки?",
        "answer": "Первые клиенты получают -10%, за несколько заказов действуют дополнительные скидки и бонусы.",
    },
    {
        "question": "Как работает реферальная программа?",
        "answer": "Поделитесь персональной ссылкой из профиля. За каждого приглашенного друга — 5% бонусов.",
    },
    {
        "question": "Как отслеживать статус заказа?",
        "answer": "Все статусы видны в профиле, плюс менеджер отправляет промежуточные отчеты и уведомления.",
    },
]

UPSELL_OPTIONS: Dict[str, Dict[str, int]] = {
    "prez": {"title": "Презентация", "price": 2000},
    "speech": {"title": "Речь для защиты", "price": 1000},
}

SETTINGS_FILE = DATA_DIR / "settings.json"
PRICES_FILE = DATA_DIR / "prices.json"
REFERRALS_FILE = DATA_DIR / "referrals.json"
ORDERS_FILE = DATA_DIR / "orders.json"
FEEDBACKS_FILE = DATA_DIR / "feedbacks.json"
USER_LOGS_FILE = DATA_DIR / "user_logs.json"


@dataclass
class OrderRecord:
    order_id: int
    type_key: str
    topic: str
    deadline_days: int
    deadline_date: str
    requirements: str
    upsells: List[str]
    status_key: str
    price: int
    status: str
    created_at: str


class DataStore:
    def __init__(self) -> None:
        default_settings = {
            "pricing_mode": DEFAULT_PRICING_MODE,
            "admin_chat_id": ADMIN_CHAT_ID_DEFAULT,
            "admin_username": DEFAULT_ADMIN_USERNAME,
            "manager_contact_url": MANAGER_CONTACT_LINK,
        }
        loaded_settings = self._load_json(SETTINGS_FILE, default_settings)
        changed = False
        for key, value in default_settings.items():
            if key not in loaded_settings:
                loaded_settings[key] = value
                changed = True
        if changed:
            self._save_json(SETTINGS_FILE, loaded_settings)
        self.settings: Dict[str, object] = loaded_settings
        self.prices: Dict[str, Dict[str, int]] = self._load_json(PRICES_FILE, DEFAULT_PRICES)
        self.referrals: Dict[str, List[int]] = self._load_json(REFERRALS_FILE, {})
        self.orders: Dict[str, List[Dict[str, object]]] = self._load_json(ORDERS_FILE, {})
        self.feedbacks: Dict[str, List[str]] = self._load_json(FEEDBACKS_FILE, {})
        self.user_logs: Dict[str, List[Dict[str, str]]] = self._load_json(USER_LOGS_FILE, {})

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

    def get_admin_chat_id(self) -> int:
        try:
            return int(self.settings.get("admin_chat_id", 0))
        except (TypeError, ValueError):
            return 0

    def set_admin_chat_id(self, chat_id: int, username: Optional[str] = None) -> None:
        self.settings["admin_chat_id"] = int(chat_id)
        if username is not None:
            self.settings["admin_username"] = username or ""
        self._save_json(SETTINGS_FILE, self.settings)

    def get_admin_username(self) -> str:
        return str(self.settings.get("admin_username", "") or "")

    def get_manager_contact(self) -> str:
        return str(self.settings.get("manager_contact_url", MANAGER_CONTACT_LINK))

    def add_referral(self, referrer_id: int, new_user_id: int) -> bool:
        referrer_key = str(referrer_id)
        referred_list = self.referrals.setdefault(referrer_key, [])
        if new_user_id in referred_list:
            return False
        referred_list.append(new_user_id)
        self._save_json(REFERRALS_FILE, self.referrals)
        return True

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
        return {
            "orders": total_orders,
            "revenue": total_revenue,
            "active": active_orders,
            "users": unique_users,
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


STATE_NAVIGATION, STATE_ORDER_TOPIC, STATE_ORDER_REQUIREMENTS, STATE_FEEDBACK, STATE_ADMIN = range(5)


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


def calculate_price(order_type: str, days_left: int, complexity: float = 1.0, upsells: Iterable[str] = ()) -> int:
    price_info = store.prices.get(order_type) or DEFAULT_PRICES.get(order_type)
    if not price_info:
        logger.warning("Unknown order type for pricing: %s", order_type)
        return 0
    price = int(price_info.get("base", 0) * complexity)
    mode = store.get_pricing_mode()
    if mode == "hard":
        if days_left < 7:
            price = int(price * 1.3)
        elif days_left < 15:
            price = int(price * 1.15)
    else:
        if days_left < 3:
            price = int(price * 1.3)
        elif days_left < 7:
            price = int(price * 1.15)
    for upsell in upsells:
        option = UPSELL_OPTIONS.get(upsell)
        if option:
            price += option["price"]
    return price


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


def format_order_summary(draft: Dict[str, object], price: int) -> str:
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
    return (
        f"<b>Проверим данные перед оформлением:</b>\n\n"
        f"Тип: {order_type.get('icon', '')} {order_type.get('name', 'Неизвестно')}\n"
        f"Тема: {html.escape(str(draft.get('topic', 'не указана')))}\n"
        f"Срок: {deadline_days} дн. (до {deadline_date})\n"
        f"Требования: {html.escape(str(draft.get('requirements', 'не указаны')))}\n"
        f"Доп. услуги: {upsell_text}\n\n"
        f"Итого к оплате: <b>{price} ₽</b>"
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
    message_text = text or "Выберите нужный раздел 👇"
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
    text = "Выберите срок сдачи. Чем больше времени — тем выгоднее стоимость."
    today = datetime.now()
    keyboard: List[List[InlineKeyboardButton]] = []
    for days in (3, 7, 14, 21, 30):
        deadline = today + timedelta(days=days)
        keyboard.append(
            [InlineKeyboardButton(f"{deadline:%d.%m} ({days} дн.)", callback_data=f"order:deadline:{days}")]
        )
    keyboard.append([InlineKeyboardButton("⬅️ Отмена", callback_data="order:cancel")])
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=markup)
    return STATE_NAVIGATION


async def handle_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE, days: int) -> int:
    draft = get_order_draft(context)
    draft["deadline_days"] = days
    query = update.callback_query
    await query.edit_message_text(
        "Расскажите дополнительные требования и пожелания сообщением. Если их нет — нажмите /skip",
    )
    return STATE_ORDER_REQUIREMENTS


async def receive_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = get_order_draft(context)
    draft["requirements"] = update.message.text.strip()
    log_user_action(update, "order_requirements_set")
    return await show_upsell_menu(update, context)


async def skip_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    draft = get_order_draft(context)
    draft["requirements"] = "Нет"
    return await show_upsell_menu(update, context)


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
            "Хотите добавить дополнительные материалы? Презентация или речь экономят время на подготовке!",
            reply_markup=build_upsell_keyboard(selected),
        )
    else:
        query = update.callback_query
        await query.edit_message_text(
            "Хотите добавить дополнительные материалы?",
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
    if "topic" not in draft or "deadline_days" not in draft:
        return await show_main_menu(update, context, "Начните оформление заказа заново.")
    upsells = list(draft.get("upsells", set()))
    draft["upsells"] = upsells
    price = calculate_price(draft["type_key"], int(draft["deadline_days"]), 1.0, upsells)
    draft["price"] = price
    text = format_order_summary(draft, price)
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
    order = OrderRecord(
        order_id=order_id,
        type_key=str(draft.get("type_key")),
        topic=str(draft.get("topic", "")),
        deadline_days=deadline_days,
        deadline_date=deadline_date,
        requirements=str(draft.get("requirements", "")),
        upsells=list(draft.get("upsells", [])),
        status_key="new",
        price=int(draft.get("price", 0)),
        status=ORDER_STATUS_TITLES.get("new", "новый"),
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    store.add_order(user.id, order)
    log_user_action(update, f"order_confirmed:{order.order_id}")
    context.user_data.pop("order_draft", None)
    text = (
        f"Спасибо! Заказ #{order.order_id} оформлен.\n"
        f"Менеджер свяжется с вами в ближайшее время. Статус можно отслеживать в профиле."
    )
    query = update.callback_query
    await query.edit_message_text(text)
    admin_chat_id = store.get_admin_chat_id()
    if admin_chat_id:
        order_type = order_type_name_from_key(order.type_key)
        admin_text = (
            f"Новый заказ #{order.order_id}\n"
            f"Пользователь: {user.id} ({user.username or user.full_name})\n"
            f"Тип: {order_type}\n"
            f"Тема: {order.topic}\n"
            f"Срок: {order.deadline_days} дн. (до {order.deadline_date})\n"
            f"Сумма: {order.price} ₽"
        )
        try:
            await context.bot.send_message(admin_chat_id, admin_text)
        except Exception as exc:  # pragma: no cover - depends on Telegram API
            logger.error("Failed to notify admin: %s", exc)
    return await show_main_menu(update, context, "Хотите оформить еще одну работу?")

async def show_price_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    log_user_action(update, "open_price_list")
    rows = []
    for key, info in ORDER_TYPES.items():
        price_info = store.prices.get(key, DEFAULT_PRICES[key])
        rows.append(f"{info['icon']} <b>{info['name']}</b> — от {price_info['base']} ₽")
    text = "💰 <b>Прайс-лист</b>\n\n" + "\n".join(rows)
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
        f"<b>Примеры:</b> {html.escape(', '.join(info.get('examples', [])))}"
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
    for days in (3, 7, 14, 21, 30):
        keyboard.append([InlineKeyboardButton(f"{days} дней", callback_data=f"calc:deadline:{days}")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="main:calculator")])
    await update.callback_query.edit_message_text(
        "Выберите срок выполнения:", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return STATE_NAVIGATION


async def calculator_select_complexity(update: Update, context: ContextTypes.DEFAULT_TYPE, days: int) -> int:
    context.user_data.setdefault("calculator", {})["deadline"] = days
    keyboard = [
        [InlineKeyboardButton("Базовая", callback_data="calc:complexity:1.0")],
        [
            InlineKeyboardButton("Средняя (+10%)", callback_data="calc:complexity:1.1"),
            InlineKeyboardButton("Сложная (+30%)", callback_data="calc:complexity:1.3"),
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main:calculator")],
    ]
    await update.callback_query.edit_message_text(
        "Выберите сложность темы:", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return STATE_NAVIGATION


async def show_calculation_result(update: Update, context: ContextTypes.DEFAULT_TYPE, complexity: float) -> int:
    data = context.user_data.get("calculator", {})
    type_key = data.get("type")
    days = int(data.get("deadline", 14))
    if not type_key:
        return await show_calculator(update, context)
    price = calculate_price(type_key, days, complexity)
    info = ORDER_TYPES.get(type_key, {})
    text = (
        f"Расчет для {info.get('icon', '')} <b>{info.get('name', 'работы')}</b>\n"
        f"Срок: {days} дней\n"
        f"Сложность: {int((complexity - 1) * 100)}%\n\n"
        f"Примерная стоимость: <b>{price} ₽</b>\n\n"
        f"Хотите оформить заказ прямо сейчас?"
    )
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
    bot_username = await get_bot_username(context)
    ref_link = f"https://t.me/{bot_username}?start={user.id}" if bot_username else "—"
    text = (
        f"👤 <b>Профиль {html.escape(user.first_name or user.full_name or '')}</b>\n\n"
        f"Заказов: {total_orders}\n"
        f"На сумму: {total_spent} ₽\n"
        f"Рефералов: {len(referrals)}\n"
        f"Реферальная ссылка: {ref_link}\n\n"
        "Приглашайте друзей и получайте бонусы!"
    )
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
            lines.append(
                f"#{order.get('order_id')} — {name}\n"
                f"Тема: {order.get('topic')}\n"
                f"Срок: {order.get('deadline_date')}\n"
                f"Статус: {order.get('status', 'в работе')}\n"
            )
        text = "\n".join(lines)
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
    await update.message.reply_text("Спасибо! Мы ценим обратную связь.")
    admin_chat_id = store.get_admin_chat_id()
    if admin_chat_id:
        try:
            await context.bot.send_message(
                admin_chat_id,
                f"Новый отзыв от {user.id} ({user.username or user.full_name}):\n{feedback}",
            )
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to send feedback to admin: %s", exc)
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
    user = update.effective_user
    admin_chat_id = store.get_admin_chat_id()
    if not user or user.id != admin_chat_id:
        if update.message:
            await update.message.reply_text("Админ-панель доступна только владельцу бота.")
        elif update.callback_query:
            await update.callback_query.answer("Нет доступа", show_alert=True)
        return STATE_NAVIGATION
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="admin:stats")],
        [InlineKeyboardButton("📋 Последние заказы", callback_data="admin:orders")],
        [InlineKeyboardButton("💰 Режим ценообразования", callback_data="admin:pricing")],
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
    user = update.effective_user
    admin_chat_id = store.get_admin_chat_id()
    if not user or user.id != admin_chat_id:
        if update.message:
            await update.message.reply_text("Команда доступна только администратору.")
        elif update.callback_query:
            await update.callback_query.answer("Нет доступа", show_alert=True)
        return STATE_NAVIGATION
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


async def admin_show_stats(update: Update) -> int:
    stats = store.get_statistics()
    text = (
        "📊 <b>Сводка по заказам</b>\n\n"
        f"Всего заказов: {stats['orders']}\n"
        f"Активных заказов: {stats['active']}\n"
        f"Выручка: {stats['revenue']} ₽\n"
        f"Клиентов: {stats['users']}"
    )
    await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin:menu")]]))
    return STATE_NAVIGATION


async def admin_show_orders(update: Update) -> int:
    records = [order for orders in store.orders.values() for order in orders]
    records = sorted(records, key=lambda item: item.get("created_at", ""), reverse=True)[:10]
    if not records:
        text = "Заказов пока нет."
    else:
        lines = []
        for record in records:
            name = order_type_name_from_record(record)
            lines.append(
                f"#{record.get('order_id')} — {name}\n"
                f"Тема: {record.get('topic')}\n"
                f"Статус: {record.get('status', 'в работе')}\n"
                f"Цена: {record.get('price')} ₽\n"
            )
        text = "\n".join(lines)
    await update.callback_query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin:menu")]])
    )
    return STATE_NAVIGATION


async def admin_request_pricing_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["admin_state"] = "pricing_mode"
    await update.callback_query.edit_message_text(
        f"Текущий режим: {store.get_pricing_mode()}. Введите hard или light:",
    )
    return STATE_ADMIN


async def admin_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    path = store.export_orders()
    if not path:
        await update.callback_query.edit_message_text(
            "Нет данных для экспорта.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin:menu")]])
        )
        return STATE_NAVIGATION
    await update.callback_query.edit_message_text("Отправляю файл с заказами…")
    try:
        admin_chat_id = store.get_admin_chat_id()
        if admin_chat_id:
            await context.bot.send_document(admin_chat_id, document=path.open("rb"))
    finally:
        path.unlink(missing_ok=True)
    await update.callback_query.edit_message_text(
        "Экспорт заказов успешно отправлен ✅",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="admin:menu")]]),
    )
    return STATE_NAVIGATION


async def admin_show_logs(update: Update) -> int:
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
            f"Статус вашего заказа #{order_id}: {status_title}",
        )
    except Exception as exc:  # pragma: no cover - зависит от Telegram API
        logger.warning("Could not notify user %s about status change: %s", user_id, exc)
    context.user_data.pop("admin_status_target", None)
    return STATE_NAVIGATION


async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    if data.startswith("order:upsell:"):
        key = data.split(":", maxsplit=2)[2]
        if key:
            return await toggle_upsell(update, context, key)
    if data == "order:upsell":
        return await show_upsell_menu(update, context)
    if data == "order:summary":
        return await show_order_summary_step(update, context)
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
        return await calculator_select_complexity(update, context, days)
    if data.startswith("calc:complexity:"):
        complexity = float(data.split(":", maxsplit=2)[2])
        return await show_calculation_result(update, context, complexity)
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
        return await admin_show_stats(update)
    if data == "admin:orders":
        return await admin_show_orders(update)
    if data == "admin:pricing":
        return await admin_request_pricing_mode(update, context)
    if data == "admin:export":
        return await admin_export(update, context)
    if data == "admin:logs":
        return await admin_show_logs(update)
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
    admin_chat_id = store.get_admin_chat_id()
    if user and admin_chat_id == 0:
        store.set_admin_chat_id(user.id, user.username or user.full_name or "")
        admin_chat_id = user.id
        promoted_text = (
            "\n\nВы назначены администратором бота. Используйте /admin для управления заказами."
        )
    if context.args:
        payload = context.args[0]
        if payload.isdigit():
            referrer_id = int(payload)
            if referrer_id != user.id and store.add_referral(referrer_id, user.id):
                admin_id = store.get_admin_chat_id()
                if admin_id:
                    try:
                        await context.bot.send_message(
                            admin_id,
                            f"Новый реферал: {user.id} (пригласил {referrer_id})",
                        )
                    except Exception as exc:  # pragma: no cover
                        logger.error("Failed to notify admin about referral: %s", exc)
    greeting = (
        f"👋 Привет, {html.escape(user.first_name or user.full_name or 'друг')}!\n\n"
        "Я помогу оформить любую учебную работу: от самостоятельной до магистерской."
    )
    if WELCOME_MESSAGE:
        greeting += f"\n{WELCOME_MESSAGE}"
    if promoted_text:
        greeting += promoted_text
    if update.message:
        await update.message.reply_text(greeting)
    return await show_main_menu(update, context, "Готовы сделать заказ?")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "Используйте /start для перехода к главному меню.\n"
        "Кнопка '📝 Сделать заказ' запустит пошаговое оформление.\n"
        "Команда /cancel завершит текущий процесс."
    )
    await update.message.reply_text(text)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await cancel_order(update, context)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error: %s", context.error)
    admin_chat_id = store.get_admin_chat_id()
    if admin_chat_id:
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
            STATE_ORDER_REQUIREMENTS: [
                CallbackQueryHandler(handle_callback),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_requirements),
                CommandHandler("skip", skip_requirements),
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
