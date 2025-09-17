import os
import logging
import json
import html
import re
import csv
from typing import Optional
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters, ConversationHandler
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from dotenv import load_dotenv

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
USERS_FILE = os.path.join(DATA_DIR, 'users.json')

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

# Глобальные данные (инициализируются позже через initialize_storage)
PRICES = {}
REFERALS = {}
ORDERS = {}
FEEDBACKS = {}
BONUSES = {}
USER_LOGS = {}
USERS = {}

# Глобальные данные по умолчанию
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


# Инициализация данных выполняется после определения вспомогательных функций

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

EXPORT_FIELD_ORDER = [
    'user_id',
    'order_id',
    'type',
    'topic',
    'status',
    'status_code',
    'created_at',
    'updated_at',
    'deadline_key',
    'deadline_label',
    'deadline_days',
    'price',
    'bonus_used',
    'referrer_id',
    'referral_rewarded',
    'loyalty_rewarded',
    'upsells',
    'contact',
    'contact_link',
    'requirements',
    'files',
    'status_history',
]

FEEDBACK_BONUS_AMOUNT = 200

LOYALTY_BONUS_RATE = 0.1
LOYALTY_BONUS_MIN = 300
REFERRAL_BONUS_RATE = 0.05
REFERRAL_BONUS_MIN = 200
BONUS_EXPIRATION_DAYS = 30
BONUS_USAGE_LIMIT = 0.5

ORDER_STATUS_CHOICES = [
    {'code': 'new', 'label': '🆕 Новый'},
    {'code': 'confirmed', 'label': '✅ Подтверждён'},
    {'code': 'in_progress', 'label': '⚙️ В работе'},
    {'code': 'waiting_payment', 'label': '💳 Ждёт оплату'},
    {'code': 'paid', 'label': '💰 Оплачен'},
    {'code': 'ready', 'label': '📦 Готов'},
    {'code': 'delivered', 'label': '🏁 Завершён'},
    {'code': 'paused', 'label': '⏸ На паузе'},
    {'code': 'cancelled', 'label': '❌ Отменён'},
]

ORDER_STATUS_BY_CODE = {item['code']: item for item in ORDER_STATUS_CHOICES}
ORDER_STATUS_BY_LABEL = {item['label']: item for item in ORDER_STATUS_CHOICES}
DEFAULT_ORDER_STATUS = 'new'

BONUS_CREDIT_TYPES = {
    'credit',
    'manual_credit',
    'loyalty',
    'referral',
    'referral_bonus',
    'feedback',
    'feedback_bonus',
}
BONUS_DEBIT_TYPES = {
    'debit',
    'manual_debit',
    'order_payment',
    'expire',
}

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


def get_status_entry_by_code(code: str) -> dict:
    return ORDER_STATUS_BY_CODE.get(code, ORDER_STATUS_BY_CODE[DEFAULT_ORDER_STATUS])


def get_status_label(code: str) -> str:
    return get_status_entry_by_code(code).get('label', 'Статус')


def resolve_status_code(value: Optional[str]) -> str:
    if not value:
        return DEFAULT_ORDER_STATUS
    if value in ORDER_STATUS_BY_CODE:
        return value
    if value in ORDER_STATUS_BY_LABEL:
        return ORDER_STATUS_BY_LABEL[value]['code']
    cleaned = str(value).strip().lower()
    for item in ORDER_STATUS_CHOICES:
        label = item.get('label', '')
        if cleaned == label.lower() or cleaned == label.split(' ', 1)[-1].lower():
            return item['code']
    return DEFAULT_ORDER_STATUS


def normalize_referrals_structure(raw):
    structure = {'referrers': {}, 'links': {}}
    if not isinstance(raw, dict):
        return structure
    if 'referrers' in raw or 'links' in raw:
        referrers_raw = raw.get('referrers', {})
        links_raw = raw.get('links', {})
    else:
        referrers_raw = raw
        links_raw = {}
    for ref_id, entries in referrers_raw.items():
        if not isinstance(entries, list):
            continue
        normalized_entries = []
        for entry in entries:
            if isinstance(entry, dict):
                user_id = entry.get('user_id') or entry.get('id') or entry.get('uid')
                username = entry.get('username')
                full_name = entry.get('full_name') or entry.get('name')
                joined_at = entry.get('joined_at') or entry.get('timestamp')
                status = entry.get('status') or entry.get('state') or 'приглашён'
                orders = entry.get('orders') if isinstance(entry.get('orders'), list) else []
                awarded_orders = entry.get('awarded_orders') if isinstance(entry.get('awarded_orders'), list) else []
                bonus_total = entry.get('bonus_total') if isinstance(entry.get('bonus_total'), (int, float)) else 0
            else:
                user_id = entry
                username = None
                full_name = None
                joined_at = None
                status = 'приглашён'
                orders = []
                awarded_orders = []
                bonus_total = 0
            if not user_id:
                continue
            try:
                normalized_user_id = int(user_id)
            except (TypeError, ValueError):
                normalized_user_id = str(user_id)
            record = {
                'user_id': normalized_user_id,
                'username': username,
                'full_name': full_name,
                'joined_at': joined_at,
                'status': status,
                'orders': orders,
                'awarded_orders': awarded_orders,
                'bonus_total': int(bonus_total) if isinstance(bonus_total, (int, float)) else 0,
            }
            normalized_entries.append(record)
            structure['links'][str(normalized_user_id)] = str(ref_id)
        if normalized_entries:
            structure['referrers'][str(ref_id)] = normalized_entries
    if isinstance(links_raw, dict):
        for uid, rid in links_raw.items():
            structure['links'].setdefault(str(uid), str(rid))
    return structure


def get_referrer_for_user(user_id: int) -> Optional[str]:
    return str(REFERALS.get('links', {}).get(str(user_id))) if isinstance(REFERALS, dict) else None


def update_referral_entry(referrer_id: str, user_id: int, **kwargs):
    referrer_list = REFERALS.setdefault('referrers', {}).setdefault(str(referrer_id), [])
    for entry in referrer_list:
        if str(entry.get('user_id')) == str(user_id):
            if 'add_order' in kwargs and kwargs['add_order'] is not None:
                orders = entry.setdefault('orders', [])
                if kwargs['add_order'] not in orders:
                    orders.append(kwargs['add_order'])
            if 'add_awarded' in kwargs and kwargs['add_awarded'] is not None:
                awarded = entry.setdefault('awarded_orders', [])
                if kwargs['add_awarded'] not in awarded:
                    awarded.append(kwargs['add_awarded'])
            if 'bonus_increment' in kwargs and kwargs['bonus_increment']:
                entry['bonus_total'] = int(entry.get('bonus_total', 0) + kwargs['bonus_increment'])
            update_payload = {
                k: v for k, v in kwargs.items()
                if k not in {'add_order', 'add_awarded', 'bonus_increment'} and v is not None
            }
            if update_payload:
                entry.update(update_payload)
            return entry
    record = {
        'user_id': user_id,
        'username': kwargs.get('username'),
        'full_name': kwargs.get('full_name'),
        'joined_at': kwargs.get('joined_at'),
        'status': kwargs.get('status', 'приглашён'),
        'orders': [],
        'awarded_orders': [],
        'bonus_total': int(kwargs.get('bonus_total', 0) or 0),
    }
    if kwargs.get('add_order') is not None:
        record['orders'].append(kwargs['add_order'])
    elif isinstance(kwargs.get('orders'), list):
        record['orders'].extend(kwargs['orders'])
    if kwargs.get('add_awarded') is not None:
        record['awarded_orders'].append(kwargs['add_awarded'])
    elif isinstance(kwargs.get('awarded_orders'), list):
        record['awarded_orders'].extend(kwargs['awarded_orders'])
    referrer_list.append(record)
    return record


