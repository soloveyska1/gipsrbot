import os
import logging
import json
import html
import re
from typing import Optional
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters, ConversationHandler
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.helpers import escape_markdown
from dotenv import load_dotenv
import pandas as pd

# Загрузка переменных окружения
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID', 0))

# Директории
BASE_DIR = os.path.join(os.getcwd(), 'clients')
DATA_DIR = os.path.join(os.getcwd(), 'data')
LOGS_DIR = os.path.join(os.getcwd(), 'logs')
for directory in [BASE_DIR, DATA_DIR, LOGS_DIR]:
    os.makedirs(directory, exist_ok=True)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
file_handler = logging.FileHandler(os.path.join(LOGS_DIR, 'bot.log'))
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

# Файлы данных
PRICES_FILE = os.path.join(DATA_DIR, 'prices.json')
REFERRALS_FILE = os.path.join(DATA_DIR, 'referrals.json')
ORDERS_FILE = os.path.join(DATA_DIR, 'orders.json')
FEEDBACKS_FILE = os.path.join(DATA_DIR, 'feedbacks.json')
BONUSES_FILE = os.path.join(DATA_DIR, 'bonuses.json')
USER_LOGS_FILE = os.path.join(DATA_DIR, 'user_logs.json')

# Функции загрузки/сохранения с обработкой ошибок
def load_json(file_path, default=None):
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return default or {}
    except Exception as e:
        logger.error(f"Ошибка загрузки {file_path}: {e}")
        return default or {}

def save_json(file_path, data):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка сохранения {file_path}: {e}")

# Глобальные данные
DEFAULT_PRICES = {
    'samostoyatelnye': {'base': 2500, 'min': 2500},
    'kursovaya_teoreticheskaya': {'base': 8000, 'min': 8000},
    'kursovaya_s_empirikov': {'base': 12000, 'min': 12000},
    'diplomnaya': {'base': 35000, 'min': 35000},
    'magisterskaya': {'base': 40000, 'min': 40000},
    'normcontrol': {'base': 5000, 'min': 5000},
}

LEGACY_PRICE_KEYS = {
    'self': 'samostoyatelnye',
    'course_theory': 'kursovaya_teoreticheskaya',
    'course_empirical': 'kursovaya_s_empirikov',
    'vkr': 'diplomnaya',
    'master': 'magisterskaya',
}


def normalize_prices(raw_prices):
    normalized = {key: value.copy() for key, value in DEFAULT_PRICES.items()}
    if not isinstance(raw_prices, dict):
        return normalized

    for raw_key, raw_value in raw_prices.items():
        target_key = LEGACY_PRICE_KEYS.get(raw_key, raw_key)
        if not isinstance(raw_value, dict):
            continue
        base = float(raw_value.get('base', 0) or 0)
        minimum = float(raw_value.get('min', 0) or 0)
        default_entry = DEFAULT_PRICES.get(target_key, {'base': 0, 'min': 0})
        default_base = default_entry.get('base', 0)
        default_min = default_entry.get('min', default_base)
        if base <= 0:
            base = default_base
        base = max(base, default_base)
        if minimum <= 0:
            minimum = max(base, default_min)
        minimum = max(minimum, base, default_min)
        normalized[target_key] = {
            'base': int(base),
            'min': int(minimum),
        }
    return normalized


PRICES = normalize_prices(load_json(PRICES_FILE, {}))
REFERALS = load_json(REFERRALS_FILE)
ORDERS = load_json(ORDERS_FILE)
FEEDBACKS = load_json(FEEDBACKS_FILE)
BONUSES = load_json(BONUSES_FILE)
USER_LOGS = load_json(USER_LOGS_FILE)

ORDER_TYPES = {
    'samostoyatelnye': {
        'name': 'Самостоятельные, контрольные, эссе',
        'icon': '📝',
        'description': (
            'Быстрые задания для студентов — эссе, контрольные, рефераты. Уже 5000+ работ выполнено идеально 🔥\n\n'
            'Подходит, когда нужно закрыть самостоятельную без стресса и задержек.'
        ),
        'details': (
            '• Объём: от 1 страницы до расширенных самостоятельных свыше 20 страниц.\n'
            '• Специализации: психология, социальная работа, конфликтология и смежные дисциплины.\n'
            '• Стоимость рассчитываем по срокам, сложности и объёму — подбираем решение, которое выгодно и надёжно.'
        ),
        'examples': ['Эссе по психологии личности', 'Контрольная по конфликтологии', 'Реферат по социальной работе']
    },
    'kursovaya_teoreticheskaya': {
        'name': 'Курсовая теоретическая',
        'icon': '📘',
        'description': 'Глубокий анализ литературы. Получите отличную оценку без стресса! 📈',
        'details': 'Теоретическая основа, анализ источников, структура по ГОСТ.',
        'examples': ['Теория маркетинга', 'Обзор психологии развития']
    },
    'kursovaya_s_empirikov': {
        'name': 'Курсовая с эмпирикой',
        'icon': '📊',
        'description': (
            'Теория + данные и глубокий анализ.\n'
            'Клиенты говорят: "Лучшая помощь!" ⭐️'
        ),
        'details': (
            '• Работаем с собранными данными или вместе с менеджером организуем сбор под вашу тему.\n'
            '• Проводим опросы, расчёты и математическую статистику.\n'
            '• Оформляем таблицы, графики, приложения и рекомендации по требованиям вуза.\n\n'
            'Примеры: Исследование рынка, Анализ поведения потребителей\n\n'
            'Минимальная стоимость: 12000 ₽ при комфортных сроках.\n\n'
            'Готовы оформить заказ?'
        ),
        'examples': ['Исследование рынка', 'Анализ поведения потребителей']
    },
    'diplomnaya': {
        'name': 'Дипломная работа',
        'icon': '🎓',
        'description': 'Полный цикл для успешной защиты. Скидка 10% на первый диплом! 💼',
        'details': 'Глубокий анализ, эмпирика и сопровождение до защиты.',
        'examples': ['Социальная адаптация студентов', 'Стратегии урегулирования конфликтов в организации']
    },
    'magisterskaya': {
        'name': 'Магистерская диссертация',
        'icon': '🔍',
        'description': 'Инновационное исследование. Высокая оригинальность и глубина проработки. 🌟',
        'details': 'Научная новизна, продуманная методология, рекомендации по публикациям.',
        'examples': ['Развитие эмоционального интеллекта руководителей', 'Социальная поддержка семей в кризисных ситуациях']
    },
    'normcontrol': {
        'name': 'Нормоконтроль',
        'icon': '📐',
        'description': 'Проверим оформление по ГОСТ и методичкам без стресса. Быстрый разбор замечаний.',
        'details': 'Приведем текст в идеальное состояние: структура, ссылки, списки литературы. Минимальная стоимость — 5000 ₽, далее зависит от объема и срочности.',
        'examples': ['Нормоконтроль диплома', 'Проверка курсовой перед сдачей']
    }
}

UPSELL_LABELS = {
    'prez': 'Презентация',
    'speech': 'Речь'
}

UPSELL_PRICES = {
    'prez': 2000,
    'speech': 1000,
}

FEEDBACK_BONUS_AMOUNT = 200

DEADLINE_PRESETS = [
    {
        'key': '24h',
        'label': '⏱ 24 часа или меньше',
        'days': 1,
        'multiplier': 1.8,
        'badge': 'Экстренно: приоритетная команда и бонус за смелость заказа',
    },
    {
        'key': '3d',
        'label': '🚀 3 дня',
        'days': 3,
        'multiplier': 1.45,
        'badge': 'Ускоренный срок с бонусом на следующий заказ',
    },
    {
        'key': '5d',
        'label': '⚡️ 5 дней',
        'days': 5,
        'multiplier': 1.3,
        'badge': 'Срочно, но комфортно: прогресс-отчёты и бонус за планирование',
    },
    {
        'key': '7d',
        'label': '📅 Неделя',
        'days': 7,
        'multiplier': 1.15,
        'badge': 'Оптимальный баланс с поддержкой и накопительным бонусом',
    },
    {
        'key': '14d',
        'label': '✅ 2 недели',
        'days': 14,
        'multiplier': 1.0,
        'badge': 'Базовый тариф и фиксированный бонус постоянного клиента',
    },
    {
        'key': '21d',
        'label': '🌿 3 недели',
        'days': 21,
        'multiplier': 0.95,
        'badge': 'Спокойный темп: бесплатная консультация и бонус лояльности',
    },
    {
        'key': '30d',
        'label': '🧘 Месяц',
        'days': 30,
        'multiplier': 0.9,
        'badge': 'Без спешки: расширенная гарантия и бонус за доверие',
    },
    {
        'key': '45d',
        'label': '🛡 Больше месяца',
        'days': 45,
        'multiplier': 0.85,
        'badge': 'Максимальная выгода: лучшие условия и дополнительный бонус',
    },
]

DEADLINE_LOOKUP = {item['key']: item for item in DEADLINE_PRESETS}
DEFAULT_DEADLINE_KEY = '14d'


def get_deadline_preset(key):
    return DEADLINE_LOOKUP.get(key) or DEADLINE_LOOKUP[DEFAULT_DEADLINE_KEY]


def round_price(amount: float) -> int:
    return int(max(0, (float(amount) + 25) // 50 * 50))

FAQ_ITEMS = [
    {'question': 'Как сделать заказ?', 'answer': 'Выберите "Сделать заказ" и следуйте шагам. Можно заказать несколько работ сразу!'},
    {'question': 'Как рассчитывается стоимость?', 'answer': 'Зависит от типа, срочности и сложности. Используйте калькулятор для точной цены!'},
    {'question': 'Как работает реферальная программа?', 'answer': 'Поделитесь ссылкой — получите 5% от заказов друзей как бонус.'},
    {'question': 'Гарантии качества?', 'answer': 'Антиплагиат, правки бесплатно 14 дней, поддержка до защиты.'},
    {'question': 'Скидки?', 'answer': '5-15% для постоянных, 10% на первый, рефералы.'},
    {'question': 'Отслеживание заказа?', 'answer': 'В профиле статусы, уведомления от менеджера.'}
]

current_pricing_mode = 'light'

# Состояния
(
    SELECT_MAIN_MENU,
    SELECT_ORDER_TYPE,
    VIEW_ORDER_DETAILS,
    INPUT_TOPIC,
    SELECT_DEADLINE,
    INPUT_REQUIREMENTS,
    INPUT_CONTACT,
    UPLOAD_FILES,
    ADD_UPSSELL,
    ADD_ANOTHER_ORDER,
    CONFIRM_CART,
    ADMIN_MENU,
    PROFILE_MENU,
    SHOW_PRICE_LIST,
    PRICE_CALCULATOR,
    SELECT_CALC_DEADLINE,
    SELECT_CALC_COMPLEXITY,
    SHOW_FAQ,
    FAQ_DETAILS,
    PROFILE_ORDERS,
    PROFILE_ORDER_DETAIL,
    PROFILE_FEEDBACKS,
    PROFILE_FEEDBACK_INPUT,
    PROFILE_REFERRALS,
    PROFILE_BONUSES,
) = range(25)

# Логирование действий пользователя
def log_user_action(user_id, username, action):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    USER_LOGS.setdefault(str(user_id), []).append({'timestamp': timestamp, 'action': action, 'username': username})
    save_json(USER_LOGS_FILE, USER_LOGS)
    logger.info(f"Пользователь {user_id} ({username}): {action}")

async def answer_callback_query(query, context):
    if not query:
        return
    last_answered_id = context.user_data.get('_last_answered_query')
    if last_answered_id == query.id:
        return
    await query.answer()
    context.user_data['_last_answered_query'] = query.id


def ensure_bonus_account(user_id: str):
    user_key = str(user_id)
    entry = BONUSES.setdefault(user_key, {})
    changed = False
    credited = entry.get('credited', 0)
    redeemed = entry.get('redeemed', 0)
    history = entry.get('history', [])
    balance = entry.get('balance')
    try:
        credited = int(credited)
    except (TypeError, ValueError):
        credited = 0
        changed = True
    try:
        redeemed = int(redeemed)
    except (TypeError, ValueError):
        redeemed = 0
        changed = True
    if not isinstance(history, list):
        history = []
        changed = True
    calculated_balance = credited - redeemed
    try:
        balance = int(balance)
    except (TypeError, ValueError):
        balance = calculated_balance
        changed = True
    if balance != calculated_balance:
        balance = calculated_balance
        changed = True
    entry.update({
        'credited': credited,
        'redeemed': redeemed,
        'balance': balance,
        'history': history,
    })
    if changed:
        save_json(BONUSES_FILE, BONUSES)
    return entry


def get_bonus_summary(user_id: str):
    entry = ensure_bonus_account(user_id)
    return (
        entry.get('credited', 0),
        entry.get('redeemed', 0),
        entry.get('balance', 0),
        entry.get('history', []),
    )


def add_bonus_operation(user_id: str, amount: int, operation_type: str, reason: str):
    amount = int(amount)
    entry = ensure_bonus_account(user_id)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if operation_type == 'credit':
        entry['credited'] += amount
        entry['balance'] += amount
    elif operation_type == 'debit':
        entry['redeemed'] += amount
        entry['balance'] = max(0, entry['balance'] - amount)
    entry.setdefault('history', []).append({
        'type': operation_type,
        'amount': amount,
        'reason': reason,
        'timestamp': timestamp,
    })
    save_json(BONUSES_FILE, BONUSES)


def get_feedback_entries(user_id: str):
    items = FEEDBACKS.get(str(user_id), [])
    normalized = []
    for entry in items:
        if isinstance(entry, dict):
            text = entry.get('text', '')
            created_at = entry.get('created_at')
        else:
            text = str(entry)
            created_at = None
        normalized.append({'text': text, 'created_at': created_at})
    return normalized


def save_feedback_entries(user_id: str, entries):
    FEEDBACKS[str(user_id)] = entries
    save_json(FEEDBACKS_FILE, FEEDBACKS)


def truncate_for_button(text: str, limit: int = 32) -> str:
    clean = text.replace('\n', ' ').strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + '…'


def is_order_paused(order: dict) -> bool:
    status = str(order.get('status', '')).lower()
    return bool(order.get('client_paused')) or status.startswith('на паузе')


def build_order_status(order: dict) -> str:
    status = order.get('status') or 'без статуса'
    if is_order_paused(order):
        return f"{status} · на паузе"
    return status


def build_order_detail_text(order: dict) -> str:
    order_name = ORDER_TYPES.get(order.get('type'), {}).get('name', 'Неизвестный тип')
    topic = order.get('topic', 'Без темы')
    deadline_display = order.get('deadline_label') or f"{order.get('deadline_days', '—')} дней"
    upsell_titles = [UPSELL_LABELS.get(u, u) for u in order.get('upsells', [])]
    upsell_text = ', '.join(upsell_titles) if upsell_titles else 'нет'
    contact_display = html.escape(order.get('contact', 'Не указан'))
    contact_link = order.get('contact_link')
    if contact_link:
        contact_html = f"<a href=\"{html.escape(contact_link, quote=True)}\">{contact_display}</a>"
    else:
        contact_html = contact_display
    requirements = html.escape(order.get('requirements', 'Нет'))
    files_count = len(order.get('files', [])) if order.get('files') else 0
    lines = [
        f"<b>{html.escape(order_name)}</b>",
        f"Тема: {html.escape(topic)}",
        f"Статус: {html.escape(build_order_status(order))}",
        f"Срок: {html.escape(deadline_display)}",
        f"Контакт: {contact_html}",
        f"Допы: {html.escape(upsell_text)}",
        f"Стоимость: {order.get('price', 0)} ₽",
        f"Требования: {requirements}",
    ]
    if files_count:
        lines.append(f"Файлы: {files_count} шт.")
    return "\n".join(lines)


def find_user_order(user_id: str, order_id: str):
    user_orders = ORDERS.get(str(user_id), [])
    for order in user_orders:
        if str(order.get('order_id')) == str(order_id):
            return order, user_orders
    return None, user_orders


async def edit_or_send(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, keyboard=None, parse_mode=ParseMode.HTML):
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    if update.callback_query:
        query = update.callback_query
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )
    elif update.message:
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )
    else:
        chat_id = update.effective_chat.id
        await context.bot.send_message(
            chat_id,
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )

def build_contact_link(contact_text):
    if not contact_text:
        return None
    contact = contact_text.strip()
    if not contact:
        return None
    lowered = contact.lower()
    if lowered.startswith(('http://', 'https://', 'tg://', 'mailto:')):
        return contact
    if lowered.startswith(('t.me/', 'telegram.me/')):
        return f"https://{contact}" if lowered.startswith('t.me/') else f"https://{contact.split('://', 1)[-1]}"
    if lowered.startswith('vk.com/'):
        return f"https://{contact}"
    if contact.startswith('@') and re.fullmatch(r'@[A-Za-z0-9_]{4,}', contact):
        return f"https://t.me/{contact[1:]}"
    if re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', contact):
        return f"mailto:{contact}"
    if lowered.startswith(('vk.com', 't.me')):
        return f"https://{contact}"
    return None


def build_deadline_keyboard(callback_prefix: str, include_back: bool = False, back_callback: Optional[str] = None):
    rows = []
    for i in range(0, len(DEADLINE_PRESETS), 2):
        chunk = DEADLINE_PRESETS[i:i + 2]
        row = [
            InlineKeyboardButton(item['label'], callback_data=f"{callback_prefix}{item['key']}")
            for item in chunk
        ]
        rows.append(row)
    if include_back and back_callback:
        rows.append([InlineKeyboardButton('⬅️ Назад', callback_data=back_callback)])
    return InlineKeyboardMarkup(rows)


REQUIREMENTS_PROMPT_TEXT = (
    "📚 *Расскажите про дополнительные требования.*\n"
    "• Что указано в методичке или задании преподавателя.\n"
    "• Объём, формат оформления, список литературы, примеры желаемого уровня.\n"
    "Можно написать текстом сейчас или приложить материалы чуть позже на шаге с файлами.\n\n"
    "Если дополнительных указаний нет, нажмите «Пропустить» или отправьте /skip."
)

REQUIREMENTS_EXAMPLE_TEXT = (
    "Пример: «Методичка №3, тема 2, объём 8 страниц, Times New Roman 14, интервал 1,5; нужно 3 источника из списка преподавателя.»"
)


def build_requirements_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('💡 Подсказать, что написать', callback_data='requirements_hint')],
        [InlineKeyboardButton('⏭ Пропустить', callback_data='requirements_skip')],
    ])


def get_user_link(user):
    if user.username:
        return f"https://t.me/{user.username}"
    return f"tg://user?id={user.id}"

# Расчет цены
def calculate_price(order_type_key: str, deadline_key: str, complexity_factor: float = 1.0) -> int:
    if order_type_key not in PRICES:
        logger.error(f"Неизвестный тип: {order_type_key}")
        return 0
    pricing = PRICES[order_type_key]
    base = pricing.get('base', pricing.get('min', 0))
    min_price = pricing.get('min', base)
    preset = get_deadline_preset(deadline_key)
    deadline_multiplier = preset.get('multiplier', 1.0)
    mode_multiplier = 1.1 if current_pricing_mode == 'hard' else 1.0
    raw_price = base * deadline_multiplier * complexity_factor * mode_multiplier
    price = max(raw_price, min_price)
    return round_price(price)