def register_referral(referrer_id: int, user) -> None:
    if not referrer_id or not user:
        return
    if int(referrer_id) == int(user.id):
        return
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    REFERALS.setdefault('links', {})[str(user.id)] = str(referrer_id)
    update_referral_entry(
        str(referrer_id),
        user.id,
        username=user.username,
        full_name=user.full_name,
        joined_at=timestamp,
        status='перешёл по ссылке',
    )
    save_json(REFERRALS_FILE, REFERALS)


def get_referrals_for_referrer(referrer_id: int) -> list:
    entries = REFERALS.get('referrers', {}).get(str(referrer_id), [])
    if isinstance(entries, list):
        return entries
    return []


def normalize_order_record(order: dict, owner_id: Optional[str] = None) -> dict:
    if not isinstance(order, dict):
        return {}
    created_at = order.get('created_at') or order.get('date')
    if not created_at:
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    order['created_at'] = created_at
    order.setdefault('updated_at', created_at)
    status_code = resolve_status_code(order.get('status_code') or order.get('status'))
    order['status_code'] = status_code
    order['status'] = get_status_label(status_code)
    if not isinstance(order.get('status_history'), list):
        order['status_history'] = []
    normalized_history = []
    for item in order.get('status_history', []):
        if not isinstance(item, dict):
            continue
        hist_code = resolve_status_code(item.get('code') or item.get('status'))
        timestamp = item.get('timestamp') or created_at
        note = item.get('note')
        normalized_history.append({
            'code': hist_code,
            'status': get_status_label(hist_code),
            'timestamp': timestamp,
            'note': note,
        })
    if not normalized_history:
        normalized_history.append({
            'code': status_code,
            'status': get_status_label(status_code),
            'timestamp': created_at,
            'note': 'Создан автоматически',
        })
    order['status_history'] = normalized_history
    try:
        order['price'] = int(order.get('price', 0))
    except (TypeError, ValueError):
        order['price'] = 0
    try:
        bonus_used = int(order.get('bonus_used', 0) or 0)
    except (TypeError, ValueError):
        bonus_used = 0
    order['bonus_used'] = max(0, bonus_used)
    order['referral_rewarded'] = bool(order.get('referral_rewarded', False))
    order['loyalty_rewarded'] = bool(order.get('loyalty_rewarded', False))
    if owner_id is not None and not order.get('referrer_id'):
        referrer_id = get_referrer_for_user(int(owner_id))
        if referrer_id:
            order['referrer_id'] = referrer_id
    return order


def normalize_orders_storage() -> None:
    changed = False
    normalized_orders = {}
    for user_id, orders in ORDERS.items():
        user_key = str(user_id)
        if not isinstance(orders, list):
            continue
        normalized_list = []
        for order in orders:
            if not isinstance(order, dict):
                continue
            normalized_list.append(normalize_order_record(order, user_key))
        normalized_orders[user_key] = normalized_list
    if normalized_orders != ORDERS:
        ORDERS.clear()
        ORDERS.update(normalized_orders)
        changed = True
    if changed:
        save_json(ORDERS_FILE, ORDERS)


def initialize_storage() -> None:
    global PRICES, REFERALS, ORDERS, FEEDBACKS, BONUSES, USER_LOGS, USERS

    PRICES = normalize_prices(load_json(PRICES_FILE, {}))

    REFERALS = load_json(REFERRALS_FILE)
    if not isinstance(REFERALS, dict):
        REFERALS = {}
    REFERALS = normalize_referrals_structure(REFERALS)

    ORDERS = load_json(ORDERS_FILE)
    if not isinstance(ORDERS, dict):
        ORDERS = {}

    FEEDBACKS = load_json(FEEDBACKS_FILE)
    if not isinstance(FEEDBACKS, dict):
        FEEDBACKS = {}

    BONUSES = load_json(BONUSES_FILE)
    if not isinstance(BONUSES, dict):
        BONUSES = {}

    USER_LOGS = load_json(USER_LOGS_FILE)
    if not isinstance(USER_LOGS, dict):
        USER_LOGS = {}

    USERS = load_json(USERS_FILE)
    if not isinstance(USERS, dict):
        USERS = {}

    normalize_orders_storage()


initialize_storage()

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
def log_user_action(user_id, username, action, full_name=None):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = {'timestamp': timestamp, 'action': action}
    if username:
        log_entry['username'] = username
    if full_name:
        log_entry['full_name'] = full_name
    USER_LOGS.setdefault(str(user_id), []).append(log_entry)
    save_json(USER_LOGS_FILE, USER_LOGS)
    profile = USERS.setdefault(str(user_id), {})
    profile.setdefault('first_seen', timestamp)
    profile['last_seen'] = timestamp
    profile['last_action'] = action
    if username:
        profile['username'] = username
    if full_name:
        profile['full_name'] = full_name
    save_json(USERS_FILE, USERS)
    display_name = username or full_name or str(user_id)
    logger.info(f"Пользователь {user_id} ({display_name}): {action}")

async def answer_callback_query(query, context):
    if not query:
        return
    last_answered_id = context.user_data.get('_last_answered_query')
    if last_answered_id == query.id:
        return
    await query.answer()
    context.user_data['_last_answered_query'] = query.id


def parse_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value)
        except (OverflowError, OSError, ValueError):
            return datetime.now()
    if isinstance(value, str):
        for pattern in (
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S',
            '%d.%m.%Y %H:%M',
            '%Y-%m-%d',
        ):
            try:
                return datetime.strptime(value, pattern)
            except ValueError:
                continue
    return datetime.now()


def recalculate_bonus_entry(entry: dict) -> bool:
    history = entry.get('history', [])
    if not isinstance(history, list):
        history = []
        entry['history'] = history
    total_credit = 0
    total_debit = 0
    for item in history:
        if not isinstance(item, dict):
            continue
        try:
            amount = int(item.get('amount', 0) or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            continue
        entry_type = item.get('type') or item.get('operation')
        if entry_type in BONUS_CREDIT_TYPES:
            total_credit += amount
        elif entry_type in BONUS_DEBIT_TYPES:
            total_debit += amount
    balance = max(0, total_credit - total_debit)
    changed = False
    if entry.get('credited') != total_credit:
        entry['credited'] = total_credit
        changed = True
    if entry.get('redeemed') != total_debit:
        entry['redeemed'] = total_debit
        changed = True
    if entry.get('balance') != balance:
        entry['balance'] = balance
        changed = True
    return changed


def expire_outdated_bonuses(entry: dict) -> bool:
    history = entry.setdefault('history', [])
    if not history:
        return False
    ledger = []
    for item in sorted(history, key=lambda i: parse_datetime((i or {}).get('timestamp'))):
        if not isinstance(item, dict):
            continue
        try:
            amount = int(item.get('amount', 0) or 0)
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            continue
        entry_type = item.get('type') or item.get('operation')
        timestamp = parse_datetime(item.get('timestamp'))
        if entry_type in BONUS_CREDIT_TYPES:
            ledger.append({'amount': amount, 'remaining': amount, 'timestamp': timestamp})
        elif entry_type in BONUS_DEBIT_TYPES:
            to_remove = amount
            for credit in ledger:
                if to_remove <= 0:
                    break
                available = credit.get('remaining', 0)
                if available <= 0:
                    continue
                consume = min(available, to_remove)
                credit['remaining'] = available - consume
                to_remove -= consume
    now = datetime.now()
    expired_total = 0
    for credit in ledger:
        remaining = credit.get('remaining', 0)
        if remaining <= 0:
            continue
        if now - credit['timestamp'] >= timedelta(days=BONUS_EXPIRATION_DAYS):
            expired_total += remaining
            credit['remaining'] = 0
            history.append({
                'type': 'expire',
                'amount': remaining,
                'reason': 'Бонусы сгорели (30 дней без использования)',
                'timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
            })
    if expired_total:
        entry['redeemed'] = int(entry.get('redeemed', 0)) + expired_total
        entry['balance'] = max(0, int(entry.get('balance', 0)) - expired_total)
        return True
    return False


def ensure_bonus_account(user_id: str):
    user_key = str(user_id)
    entry = BONUSES.setdefault(user_key, {})
    changed = False
    if expire_outdated_bonuses(entry):
        changed = True
    if recalculate_bonus_entry(entry):
        changed = True
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
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        return ensure_bonus_account(user_id)
    entry = ensure_bonus_account(user_id)
    available_balance = int(entry.get('balance', 0))
    if operation_type in BONUS_DEBIT_TYPES:
        amount = min(amount, available_balance)
        if amount <= 0:
            return entry
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    entry.setdefault('history', []).append({
        'type': operation_type,
        'amount': amount,
        'reason': reason,
        'timestamp': timestamp,
    })
    recalculate_bonus_entry(entry)
    save_json(BONUSES_FILE, BONUSES)
    return entry


def get_user_profile(user_id: int) -> dict:
    return USERS.get(str(user_id), {})


def format_username(username: Optional[str]) -> Optional[str]:
    if not username:
        return None
    return username if username.startswith('@') else f"@{username}"


def format_user_display_name(user_id: int) -> str:
    profile = get_user_profile(user_id)
    username = format_username(profile.get('username'))
    full_name = profile.get('full_name')
    if username:
        return username
    if full_name:
        return full_name
    return str(user_id)


def build_user_contact_link(user_id: int) -> str:
    profile = get_user_profile(user_id)
    username = profile.get('username')
    if username:
        return f"https://t.me/{username}"
    return f"tg://user?id={user_id}"


def get_recent_user_profiles(limit: Optional[int] = None):
    records = []
    for user_id, profile in USERS.items():
        last_seen = parse_datetime(profile.get('last_seen')) if profile.get('last_seen') else datetime.min
        records.append((last_seen, user_id, profile))
    records.sort(key=lambda item: item[0], reverse=True)
    if limit is not None:
        records = records[:limit]
    return records


async def safe_send_message(bot, chat_id: int, text: str, **kwargs):
    try:
        await bot.send_message(chat_id, text, **kwargs)
    except TelegramError as exc:
        logger.warning(f"Не удалось отправить сообщение {chat_id}: {exc}")


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


def save_prices():
    save_json(PRICES_FILE, PRICES)


def adjust_price_value(order_type_key: str, field: str, delta: int) -> dict:
    entry = PRICES.setdefault(
        order_type_key,
        dict(DEFAULT_PRICES.get(order_type_key, {'base': 0, 'min': 0}))
    )
    if field not in {'base', 'min'}:
        return entry
    try:
        current_value = int(entry.get(field, 0))
    except (TypeError, ValueError):
        current_value = 0
    new_value = max(0, current_value + delta)
    entry[field] = new_value
    base = int(entry.get('base', 0))
    minimum = int(entry.get('min', base))
    if field == 'base' and minimum < new_value:
        entry['min'] = new_value
    elif field == 'min' and new_value < base:
        entry['min'] = base
    save_prices()
    return entry


def set_price_value(order_type_key: str, base: Optional[int] = None, minimum: Optional[int] = None) -> dict:
    entry = PRICES.setdefault(
        order_type_key,
        dict(DEFAULT_PRICES.get(order_type_key, {'base': 0, 'min': 0}))
    )
    if base is not None:
        try:
            base_val = max(0, int(base))
        except (TypeError, ValueError):
            base_val = entry.get('base', 0)
        entry['base'] = base_val
    if minimum is not None:
        try:
            min_val = max(0, int(minimum))
        except (TypeError, ValueError):
            min_val = entry.get('min', entry.get('base', 0))
        entry['min'] = min_val
    base_val = int(entry.get('base', 0))
    min_val = int(entry.get('min', base_val))
    if min_val < base_val:
        entry['min'] = base_val
    save_prices()
    return entry

# Обработчик ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")
    if ADMIN_CHAT_ID:
        await context.bot.send_message(ADMIN_CHAT_ID, f"Ошибка: {context.error}")

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    log_user_action(user.id, user.username, "/start", user.full_name)
    args = update.message.text.split()
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={user.id}"
    context.user_data['ref_link'] = ref_link
    if len(args) > 1 and args[1].lstrip('-').isdigit():
        referrer_id = int(args[1])
        if referrer_id != user.id:
            register_referral(referrer_id, user)
            context.user_data['referrer_id'] = referrer_id
            try:
                await context.bot.send_message(referrer_id, f"🎉 Новый реферал: {user.first_name}")
            except TelegramError as exc:
                logger.warning(f"Не удалось уведомить реферера {referrer_id}: {exc}")
    welcome = (
        f"👋 Добро пожаловать, {user.first_name}! Работаем со всеми дисциплинами, кроме технических (чертежи)."
        f" Уже 5000+ клиентов и 10% скидка на первый заказ 🔥\nПоделитесь ссылкой для бонусов: {ref_link}"
    )
    return await main_menu(update, context, welcome)

# Главное меню
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, message=None):
    user = update.effective_user
    log_user_action(user.id, user.username, "Главное меню", user.full_name)
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
    log_user_action(user.id, user.username, f"Выбор в меню: {data}", user.full_name)
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
    log_user_action(user.id, user.username, "Выбор типа заказа", user.full_name)
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
    log_user_action(user.id, user.username, f"Тема: {update.message.text}", user.full_name)
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
        user = update.effective_user
        user_id = str(user.id)
        user_orders = ORDERS.setdefault(user_id, [])
        existing_ids = [order.get('order_id', 0) for order in user_orders]
        order_id = max(existing_ids, default=0) + 1
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new_orders = []
        for raw_order in context.user_data['cart']:
            order_data = dict(raw_order)
            order_data['order_id'] = order_id
            order_data['user_id'] = int(user_id)
            order_data['created_at'] = created_at
            order_data['updated_at'] = created_at
            status_code = DEFAULT_ORDER_STATUS
            order_data['status_code'] = status_code
            order_data['status'] = get_status_label(status_code)
            order_data['status_history'] = [{
                'code': status_code,
                'status': get_status_label(status_code),
                'timestamp': created_at,
                'note': 'Заказ создан клиентом',
            }]
            order_data['bonus_used'] = 0
            order_data['referral_rewarded'] = False
            order_data['loyalty_rewarded'] = False
            referrer_id = get_referrer_for_user(int(user_id))
            if referrer_id:
                order_data['referrer_id'] = referrer_id
                update_referral_entry(
                    referrer_id,
                    int(user_id),
                    add_order=order_id,
                    status='оформил заказ',
                )
                save_json(REFERRALS_FILE, REFERALS)
            user_orders.append(order_data)
            new_orders.append(order_data)
            order_id += 1
        save_json(ORDERS_FILE, ORDERS)
        text = (
            "✅ Заказ оформлен! Наш менеджер скоро свяжется с вами.\n"
            "[Администратор](https://t.me/Thisissaymoon) уже получил все детали и файлы."
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
        if ADMIN_CHAT_ID:
            await notify_admin_about_order(update, context, new_orders)
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
    log_user_action(user.id, user.username, "Прайс-лист", user.full_name)
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
    log_user_action(user.id, user.username, "Калькулятор", user.full_name)
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
            log_user_action(user.id, user.username, "Профиль", user.full_name)
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
    try:
        referrals = get_referrals_for_referrer(int(user_id))
    except (TypeError, ValueError):
        referrals = []
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
    log_user_action(user.id, user.username, "Профиль: список заказов", user.full_name)
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
    log_user_action(user.id, user.username, f"Профиль: заказ #{order_id}", user.full_name)
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
    log_user_action(user.id, user.username, f"Профиль: {action} заказ #{order_id}", user.full_name)
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
    log_user_action(user.id, user.username, f"Профиль: удалил заказ #{order_id}", user.full_name)
    if ADMIN_CHAT_ID:
        await notify_admin_order_event(context, user, order, 'удалил', extra_note='Клиент запросил отмену заказа через профиль.')
    return await profile_show_orders(update, context, notice='Заказ удалён. Если планы изменятся — создайте новый заказ.')


async def profile_remind_order(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str):
    user = update.effective_user
    order, _ = find_user_order(user.id, order_id)
    if not order:
        return await profile_show_orders(update, context, notice="Заказ не найден.")
    log_user_action(user.id, user.username, f"Профиль: напомнил о заказе #{order_id}", user.full_name)
    if ADMIN_CHAT_ID:
        deadline = order.get('deadline_label') or f"{order.get('deadline_days', '—')} дней"
        extra = f"Напоминание от клиента. Срок: {deadline}."
        await notify_admin_order_event(context, user, order, 'напомнил о', extra_note=extra)
    notice = "Напоминание отправлено менеджеру. Мы скоро свяжемся!"
    return await profile_show_order_detail(update, context, order_id, notice=notice)


async def profile_show_feedbacks(update: Update, context: ContextTypes.DEFAULT_TYPE, notice: Optional[str] = None):
    user = update.effective_user
    entries = get_feedback_entries(user.id)
    log_user_action(user.id, user.username, "Профиль: отзывы", user.full_name)
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
    log_user_action(user.id, user.username, f"Профиль: удалил отзыв №{idx + 1}", user.full_name)
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
    try:
        referrals = get_referrals_for_referrer(int(user_id))
    except (TypeError, ValueError):
        referrals = []
    log_user_action(user.id, user.username, "Профиль: рефералы", user.full_name)
    lines = ["👥 <b>Реферальная программа</b>"]
    if not referrals:
        lines.append("Пока нет приглашённых друзей. Поделитесь ссылкой и получайте бонусы с их заказов!")
    else:
        for idx, ref in enumerate(referrals, 1):
            ref_user_id = ref.get('user_id')
            display_name = ref.get('full_name') or ref.get('username') or ref_user_id or f"Реферал №{idx}"
            status = html.escape(str(ref.get('status', 'в процессе')))
            bonus_total = ref.get('bonus_total', 0)
            if ref_user_id:
                try:
                    link = build_user_contact_link(int(ref_user_id))
                    name_html = f"<a href=\"{html.escape(link, quote=True)}\">{html.escape(str(display_name))}</a>"
                except (TypeError, ValueError):
                    name_html = html.escape(str(display_name))
            else:
                name_html = html.escape(str(display_name))
            lines.append(f"{idx}. {name_html} — {status} (начислено бонусов {bonus_total} ₽)")
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
    log_user_action(user.id, user.username, "Профиль: бонусы", user.full_name)
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
    lines.append("\nБонусами можно оплатить до 50% стоимости заказа. Не забывайте использовать их в течение 30 дней — иначе они сгорают.")
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
    log_user_action(user.id, user.username, "FAQ", user.full_name)
    text = "❓ FAQ: Выберите вопрос"
    keyboard = [[InlineKeyboardButton(item['question'], callback_data=f'faq_{i}')] for i, item in enumerate(FAQ_ITEMS)]
    keyboard.append([InlineKeyboardButton("⬅️ Меню", callback_data='back_to_main')])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return SHOW_FAQ

# Показ админ меню
async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📦 Все заказы", callback_data='admin_orders'), InlineKeyboardButton("🔥 Последние", callback_data='admin_recent_orders')],
        [InlineKeyboardButton("👥 Лиды", callback_data='admin_leads'), InlineKeyboardButton("🎁 Бонусы", callback_data='admin_bonuses')],
        [InlineKeyboardButton("💲 Цены", callback_data='admin_prices'), InlineKeyboardButton("📤 Экспорт", callback_data='admin_export')],
        [InlineKeyboardButton("⬅️ Выход", callback_data='back_to_main')]
    ]
    text = "🔐 Админ-панель. Выберите раздел:"
    if update.callback_query:
        query = update.callback_query
        await answer_callback_query(query, context)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU

def find_order_for_admin(user_id, order_id):
    user_key = str(user_id)
    user_orders = ORDERS.get(user_key, [])
    for order in user_orders:
        if str(order.get('order_id')) == str(order_id):
            normalize_order_record(order, user_key)
            return order, user_orders
    return None, user_orders


def set_order_status(order: dict, status_code: str, note: Optional[str] = None) -> bool:
    target_code = resolve_status_code(status_code)
    current_code = resolve_status_code(order.get('status_code') or order.get('status'))
    if target_code == current_code:
        return False
    label = get_status_label(target_code)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    order['status_code'] = target_code
    order['status'] = label
    order['updated_at'] = timestamp
    history = order.setdefault('status_history', [])
    history.append({
        'code': target_code,
        'status': label,
        'timestamp': timestamp,
        'note': note,
    })
    return True


def calculate_loyalty_bonus(amount: int) -> int:
    raw_bonus = amount * LOYALTY_BONUS_RATE
    return max(LOYALTY_BONUS_MIN, round_price(raw_bonus))


def calculate_referral_bonus(amount: int) -> int:
    raw_bonus = amount * REFERRAL_BONUS_RATE
    return max(REFERRAL_BONUS_MIN, round_price(raw_bonus))


async def award_loyalty_bonus(context: ContextTypes.DEFAULT_TYPE, user_id: int, order: dict):
    if order.get('loyalty_rewarded'):
        return
    price = int(order.get('price', 0) or 0)
    if price <= 0:
        return
    bonus_amount = calculate_loyalty_bonus(price)
    add_bonus_operation(str(user_id), bonus_amount, 'loyalty', f'Бонус за оплату заказа #{order.get("order_id")}')
    order['loyalty_rewarded'] = True
    await safe_send_message(
        context.bot,
        user_id,
        f"🎁 За заказ #{order.get('order_id')} начислено {bonus_amount} ₽ бонусами. Спасибо за доверие!",
    )


async def award_referral_bonus(context: ContextTypes.DEFAULT_TYPE, user_id: int, order: dict):
    if order.get('referral_rewarded'):
        return
    referrer_id = order.get('referrer_id') or get_referrer_for_user(user_id)
    if not referrer_id:
        return
    try:
        referrer_int = int(referrer_id)
    except (TypeError, ValueError):
        referrer_int = None
    price = int(order.get('price', 0) or 0)
    if price <= 0:
        return
    bonus_amount = calculate_referral_bonus(price)
    add_bonus_operation(str(referrer_id), bonus_amount, 'referral', f'Бонус за заказ #{order.get("order_id")} приглашённого пользователя')
    order['referral_rewarded'] = True
    update_referral_entry(
        str(referrer_id),
        user_id,
        add_awarded=order.get('order_id'),
        status='реферал оплатил заказ',
        bonus_increment=bonus_amount,
    )
    save_json(REFERRALS_FILE, REFERALS)
    if referrer_int:
        await safe_send_message(
            context.bot,
            referrer_int,
            f"🎉 Ваш приглашённый клиент оплатил заказ #{order.get('order_id')}! Начислено {bonus_amount} ₽.",
        )


async def process_paid_order(context: ContextTypes.DEFAULT_TYPE, user_id: int, order: dict):
    await award_loyalty_bonus(context, user_id, order)
    await award_referral_bonus(context, user_id, order)