# Обработчик ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")
    if ADMIN_CHAT_ID:
        await context.bot.send_message(ADMIN_CHAT_ID, f"Ошибка: {context.error}")

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    log_user_action(user.id, user.username, "/start")
    message_text = update.message.text if update.message and update.message.text else ""
    args = message_text.split()
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={user.id}"
    context.user_data['ref_link'] = ref_link
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if referrer_id != user.id:
            REFERALS.setdefault(str(referrer_id), []).append(user.id)
            save_json(REFERRALS_FILE, REFERALS)
            await context.bot.send_message(referrer_id, f"🎉 Новый реферал: {user.first_name}")
    display_name = user.first_name or user.full_name or "друг"
    safe_name = escape_markdown(display_name, version=1)
    safe_ref_link = escape_markdown(ref_link, version=1)
    welcome = (
        f"👋 Добро пожаловать, {safe_name}! Работаем со всеми дисциплинами, кроме технических (чертежи)."
        f" Уже 5000+ клиентов и 10% скидка на первый заказ 🔥\nПоделитесь ссылкой для бонусов: {safe_ref_link}"
    )
    return await main_menu(update, context, welcome)

# Главное меню
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, message=None):
    user = update.effective_user
    log_user_action(user.id, user.username, "Главное меню")
    text = message or "Выберите раздел:"
    keyboard = [
        [InlineKeyboardButton("📝 Сделать заказ", callback_data='make_order')],
        [InlineKeyboardButton("💲 Прайс-лист", callback_data='price_list'), InlineKeyboardButton("🧮 Калькулятор", callback_data='price_calculator')],
        [InlineKeyboardButton("👤 Профиль", callback_data='profile'), InlineKeyboardButton("❓ FAQ", callback_data='faq')],
        [InlineKeyboardButton("📞 Администратор", url='https://t.me/Thisissaymoon')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        query = update.callback_query
        await answer_callback_query(query, context)
        try:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        except TelegramError as e:
            if "message is not modified" in str(e).lower():
                pass
            else:
                logger.error(f"Ошибка редактирования сообщения: {e}")
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    return SELECT_MAIN_MENU

# Обработчик главного меню
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    data = query.data
    user = update.effective_user
    log_user_action(user.id, user.username, f"Выбор в меню: {data}")
    if data == 'make_order':
        return await select_order_type(update, context)
    elif data == 'price_list':
        return await show_price_list(update, context)
    elif data == 'price_calculator':
        return await price_calculator(update, context)
    elif data == 'profile':
        return await show_profile(update, context)
    elif data == 'faq':
        return await show_faq(update, context)
    await query.edit_message_text("Неизвестная команда. Возвращаюсь в главное меню.")
    return await main_menu(update, context)
    return SELECT_MAIN_MENU

# Выбор типа заказа
async def select_order_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    data = query.data if query else None
    user = update.effective_user
    log_user_action(user.id, user.username, "Выбор типа заказа")
    if data and data.startswith('type_'):
        return await view_order_details(update, context)
    if data == 'back_to_main':
        return await main_menu(update, context)
    text = "Выберите тип работы (добавьте несколько в корзину для скидки!):"
    keyboard = [[InlineKeyboardButton(f"{val['icon']} {val['name']}", callback_data=f'type_{key}')] for key, val in ORDER_TYPES.items()]
    navigation_row = [InlineKeyboardButton("⬅️ Меню", callback_data='back_to_main')]
    current_type = context.user_data.get('current_order_type')
    if current_type in ORDER_TYPES:
        navigation_row.append(InlineKeyboardButton("🔙 К описанию", callback_data=f'type_{current_type}'))
    keyboard.append(navigation_row)
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except TelegramError as e:
        if "message is not modified" in str(e).lower():
            pass
        else:
            raise
    return SELECT_ORDER_TYPE

# Подробности о типе заказа
async def view_order_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    data = query.data
    if data.startswith('order_'):
        key = data[6:]
        context.user_data['current_order_type'] = key
        prompt_lines = [
            "✍️ *Введите тему задания.*",
            "Опишите дисциплину, формат и основные акценты, чтобы мы сразу передали задачу профильному эксперту.",
            "Если точной темы ещё нет — так и напишите, и мы поможем сформулировать лучший вариант.",
        ]
        if key == 'samostoyatelnye':
            prompt_lines.append(
                "Например: «Эссе по конфликтологии о стратегиях медиации» или «Реферат по социальной работе о профилактике выгорания»."
            )
        await query.edit_message_text(
            "\n\n".join(prompt_lines),
            parse_mode=ParseMode.MARKDOWN,
        )
        return INPUT_TOPIC
    elif data == 'select_order_type':
        return await select_order_type(update, context)
    elif data.startswith('type_'):
        key = data[5:]
        if key not in ORDER_TYPES:
            await query.edit_message_text("Ошибка: неизвестный тип.")
            return SELECT_ORDER_TYPE
        val = ORDER_TYPES[key]
        prices = PRICES.get(key, {})
        min_price = prices.get('min') or prices.get('base')
        price_line = f"Минимальная стоимость: {min_price} ₽ при комфортных сроках." if min_price else ""
        text = (
            f"{val['icon']} *{val['name']}*\n\n{val['description']}\n{val['details']}\n"
            f"Примеры: {', '.join(val['examples'])}"
        )
        if price_line:
            text += f"\n\n{price_line}"
        text += "\n\nГотовы оформить заказ?"
        keyboard = [
            [InlineKeyboardButton("✅ Заказать", callback_data=f'order_{key}')],
            [InlineKeyboardButton("Назад", callback_data='select_order_type')]
        ]
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        return VIEW_ORDER_DETAILS

# Ввод темы
async def input_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic_text = (update.message.text or '').strip()
    context.user_data['topic'] = topic_text
    user = update.effective_user
    log_user_action(user.id, user.username, f"Тема: {update.message.text}")
    descriptions = [
        "⏰ *Выберите срок сдачи — чем спокойнее, тем выгоднее.*",
        "_Мы закрепляем бонусы за ранний заказ — выбирайте комфортный вариант:_",
        "",
    ]
    for preset in DEADLINE_PRESETS:
        descriptions.append(f"{preset['label']} — {preset['badge']}")
    text = "\n".join(descriptions)
    back_target = context.user_data.get('current_order_type')
    reply_markup = build_deadline_keyboard(
        'deadline_',
        include_back=True,
        back_callback=f'type_{back_target}' if back_target else 'select_order_type'
    )
    await update.message.reply_text(
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
    return SELECT_DEADLINE

# Выбор срока
async def select_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    data = query.data
    if data.startswith('deadline_'):
        key = data[9:]
        preset = get_deadline_preset(key)
        context.user_data['deadline_key'] = key
        context.user_data['deadline_days'] = preset['days']
        context.user_data['deadline_label'] = preset['label']
        await query.edit_message_text(
            REQUIREMENTS_PROMPT_TEXT,
            reply_markup=build_requirements_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
        return INPUT_REQUIREMENTS
    elif data.startswith('type_'):
        return await view_order_details(update, context)
    return SELECT_DEADLINE

# Ввод требований
async def input_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    requirements_text = (update.message.text or '').strip()
    context.user_data['requirements'] = requirements_text or 'Нет'
    return await ask_contact(update, context)

async def skip_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['requirements'] = 'Нет'
    return await ask_contact(update, context)


async def requirements_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    data = query.data
    if data == 'requirements_hint':
        await query.message.reply_text(REQUIREMENTS_EXAMPLE_TEXT)
        return INPUT_REQUIREMENTS
    if data == 'requirements_skip':
        context.user_data['requirements'] = 'Нет'
        await query.edit_message_text('✅ Дополнительные требования можно будет уточнить позже.')
        return await ask_contact(update, context)
    return INPUT_REQUIREMENTS

async def ask_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📬 *Оставьте контакт, куда менеджеру написать.*\n"
        "Пришлите активную ссылку на Telegram, VK или рабочую почту — так менеджер быстро свяжется с вами.\n"
        "Пример: https://t.me/username, @username, https://vk.com/id123 или name@example.com.\n"
        "_Без контакта мы не сможем принять заказ._"
    )
    if update.message:
        target = update.message
    else:
        target = update.callback_query.message
    await target.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
    return INPUT_CONTACT

async def input_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact_text = update.message.text.strip()
    link = build_contact_link(contact_text)
    if not link:
        await update.message.reply_text(
            "Пожалуйста, пришлите рабочую ссылку или e-mail, чтобы мы смогли написать вам.\n"
            "Примеры: https://t.me/username, @username, https://vk.com/id123, name@example.com",
            disable_web_page_preview=True,
        )
        return INPUT_CONTACT
    context.user_data['contact'] = contact_text
    context.user_data['contact_link'] = link
    context.user_data['pending_files'] = []
    return await prompt_file_upload(update, context)

async def prompt_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📎 Прикрепите файлы для задания (если есть).\n\n"
        "• Отправляйте по одному сообщению — принимаем документы, фото, видео, аудио.\n"
        "• Когда закончите, нажмите «Готово» или используйте /done.\n"
        "• Если файлов нет, нажмите «Пропустить» или используйте /skip."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Готово", callback_data='files_done')],
        [InlineKeyboardButton("⏭ Пропустить", callback_data='files_skip')]
    ])
    await update.message.reply_text(text, reply_markup=keyboard)
    return UPLOAD_FILES

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files_list = context.user_data.setdefault('pending_files', [])
    message = update.message
    acknowledgement = None
    if message.document:
        document = message.document
        files_list.append({
            'type': 'document',
            'file_id': document.file_id,
            'file_name': document.file_name,
        })
        acknowledgement = f"📄 Файл {document.file_name or 'загружен'} сохранен."
    elif message.photo:
        photo = message.photo[-1]
        files_list.append({
            'type': 'photo',
            'file_id': photo.file_id,
        })
        acknowledgement = "🖼 Фото сохранено."
    elif message.audio:
        audio = message.audio
        files_list.append({
            'type': 'audio',
            'file_id': audio.file_id,
            'file_name': audio.file_name or audio.title,
        })
        acknowledgement = "🎧 Аудио сохранено."
    elif message.voice:
        voice = message.voice
        files_list.append({
            'type': 'voice',
            'file_id': voice.file_id,
        })
        acknowledgement = "🎙 Голосовое сообщение сохранено."
    elif message.video:
        video = message.video
        files_list.append({
            'type': 'video',
            'file_id': video.file_id,
            'file_name': video.file_name,
        })
        acknowledgement = "🎬 Видео сохранено."
    elif message.video_note:
        video_note = message.video_note
        files_list.append({
            'type': 'video_note',
            'file_id': video_note.file_id,
        })
        acknowledgement = "📹 Видео-заметка сохранена."
    elif message.animation:
        animation = message.animation
        files_list.append({
            'type': 'animation',
            'file_id': animation.file_id,
            'file_name': animation.file_name,
        })
        acknowledgement = "🌀 GIF сохранен."
    elif message.sticker:
        sticker = message.sticker
        files_list.append({
            'type': 'sticker',
            'file_id': sticker.file_id,
            'file_emoji': sticker.emoji,
        })
        acknowledgement = "🔖 Стикер сохранен."
    if acknowledgement:
        await message.reply_text(f"{acknowledgement} Можете прикрепить еще или нажать «Готово».")
    else:
        await message.reply_text("Не удалось определить файл. Попробуйте еще раз или нажмите «Готово».")
    return UPLOAD_FILES

async def skip_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.setdefault('pending_files', [])
    return await add_upsell(update, context)


async def file_upload_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    data = query.data
    if data == 'files_skip':
        context.user_data['pending_files'] = []
    elif not context.user_data.get('pending_files'):
        context.user_data['pending_files'] = []
    return await add_upsell(update, context)

async def remind_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отправьте файл или нажмите «Готово», когда закончите (можно также использовать /done).")
    return UPLOAD_FILES

# Добавление допуслуг
async def add_upsell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        'Добавим дополнительные материалы? Клиенты, которые выбирают презентацию или речь, '
        'получают +5% скидку на следующий заказ и готовый комплект.'
    )
    keyboard = [
        [InlineKeyboardButton("Презентация (+2000₽)", callback_data='add_prez')],
        [InlineKeyboardButton("Речь (+1000₽)", callback_data='add_speech')],
        [InlineKeyboardButton("Без допов", callback_data='no_upsell')]
    ]
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        query = update.callback_query
        await answer_callback_query(query, context)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_UPSSELL