def available_bonus_for_order(order: dict) -> int:
    try:
        price = int(order.get('price', 0) or 0)
    except (TypeError, ValueError):
        price = 0
    try:
        used = int(order.get('bonus_used', 0) or 0)
    except (TypeError, ValueError):
        used = 0
    limit = int(price * BONUS_USAGE_LIMIT)
    return max(0, limit - used)


def collect_all_orders() -> list:
    collected = []
    for user_id, orders in ORDERS.items():
        if not isinstance(orders, list):
            continue
        for order in orders:
            if not isinstance(order, dict):
                continue
            normalize_order_record(order, user_id)
            created = parse_datetime(order.get('created_at'))
            updated = parse_datetime(order.get('updated_at'))
            try:
                owner_id = int(user_id)
            except (TypeError, ValueError):
                owner_id = user_id
            collected.append({
                'user_id': owner_id,
                'order': order,
                'created': created,
                'updated': updated,
            })
    collected.sort(key=lambda item: item['created'], reverse=True)
    return collected


async def debit_bonuses_for_order(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    order: dict,
    requested_amount: int,
):
    entry = ensure_bonus_account(str(user_id))
    balance = int(entry.get('balance', 0))
    limit = available_bonus_for_order(order)
    amount = min(requested_amount, balance, limit)
    if amount <= 0:
        return 0
    add_bonus_operation(str(user_id), amount, 'order_payment', f'Списание на заказ #{order.get("order_id")}')
    order['bonus_used'] = order.get('bonus_used', 0) + amount
    updated_entry = ensure_bonus_account(user_id)
    new_balance = updated_entry.get('balance', 0)
    await safe_send_message(
        context.bot,
        user_id,
        f"✅ Списано {amount} ₽ бонусами за заказ #{order.get('order_id')} (осталось {new_balance} ₽).",
    )
    return amount

def chunk_buttons(buttons, size=2):
    return [buttons[i:i + size] for i in range(0, len(buttons), size) if buttons[i:i + size]]


def build_admin_order_view(user_id, order: dict, notice: Optional[str] = None):
    owner_id = int(user_id)
    order_name = ORDER_TYPES.get(order.get('type'), {}).get('name', 'Неизвестный тип')
    contact_link = order.get('contact_link') or build_user_contact_link(owner_id)
    contact_display = order.get('contact') or format_user_display_name(owner_id)
    contact_html = f"<a href=\"{html.escape(contact_link, quote=True)}\">{html.escape(contact_display)}</a>"
    upsell_titles = [UPSELL_LABELS.get(u, u) for u in order.get('upsells', [])]
    upsell_text = ', '.join(upsell_titles) if upsell_titles else 'нет'
    history_lines = []
    for item in order.get('status_history', [])[-5:]:
        if isinstance(item, dict):
            stamp = item.get('timestamp') or '—'
            status_text = item.get('status') or item.get('code') or '—'
            note = item.get('note')
            suffix = f" · {note}" if note else ''
            history_lines.append(f"{html.escape(str(stamp))} — {html.escape(str(status_text))}{html.escape(suffix)}")
    bonus_used = order.get('bonus_used', 0)
    referrer_id = order.get('referrer_id')
    ref_info = ''
    if referrer_id:
        try:
            ref_display = format_user_display_name(int(referrer_id))
            ref_link = build_user_contact_link(int(referrer_id))
            ref_info = f"<a href=\"{html.escape(ref_link, quote=True)}\">{html.escape(ref_display)}</a>"
        except (TypeError, ValueError):
            ref_info = html.escape(str(referrer_id))
    lines = [f"📦 <b>Заказ #{html.escape(str(order.get('order_id', '—')))}</b>"]
    if notice:
        lines.append(f"<i>{html.escape(notice)}</i>")
    lines.extend([
        f"Тип: {html.escape(order_name)}",
        f"Клиент: {contact_html}",
        f"Телеграм: <a href=\"{html.escape(build_user_contact_link(owner_id), quote=True)}\">{html.escape(format_user_display_name(owner_id))}</a>",
        f"Статус: {html.escape(order.get('status', '—'))}",
        f"Создан: {html.escape(str(order.get('created_at', '—')))}",
        f"Обновлён: {html.escape(str(order.get('updated_at', '—')))}",
        f"Цена: {order.get('price', 0)} ₽ (бонусами оплачено {bonus_used} ₽)",
    ])
    if order.get('deadline_label') or order.get('deadline_days'):
        deadline_display = order.get('deadline_label') or f"{order.get('deadline_days', '—')} дней"
        lines.append(f"Срок: {html.escape(deadline_display)}")
    if order.get('topic'):
        lines.append(f"Тема: {html.escape(order.get('topic', ''))}")
    if order.get('requirements'):
        lines.append(f"Требования: {html.escape(order.get('requirements', ''))}")
    lines.append(f"Контакт клиента: {contact_html}")
    lines.append(f"Допы: {html.escape(upsell_text)}")
    if ref_info:
        lines.append(f"Реферер: {ref_info}")
    lines.append(f"Файлы: {len(order.get('files', []) or [])}")
    if history_lines:
        lines.append("\nИстория статусов:")
        lines.extend(history_lines)
    keyboard_buttons = []
    status_buttons = []
    current_code = resolve_status_code(order.get('status_code') or order.get('status'))
    for status in ORDER_STATUS_CHOICES:
        prefix = '✅' if status['code'] == current_code else '•'
        status_buttons.append(
            InlineKeyboardButton(
                f"{prefix} {status['label']}",
                callback_data=f"admin_status_{user_id}_{order.get('order_id')}_{status['code']}"
            )
        )
    keyboard_buttons.extend(chunk_buttons(status_buttons, 2))
    available_for_order = available_bonus_for_order(order)
    client_balance = ensure_bonus_account(str(user_id)).get('balance', 0)
    if available_for_order and client_balance:
        keyboard_buttons.append([
            InlineKeyboardButton(
                "💳 Списать бонусы",
                callback_data=f"admin_order_bonus_{user_id}_{order.get('order_id')}"
            )
        ])
    keyboard_buttons.append([
        InlineKeyboardButton("🎁 Бонусы клиента", callback_data=f'admin_bonus_user_{user_id}')
    ])
    keyboard_buttons.append([
        InlineKeyboardButton("🗑 Удалить заказ", callback_data=f'admin_delete_{user_id}_{order.get('order_id')}')
    ])
    keyboard_buttons.append([InlineKeyboardButton("⬅️ К списку", callback_data='admin_orders')])
    markup = InlineKeyboardMarkup(keyboard_buttons)
    return "\n".join(lines), markup


async def admin_show_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    orders = collect_all_orders()
    status_counts = {}
    for item in orders:
        status_label = item['order'].get('status') or get_status_label(item['order'].get('status_code'))
        status_counts[status_label] = status_counts.get(status_label, 0) + 1
    lines = [
        "📦 <b>Все заказы</b>",
        f"Всего заказов: {len(orders)}",
    ]
    if status_counts:
        lines.append("По статусам:")
        for label, count in sorted(status_counts.items(), key=lambda x: x[0]):
            lines.append(f"• {html.escape(label)} — {count}")
    lines.append("")
    if orders:
        lines.append("Последние 15 заказов:")
        for item in orders[:15]:
            order = item['order']
            user_id = item['user_id']
            order_name = ORDER_TYPES.get(order.get('type'), {}).get('name', 'Неизвестный тип')
            link = build_user_contact_link(user_id)
            display = html.escape(format_user_display_name(user_id))
            status = html.escape(order.get('status', '—'))
            created = item['created'].strftime('%Y-%m-%d %H:%M')
            lines.append(
                f"#{order.get('order_id')} · {status} · {html.escape(order_name)} · {order.get('price', 0)} ₽ · "
                f"<a href=\"{html.escape(link, quote=True)}\">{display}</a> · {created}"
            )
    else:
        lines.append("Заказов пока нет.")
    keyboard = [
        [
            InlineKeyboardButton(
                f"#{item['order'].get('order_id')} · {item['order'].get('status', '')}",
                callback_data=f"admin_view_{item['user_id']}_{item['order'].get('order_id')}"
            )
        ]
        for item in orders[:15]
    ]
    keyboard.append([InlineKeyboardButton("🔥 Последние", callback_data='admin_recent_orders')])
    keyboard.append([InlineKeyboardButton("⬅️ Меню", callback_data='admin_menu')])
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True,
    )
    return ADMIN_MENU