# Обработчик допуслуг
async def upsell_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    data = query.data
    upsells = context.user_data.setdefault('upsells', set())
    added = False
    if data == 'add_prez':
        if 'prez' not in upsells:
            upsells.add('prez')
            added = True
    elif data == 'add_speech':
        if 'speech' not in upsells:
            upsells.add('speech')
            added = True
    elif data == 'no_upsell':
        return await process_order(update, context)
    selected = [UPSELL_LABELS.get(u, u) for u in upsells]
    if added:
        text = 'Добавить ещё опции? Полный комплект фиксирует +5% скидку на следующий заказ.'
    elif upsells:
        text = (
            f"Вы уже выбрали: {', '.join(selected)}.\n"
            'Скидка +5% на следующий заказ закреплена — добавить что-то ещё?'
        )
    else:
        text = (
            'Выберите дополнительные материалы — презентацию или речь. '
            'Так вы получите +5% скидку на следующий заказ и полный комплект для выступления.'
        )
    keyboard = [
        [InlineKeyboardButton(f"{'✅ ' if 'prez' in upsells else ''}Презентация (+2000₽)", callback_data='add_prez')],
        [InlineKeyboardButton(f"{'✅ ' if 'speech' in upsells else ''}Речь (+1000₽)", callback_data='add_speech')],
        [InlineKeyboardButton("Продолжить", callback_data='no_upsell')]
    ]
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    except TelegramError as e:
        if "message is not modified" in str(e).lower():
            pass
    return ADD_UPSSELL

async def process_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    type_key = context.user_data.get('current_order_type')
    if not type_key or type_key not in ORDER_TYPES:
        await query.edit_message_text("Ошибка: неверный тип заказа.")
        return ConversationHandler.END
    topic = context.user_data.get('topic', 'Без темы')
    deadline_key = context.user_data.get('deadline_key', DEFAULT_DEADLINE_KEY)
    preset = get_deadline_preset(deadline_key)
    deadline_days = preset['days']
    deadline_label = context.user_data.get('deadline_label', preset['label'])
    requirements = context.user_data.get('requirements', 'Нет')
    contact = context.user_data.get('contact', '')
    contact_link = context.user_data.get('contact_link')
    files = list(context.user_data.get('pending_files', []))
    upsells = list(context.user_data.get('upsells', set()))
    price = calculate_price(type_key, deadline_key)
    extra = sum(UPSELL_PRICES.get(u, 0) for u in upsells)
    price += extra
    order = {
        'type': type_key,
        'topic': topic,
        'deadline_key': deadline_key,
        'deadline_days': deadline_days,
        'deadline_label': deadline_label,
        'requirements': requirements,
        'upsells': upsells,
        'price': price,
        'status': 'новый',
        'contact': contact,
        'contact_link': contact_link,
        'files': files,
    }
    context.user_data.setdefault('cart', []).append(order)
    context.user_data.pop('upsells', None)
    context.user_data.pop('requirements', None)
    context.user_data.pop('deadline_key', None)
    context.user_data.pop('deadline_days', None)
    context.user_data.pop('deadline_label', None)
    context.user_data.pop('topic', None)
    context.user_data.pop('current_order_type', None)
    context.user_data.pop('contact', None)
    context.user_data.pop('contact_link', None)
    context.user_data.pop('pending_files', None)
    return await add_another_order(update, context)