async def admin_show_recent_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    orders = collect_all_orders()[:8]
    lines = ["🔥 <b>Последние заказы</b>"]
    if not orders:
        lines.append("Пока нет новых заказов. Проверьте позже.")
    for item in orders:
        order = item['order']
        user_id = item['user_id']
        order_name = ORDER_TYPES.get(order.get('type'), {}).get('name', 'Неизвестный тип')
        lines.extend([
            f"\n#{order.get('order_id')} · {html.escape(order.get('status', '—'))} · {html.escape(order_name)}",
            f"Клиент: <a href=\"{html.escape(build_user_contact_link(user_id), quote=True)}\">{html.escape(format_user_display_name(user_id))}</a>",
            f"Создан: {html.escape(str(order.get('created_at', '—')))} · Обновлён: {html.escape(str(order.get('updated_at', '—')))}",
            f"Цена: {order.get('price', 0)} ₽ · Бонусами оплачено {order.get('bonus_used', 0)} ₽",
        ])
        if order.get('deadline_label'):
            lines.append(f"Срок: {html.escape(order.get('deadline_label'))}")
        if order.get('topic'):
            lines.append(f"Тема: {html.escape(order.get('topic', ''))}")
        if order.get('requirements'):
            lines.append(f"Требования: {html.escape(order.get('requirements', ''))}")
    keyboard = [
        [InlineKeyboardButton(f"Открыть #{order['order'].get('order_id')}", callback_data=f"admin_view_{order['user_id']}_{order['order'].get('order_id')}")]
        for order in orders
    ]
    keyboard.append([InlineKeyboardButton("📦 Все заказы", callback_data='admin_orders')])
    keyboard.append([InlineKeyboardButton("⬅️ Меню", callback_data='admin_menu')])
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True,
    )
    return ADMIN_MENU


async def admin_show_leads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    records = get_recent_user_profiles(25)
    lines = [
        "👥 <b>Переходы в бота</b>",
        f"Всего пользователей: {len(USERS)}",
        "Активные посетители за последние переходы:",
    ]
    for idx, (last_seen, user_id, profile) in enumerate(records, 1):
        display = html.escape(format_user_display_name(int(user_id)))
        link = html.escape(build_user_contact_link(int(user_id)), quote=True)
        first_seen = profile.get('first_seen', '—')
        last_action = html.escape(str(profile.get('last_action', '—')))
        lines.append(
            f"{idx}. <a href=\"{link}\">{display}</a> — последняя активность {html.escape(str(profile.get('last_seen', last_seen.strftime('%Y-%m-%d %H:%M'))))}"
        )
        lines.append(f"   Первое посещение: {html.escape(str(first_seen))}. Действие: {last_action}")
    keyboard = [[InlineKeyboardButton("⬅️ Меню", callback_data='admin_menu')]]
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True,
    )
    return ADMIN_MENU


async def admin_show_bonuses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    entries = []
    for user_id in BONUSES.keys():
        entry = ensure_bonus_account(user_id)
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            uid = user_id
        entries.append({'user_id': uid, 'entry': entry})
    entries.sort(key=lambda item: item['entry'].get('balance', 0), reverse=True)
    lines = [
        "🎁 <b>Бонусные счета и рефералы</b>",
        f"Активных счетов: {len(entries)}",
        "Напоминание: бонусы автоматически сгорают через 30 дней без активности и могут покрыть до 50% заказа.",
        "",
    ]
    for idx, item in enumerate(entries[:15], 1):
        entry = item['entry']
        user_id = item['user_id']
        referrals = len(get_referrals_for_referrer(user_id))
        lines.append(
            f"{idx}. {html.escape(format_user_display_name(user_id))} — баланс {entry.get('balance', 0)} ₽ ("
            f"начислено {entry.get('credited', 0)} ₽ / списано {entry.get('redeemed', 0)} ₽), рефералов: {referrals}"
        )
    keyboard = [
        [InlineKeyboardButton(f"{format_user_display_name(item['user_id'])} · {item['entry'].get('balance', 0)} ₽", callback_data=f"admin_bonus_user_{item['user_id']}")]
        for item in entries[:15]
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Меню", callback_data='admin_menu')])
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True,
    )
    return ADMIN_MENU


async def admin_view_bonus_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_user_id: str,
    notice: Optional[str] = None,
):
    query = update.callback_query
    await answer_callback_query(query, context)
    entry = ensure_bonus_account(target_user_id)
    try:
        uid = int(target_user_id)
    except (TypeError, ValueError):
        uid = target_user_id
    profile_name = format_user_display_name(uid)
    referrer = get_referrer_for_user(uid)
    referrals = get_referrals_for_referrer(uid)
    lines = [f"🎁 <b>Бонусы пользователя {html.escape(profile_name)}</b>"]
    if notice:
        lines.append(f"<i>{html.escape(notice)}</i>")
    lines.extend([
        f"Баланс: {entry.get('balance', 0)} ₽",
        f"Начислено всего: {entry.get('credited', 0)} ₽",
        f"Списано всего: {entry.get('redeemed', 0)} ₽",
    ])
    if referrer:
        try:
            ref_link = build_user_contact_link(int(referrer))
            ref_display = format_user_display_name(int(referrer))
            lines.append(f"Пригласил: <a href=\"{html.escape(ref_link, quote=True)}\">{html.escape(ref_display)}</a>")
        except (TypeError, ValueError):
            lines.append(f"Пригласил: {html.escape(str(referrer))}")
    if referrals:
        lines.append("\nРефералы:")
        for ref in referrals[:10]:
            ref_name = ref.get('full_name') or ref.get('username') or ref.get('user_id')
            status = ref.get('status')
            bonus_total = ref.get('bonus_total', 0)
            lines.append(f"• {html.escape(str(ref_name))} — {status or 'без статуса'} (бонусов начислено {bonus_total} ₽)")
    history = entry.get('history', [])
    if history:
        lines.append("\nПоследние операции:")
        for item in history[-5:]:
            if isinstance(item, dict):
                lines.append(
                    f"{html.escape(str(item.get('timestamp', '—')))} — {html.escape(str(item.get('type', 'операция')))}: {item.get('amount', 0)} ₽ ({html.escape(str(item.get('reason', '')))} )"
                )
    keyboard = [
        [InlineKeyboardButton("📈 Начислить", callback_data=f'admin_bonus_credit_{target_user_id}')],
        [InlineKeyboardButton("📉 Списать", callback_data=f'admin_bonus_debit_{target_user_id}')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='admin_bonuses')],
    ]
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True,
    )
    return ADMIN_MENU


async def admin_prompt_manual_bonus(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    target_user_id: str,
    mode: str,
):
    context.user_data['admin_state'] = {
        'name': 'bonus_manual',
        'mode': mode,
        'user_id': target_user_id,
    }
    action = 'начисления' if mode == 'credit' else 'списания'
    await admin_view_bonus_user(
        update,
        context,
        target_user_id,
        notice=f"Введите сумму для {action} бонусов и отправьте сообщением. Можно добавить комментарий: «500 За отзыв». Для отмены напишите 'отмена'.",
    )
    return ADMIN_MENU


async def admin_view_order(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str, order_id: str, notice: Optional[str] = None):
    query = update.callback_query
    await answer_callback_query(query, context)
    order, _ = find_order_for_admin(user_id, order_id)
    if not order:
        await query.edit_message_text(
            "Заказ не найден.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ К списку", callback_data='admin_orders')]])
        )
        return ADMIN_MENU
    text, markup = build_admin_order_view(user_id, order, notice)
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )
    return ADMIN_MENU


async def admin_change_order_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: str,
    order_id: str,
    status_code: str,
):
    order, _ = find_order_for_admin(user_id, order_id)
    if not order:
        query = update.callback_query
        await answer_callback_query(query, context)
        await query.edit_message_text(
            "Заказ не найден.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ К списку", callback_data='admin_orders')]])
        )
        return ADMIN_MENU
    changed = set_order_status(order, status_code, note='Изменено администратором')
    save_json(ORDERS_FILE, ORDERS)
    notice = None
    if changed:
        notice = 'Статус обновлён.'
        try:
            await safe_send_message(
                context.bot,
                int(user_id),
                f"Статус вашего заказа #{order.get('order_id')} обновлён: {get_status_label(status_code)}.",
            )
        except (TypeError, ValueError):
            pass
        if status_code == 'paid':
            await process_paid_order(context, int(user_id), order)
    return await admin_view_order(update, context, user_id, order_id, notice=notice)


async def admin_delete_order(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: str, order_id: str):
    query = update.callback_query
    await answer_callback_query(query, context)
    order, user_orders = find_order_for_admin(user_id, order_id)
    if not order:
        await query.edit_message_text(
            "Заказ не найден.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ К списку", callback_data='admin_orders')]])
        )
        return ADMIN_MENU
    user_orders[:] = [ordr for ordr in user_orders if str(ordr.get('order_id')) != str(order_id)]
    if not user_orders:
        ORDERS.pop(str(user_id), None)
    save_json(ORDERS_FILE, ORDERS)
    await query.edit_message_text(
        "Заказ удалён.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ К списку", callback_data='admin_orders')]])
    )
    return ADMIN_MENU


async def admin_handle_order_bonus_request(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: str,
    order_id: str,
):
    context.user_data['admin_state'] = {
        'name': 'order_bonus',
        'user_id': user_id,
        'order_id': order_id,
    }
    await admin_view_order(
        update,
        context,
        user_id,
        order_id,
        notice='Отправьте сумму списания бонусов числом. Для отмены напишите «отмена».',
    )
    return ADMIN_MENU


def build_admin_prices_view():
    lines = [
        "💲 <b>Управление ценами</b>",
        f"Текущий режим: {current_pricing_mode}",
        "Выберите тип работы для точной настройки.",
        "",
    ]
    keyboard = []
    for key, info in ORDER_TYPES.items():
        prices = PRICES.get(key, DEFAULT_PRICES.get(key, {'base': 0, 'min': 0}))
        lines.append(
            f"{info['icon']} {info['name']} — базовая {prices.get('base', 0)} ₽ / минимум {prices.get('min', prices.get('base', 0))} ₽"
        )
        keyboard.append([InlineKeyboardButton(info['name'], callback_data=f'admin_price_{key}')])
    keyboard.append([InlineKeyboardButton("Переключить режим", callback_data='admin_price_mode')])
    keyboard.append([InlineKeyboardButton("⬅️ Меню", callback_data='admin_menu')])
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


async def admin_show_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    text, markup = build_admin_prices_view()
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )
    return ADMIN_MENU


async def admin_view_price_type(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    order_type_key: str,
    notice: Optional[str] = None,
):
    query = update.callback_query
    await answer_callback_query(query, context)
    info = ORDER_TYPES.get(order_type_key)
    if not info:
        await query.edit_message_text(
            "Тип не найден.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data='admin_prices')]])
        )
        return ADMIN_MENU
    prices = PRICES.get(order_type_key, DEFAULT_PRICES.get(order_type_key, {'base': 0, 'min': 0}))
    lines = [
        f"💲 <b>{info['icon']} {html.escape(info['name'])}</b>",
        f"Базовая цена: {prices.get('base', 0)} ₽",
        f"Минимальная цена: {prices.get('min', prices.get('base', 0))} ₽",
    ]
    if notice:
        lines.append(f"<i>{html.escape(notice)}</i>")
    lines.append("\nИспользуйте кнопки ниже для быстрой корректировки или установите точное значение.")
    keyboard = []
    keyboard.extend(chunk_buttons([
        InlineKeyboardButton("−1000 базовая", callback_data=f'admin_price_adj_{order_type_key}_base_-1000'),
        InlineKeyboardButton("+1000 базовая", callback_data=f'admin_price_adj_{order_type_key}_base_1000'),
        InlineKeyboardButton("−500 базовая", callback_data=f'admin_price_adj_{order_type_key}_base_-500'),
        InlineKeyboardButton("+500 базовая", callback_data=f'admin_price_adj_{order_type_key}_base_500'),
    ], 2))
    keyboard.extend(chunk_buttons([
        InlineKeyboardButton("−1000 минимум", callback_data=f'admin_price_adj_{order_type_key}_min_-1000'),
        InlineKeyboardButton("+1000 минимум", callback_data=f'admin_price_adj_{order_type_key}_min_1000'),
        InlineKeyboardButton("−500 минимум", callback_data=f'admin_price_adj_{order_type_key}_min_-500'),
        InlineKeyboardButton("+500 минимум", callback_data=f'admin_price_adj_{order_type_key}_min_500'),
    ], 2))
    keyboard.append([
        InlineKeyboardButton("✏️ Установить базовую", callback_data=f'admin_price_set_{order_type_key}_base'),
        InlineKeyboardButton("✏️ Установить минимум", callback_data=f'admin_price_set_{order_type_key}_min'),
    ])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='admin_prices')])
    await query.edit_message_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True,
    )
    return ADMIN_MENU


async def admin_toggle_pricing_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)
    global current_pricing_mode
    current_pricing_mode = 'hard' if current_pricing_mode == 'light' else 'light'
    text, markup = build_admin_prices_view()
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
        disable_web_page_preview=True,
    )
    return ADMIN_MENU


async def admin_adjust_price(update: Update, context: ContextTypes.DEFAULT_TYPE, order_type_key: str, field: str, delta: int):
    adjust_price_value(order_type_key, field, delta)
    return await admin_view_price_type(update, context, order_type_key, notice='Цена обновлена.')


async def admin_prompt_price_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    order_type_key: str,
    field: str,
):
    context.user_data['admin_state'] = {
        'name': 'price_manual',
        'order_type': order_type_key,
        'field': field,
    }
    field_label = 'базовой' if field == 'base' else 'минимальной'
    await admin_view_price_type(
        update,
        context,
        order_type_key,
        notice=f"Введите новое значение {field_label} цены числом. Для отмены напишите 'отмена'.",
    )
    return ADMIN_MENU


def _serialize_export_value(value):
    if value is None:
        return ''
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (list, dict)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