# Добавить еще заказ
async def add_another_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text = "Добавить еще заказ? (Несколько заказов = 10% скидка!)"
    keyboard = [
        [InlineKeyboardButton("Да", callback_data='add_another_yes')],
        [InlineKeyboardButton("Нет, оформить", callback_data='confirm_cart')]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_ANOTHER_ORDER

async def add_another_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    data = query.data
    if data == 'add_another_yes':
        return await select_order_type(update, context)
    elif data == 'confirm_cart':
        return await confirm_cart(update, context)
    return ADD_ANOTHER_ORDER

# Подтверждение корзины
async def confirm_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    cart = context.user_data.get('cart', [])
    if not cart:
        await query.edit_message_text("Корзина пуста.")
        return await main_menu(update, context)
    text_lines = ["<b>Ваша корзина. Подтвердите — зафиксируем персональный бонус:</b>"]
    total = 0
    for i, order in enumerate(cart, 1):
        order_name = ORDER_TYPES.get(order['type'], {}).get('name', 'Неизвестно')
        contact_display = order.get('contact', 'Не указан')
        deadline_display = order.get('deadline_label') or f"{order.get('deadline_days', 0)} дней"
        contact_link = order.get('contact_link')
        if contact_link:
            contact_html = f"<a href=\"{html.escape(contact_link, quote=True)}\">{html.escape(contact_display)}</a>"
        else:
            contact_html = html.escape(contact_display)
        upsell_titles = [UPSELL_LABELS.get(u, u) for u in order.get('upsells', [])]
        if upsell_titles:
            upsell_html = html.escape(', '.join(upsell_titles))
        else:
            upsell_html = 'нет'
        text_lines.extend([
            f"{i}. <b>{html.escape(order_name)}</b> — {html.escape(order.get('topic', 'Без темы'))} — {order['price']} ₽",
            f"• Срок: {html.escape(deadline_display)}",
            f"• Контакт: {contact_html}",
            f"• Допы: {upsell_html}",
        ])
        if order.get('files'):
            text_lines.append(f"• Файлы: {len(order['files'])} шт.")
        total += order['price']
    if len(cart) > 1:
        discount = round_price(total * 0.1)
        total -= discount
        text_lines.append(f"Скидка за несколько заказов: -{discount} ₽")
    text_lines.append(f"<b>Итого: {total} ₽</b> — сумма с учётом допов и скидок.")
    text_lines.append(
        'После подтверждения наш менеджер свяжется с вами для финального согласования '
        'и ответит на любые вопросы.'
    )
    text_lines.append("Подтвердить оформление?")
    text = "\n".join(text_lines)
    keyboard = [
        [InlineKeyboardButton("Подтвердить", callback_data='place_order')],
        [InlineKeyboardButton("Отменить", callback_data='cancel_cart')]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    return CONFIRM_CART

async def confirm_cart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    data = query.data
    if data == 'place_order':
        user_id = str(update.effective_user.id)
        user_orders = ORDERS.setdefault(user_id, [])
        existing_ids = [order.get('order_id', 0) for order in user_orders]
        order_id = max(existing_ids, default=0) + 1
        for order in context.user_data['cart']:
            order['order_id'] = order_id
            user_orders.append(order)
            order_id += 1
        save_json(ORDERS_FILE, ORDERS)
        text = (
            "✅ Заказ оформлен! Наш менеджер скоро свяжется с вами.\n"
            "[Администратор](https://t.me/Thisissaymoon) уже получил все детали и файлы."
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
        if ADMIN_CHAT_ID:
            await notify_admin_about_order(update, context, context.user_data['cart'])
        context.user_data.pop('cart', None)
        return await main_menu(
            update,
            context,
            "Спасибо! Хотите заказать ещё? Наш менеджер уже на связи — [администратор](https://t.me/Thisissaymoon).",
        )
    elif data == 'cancel_cart':
        context.user_data.pop('cart', None)
        return await main_menu(update, context, "Корзина отменена. Посмотрите еще?")
    return CONFIRM_CART

async def notify_admin_about_order(update: Update, context: ContextTypes.DEFAULT_TYPE, orders):
    if not ADMIN_CHAT_ID:
        return
    user = update.effective_user
    user_id = str(user.id)
    user_link = get_user_link(user)
    user_name = html.escape(user.full_name or user.first_name or str(user.id))
    header = f"🆕 Новый заказ от <a href=\"{html.escape(user_link, quote=True)}\">{user_name}</a> (ID: {user_id})"
    blocks = []
    for order in orders:
        order_name = ORDER_TYPES.get(order.get('type'), {}).get('name', 'Неизвестно')
        contact_display = order.get('contact', 'Не указан')
        contact_link = order.get('contact_link')
        if contact_link:
            contact_html = f"<a href=\"{html.escape(contact_link, quote=True)}\">{html.escape(contact_display)}</a>"
        else:
            contact_html = html.escape(contact_display)
        upsell_titles = [UPSELL_LABELS.get(u, u) for u in order.get('upsells', [])]
        upsell_text = ', '.join(upsell_titles) if upsell_titles else 'нет'
        deadline_display = order.get('deadline_label') or f"{order.get('deadline_days', 0)} дней"
        block = (
            f"#{order.get('order_id', 'N/A')} — {html.escape(order_name)}\n"
            f"Тема: {html.escape(order.get('topic', 'Без темы'))}\n"
            f"Срок: {html.escape(deadline_display)}\n"
            f"Контакт клиента: {contact_html}\n"
            f"Допы: {html.escape(upsell_text)}\n"
            f"Требования: {html.escape(order.get('requirements', 'Нет'))}\n"
            f"Сумма: {order.get('price', 0)} ₽"
        )
        if order.get('files'):
            block += f"\nФайлы: {len(order['files'])} шт."
        blocks.append(block)
    message = header + "\n\n" + "\n\n".join(blocks)
    await context.bot.send_message(ADMIN_CHAT_ID, message, parse_mode=ParseMode.HTML)
    for order in orders:
        order_name = ORDER_TYPES.get(order.get('type'), {}).get('name', 'Неизвестно')
        caption_base = f"Файлы для заказа #{order.get('order_id', 'N/A')} — {order_name}"
        for file_info in order.get('files', []):
            file_type = file_info.get('type')
            file_id = file_info.get('file_id')
            if not file_id:
                continue
            if file_type == 'document':
                caption = caption_base
                if file_info.get('file_name'):
                    caption += f"\n{file_info['file_name']}"
                await context.bot.send_document(ADMIN_CHAT_ID, file_id, caption=caption)
            elif file_type == 'photo':
                await context.bot.send_photo(ADMIN_CHAT_ID, file_id, caption=caption_base)
            elif file_type == 'audio':
                caption = caption_base
                if file_info.get('file_name'):
                    caption += f"\n{file_info['file_name']}"
                await context.bot.send_audio(ADMIN_CHAT_ID, file_id, caption=caption)
            elif file_type == 'voice':
                await context.bot.send_voice(ADMIN_CHAT_ID, file_id, caption=caption_base)
            elif file_type == 'video':
                caption = caption_base
                if file_info.get('file_name'):
                    caption += f"\n{file_info['file_name']}"
                await context.bot.send_video(ADMIN_CHAT_ID, file_id, caption=caption)
            elif file_type == 'video_note':
                await context.bot.send_video_note(ADMIN_CHAT_ID, file_id)
                await context.bot.send_message(ADMIN_CHAT_ID, caption_base)
            elif file_type == 'animation':
                caption = caption_base
                if file_info.get('file_name'):
                    caption += f"\n{file_info['file_name']}"
                await context.bot.send_animation(ADMIN_CHAT_ID, file_id, caption=caption)
            elif file_type == 'sticker':
                await context.bot.send_sticker(ADMIN_CHAT_ID, file_id)
                await context.bot.send_message(ADMIN_CHAT_ID, caption_base)


async def notify_admin_order_event(context: ContextTypes.DEFAULT_TYPE, user, order: dict, action: str, extra_note: Optional[str] = None):
    if not ADMIN_CHAT_ID:
        return
    user_link = get_user_link(user)
    user_name = html.escape(user.full_name or user.first_name or str(user.id))
    order_id = html.escape(str(order.get('order_id', 'N/A')))
    order_name = html.escape(ORDER_TYPES.get(order.get('type'), {}).get('name', 'Неизвестный тип'))
    status_html = html.escape(build_order_status(order))
    deadline_display = order.get('deadline_label') or f"{order.get('deadline_days', '—')} дней"
    contact_display = order.get('contact', 'Не указан')
    contact_link = order.get('contact_link')
    if contact_link:
        contact_html = f"<a href=\"{html.escape(contact_link, quote=True)}\">{html.escape(contact_display)}</a>"
    else:
        contact_html = html.escape(contact_display)
    lines = [
        f"ℹ️ Клиент <a href=\"{html.escape(user_link, quote=True)}\">{user_name}</a> {html.escape(action)} заказ #{order_id} — {order_name}.",
        f"Статус: {status_html}.",
        f"Срок: {html.escape(deadline_display)}",
        f"Контакт клиента: {contact_html}",
    ]
    if extra_note:
        lines.append(html.escape(extra_note))
    await context.bot.send_message(ADMIN_CHAT_ID, "\n".join(lines), parse_mode=ParseMode.HTML, disable_web_page_preview=True)


# Показ прайс-листа
async def show_price_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    data = query.data
    if data.startswith('price_detail_'):
        key = data[13:]
        val = ORDER_TYPES.get(key, {})
        if not val:
            await query.edit_message_text("Ошибка: неизвестный тип.")
            return SHOW_PRICE_LIST
        prices = PRICES.get(key, {})
        min_price = prices.get('min') or prices.get('base')
        rush_price = calculate_price(key, '24h') if prices else None
        text_lines = [
            f"{val.get('icon', '')} *{val.get('name', '')}*",
            "",
            val.get('description', ''),
            val.get('details', ''),
            f"Примеры: {', '.join(val.get('examples', []))}",
        ]
        if min_price:
            text_lines.append(f"Минимальная стоимость: {min_price} ₽")
        if rush_price and rush_price != min_price:
            text_lines.append(f"Срочный заказ (24 часа или меньше): {rush_price} ₽")
        text_lines.append("\nЗакажите со скидкой!")
        text = "\n".join(filter(None, text_lines))
        keyboard = [
            [InlineKeyboardButton("Рассчитать", callback_data='price_calculator')],
            [InlineKeyboardButton("Заказать", callback_data=f'type_{key}')],
            [InlineKeyboardButton("Назад", callback_data='price_list')]
        ]
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        return SHOW_PRICE_LIST
    elif data.startswith('type_'):
        return await view_order_details(update, context)
    elif data == 'price_calculator':
        return await price_calculator(update, context)
    elif data == 'back_to_main':
        return await main_menu(update, context)
    user = update.effective_user
    log_user_action(user.id, user.username, "Прайс-лист")
    text = "💲 Прайс-лист (10% скидка сегодня! 🔥):\n\n"
    for key, val in ORDER_TYPES.items():
        prices = PRICES.get(key, {})
        min_price = prices.get('min') or prices.get('base', 0)
        text += f"{val['icon']} *{val['name']}* — от {min_price} ₽\n"
    keyboard = [[InlineKeyboardButton(f"Подробности {val['name']}", callback_data=f'price_detail_{key}')] for key, val in ORDER_TYPES.items()]
    keyboard.append([InlineKeyboardButton("🧮 Рассчитать цену", callback_data='price_calculator')])
    keyboard.append([InlineKeyboardButton("⬅️ Меню", callback_data='back_to_main')])
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    return SHOW_PRICE_LIST

# Калькулятор цен
async def price_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    data = query.data
    if data.startswith('type_'):
        return await view_order_details(update, context)
    if data.startswith('calc_type_'):
        key = data[10:]
        context.user_data['calc_type'] = key
        descriptions = [
            f"Тип: {ORDER_TYPES.get(key, {}).get('name', 'Неизвестно')}",
            "Выберите срок — спокойные сроки дают бонусы:",
            "",
        ]
        for preset in DEADLINE_PRESETS:
            descriptions.append(f"{preset['label']} — {preset['badge']}")
        reply_markup = build_deadline_keyboard('calc_dead_', include_back=True, back_callback='price_calculator')
        await query.edit_message_text("\n".join(descriptions), reply_markup=reply_markup)
        return SELECT_CALC_DEADLINE
    elif data == 'back_to_main':
        return await main_menu(update, context)
    user = update.effective_user
    log_user_action(user.id, user.username, "Калькулятор")
    text = "🧮 Выберите тип:"
    keyboard = [[InlineKeyboardButton(f"{v['icon']} {v['name']}", callback_data=f'calc_type_{k}')] for k, v in ORDER_TYPES.items()]
    keyboard.append([InlineKeyboardButton("⬅️ Меню", callback_data='back_to_main')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return PRICE_CALCULATOR

async def calc_select_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    data = query.data
    if data.startswith('calc_dead_'):
        key = data[10:]
        preset = get_deadline_preset(key)
        context.user_data['calc_deadline_key'] = key
        text = f"Срок: {preset['label']}\n{preset['badge']}\n\nВыберите сложность:"
        calc_type = context.user_data.get('calc_type')
        back_target = f'calc_type_{calc_type}' if calc_type else 'price_calculator'
        keyboard = [
            [InlineKeyboardButton("Простая (базовая)", callback_data='calc_comp_1.0')],
            [InlineKeyboardButton("Средняя (+10%)", callback_data='calc_comp_1.1'), InlineKeyboardButton("Сложная (+30%)", callback_data='calc_comp_1.3')],
            [InlineKeyboardButton("Назад", callback_data=back_target)]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return SELECT_CALC_COMPLEXITY
    return SELECT_CALC_DEADLINE

async def calc_select_complexity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    data = query.data
    if data.startswith('calc_comp_'):
        comp_key = data[10:]
        comp = float(comp_key)
        key = context.user_data.get('calc_type')
        if not key:
            return await price_calculator(update, context)
        deadline_key = context.user_data.get('calc_deadline_key', DEFAULT_DEADLINE_KEY)
        preset = get_deadline_preset(deadline_key)
        price = calculate_price(key, deadline_key, comp)
        name = ORDER_TYPES.get(key, {}).get('name', 'Неизвестно')
        complexity_labels = {
            '1.0': 'Простая (базовая)',
            '1.1': 'Средняя (+10%)',
            '1.3': 'Сложная (+30%)',
        }
        complexity_text = complexity_labels.get(comp_key, f"{int((comp - 1) * 100)}%")
        text = (
            f"Расчет: {name}\n"
            f"Срок: {preset['label']}\n"
            f"Сложность: {complexity_text}\n"
            f"Цена: {price} ₽ (Скидка сегодня!)\n\nЗаказать?"
        )
        keyboard = [
            [InlineKeyboardButton("📝 Заказать", callback_data=f'type_{key}')],
            [InlineKeyboardButton("Пересчитать", callback_data='price_calculator'), InlineKeyboardButton("Меню", callback_data='back_to_main')]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return PRICE_CALCULATOR
    return SELECT_CALC_COMPLEXITY

# Показ профиля
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data if query else None
    if query:
        await answer_callback_query(query, context)
    user = update.effective_user
    if data in (None, 'profile', 'profile_main', 'profile_home'):
        if data == 'profile':
            log_user_action(user.id, user.username, "Профиль")
        return await render_profile_main(update, context)
    if data == 'profile_back' or data == 'back_to_main':
        return await main_menu(update, context)
    if data == 'profile_orders':
        return await profile_show_orders(update, context)
    if data and data.startswith('profile_order_pause_'):
        order_id = data.rsplit('_', 1)[-1]
        return await profile_toggle_order_pause(update, context, order_id)
    if data and data.startswith('profile_order_delete_'):
        order_id = data.rsplit('_', 1)[-1]
        return await profile_delete_order(update, context, order_id)
    if data and data.startswith('profile_order_remind_'):
        order_id = data.rsplit('_', 1)[-1]
        return await profile_remind_order(update, context, order_id)
    if data and data.startswith('profile_order_'):
        order_id = data.rsplit('_', 1)[-1]
        return await profile_show_order_detail(update, context, order_id)
    if data == 'profile_feedbacks':
        return await profile_show_feedbacks(update, context)
    if data == 'profile_feedback_add':
        return await profile_prompt_feedback(update, context)
    if data and data.startswith('profile_feedback_delete_'):
        index_key = data.rsplit('_', 1)[-1]
        return await profile_delete_feedback(update, context, index_key)
    if data == 'profile_referrals':
        return await profile_show_referrals(update, context)
    if data == 'profile_bonuses':
        return await profile_show_bonuses(update, context)
    return await render_profile_main(update, context)

# Показ заказов


async def render_profile_main(update: Update, context: ContextTypes.DEFAULT_TYPE, notice: Optional[str] = None):
    user = update.effective_user
    user_id = str(user.id)
    orders = ORDERS.get(user_id, [])
    feedbacks = get_feedback_entries(user_id)
    referrals = REFERALS.get(user_id, [])
    credited, redeemed, balance, _ = get_bonus_summary(user_id)
    ref_link = context.user_data.get('ref_link')
    if not ref_link:
        bot_username = (await context.bot.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start={user_id}"
        context.user_data['ref_link'] = ref_link
    lines = [f"👤 <b>{html.escape(user.full_name or user.first_name or 'Профиль')}</b>"]
    if notice:
        lines.append(f"<i>{html.escape(notice)}</i>")
    lines.extend([
        f"\n📦 Заказы: {len(orders)}",
        f"⭐ Отзывы: {len(feedbacks)}",
        f"👥 Рефералы: {len(referrals)}",
        f"🎁 Бонусы: {balance} ₽ (начислено {credited} ₽ / списано {redeemed} ₽)",
        "",
        "Приглашайте друзей и копите бонусы за их заказы!",
        f"Реферальная ссылка: <a href=\"{html.escape(ref_link, quote=True)}\">{html.escape(ref_link)}</a>",
    ])
    keyboard = [
        [InlineKeyboardButton("📦 Мои заказы", callback_data='profile_orders')],
        [InlineKeyboardButton("⭐ Отзывы", callback_data='profile_feedbacks')],
        [InlineKeyboardButton("👥 Рефералы", callback_data='profile_referrals'), InlineKeyboardButton("🎁 Бонусы", callback_data='profile_bonuses')],
        [InlineKeyboardButton("⬅️ Меню", callback_data='back_to_main')],
    ]
    await edit_or_send(update, context, "\n".join(lines), keyboard)
    return PROFILE_MENU


async def profile_show_orders(update: Update, context: ContextTypes.DEFAULT_TYPE, notice: Optional[str] = None):
    user = update.effective_user
    user_id = str(user.id)
    log_user_action(user.id, user.username, "Профиль: список заказов")
    orders = sorted(ORDERS.get(user_id, []), key=lambda o: o.get('order_id', 0))
    lines = ["📦 <b>Ваши заказы</b>"]
    if notice:
        lines.append(f"<i>{html.escape(notice)}</i>")
    if not orders:
        lines.append("Пока заказов нет. Оформите первый заказ через раздел «Сделать заказ».")
    else:
        for order in orders:
            order_id = order.get('order_id', '—')
            order_name = ORDER_TYPES.get(order.get('type'), {}).get('name', 'Неизвестный тип')
            status = build_order_status(order)
            lines.append(
                f"• #{html.escape(str(order_id))} — {html.escape(order_name)} ({html.escape(status)})"
            )
    keyboard = []
    for order in orders:
        order_id = order.get('order_id')
        if order_id is None:
            continue
        order_name = ORDER_TYPES.get(order.get('type'), {}).get('name', 'Заказ')
        prefix = '⏸ ' if is_order_paused(order) else ''
        label = f"{prefix}#{order_id} · {truncate_for_button(order_name)}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f'profile_order_{order_id}')])
    keyboard.append([InlineKeyboardButton("⬅️ Профиль", callback_data='profile')])
    await edit_or_send(update, context, "\n".join(lines), keyboard)
    return PROFILE_ORDERS


async def profile_show_order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str, notice: Optional[str] = None):
    user = update.effective_user
    order, _ = find_user_order(user.id, order_id)
    if not order:
        return await profile_show_orders(update, context, notice="Заказ не найден или уже удалён.")
    log_user_action(user.id, user.username, f"Профиль: заказ #{order_id}")
    order_number = html.escape(str(order.get('order_id', order_id)))
    header = f"📦 <b>Заказ #{order_number}</b>"
    details = build_order_detail_text(order)
    parts = [header]
    if notice:
        parts.append(f"<i>{html.escape(notice)}</i>")
    parts.append(details)
    pause_label = "▶️ Возобновить" if is_order_paused(order) else "⏸ Пауза"
    keyboard = [
        [InlineKeyboardButton(pause_label, callback_data=f'profile_order_pause_{order_id}')],
        [InlineKeyboardButton("🔔 Напомнить менеджеру", callback_data=f'profile_order_remind_{order_id}')],
        [InlineKeyboardButton("🗑 Удалить заказ", callback_data=f'profile_order_delete_{order_id}')],
        [InlineKeyboardButton("⬅️ К заказам", callback_data='profile_orders')],
        [InlineKeyboardButton("🏠 Профиль", callback_data='profile')],
    ]
    await edit_or_send(update, context, "\n\n".join(parts), keyboard)
    return PROFILE_ORDER_DETAIL


async def profile_toggle_order_pause(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str):
    user = update.effective_user
    order, _ = find_user_order(user.id, order_id)
    if not order:
        return await profile_show_orders(update, context, notice="Заказ не найден.")
    if is_order_paused(order):
        previous = order.get('status_before_pause', 'в работе')
        order['status'] = previous
        order['client_paused'] = False
        order.pop('status_before_pause', None)
        notice = "Заказ возобновлён. Менеджер получил уведомление."
        action = "возобновил"
    else:
        order['status_before_pause'] = order.get('status', 'новый')
        order['status'] = 'на паузе (клиент)'
        order['client_paused'] = True
        notice = "Заказ поставлен на паузу. Мы подождём вашего сигнала."
        action = "поставил на паузу"
    save_json(ORDERS_FILE, ORDERS)
    log_user_action(user.id, user.username, f"Профиль: {action} заказ #{order_id}")
    if ADMIN_CHAT_ID:
        await notify_admin_order_event(context, user, order, action)
    return await profile_show_order_detail(update, context, order_id, notice=notice)


async def profile_delete_order(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str):
    user = update.effective_user
    order, user_orders = find_user_order(user.id, order_id)
    if not order:
        return await profile_show_orders(update, context, notice="Заказ не найден.")
    user_orders[:] = [o for o in user_orders if str(o.get('order_id')) != str(order_id)]
    if not user_orders:
        ORDERS.pop(str(user.id), None)
    save_json(ORDERS_FILE, ORDERS)
    log_user_action(user.id, user.username, f"Профиль: удалил заказ #{order_id}")
    if ADMIN_CHAT_ID:
        await notify_admin_order_event(context, user, order, 'удалил', extra_note='Клиент запросил отмену заказа через профиль.')
    return await profile_show_orders(update, context, notice='Заказ удалён. Если планы изменятся — создайте новый заказ.')


async def profile_remind_order(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str):
    user = update.effective_user
    order, _ = find_user_order(user.id, order_id)
    if not order:
        return await profile_show_orders(update, context, notice="Заказ не найден.")
    log_user_action(user.id, user.username, f"Профиль: напомнил о заказе #{order_id}")
    if ADMIN_CHAT_ID:
        deadline = order.get('deadline_label') or f"{order.get('deadline_days', '—')} дней"
        extra = f"Напоминание от клиента. Срок: {deadline}."
        await notify_admin_order_event(context, user, order, 'напомнил о', extra_note=extra)
    notice = "Напоминание отправлено менеджеру. Мы скоро свяжемся!"
    return await profile_show_order_detail(update, context, order_id, notice=notice)


async def profile_show_feedbacks(update: Update, context: ContextTypes.DEFAULT_TYPE, notice: Optional[str] = None):
    user = update.effective_user
    entries = get_feedback_entries(user.id)
    log_user_action(user.id, user.username, "Профиль: отзывы")
    lines = ["⭐ <b>Ваши отзывы</b>"]
    if notice:
        lines.append(f"<i>{html.escape(notice)}</i>")
    if not entries:
        lines.append("Вы ещё не оставляли отзыв. Поделитесь впечатлением и получите бонусы!")
    else:
        for idx, entry in enumerate(entries, 1):
            text = html.escape(entry.get('text', '')) or '—'
            created = entry.get('created_at')
            if created:
                lines.append(f"{idx}. {text}\n<small>{html.escape(str(created))}</small>")
            else:
                lines.append(f"{idx}. {text}")
    keyboard = [[InlineKeyboardButton("➕ Добавить отзыв", callback_data='profile_feedback_add')]]
    if entries:
        row = []
        for idx in range(len(entries)):
            row.append(InlineKeyboardButton(f"🗑 №{idx + 1}", callback_data=f'profile_feedback_delete_{idx}'))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
    keyboard.append([InlineKeyboardButton("⬅️ Профиль", callback_data='profile')])
    await edit_or_send(update, context, "\n".join(lines), keyboard)
    return PROFILE_FEEDBACKS


async def profile_prompt_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "⭐ <b>Оставьте отзыв</b>\n\n"
        f"Напишите текстовым сообщением, что понравилось или что можно улучшить. За отзыв начислим {FEEDBACK_BONUS_AMOUNT} ₽ на бонусный счёт.\n\n"
        "Чтобы отменить, нажмите «⬅️ Профиль» или отправьте /cancel."
    )
    keyboard = [[InlineKeyboardButton("⬅️ Профиль", callback_data='profile_feedbacks')]]
    await edit_or_send(update, context, text, keyboard)
    return PROFILE_FEEDBACK_INPUT


async def input_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    text = (update.message.text or '').strip()
    if not text:
        await update.message.reply_text("Отзыв не может быть пустым. Попробуйте ещё раз или отправьте /cancel.")
        return PROFILE_FEEDBACK_INPUT
    if text.lower() in {'/cancel', 'отмена'}:
        await update.message.reply_text("Добавление отзыва отменено.")
        return await profile_show_feedbacks(update, context, notice='Отмена добавления отзыва.')
    entries = get_feedback_entries(user_id)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    entries.append({'text': text, 'created_at': timestamp})
    save_feedback_entries(user_id, entries)
    add_bonus_operation(user_id, FEEDBACK_BONUS_AMOUNT, 'credit', 'Отзыв клиента')
    await update.message.reply_text(f"Спасибо за отзыв! На бонусный счёт начислено {FEEDBACK_BONUS_AMOUNT} ₽.")
    if ADMIN_CHAT_ID:
        user_link = get_user_link(user)
        admin_text = (
            f"⭐ Новый отзыв от <a href=\"{html.escape(user_link, quote=True)}\">{html.escape(user.full_name or user.first_name or user_id)}</a>\n"
            f"Текст: {html.escape(text)}"
        )
        await context.bot.send_message(ADMIN_CHAT_ID, admin_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    return await profile_show_feedbacks(update, context, notice='Отзыв сохранён и передан менеджеру.')


async def profile_delete_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE, index_key: str):
    user = update.effective_user
    user_id = str(user.id)
    entries = get_feedback_entries(user_id)
    try:
        idx = int(index_key)
    except (TypeError, ValueError):
        return await profile_show_feedbacks(update, context, notice='Не удалось определить отзыв.')
    if idx < 0 or idx >= len(entries):
        return await profile_show_feedbacks(update, context, notice='Отзыв не найден.')
    removed = entries.pop(idx)
    save_feedback_entries(user_id, entries)
    log_user_action(user.id, user.username, f"Профиль: удалил отзыв №{idx + 1}")
    if ADMIN_CHAT_ID:
        user_link = get_user_link(user)
        removed_text = removed.get('text', '')
        admin_text = (
            f"🗑 Клиент <a href=\"{html.escape(user_link, quote=True)}\">{html.escape(user.full_name or user.first_name or user_id)}</a> удалил отзыв.\n"
            f"Текст: {html.escape(removed_text)}"
        )
        await context.bot.send_message(ADMIN_CHAT_ID, admin_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    return await profile_show_feedbacks(update, context, notice='Отзыв удалён.')


async def profile_show_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    referrals = REFERALS.get(user_id, [])
    log_user_action(user.id, user.username, "Профиль: рефералы")
    lines = ["👥 <b>Реферальная программа</b>"]
    if not referrals:
        lines.append("Пока нет приглашённых друзей. Поделитесь ссылкой и получайте бонусы с их заказов!")
    else:
        for idx, ref in enumerate(referrals, 1):
            if isinstance(ref, dict):
                name = ref.get('name') or ref.get('username') or ref.get('user_id') or f"Реферал №{idx}"
                status = ref.get('status')
                bonus = ref.get('bonus')
                parts = [html.escape(str(name))]
                extras = []
                if status:
                    extras.append(str(status))
                if bonus:
                    extras.append(f"бонус {bonus} ₽")
                if extras:
                    parts.append(f"({', '.join(html.escape(item) for item in extras)})")
                lines.append(f"{idx}. {' '.join(parts)}")
            else:
                lines.append(f"{idx}. {html.escape(str(ref))}")
    ref_link = context.user_data.get('ref_link')
    if not ref_link:
        bot_username = (await context.bot.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start={user_id}"
        context.user_data['ref_link'] = ref_link
    lines.extend([
        "",
        f"Ваша ссылка: <a href=\"{html.escape(ref_link, quote=True)}\">{html.escape(ref_link)}</a>",
    ])
    keyboard = [
        [InlineKeyboardButton("⬅️ Профиль", callback_data='profile')],
    ]
    await edit_or_send(update, context, "\n".join(lines), keyboard)
    return PROFILE_REFERRALS


async def profile_show_bonuses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    credited, redeemed, balance, history = get_bonus_summary(user_id)
    log_user_action(user.id, user.username, "Профиль: бонусы")
    lines = [
        "🎁 <b>Бонусный счёт</b>",
        f"Начислено: {credited} ₽",
        f"Списано: {redeemed} ₽",
        f"Актуальный баланс: {balance} ₽",
    ]
    if history:
        lines.append("\nПоследние операции:")
        for item in reversed(history[-5:]):
            if isinstance(item, dict):
                amount = item.get('amount', 0)
                op_type = item.get('type')
                sign = '+' if op_type == 'credit' else '-'
                reason = item.get('reason', '')
                timestamp = item.get('timestamp', '')
                line = f"{timestamp} {sign}{amount} ₽ — {reason}".strip()
                lines.append(html.escape(line))
            else:
                lines.append(html.escape(str(item)))
    else:
        lines.append("\nИстория операций появится после начислений.")
    lines.append("\nБонусами можно оплатить часть следующего заказа — уточните у менеджера.")
    keyboard = [
        [InlineKeyboardButton("⬅️ Профиль", callback_data='profile')],
    ]
    await edit_or_send(update, context, "\n".join(lines), keyboard)
    return PROFILE_BONUSES

# Показ FAQ
async def show_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    data = query.data
    if data.startswith('faq_'):
        idx = int(data[4:])
        item = FAQ_ITEMS[idx]
        text = f"❓ {item['question']}\n\n{item['answer']}"
        keyboard = [[InlineKeyboardButton("Назад к FAQ", callback_data='faq')],
                    [InlineKeyboardButton("Меню", callback_data='back_to_main')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return FAQ_DETAILS
    elif data == 'back_to_main':
        return await main_menu(update, context)
    user = update.effective_user
    log_user_action(user.id, user.username, "FAQ")
    text = "❓ FAQ: Выберите вопрос"
    keyboard = [[InlineKeyboardButton(item['question'], callback_data=f'faq_{i}')] for i, item in enumerate(FAQ_ITEMS)]
    keyboard.append([InlineKeyboardButton("⬅️ Меню", callback_data='back_to_main')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return SHOW_FAQ

# Показ админ меню
async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📋 Заказы", callback_data='admin_orders')],
        [InlineKeyboardButton("👥 Пользователи", callback_data='admin_users'), InlineKeyboardButton("📊 Логи", callback_data='admin_logs')],
        [InlineKeyboardButton("💲 Цены", callback_data='admin_prices')],
        [InlineKeyboardButton("📤 Экспорт", callback_data='admin_export')],
        [InlineKeyboardButton("⬅️ Выход", callback_data='back_to_main')]
    ]
    text = "🔐 Админ-панель"
    if update.callback_query:
        query = update.callback_query
        await answer_callback_query(query, context)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU

def find_order_for_admin(user_id, order_id):
    user_orders = ORDERS.get(user_id, [])
    for order in user_orders:
        if str(order.get('order_id')) == str(order_id):
            return order, user_orders
    return None, user_orders

async def admin_show_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    text_lines = ["📋 Заказы (выберите, чтобы изменить статус или удалить):"]
    keyboard = []
    has_orders = False
    user_ids = sorted(
        ORDERS.keys(),
        key=lambda x: int(x) if str(x).lstrip('-').isdigit() else str(x)
    ) if ORDERS else []
    for uid in user_ids:
        for order in sorted(ORDERS.get(uid, []), key=lambda o: o.get('order_id', 0)):
            order_id = order.get('order_id')
            if order_id is None:
                continue
            status = order.get('status', 'новый')
            button_text = f"#{order_id} · {uid} · {status}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f'admin_view_{uid}_{order_id}')])
            has_orders = True
    if not has_orders:
        text_lines.append("Заказов пока нет.")
    keyboard.append([InlineKeyboardButton("Назад", callback_data='admin_menu')])
    await query.edit_message_text("\n".join(text_lines), reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU

async def admin_view_order(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str, order_id: str):
    query = update.callback_query
    order, _ = find_order_for_admin(user_id, order_id)
    if not order:
        await query.edit_message_text(
            "Заказ не найден.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data='admin_orders')]])
        )
        return ADMIN_MENU
    order_name = ORDER_TYPES.get(order.get('type'), {}).get('name', 'Неизвестно')
    contact_display = order.get('contact', 'Не указан')
    contact_link = order.get('contact_link')
    if contact_link:
        contact_html = f"<a href=\"{html.escape(contact_link, quote=True)}\">{html.escape(contact_display)}</a>"
    else:
        contact_html = html.escape(contact_display)
    upsell_titles = [UPSELL_LABELS.get(u, u) for u in order.get('upsells', [])]
    upsell_text = ', '.join(upsell_titles) if upsell_titles else 'нет'
    files_count = len(order.get('files', [])) if order.get('files') else 0
    user_link = f"tg://user?id={user_id}"
    deadline_display = order.get('deadline_label') or f"{order.get('deadline_days', 0)} дней"
    text = (
        f"Заказ #{order.get('order_id', 'N/A')} от <a href=\"{user_link}\">{user_id}</a>\n"
        f"Тип: {html.escape(order_name)}\n"
        f"Статус: {html.escape(order.get('status', 'новый'))}\n"
        f"Тема: {html.escape(order.get('topic', 'Без темы'))}\n"
        f"Срок: {html.escape(deadline_display)}\n"
        f"Контакт: {contact_html}\n"
        f"Допы: {html.escape(upsell_text)}\n"
        f"Требования: {html.escape(order.get('requirements', 'Нет'))}\n"
        f"Сумма: {order.get('price', 0)} ₽\n"
        f"Файлы: {files_count}"
    )
    keyboard = [
        [InlineKeyboardButton("Отменить заказ", callback_data=f'admin_cancel_{user_id}_{order_id}')],
        [InlineKeyboardButton("Удалить заказ", callback_data=f'admin_delete_{user_id}_{order_id}')],
        [InlineKeyboardButton("Назад", callback_data='admin_orders')]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return ADMIN_MENU

async def admin_cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str, order_id: str):
    query = update.callback_query
    order, _ = find_order_for_admin(user_id, order_id)
    if not order:
        await query.edit_message_text(
            "Заказ не найден.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data='admin_orders')]])
        )
        return ADMIN_MENU
    order['status'] = 'отменен'
    save_json(ORDERS_FILE, ORDERS)
    return await admin_view_order(update, context, user_id, order_id)

async def admin_delete_order(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str, order_id: str):
    query = update.callback_query
    order, user_orders = find_order_for_admin(user_id, order_id)
    if not order:
        await query.edit_message_text(
            "Заказ не найден.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data='admin_orders')]])
        )
        return ADMIN_MENU
    user_orders[:] = [ordr for ordr in user_orders if str(ordr.get('order_id')) != str(order_id)]
    if not user_orders:
        ORDERS.pop(user_id, None)
    save_json(ORDERS_FILE, ORDERS)
    return await admin_show_orders(update, context)

# Админ старт
async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("Доступ запрещен!")
        return
    user = update.effective_user
    log_user_action(user.id, user.username, "Админ-панель")
    return await show_admin_menu(update, context)

# Обработчик админ-меню
async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    data = query.data
    if data == 'admin_menu':
        return await show_admin_menu(update, context)
    if data == 'admin_orders':
        return await admin_show_orders(update, context)
    if data.startswith('admin_view_'):
        _, _, payload = data.partition('admin_view_')
        parts = payload.split('_')
        if len(parts) >= 2:
            user_id, order_id = parts[0], parts[1]
            return await admin_view_order(update, context, user_id, order_id)
    if data.startswith('admin_cancel_'):
        _, _, payload = data.partition('admin_cancel_')
        parts = payload.split('_')
        if len(parts) >= 2:
            user_id, order_id = parts[0], parts[1]
            return await admin_cancel_order(update, context, user_id, order_id)
    if data.startswith('admin_delete_'):
        _, _, payload = data.partition('admin_delete_')
        parts = payload.split('_')
        if len(parts) >= 2:
            user_id, order_id = parts[0], parts[1]
            return await admin_delete_order(update, context, user_id, order_id)
    text = ""
    keyboard = [[InlineKeyboardButton("Назад", callback_data='admin_menu')]]
    if data == 'admin_users':
        text = "👥 Пользователи:\n" + "\n".join(f"ID: {uid}" for uid in ORDERS.keys())
    elif data == 'admin_logs':
        text = "📊 Логи (последние 10):\n"
        for uid, logs in list(USER_LOGS.items())[-10:]:
            if logs:
                text += f"Пользователь {uid}: {logs[-1]['action']}\n"
    elif data == 'admin_prices':
        text = f"Текущий режим: {current_pricing_mode}\nВведите новый режим (hard/light):"
        context.user_data['admin_state'] = 'change_mode'
    elif data == 'admin_export':
        df = pd.DataFrame([{'user_id': uid, **ord} for uid, ords in ORDERS.items() for ord in ords])
        export_file = os.path.join(DATA_DIR, 'orders_export.csv')
        df.to_csv(export_file, index=False)
        await context.bot.send_document(ADMIN_CHAT_ID, open(export_file, 'rb'))
        os.remove(export_file)
        text = "📤 Экспорт отправлен!"
    elif data == 'back_to_main':
        return await main_menu(update, context)
    await query.edit_message_text(text or "Неизвестная команда. Возвращаюсь в админ-меню.", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU

# Обработчик сообщений админа
async def admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('admin_state')
    if state == 'change_mode':
        global current_pricing_mode
        current_pricing_mode = update.message.text.lower()
        await update.message.reply_text("Режим изменен!")
        context.user_data.pop('admin_state')
        return await show_admin_menu(update, context)
    return ADMIN_MENU

# Основная функция
def main():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start), CommandHandler('admin', admin_start)],
        states={
            SELECT_MAIN_MENU: [CallbackQueryHandler(main_menu_handler)],
            SELECT_ORDER_TYPE: [CallbackQueryHandler(select_order_type)],
            VIEW_ORDER_DETAILS: [CallbackQueryHandler(view_order_details)],
            INPUT_TOPIC: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_topic)],
            SELECT_DEADLINE: [CallbackQueryHandler(select_deadline)],
            INPUT_REQUIREMENTS: [
                CallbackQueryHandler(requirements_button_handler, pattern='^requirements_(hint|skip)$'),
                MessageHandler(filters.TEXT & ~filters.COMMAND, input_requirements),
                CommandHandler('skip', skip_requirements),
            ],
            INPUT_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_contact)],
            UPLOAD_FILES: [
                CallbackQueryHandler(file_upload_action, pattern='^files_(done|skip)$'),
                MessageHandler(
                    (
                        filters.Document.ALL
                        | filters.PHOTO
                        | filters.AUDIO
                        | filters.VOICE
                        | filters.VIDEO
                        | filters.VIDEO_NOTE
                        | filters.ANIMATION
                        | filters.Sticker.ALL
                    ),
                    handle_file_upload,
                ),
                CommandHandler('skip', skip_file_upload),
                CommandHandler('done', skip_file_upload),
                MessageHandler(filters.TEXT & ~filters.COMMAND, remind_file_upload),
            ],
            ADD_UPSSELL: [CallbackQueryHandler(upsell_handler)],
            ADD_ANOTHER_ORDER: [CallbackQueryHandler(add_another_handler)],
            CONFIRM_CART: [CallbackQueryHandler(confirm_cart_handler)],
            ADMIN_MENU: [CallbackQueryHandler(admin_menu_handler), MessageHandler(filters.TEXT & ~filters.COMMAND, admin_message)],
            PROFILE_MENU: [CallbackQueryHandler(show_profile)],
            PROFILE_ORDERS: [CallbackQueryHandler(show_profile)],
            PROFILE_ORDER_DETAIL: [CallbackQueryHandler(show_profile)],
            PROFILE_FEEDBACKS: [CallbackQueryHandler(show_profile)],
            PROFILE_REFERRALS: [CallbackQueryHandler(show_profile)],
            PROFILE_BONUSES: [CallbackQueryHandler(show_profile)],
            SHOW_PRICE_LIST: [CallbackQueryHandler(show_price_list)],
            PRICE_CALCULATOR: [CallbackQueryHandler(price_calculator)],
            SELECT_CALC_DEADLINE: [CallbackQueryHandler(calc_select_deadline)],
            SELECT_CALC_COMPLEXITY: [CallbackQueryHandler(calc_select_complexity)],
            SHOW_FAQ: [CallbackQueryHandler(show_faq)],
            FAQ_DETAILS: [CallbackQueryHandler(show_faq)],
            PROFILE_FEEDBACK_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, input_feedback),
                CallbackQueryHandler(show_profile),
            ],
        },
        fallbacks=[CommandHandler('start', start)],
    )
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