async def admin_export_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback_query(query, context)

    export_rows = []
    encountered_fields = []

    def register_field(field_name: str):
        if field_name not in encountered_fields:
            encountered_fields.append(field_name)

    for orders in ORDERS.values():
        if not isinstance(orders, list):
            continue
        for order in orders:
            if not isinstance(order, dict):
                continue
            row = {}
            for key, value in order.items():
                register_field(key)
                row[key] = _serialize_export_value(value)
            export_rows.append(row)

    if not export_rows:
        await query.edit_message_text(
            "📂 Пока нет заказов для экспорта.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data='admin_menu')]]),
        )
        return ADMIN_MENU

    preferred = [field for field in EXPORT_FIELD_ORDER if field in encountered_fields]
    remaining = [field for field in encountered_fields if field not in preferred]
    fieldnames = preferred + remaining

    export_file = os.path.join(DATA_DIR, 'orders_export.csv')
    with open(export_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for row in export_rows:
            writer.writerow({field: row.get(field, '') for field in fieldnames})

    try:
        with open(export_file, 'rb') as export_handle:
            await context.bot.send_document(ADMIN_CHAT_ID, export_handle)
    finally:
        try:
            os.remove(export_file)
        except OSError:
            logger.warning("Не удалось удалить временный файл экспорта %s", export_file)

    await query.edit_message_text(
        "📤 Экспорт отправлен в чат.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data='admin_menu')]]),
    )
    return ADMIN_MENU

# Админ старт
async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("Доступ запрещен!")
        return
    user = update.effective_user
    log_user_action(user.id, user.username, "Админ-панель", user.full_name)
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
    if data == 'admin_recent_orders':
        return await admin_show_recent_orders(update, context)
    if data == 'admin_leads':
        return await admin_show_leads(update, context)
    if data == 'admin_bonuses':
        return await admin_show_bonuses(update, context)
    if data.startswith('admin_bonus_user_'):
        target = data.split('_', 3)[-1]
        return await admin_view_bonus_user(update, context, target)
    if data.startswith('admin_bonus_credit_'):
        target = data.split('_', 3)[-1]
        return await admin_prompt_manual_bonus(update, context, target, 'credit')
    if data.startswith('admin_bonus_debit_'):
        target = data.split('_', 3)[-1]
        return await admin_prompt_manual_bonus(update, context, target, 'debit')
    if data.startswith('admin_view_'):
        _, _, payload = data.partition('admin_view_')
        parts = payload.split('_')
        if len(parts) >= 2:
            user_id, order_id = parts[0], parts[1]
            return await admin_view_order(update, context, user_id, order_id)
    if data.startswith('admin_status_'):
        _, _, payload = data.partition('admin_status_')
        parts = payload.split('_')
        if len(parts) >= 3:
            user_id, order_id, status_code = parts[0], parts[1], parts[2]
            return await admin_change_order_status(update, context, user_id, order_id, status_code)
    if data.startswith('admin_order_bonus_'):
        _, _, payload = data.partition('admin_order_bonus_')
        parts = payload.split('_')
        if len(parts) >= 2:
            user_id, order_id = parts[0], parts[1]
            return await admin_handle_order_bonus_request(update, context, user_id, order_id)
    if data.startswith('admin_delete_'):
        _, _, payload = data.partition('admin_delete_')
        parts = payload.split('_')
        if len(parts) >= 2:
            user_id, order_id = parts[0], parts[1]
            return await admin_delete_order(update, context, user_id, order_id)
    if data == 'admin_prices':
        return await admin_show_prices(update, context)
    if data == 'admin_price_mode':
        return await admin_toggle_pricing_mode(update, context)
    if data.startswith('admin_price_adj_'):
        _, _, payload = data.partition('admin_price_adj_')
        parts = payload.split('_')
        if len(parts) >= 3:
            order_type, field, delta = parts[0], parts[1], parts[2]
            try:
                delta_value = int(delta)
            except ValueError:
                delta_value = 0
            return await admin_adjust_price(update, context, order_type, field, delta_value)
    if data.startswith('admin_price_set_'):
        _, _, payload = data.partition('admin_price_set_')
        parts = payload.split('_')
        if len(parts) >= 2:
            order_type, field = parts[0], parts[1]
            return await admin_prompt_price_input(update, context, order_type, field)
    if data.startswith('admin_price_'):
        order_type = data.split('_', 2)[-1]
        if order_type in ORDER_TYPES:
            return await admin_view_price_type(update, context, order_type)
    if data == 'admin_export':
        return await admin_export_orders(update, context)
    if data == 'back_to_main':
        return await main_menu(update, context)
    await query.edit_message_text(
        "Неизвестная команда. Возвращаюсь в админ-меню.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data='admin_menu')]])
    )
    return ADMIN_MENU

# Обработчик сообщений админа
async def admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('admin_state')
    if not state:
        await update.message.reply_text("Используйте кнопки админ-панели для действий.")
        return ADMIN_MENU
    text = (update.message.text or '').strip()
    if isinstance(state, dict):
        state_name = state.get('name')
    else:
        state_name = state
    if text.lower() in {'отмена', '/cancel', 'cancel'}:
        context.user_data.pop('admin_state', None)
        await update.message.reply_text("Действие отменено.")
        return ADMIN_MENU
    if state_name == 'bonus_manual':
        target_user = state.get('user_id')
        mode = state.get('mode', 'credit')
        parts = text.split(None, 1)
        try:
            amount = int(parts[0])
        except (ValueError, IndexError):
            await update.message.reply_text("Укажите сумму числом, например: 500 или '500 За отзыв'.")
            return ADMIN_MENU
        reason = parts[1] if len(parts) > 1 else (
            'Начисление администратором' if mode == 'credit' else 'Списание администратором'
        )
        before = ensure_bonus_account(target_user)
        balance_before = before.get('balance', 0)
        entry_type = 'manual_credit' if mode == 'credit' else 'manual_debit'
        after = add_bonus_operation(str(target_user), amount, entry_type, reason)
        balance_after = after.get('balance', 0)
        try:
            target_chat_id = int(target_user)
        except (TypeError, ValueError):
            target_chat_id = None
        if mode == 'credit':
            actual = balance_after - balance_before
            if actual > 0:
                if target_chat_id is not None:
                    await safe_send_message(
                        context.bot,
                        target_chat_id,
                        f"🎁 Вам начислено {actual} ₽ бонусов: {reason}.",
                    )
                await update.message.reply_text(f"Начислено {actual} ₽. Баланс: {balance_after} ₽.")
            else:
                await update.message.reply_text("Не удалось начислить бонусы. Проверьте сумму.")
        else:
            actual = balance_before - balance_after
            if actual > 0:
                if target_chat_id is not None:
                    await safe_send_message(
                        context.bot,
                        target_chat_id,
                        f"ℹ️ С вашего бонусного счёта списано {actual} ₽: {reason}.",
                    )
                await update.message.reply_text(f"Списано {actual} ₽. Баланс: {balance_after} ₽.")
            else:
                await update.message.reply_text("Недостаточно бонусов для списания.")
        context.user_data.pop('admin_state', None)
        return ADMIN_MENU
    if state_name == 'order_bonus':
        user_id = state.get('user_id')
        order_id = state.get('order_id')
        try:
            amount = int(text)
        except ValueError:
            await update.message.reply_text("Сумма должна быть числом.")
            return ADMIN_MENU
        order, _ = find_order_for_admin(user_id, order_id)
        if not order:
            await update.message.reply_text("Заказ не найден.")
        else:
            applied = await debit_bonuses_for_order(context, int(user_id), order, amount)
            save_json(ORDERS_FILE, ORDERS)
            if applied:
                balance = ensure_bonus_account(user_id).get('balance', 0)
                await update.message.reply_text(f"Списано {applied} ₽ бонусов. Текущий баланс клиента: {balance} ₽.")
            else:
                await update.message.reply_text("Не удалось списать бонусы. Проверьте баланс и лимит 50%.")
        context.user_data.pop('admin_state', None)
        return ADMIN_MENU
    if state_name == 'price_manual':
        order_type = state.get('order_type')
        field = state.get('field')
        try:
            value = int(text)
        except ValueError:
            await update.message.reply_text("Введите числовое значение цены.")
            return ADMIN_MENU
        if field == 'base':
            set_price_value(order_type, base=value)
        else:
            set_price_value(order_type, minimum=value)
        await update.message.reply_text("Цена обновлена.")
        context.user_data.pop('admin_state', None)
        return ADMIN_MENU
    await update.message.reply_text("Не удалось обработать сообщение. Используйте кнопки панели.")
    context.user_data.pop('admin_state', None)
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
