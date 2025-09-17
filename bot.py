import os
import sys
import logging
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from html import escape
from typing import Callable, Dict, List, Optional, Tuple
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters, ConversationHandler
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from dotenv import load_dotenv

try:  # pragma: no cover - окружения без pandas должны работать
    import pandas as pd  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover - обработка отсутствующей зависимости
    pd = None  # type: ignore[assignment]

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

if pd is None:
    logger.warning('Библиотека pandas не найдена, CSV-экспорт будет отключен.')

# Файлы данных
PRICES_FILE = os.path.join(DATA_DIR, 'prices.json')
REFERRALS_FILE = os.path.join(DATA_DIR, 'referrals.json')
ORDERS_FILE = os.path.join(DATA_DIR, 'orders.json')
FEEDBACKS_FILE = os.path.join(DATA_DIR, 'feedbacks.json')
USER_LOGS_FILE = os.path.join(DATA_DIR, 'user_logs.json')
BONUSES_FILE = os.path.join(DATA_DIR, 'bonuses.json')
SETTINGS_FILE = os.path.join(DATA_DIR, 'settings.json')

DEFAULT_SETTINGS = {
    'pricing_mode': 'light',
    'upsell_prices': {'prez': 2000, 'speech': 1000},
    'bonus_percent': 0.05,
    'admin_contact': 'https://t.me/Thisissaymoon',
    'status_options': ['новый', 'в работе', 'ожидает оплаты', 'выполнен', 'отменен'],
    'order_tags': ['🔥 Срочно', 'VIP', 'Требует звонка'],
    'managers': [],
    'blocked_users': [],
    'auto_follow_up_hours': 12,
    'payment_channels': ['Перевод', 'Оплата на сайте', 'Наличные'],
}

BACK_BUTTON_TEXT = '⬅️ Назад'

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
SETTINGS = load_json(SETTINGS_FILE, DEFAULT_SETTINGS)
for key, value in DEFAULT_SETTINGS.items():
    SETTINGS.setdefault(key, value)

def save_settings():
    save_json(SETTINGS_FILE, SETTINGS)

BONUS_PERCENT = SETTINGS.get('bonus_percent', 0.05)
ADMIN_CONTACT = SETTINGS.get('admin_contact', 'https://t.me/Thisissaymoon')
UPSELL_PRICES = SETTINGS.get('upsell_prices', {'prez': 2000, 'speech': 1000})

PRICES = load_json(PRICES_FILE, {
    'samostoyatelnye': {'base': 2000, 'min': 2000, 'max': 5000},
    'kursovaya_teoreticheskaya': {'base': 8000, 'min': 8000, 'max': 12000},
    'kursovaya_s_empirikov': {'base': 12000, 'min': 12000, 'max': 18000},
    'diplomnaya': {'base': 35000, 'min': 35000, 'max': 50000},
    'magisterskaya': {'base': 35000, 'min': 35000, 'max': 60000}
})
REFERALS = load_json(REFERRALS_FILE)
ORDERS = load_json(ORDERS_FILE)
FEEDBACKS = load_json(FEEDBACKS_FILE)
USER_LOGS = load_json(USER_LOGS_FILE)
BONUSES = load_json(BONUSES_FILE, {})

def ensure_order_payment_fields(order: dict) -> bool:
    changed = False
    if 'payment_state' not in order:
        order['payment_state'] = 'не оплачен'
        changed = True
    if 'prepayment_confirmed' not in order:
        order['prepayment_confirmed'] = False
        changed = True
    if 'full_payment_confirmed' not in order:
        order['full_payment_confirmed'] = False
        changed = True
    if 'prepayment_confirmed_at' not in order:
        order['prepayment_confirmed_at'] = None
        changed = True
    if 'full_payment_confirmed_at' not in order:
        order['full_payment_confirmed_at'] = None
        changed = True
    price = order.get('price', 0)
    if 'bonus_total' not in order:
        order['bonus_total'] = int(price * BONUS_PERCENT)
        changed = True
    if 'bonus_released_prepaid' not in order:
        order['bonus_released_prepaid'] = 0
        changed = True
    if 'bonus_released_full' not in order:
        order['bonus_released_full'] = 0
        changed = True
    if 'payment_history' not in order:
        order['payment_history'] = []
        changed = True
    if 'manager_notes' not in order:
        order['manager_notes'] = []
        changed = True
    if 'assigned_manager' not in order:
        order['assigned_manager'] = None
        changed = True
    if 'admin_tags' not in order:
        order['admin_tags'] = []
        changed = True
    if 'status_history' not in order:
        order['status_history'] = []
        changed = True
    if not order['status_history']:
        order['status_history'].append({
            'status': order.get('status', 'новый'),
            'timestamp': order.get('created_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        changed = True
    if 'price_history' not in order:
        order['price_history'] = []
        changed = True
    if 'payment_channel' not in order:
        order['payment_channel'] = SETTINGS.get('payment_channels', ['Перевод'])[0]
        changed = True
    if 'prepayment_amount' not in order:
        order['prepayment_amount'] = 0
        changed = True
    if 'full_payment_amount' not in order:
        order['full_payment_amount'] = 0
        changed = True
    if 'invoice_links' not in order:
        order['invoice_links'] = []
        changed = True
    return changed

def release_bonus(user_id: str, order: dict, stage: str) -> int:
    ensure_order_payment_fields(order)
    user_key = str(user_id)
    bonus_entry = BONUSES.setdefault(user_key, {'balance': 0, 'history': []})
    amount = 0
    if stage == 'prepayment':
        if order.get('bonus_released_prepaid'):
            return 0
        amount = order.get('bonus_total', 0) // 2
        order['bonus_released_prepaid'] = amount
    elif stage == 'full':
        if order.get('bonus_released_full'):
            return 0
        already = order.get('bonus_released_prepaid', 0)
        amount = max(order.get('bonus_total', 0) - already, 0)
        order['bonus_released_full'] = amount
    if amount <= 0:
        return 0
    bonus_entry['balance'] = bonus_entry.get('balance', 0) + amount
    history = bonus_entry.setdefault('history', [])
    history.append({
        'order_id': order.get('order_id'),
        'amount': amount,
        'stage': stage,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })
    payment_entry = {
        'type': 'bonus_release',
        'stage': stage,
        'amount': amount,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    order.setdefault('payment_history', []).append(payment_entry)
    return amount

def get_user_bonus_balance(user_id: str) -> int:
    entry = BONUSES.get(str(user_id), {})
    return int(entry.get('balance', 0))

def get_pending_bonus(user_id: str) -> int:
    total = 0
    changed = False
    for order in ORDERS.get(str(user_id), []):
        if ensure_order_payment_fields(order):
            changed = True
        credited = order.get('bonus_released_prepaid', 0) + order.get('bonus_released_full', 0)
        total += max(order.get('bonus_total', 0) - credited, 0)
    if changed:
        save_json(ORDERS_FILE, ORDERS)
    return int(total)

_orders_structure_updated = False
for _orders_list in ORDERS.values():
    for _order in _orders_list:
        if ensure_order_payment_fields(_order):
            _orders_structure_updated = True
if _orders_structure_updated:
    save_json(ORDERS_FILE, ORDERS)

def format_contact_link(contact: str) -> str:
    if not contact:
        return 'не указан'
    contact = contact.strip()
    if not contact:
        return 'не указан'
    safe_display = escape(contact)
    if contact.startswith('@') and len(contact) > 1:
        username = contact[1:].split()[0]
        if username and all(ch.isalnum() or ch == '_' for ch in username):
            href = escape(f"https://t.me/{username}", quote=True)
            display = escape(f"@{username}")
            return f'<a href="{href}">{display}</a>'
    lower_contact = contact.lower()
    if lower_contact.startswith('http://') or lower_contact.startswith('https://'):
        href = escape(contact, quote=True)
        return f'<a href="{href}">{safe_display}</a>'
    if '@' in contact and ' ' not in contact and not contact.startswith('@'):
        href = escape(f"mailto:{contact}", quote=True)
        return f'<a href="{href}">{safe_display}</a>'
    return safe_display

def build_order_details(uid: str, order: dict) -> str:
    changed = ensure_order_payment_fields(order)
    if changed:
        save_json(ORDERS_FILE, ORDERS)
    order_id = order.get('order_id', 'N/A')
    order_name = ORDER_TYPES.get(order.get('type'), {}).get('name', order.get('type', 'Неизвестно'))
    user_link = escape(f"tg://user?id={uid}", quote=True)
    lines = [
        f"<b>Заказ #{order_id}</b>",
        f"Пользователь: <a href=\"{user_link}\">{escape(str(uid))}</a>",
        f"Тип: {escape(order_name)}",
        f"Тема: {escape(order.get('topic', 'Без темы'))}",
        f"Срок: {order.get('deadline_days', 'N/A')} дней",
        f"Статус: {escape(order.get('status', 'неизвестно'))}",
        f"Оплата: {escape(order.get('payment_state', 'не оплачен'))}",
        f"Канал оплаты: {escape(order.get('payment_channel', 'не указан'))}",
        f"Контакт: {format_contact_link(order.get('contact'))}",
        f"Требования: {escape(order.get('requirements', 'Нет'))}",
    ]
    if order.get('upsells'):
        upsells_readable = ', '.join(UPSELL_TITLES.get(code, code) for code in order['upsells'])
        lines.append(f"Допы: {escape(upsells_readable)}")
    else:
        lines.append("Допы: нет")
    lines.append(f"Файлов: {len(order.get('attachments') or [])}")
    bonus_total = order.get('bonus_total', 0)
    if bonus_total:
        lines.append(
            f"Бонусы: всего {bonus_total} ₽ | предоплата {order.get('bonus_released_prepaid', 0)} ₽ | оплата {order.get('bonus_released_full', 0)} ₽"
        )
    prepay_amount = order.get('prepayment_amount')
    if prepay_amount:
        lines.append(f"Предоплата: {prepay_amount} ₽")
    full_amount = order.get('full_payment_amount')
    if full_amount:
        lines.append(f"Поступило всего: {full_amount} ₽")
    if order.get('prepayment_confirmed_at'):
        lines.append(f"Предоплата подтверждена: {escape(order['prepayment_confirmed_at'])}")
    if order.get('full_payment_confirmed_at'):
        lines.append(f"Оплата подтверждена: {escape(order['full_payment_confirmed_at'])}")
    if order.get('created_at'):
        lines.append(f"Создан: {escape(order['created_at'])}")
    if order.get('assigned_manager'):
        lines.append(f"Менеджер: {escape(order['assigned_manager'])}")
    if order.get('admin_tags'):
        lines.append(f"Теги: {escape(', '.join(order['admin_tags']))}")
    if order.get('status_history'):
        history_tail = order['status_history'][-3:]
        formatted_history = ' | '.join(
            f"{escape(entry.get('status', ''))} ({escape(entry.get('timestamp', ''))})" for entry in history_tail
        )
        lines.append(f"История статусов: {formatted_history}")
    if order.get('manager_notes'):
        last_note = order['manager_notes'][-1]
        author = escape(last_note.get('author', ''))
        note_text = escape(last_note.get('text', ''))
        note_time = escape(last_note.get('timestamp', ''))
        lines.append(f"Последняя заметка: {note_text} ({author} • {note_time})")
    if order.get('invoice_links'):
        invoices = ', '.join(escape(link) for link in order['invoice_links'][-3:])
        lines.append(f"Счета: {invoices}")
    return '<br>'.join(lines)


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%d.%m.%Y %H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def iter_all_orders():
    for uid, orders in ORDERS.items():
        for order in orders:
            yield uid, order


def find_order(uid: str, order_id: str) -> Optional[dict]:
    uid_str = str(uid)
    for order in ORDERS.get(uid_str, []):
        if str(order.get('order_id')) == str(order_id):
            return order
    return None


def add_status_history(order: dict, status: str, author: Optional[str] = None) -> None:
    ensure_order_payment_fields(order)
    entry = {
        'status': status,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    if author:
        entry['author'] = author
    order.setdefault('status_history', []).append(entry)


def add_manager_note(order: dict, text: str, author: Optional[str] = None) -> None:
    ensure_order_payment_fields(order)
    order.setdefault('manager_notes', []).append({
        'text': text,
        'author': author,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


def add_price_history(order: dict, amount: int, reason: str, author: Optional[str] = None) -> None:
    ensure_order_payment_fields(order)
    order.setdefault('price_history', []).append({
        'amount': amount,
        'reason': reason,
        'author': author,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


def compute_dashboard_metrics() -> Dict[str, int]:
    total_orders = 0
    statuses = Counter()
    pending_prepay = 0
    pending_full = 0
    outstanding_total = 0
    confirmed_total = 0
    new_today = 0
    tagged = 0
    assigned = 0
    pending_bonus_total = 0
    today = datetime.now().date()
    for uid, order in iter_all_orders():
        ensure_order_payment_fields(order)
        total_orders += 1
        status = order.get('status', 'неизвестно')
        statuses[status] += 1
        created_at = parse_dt(order.get('created_at'))
        if created_at and created_at.date() == today:
            new_today += 1
        if order.get('admin_tags'):
            tagged += 1
        if order.get('assigned_manager'):
            assigned += 1
        price = int(order.get('price', 0))
        credited = order.get('bonus_released_prepaid', 0) + order.get('bonus_released_full', 0)
        pending_bonus_total += max(order.get('bonus_total', 0) - credited, 0)
        full_amount = int(order.get('full_payment_amount') or 0)
        if order.get('full_payment_confirmed'):
            confirmed_total += full_amount or price
        else:
            pending_full += 1
            outstanding_total += max(price - full_amount, 0)
        if not order.get('prepayment_confirmed'):
            pending_prepay += 1
    metrics = {
        'total_orders': total_orders,
        'new_today': new_today,
        'pending_prepay': pending_prepay,
        'pending_full': pending_full,
        'outstanding_total': outstanding_total,
        'confirmed_total': confirmed_total,
        'tagged_orders': tagged,
        'assigned_orders': assigned,
        'pending_bonus_total': pending_bonus_total,
    }
    metrics['status_counter'] = statuses
    metrics['total_users'] = len(ORDERS)
    metrics['referrals'] = sum(len(v) for v in REFERALS.values())
    metrics['bonus_wallet'] = sum(entry.get('balance', 0) for entry in BONUSES.values())
    return metrics


def build_admin_dashboard_text(custom_message: Optional[str] = None) -> str:
    metrics = compute_dashboard_metrics()
    lines = ["<b>🔐 Админ-панель</b>"]
    if custom_message:
        lines.append(custom_message)
        lines.append('')
    lines.append(
        f"Заказы: {metrics['total_orders']} (сегодня: {metrics['new_today']}) | Пользователи: {metrics['total_users']}"
    )
    lines.append(
        f"Оплачено: {metrics['confirmed_total']} ₽ | Ожидает оплаты: {metrics['outstanding_total']} ₽"
    )
    lines.append(
        f"Предоплаты в ожидании: {metrics['pending_prepay']} | Полные оплаты в ожидании: {metrics['pending_full']}"
    )
    lines.append(
        f"Бонусы к выдаче: {metrics['pending_bonus_total']} ₽ | Бонусный кошелек: {metrics['bonus_wallet']} ₽"
    )
    lines.append(
        f"Заказы с менеджерами: {metrics['assigned_orders']} | Помечено тегами: {metrics['tagged_orders']}"
    )
    if metrics['referrals']:
        lines.append(f"Рефералов всего: {metrics['referrals']}")
    if metrics['status_counter']:
        top_statuses = ', '.join(
            f"{status}: {count}" for status, count in metrics['status_counter'].most_common(4)
        )
        lines.append(f"Статусы: {top_statuses}")
    return '<br>'.join(lines)


def format_order_summary(uid: str, order: dict) -> str:
    order_name = ORDER_TYPES.get(order.get('type'), {}).get('name', order.get('type', 'Неизвестно'))
    status = order.get('status', 'неизвестно')
    payment_state = order.get('payment_state', 'не оплачен')
    price = order.get('price', 0)
    created = order.get('created_at', 'без даты')
    return f"#{order.get('order_id', 'N/A')} • {order_name} • {status} • {payment_state} • {price} ₽ • {created}"


def sorted_orders(orders: List[Tuple[str, dict]]) -> List[Tuple[str, dict]]:
    def _sort_key(item: Tuple[str, dict]):
        _, order = item
        created = parse_dt(order.get('created_at')) or datetime.min
        return (created, order.get('order_id', 0))

    return sorted(orders, key=_sort_key, reverse=True)


def get_admin_display_name(update: Update) -> str:
    if update and update.effective_user:
        user = update.effective_user
        return user.full_name or user.username or str(user.id)
    return 'admin'


def build_order_list_message(
    title: str,
    orders: List[Tuple[str, dict]],
    back_callback: str,
    extra_buttons: Optional[List[List[InlineKeyboardButton]]] = None,
    limit: int = 20,
) -> Tuple[str, InlineKeyboardMarkup]:
    limited = sorted_orders(orders)[:limit]
    lines = [title]
    if not limited:
        lines.append('Заказы не найдены.')
    else:
        for uid, order in limited:
            lines.append(format_order_summary(uid, order))
        if len(orders) > limit:
            lines.append(f"Показаны первые {limit} из {len(orders)} записей.")
    buttons: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(f"#{order.get('order_id', 'N/A')} ({uid})", callback_data=f'admin_order|{uid}|{order.get('order_id')}')]
        for uid, order in limited
    ]
    if extra_buttons:
        buttons.extend(extra_buttons)
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data=back_callback)])
    return '<br>'.join(lines), InlineKeyboardMarkup(buttons)


def filter_orders(filter_func: Optional[Callable[[str, dict], bool]] = None) -> List[Tuple[str, dict]]:
    matched: List[Tuple[str, dict]] = []
    for uid, order in iter_all_orders():
        if filter_func and not filter_func(uid, order):
            continue
        matched.append((uid, order))
    return matched


async def admin_show_order_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    title: str,
    filter_func: Optional[Callable[[str, dict], bool]] = None,
    back_callback: str = 'admin_menu',
    extra_buttons: Optional[List[List[InlineKeyboardButton]]] = None,
):
    orders = filter_orders(filter_func)
    text, markup = build_order_list_message(title, orders, back_callback, extra_buttons=extra_buttons)
    query = update.callback_query
    await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    return ADMIN_MENU


def compile_order_filter(filter_info: Optional[Dict[str, str]]) -> Optional[Callable[[str, dict], bool]]:
    if not filter_info:
        return None
    filter_type = filter_info.get('type')
    value = filter_info.get('value')
    if filter_type == 'status' and value:
        return lambda uid, order: order.get('status') == value
    if filter_type == 'payment':
        if value == 'prepayment_pending':
            return lambda uid, order: not order.get('prepayment_confirmed')
        if value == 'full_pending':
            return lambda uid, order: not order.get('full_payment_confirmed')
        if value == 'paid':
            return lambda uid, order: order.get('full_payment_confirmed')
    if filter_type == 'user' and value:
        return lambda uid, order: str(uid) == str(value)
    if filter_type == 'search' and value:
        lowered = value.lower()
        return lambda uid, order: (
            lowered in str(order.get('order_id', '')).lower()
            or lowered in str(uid).lower()
            or lowered in (order.get('topic') or '').lower()
            or lowered in (order.get('requirements') or '').lower()
        )
    return None


def build_orders_extra_buttons(filter_info: Optional[Dict[str, str]]) -> List[List[InlineKeyboardButton]]:
    buttons = [
        [
            InlineKeyboardButton('🔁 Обновить', callback_data='admin_orders_refresh'),
            InlineKeyboardButton('🔎 Поиск', callback_data='admin_orders_search')
        ],
        [
            InlineKeyboardButton('Статусы', callback_data='admin_orders_statuses'),
            InlineKeyboardButton('Оплаты', callback_data='admin_orders_payments')
        ],
    ]
    if filter_info and filter_info.get('type') not in (None, 'all'):
        buttons.append([InlineKeyboardButton('Сбросить фильтр', callback_data='admin_orders')])
    return buttons


def compute_user_stats(uid: str) -> Dict[str, object]:
    orders = ORDERS.get(uid, [])
    stats = {
        'orders': len(orders),
        'total_spent': 0,
        'outstanding': 0,
        'last_order': None,
        'statuses': Counter(),
        'pending_bonus': 0,
    }
    for order in orders:
        ensure_order_payment_fields(order)
        stats['statuses'][order.get('status', 'неизвестно')] += 1
        price = int(order.get('price', 0))
        full_amount = int(order.get('full_payment_amount') or 0)
        if order.get('full_payment_confirmed'):
            stats['total_spent'] += full_amount or price
        else:
            stats['outstanding'] += max(price - full_amount, 0)
        credited = order.get('bonus_released_prepaid', 0) + order.get('bonus_released_full', 0)
        stats['pending_bonus'] += max(order.get('bonus_total', 0) - credited, 0)
        created_at = parse_dt(order.get('created_at'))
        if created_at and (stats['last_order'] is None or created_at > stats['last_order']):
            stats['last_order'] = created_at
    return stats


async def render_order_tags_editor(query, uid: str, order_id_str: str, order: dict) -> None:
    tags = SETTINGS.get('order_tags', [])
    current_tags = set(order.get('admin_tags') or [])
    buttons = [
        [
            InlineKeyboardButton(
                f"{'✅' if tag in current_tags else '➕'} {tag}",
                callback_data=f'ao_tags_toggle|{uid}|{order_id_str}|{idx}'
            )
        ]
        for idx, tag in enumerate(tags)
    ]
    buttons.append([InlineKeyboardButton('Добавить свой тег', callback_data=f'ao_tags_custom|{uid}|{order_id_str}')])
    if current_tags:
        buttons.append([InlineKeyboardButton('Очистить теги', callback_data=f'ao_tags_clear|{uid}|{order_id_str}')])
    buttons.append([InlineKeyboardButton('⬅️ Назад', callback_data=f'admin_order|{uid}|{order_id_str}')])
    text_lines = [
        'Выберите теги для заказа — они помогают структурировать работу.',
        f"Активные теги: {', '.join(current_tags) if current_tags else 'нет'}"
    ]
    await query.edit_message_text('<br>'.join(text_lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)


async def render_order_assignment_editor(query, uid: str, order_id_str: str, order: dict) -> None:
    managers = SETTINGS.get('managers', [])
    buttons = [
        [InlineKeyboardButton(manager, callback_data=f'ao_assign_set|{uid}|{order_id_str}|{idx}')]
        for idx, manager in enumerate(managers)
    ]
    buttons.append([InlineKeyboardButton('Ввести вручную', callback_data=f'ao_assign_custom|{uid}|{order_id_str}')])
    if order.get('assigned_manager'):
        buttons.append([InlineKeyboardButton('Снять менеджера', callback_data=f'ao_assign_clear|{uid}|{order_id_str}')])
    buttons.append([InlineKeyboardButton('⬅️ Назад', callback_data=f'admin_order|{uid}|{order_id_str}')])
    current = order.get('assigned_manager') or 'не назначен'
    text = f'Назначьте менеджера для заказа.<br>Текущий: <b>{escape(str(current))}</b>'
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)


async def render_order_payments_editor(query, uid: str, order_id_str: str, order: dict) -> None:
    text_lines = [
        'Управление платежами заказа:',
        f"Предоплата: {order.get('prepayment_amount', 0)} ₽",
        f"Оплата: {order.get('full_payment_amount', 0)} ₽",
        f"Канал: {order.get('payment_channel', 'не указан')}"
    ]
    buttons = [
        [InlineKeyboardButton('Указать предоплату', callback_data=f'ao_payment_amount|{uid}|{order_id_str}|prepay')],
        [InlineKeyboardButton('Указать полную оплату', callback_data=f'ao_payment_amount|{uid}|{order_id_str}|full')],
        [InlineKeyboardButton('Канал оплаты', callback_data=f'ao_payment_channel|{uid}|{order_id_str}')],
        [InlineKeyboardButton('⬅️ Назад', callback_data=f'admin_order|{uid}|{order_id_str}')]
    ]
    await query.edit_message_text('<br>'.join(text_lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)


async def render_order_invoice_editor(query, uid: str, order_id_str: str, order: dict) -> None:
    invoices = order.get('invoice_links') or []
    lines = ['Счета и ссылки для оплаты:']
    if invoices:
        for idx, link in enumerate(invoices, 1):
            safe = escape(link)
            lines.append(f"{idx}. {safe}")
    else:
        lines.append('Еще не добавляли ссылок.')
    buttons = [
        [InlineKeyboardButton('Добавить ссылку', callback_data=f'ao_invoice_add|{uid}|{order_id_str}')]
    ]
    if invoices:
        buttons.append([InlineKeyboardButton('Очистить список', callback_data=f'ao_invoice_clear|{uid}|{order_id_str}')])
    buttons.append([InlineKeyboardButton('⬅️ Назад', callback_data=f'admin_order|{uid}|{order_id_str}')])
    await query.edit_message_text('<br>'.join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)


async def process_admin_order_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    query = update.callback_query
    if data == 'admin_orders':
        filter_info = {'type': 'all', 'value': None, 'title': '📋 Все заказы', 'back': 'admin_menu'}
        context.user_data['admin_orders_filter'] = filter_info
        extra = build_orders_extra_buttons(filter_info)
        await admin_show_order_list(update, context, filter_info['title'], back_callback=filter_info['back'], extra_buttons=extra)
        return True
    if data == 'admin_orders_refresh':
        filter_info = context.user_data.get('admin_orders_filter') or {'type': 'all', 'value': None, 'title': '📋 Все заказы', 'back': 'admin_menu'}
        context.user_data['admin_orders_filter'] = filter_info
        filter_func = compile_order_filter(filter_info)
        extra = build_orders_extra_buttons(filter_info)
        await admin_show_order_list(
            update,
            context,
            filter_info.get('title', '📋 Все заказы'),
            filter_func,
            back_callback=filter_info.get('back', 'admin_menu'),
            extra_buttons=extra,
        )
        return True
    if data == 'admin_orders_statuses':
        statuses = SETTINGS.get('status_options', [])
        if not statuses:
            await query.edit_message_text(
                'Статусы не настроены.',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]])
            )
            return True
        buttons = [
            [InlineKeyboardButton(status.title(), callback_data=f'admin_orders_status|{idx}')]
            for idx, status in enumerate(statuses)
        ]
        buttons.append([InlineKeyboardButton('Назад', callback_data='admin_orders')])
        await query.edit_message_text('Выберите статус для фильтрации:', reply_markup=InlineKeyboardMarkup(buttons))
        return True
    if data.startswith('admin_orders_status|'):
        try:
            _, idx_str = data.split('|', 1)
            idx = int(idx_str)
        except (ValueError, IndexError):
            idx = -1
        statuses = SETTINGS.get('status_options', [])
        if 0 <= idx < len(statuses):
            status = statuses[idx]
            filter_info = {
                'type': 'status',
                'value': status,
                'title': f'📋 Заказы со статусом "{status}"',
                'back': 'admin_orders'
            }
            context.user_data['admin_orders_filter'] = filter_info
            extra = build_orders_extra_buttons(filter_info)
            await admin_show_order_list(
                update,
                context,
                filter_info['title'],
                compile_order_filter(filter_info),
                back_callback='admin_orders',
                extra_buttons=extra,
            )
            return True
        await query.edit_message_text(
            'Статус не найден.',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]])
        )
        return True
    if data == 'admin_orders_payments':
        buttons = [
            [InlineKeyboardButton('Ожидают предоплату', callback_data='admin_orders_payment|prepayment_pending')],
            [InlineKeyboardButton('Ожидают полную оплату', callback_data='admin_orders_payment|full_pending')],
            [InlineKeyboardButton('Оплаченные', callback_data='admin_orders_payment|paid')],
            [InlineKeyboardButton('Назад', callback_data='admin_orders')],
        ]
        await query.edit_message_text('Выберите фильтр по оплатам:', reply_markup=InlineKeyboardMarkup(buttons))
        return True
    if data.startswith('admin_orders_payment|'):
        value = data.split('|', 1)[1]
        titles = {
            'prepayment_pending': '📋 Заказы без подтвержденной предоплаты',
            'full_pending': '📋 Заказы, ожидающие полной оплаты',
            'paid': '📋 Полностью оплаченные заказы',
        }
        if value not in titles:
            await query.edit_message_text(
                'Фильтр не найден.',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]])
            )
            return True
        filter_info = {'type': 'payment', 'value': value, 'title': titles[value], 'back': 'admin_orders'}
        context.user_data['admin_orders_filter'] = filter_info
        extra = build_orders_extra_buttons(filter_info)
        await admin_show_order_list(
            update,
            context,
            filter_info['title'],
            compile_order_filter(filter_info),
            back_callback='admin_orders',
            extra_buttons=extra,
        )
        return True
    if data == 'admin_orders_search':
        context.user_data['admin_state'] = {'action': 'search_orders'}
        await query.edit_message_text(
            'Введите часть темы, ID пользователя или номер заказа для поиска. Отправьте текст сообщением.',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='admin_orders')]])
        )
        return True
    if data == 'admin_payments':
        filter_info = {'type': 'payment', 'value': 'full_pending', 'title': '💳 Заказы, ожидающие оплату', 'back': 'admin_menu'}
        context.user_data['admin_orders_filter'] = filter_info
        extra = [
            [InlineKeyboardButton('Ждут предоплату', callback_data='admin_orders_payment|prepayment_pending')],
            [InlineKeyboardButton('Ждут полную оплату', callback_data='admin_orders_payment|full_pending')],
            [InlineKeyboardButton('Оплаченные', callback_data='admin_orders_payment|paid')],
        ]
        await admin_show_order_list(
            update,
            context,
            filter_info['title'],
            compile_order_filter(filter_info),
            back_callback='admin_menu',
            extra_buttons=extra,
        )
        return True
    if data.startswith('admin_order|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text(
                'Некорректный идентификатор заказа.',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]])
            )
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text(
                'Заказ не найден.',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]])
            )
            return True
        text = build_order_details(uid, order)
        reply_markup = build_admin_order_keyboard(uid, order_id_str, order)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        return True
    if data.startswith('admin_confirm_prepay|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text(
                'Некорректный идентификатор заказа.',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]])
            )
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text(
                'Заказ не найден.',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]])
            )
            return True
        changed = ensure_order_payment_fields(order)
        if order.get('prepayment_confirmed'):
            if changed:
                save_json(ORDERS_FILE, ORDERS)
            info_prefix = '<b>ℹ️ Предоплата уже подтверждена.</b>'
        else:
            order['prepayment_confirmed'] = True
            order['prepayment_confirmed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if not order.get('full_payment_confirmed'):
                order['payment_state'] = 'предоплата подтверждена'
            if not order.get('prepayment_amount'):
                order['prepayment_amount'] = int(order.get('price', 0) * 0.5)
            order.setdefault('payment_history', []).append({
                'type': 'prepayment_confirmed',
                'amount': order.get('prepayment_amount', 0),
                'channel': order.get('payment_channel'),
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            admin_name = update.effective_user.full_name if update.effective_user else 'admin'
            add_status_history(order, 'предоплата подтверждена', admin_name)
            credited = release_bonus(uid, order, 'prepayment')
            save_json(ORDERS_FILE, ORDERS)
            save_json(BONUSES_FILE, BONUSES)
            info_prefix = '<b>✅ Предоплата подтверждена.</b>'
            try:
                balance = get_user_bonus_balance(uid)
                credited_text = f'Начислено бонусов: {credited} ₽.' if credited else 'Бонусы будут начислены после полной оплаты.'
                message_text = (
                    f"Ваша предоплата по заказу #{order.get('order_id')} подтверждена. {credited_text}\n"
                    f"Текущий баланс бонусов: {balance} ₽."
                )
                await context.bot.send_message(int(uid), message_text)
            except (TelegramError, ValueError) as exc:
                logger.warning('Не удалось уведомить пользователя %s о предоплате: %s', uid, exc)
        text = build_order_details(uid, order)
        reply_markup = build_admin_order_keyboard(uid, order_id_str, order)
        await query.edit_message_text(f"{info_prefix}<br><br>{text}", reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        return True
    if data.startswith('admin_confirm_full|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text(
                'Некорректный идентификатор заказа.',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]])
            )
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text(
                'Заказ не найден.',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]])
            )
            return True
        changed = ensure_order_payment_fields(order)
        if order.get('full_payment_confirmed'):
            if changed:
                save_json(ORDERS_FILE, ORDERS)
            info_prefix = '<b>ℹ️ Полная оплата уже подтверждена.</b>'
        else:
            order['full_payment_confirmed'] = True
            order['full_payment_confirmed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            order['payment_state'] = 'оплачен'
            if not order.get('full_payment_amount'):
                order['full_payment_amount'] = int(order.get('price', 0))
            order.setdefault('payment_history', []).append({
                'type': 'full_payment_confirmed',
                'amount': order.get('full_payment_amount', 0),
                'channel': order.get('payment_channel'),
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            admin_name = update.effective_user.full_name if update.effective_user else 'admin'
            add_status_history(order, 'оплата подтверждена', admin_name)
            credited = release_bonus(uid, order, 'full')
            save_json(ORDERS_FILE, ORDERS)
            save_json(BONUSES_FILE, BONUSES)
            info_prefix = '<b>✅ Оплата подтверждена.</b>'
            try:
                balance = get_user_bonus_balance(uid)
                credited_text = f'Начислено бонусов: {credited} ₽.' if credited else 'Дополнительные бонусы не начислены.'
                message_text = (
                    f"Полная оплата по заказу #{order.get('order_id')} подтверждена. {credited_text}\n"
                    f"Текущий баланс бонусов: {balance} ₽."
                )
                await context.bot.send_message(int(uid), message_text)
            except (TelegramError, ValueError) as exc:
                logger.warning('Не удалось уведомить пользователя %s об оплате: %s', uid, exc)
        text = build_order_details(uid, order)
        reply_markup = build_admin_order_keyboard(uid, order_id_str, order)
        await query.edit_message_text(f"{info_prefix}<br><br>{text}", reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        return True
    if data.startswith('admin_cancel|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text(
                'Некорректный идентификатор заказа.',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]])
            )
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text(
                'Заказ не найден.',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]])
            )
            return True
        order['status'] = 'отменен'
        add_status_history(order, 'отменен', update.effective_user.full_name if update.effective_user else 'admin')
        save_json(ORDERS_FILE, ORDERS)
        keyboard = [
            [InlineKeyboardButton('Посмотреть заказ', callback_data=f'admin_order|{uid}|{order_id_str}')],
            [InlineKeyboardButton('⬅️ К списку', callback_data='admin_orders')]
        ]
        await query.edit_message_text(f"Статус заказа #{order_id_str} обновлен на 'отменен'.", reply_markup=InlineKeyboardMarkup(keyboard))
        return True
    if data.startswith('admin_delete|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text(
                'Некорректный идентификатор заказа.',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]])
            )
            return True
        orders_list = ORDERS.get(uid, [])
        new_list = [o for o in orders_list if str(o.get('order_id')) != order_id_str]
        if len(new_list) == len(orders_list):
            await query.edit_message_text(
                'Заказ не найден.',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]])
            )
            return True
        if new_list:
            ORDERS[uid] = new_list
        else:
            ORDERS.pop(uid, None)
        save_json(ORDERS_FILE, ORDERS)
        keyboard = [
            [InlineKeyboardButton('⬅️ К списку', callback_data='admin_orders')],
            [InlineKeyboardButton('Админ-меню', callback_data='admin_menu')]
        ]
        await query.edit_message_text(f'Заказ #{order_id_str} удален.', reply_markup=InlineKeyboardMarkup(keyboard))
        return True
    if data.startswith('ao_status|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        statuses = SETTINGS.get('status_options', [])
        buttons = [
            [InlineKeyboardButton(status.title(), callback_data=f'ao_set_status|{uid}|{order_id_str}|{idx}')]
            for idx, status in enumerate(statuses)
        ]
        buttons.append([InlineKeyboardButton('Свое значение', callback_data=f'ao_status_custom|{uid}|{order_id_str}')])
        buttons.append([InlineKeyboardButton('⬅️ Назад', callback_data=f'admin_order|{uid}|{order_id_str}')])
        await query.edit_message_text('Выберите новый статус заказа:', reply_markup=InlineKeyboardMarkup(buttons))
        return True
    if data.startswith('ao_set_status|'):
        try:
            _, uid, order_id_str, idx_str = data.split('|', 3)
            idx = int(idx_str)
        except (ValueError, IndexError):
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        statuses = SETTINGS.get('status_options', [])
        if not order or not (0 <= idx < len(statuses)):
            await query.edit_message_text('Статус не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        status = statuses[idx]
        order['status'] = status
        add_status_history(order, status, get_admin_display_name(update))
        save_json(ORDERS_FILE, ORDERS)
        text = build_order_details(uid, order)
        reply_markup = build_admin_order_keyboard(uid, order_id_str, order)
        await query.edit_message_text(f'✅ Статус обновлен.<br><br>{text}', reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        return True
    if data.startswith('ao_status_custom|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        context.user_data['admin_state'] = {'action': 'custom_status', 'uid': uid, 'order_id': order_id_str}
        await query.edit_message_text('Введите новый статус текстом и отправьте сообщением.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data=f'admin_order|{uid}|{order_id_str}')]]))
        return True
    if data.startswith('ao_price|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        context.user_data['admin_state'] = {'action': 'set_price', 'uid': uid, 'order_id': order_id_str}
        await query.edit_message_text(
            f"Текущая цена: {order.get('price', 0)} ₽. Введите новую цену (целое число).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data=f'admin_order|{uid}|{order_id_str}')]])
        )
        return True
    if data.startswith('ao_deadline|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        context.user_data['admin_state'] = {'action': 'set_deadline', 'uid': uid, 'order_id': order_id_str}
        await query.edit_message_text(
            f"Текущий срок: {order.get('deadline_days', 'не указан')} дней. Введите новое количество дней до дедлайна.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data=f'admin_order|{uid}|{order_id_str}')]])
        )
        return True
    if data.startswith('ao_note|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        context.user_data['admin_state'] = {'action': 'add_note', 'uid': uid, 'order_id': order_id_str}
        await query.edit_message_text(
            'Отправьте текст заметки. Можно указать чек-лист, договоренности, статусы.',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data=f'admin_order|{uid}|{order_id_str}')]])
        )
        return True
    if data.startswith('ao_assign|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        await render_order_assignment_editor(query, uid, order_id_str, order)
        return True
    if data.startswith('ao_assign_set|'):
        try:
            _, uid, order_id_str, idx_str = data.split('|', 3)
            idx = int(idx_str)
        except (ValueError, IndexError):
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        managers = SETTINGS.get('managers', [])
        order = find_order(uid, order_id_str)
        if not order or not (0 <= idx < len(managers)):
            await query.edit_message_text('Менеджер не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order['assigned_manager'] = managers[idx]
        save_json(ORDERS_FILE, ORDERS)
        await render_order_assignment_editor(query, uid, order_id_str, order)
        return True
    if data.startswith('ao_assign_custom|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        context.user_data['admin_state'] = {'action': 'assign_manager', 'uid': uid, 'order_id': order_id_str}
        await query.edit_message_text('Введите имя менеджера текстом.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data=f'admin_order|{uid}|{order_id_str}')]]))
        return True
    if data.startswith('ao_assign_clear|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order['assigned_manager'] = None
        save_json(ORDERS_FILE, ORDERS)
        await render_order_assignment_editor(query, uid, order_id_str, order)
        return True
    if data.startswith('ao_tags|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        await render_order_tags_editor(query, uid, order_id_str, order)
        return True
    if data.startswith('ao_tags_toggle|'):
        try:
            _, uid, order_id_str, idx_str = data.split('|', 3)
            idx = int(idx_str)
        except (ValueError, IndexError):
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        tags = SETTINGS.get('order_tags', [])
        if not order or not (0 <= idx < len(tags)):
            await query.edit_message_text('Тег не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        current = set(order.get('admin_tags') or [])
        tag = tags[idx]
        if tag in current:
            current.remove(tag)
        else:
            current.add(tag)
        order['admin_tags'] = sorted(current)
        save_json(ORDERS_FILE, ORDERS)
        await render_order_tags_editor(query, uid, order_id_str, order)
        return True
    if data.startswith('ao_tags_clear|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order['admin_tags'] = []
        save_json(ORDERS_FILE, ORDERS)
        await render_order_tags_editor(query, uid, order_id_str, order)
        return True
    if data.startswith('ao_tags_custom|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        context.user_data['admin_state'] = {'action': 'add_tag', 'uid': uid, 'order_id': order_id_str}
        await query.edit_message_text('Введите новый тег текстом.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data=f'admin_order|{uid}|{order_id_str}')]]))
        return True
    if data.startswith('ao_payments|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        await render_order_payments_editor(query, uid, order_id_str, order)
        return True
    if data.startswith('ao_payment_amount|'):
        try:
            _, uid, order_id_str, stage = data.split('|', 3)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order or stage not in {'prepay', 'full'}:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        context.user_data['admin_state'] = {'action': 'set_payment_amount', 'uid': uid, 'order_id': order_id_str, 'stage': stage}
        stage_text = 'предоплаты' if stage == 'prepay' else 'полной оплаты'
        await query.edit_message_text(
            f'Введите сумму {stage_text} в рублях.',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data=f'ao_payments|{uid}|{order_id_str}')]])
        )
        return True
    if data.startswith('ao_payment_channel|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        buttons = [
            [InlineKeyboardButton(channel, callback_data=f'ao_channel_set|{uid}|{order_id_str}|{idx}')]
            for idx, channel in enumerate(SETTINGS.get('payment_channels', []))
        ]
        buttons.append([InlineKeyboardButton('⬅️ Назад', callback_data=f'ao_payments|{uid}|{order_id_str}')])
        await query.edit_message_text('Выберите канал оплаты:', reply_markup=InlineKeyboardMarkup(buttons))
        return True
    if data.startswith('ao_channel_set|'):
        try:
            _, uid, order_id_str, idx_str = data.split('|', 3)
            idx = int(idx_str)
        except (ValueError, IndexError):
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        channels = SETTINGS.get('payment_channels', [])
        order = find_order(uid, order_id_str)
        if not order or not (0 <= idx < len(channels)):
            await query.edit_message_text('Канал не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order['payment_channel'] = channels[idx]
        save_json(ORDERS_FILE, ORDERS)
        await render_order_payments_editor(query, uid, order_id_str, order)
        return True
    if data.startswith('ao_invoice|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        await render_order_invoice_editor(query, uid, order_id_str, order)
        return True
    if data.startswith('ao_invoice_add|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        context.user_data['admin_state'] = {'action': 'add_invoice', 'uid': uid, 'order_id': order_id_str}
        await query.edit_message_text('Отправьте ссылку на счет или платеж.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data=f'ao_invoice|{uid}|{order_id_str}')]]))
        return True
    if data.startswith('ao_invoice_clear|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text('Некорректные данные.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order = find_order(uid, order_id_str)
        if not order:
            await query.edit_message_text('Заказ не найден.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Назад', callback_data='admin_orders')]]))
            return True
        order['invoice_links'] = []
        save_json(ORDERS_FILE, ORDERS)
        await render_order_invoice_editor(query, uid, order_id_str, order)
        return True
    return False


async def process_admin_user_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    query = update.callback_query
    if data == 'admin_users':
        users_summary = []
        for uid, orders in ORDERS.items():
            stats = compute_user_stats(uid)
            last_order = stats['last_order'].strftime('%Y-%m-%d') if stats['last_order'] else '—'
            users_summary.append({
                'uid': uid,
                'stats': stats,
                'last_order': last_order,
                'bonus': get_user_bonus_balance(uid)
            })
        users_summary.sort(key=lambda item: (item['stats']['orders'], item['stats']['total_spent']), reverse=True)
        lines = ['👥 Активные пользователи:']
        if not users_summary:
            lines.append('Пока нет заказов от пользователей.')
        else:
            for entry in users_summary[:20]:
                stats = entry['stats']
                lines.append(
                    f"{entry['uid']}: заказов {stats['orders']} | оплаченное {stats['total_spent']} ₽ | долгов {stats['outstanding']} ₽ | последний заказ {entry['last_order']}"
                )
        buttons = [
            [InlineKeyboardButton(f"{entry['uid']} ({entry['stats']['orders']})", callback_data=f"admin_user|{entry['uid']}")]
            for entry in users_summary[:20]
        ]
        buttons.append([InlineKeyboardButton('🔎 Поиск', callback_data='admin_users_search')])
        buttons.append([InlineKeyboardButton('⬅️ Админ-меню', callback_data='admin_menu')])
        await query.edit_message_text('<br>'.join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        return True
    if data == 'admin_users_search':
        context.user_data['admin_state'] = {'action': 'search_user'}
        await query.edit_message_text('Введите ID пользователя или часть имени/ника для поиска.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='admin_users')]]))
        return True
    if data.startswith('admin_user|'):
        uid = data.split('|', 1)[1]
        stats = compute_user_stats(uid)
        bonus_balance = get_user_bonus_balance(uid)
        pending_bonus = stats['pending_bonus']
        referrals = len(REFERALS.get(uid, []))
        blocked = uid in SETTINGS.get('blocked_users', [])
        last_log_entry = USER_LOGS.get(uid, [])[-1]['action'] if USER_LOGS.get(uid) else '—'
        last_order = stats['last_order'].strftime('%Y-%m-%d %H:%M') if stats['last_order'] else '—'
        contact_hint = '—'
        for order in reversed(ORDERS.get(uid, [])):
            if order.get('contact'):
                contact_hint = order['contact']
                break
        lines = [
            f"<b>Пользователь {uid}</b>",
            f"Заказов: {stats['orders']} | Оплачено: {stats['total_spent']} ₽ | Долг: {stats['outstanding']} ₽",
            f"Бонусы: {bonus_balance} ₽ | Ожидает: {pending_bonus} ₽",
            f"Рефералов: {referrals}",
            f"Последний заказ: {last_order}",
            f"Последнее действие: {escape(last_log_entry)}",
            f"Последний контакт: {escape(contact_hint)}",
        ]
        if stats['statuses']:
            status_line = ', '.join(f"{name}: {count}" for name, count in stats['statuses'].items())
            lines.append(f"Статусы: {escape(status_line)}")
        block_label = 'Разблокировать' if blocked else 'Заблокировать'
        buttons = [
            [InlineKeyboardButton('📋 Заказы', callback_data=f'admin_user_orders|{uid}'), InlineKeyboardButton('🗒 Логи', callback_data=f'admin_user_logs|{uid}')],
            [InlineKeyboardButton('🎁 Бонусы ±', callback_data=f'admin_adjust_bonus|{uid}'), InlineKeyboardButton('✉️ Написать', callback_data=f'admin_message_user|{uid}')],
            [InlineKeyboardButton(block_label, callback_data=f'admin_toggle_block|{uid}'), InlineKeyboardButton('👥 Рефералы', callback_data=f'admin_user_refs|{uid}')],
            [InlineKeyboardButton('⬅️ Пользователи', callback_data='admin_users')]
        ]
        buttons.append([InlineKeyboardButton('👤 В Telegram', url=f'tg://user?id={uid}')])
        await query.edit_message_text('<br>'.join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        return True
    if data.startswith('admin_user_orders|'):
        uid = data.split('|', 1)[1]
        orders = [(uid, order) for order in ORDERS.get(uid, [])]
        text, markup = build_order_list_message('Заказы пользователя', orders, back_callback=f'admin_user|{uid}')
        await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        return True
    if data.startswith('admin_user_logs|'):
        uid = data.split('|', 1)[1]
        logs = USER_LOGS.get(uid, [])[-10:]
        lines = ['Последние действия:']
        if not logs:
            lines.append('Логи отсутствуют.')
        else:
            for entry in logs:
                lines.append(f"{entry['timestamp']}: {escape(entry['action'])}")
        buttons = [[InlineKeyboardButton('⬅️ Назад', callback_data=f'admin_user|{uid}')]]
        await query.edit_message_text('<br>'.join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        return True
    if data.startswith('admin_user_refs|'):
        uid = data.split('|', 1)[1]
        refs = REFERALS.get(uid, [])
        lines = ['Рефералы пользователя:']
        if not refs:
            lines.append('Нет приглашенных пользователей.')
        else:
            lines.append(', '.join(str(ref) for ref in refs))
        buttons = [[InlineKeyboardButton('⬅️ Назад', callback_data=f'admin_user|{uid}')]]
        await query.edit_message_text('<br>'.join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        return True
    if data.startswith('admin_adjust_bonus|'):
        uid = data.split('|', 1)[1]
        context.user_data['admin_state'] = {'action': 'adjust_bonus', 'uid': uid}
        await query.edit_message_text('Введите сумму для начисления или списания бонусов (например, 500 или -300).', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data=f'admin_user|{uid}')]]))
        return True
    if data.startswith('admin_message_user|'):
        uid = data.split('|', 1)[1]
        context.user_data['admin_state'] = {'action': 'direct_message_single', 'uid': uid}
        await query.edit_message_text('Введите текст сообщения пользователю.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data=f'admin_user|{uid}')]]))
        return True
    if data.startswith('admin_toggle_block|'):
        uid = data.split('|', 1)[1]
        blocked = SETTINGS.setdefault('blocked_users', [])
        if uid in blocked:
            blocked.remove(uid)
            status_text = 'Пользователь разблокирован.'
        else:
            blocked.append(uid)
            status_text = 'Пользователь заблокирован.'
        save_settings()
        await query.answer(status_text, show_alert=False)
        await process_admin_user_action(update, context, f'admin_user|{uid}')
        return True
    return False


async def process_admin_pricing_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    query = update.callback_query
    if data == 'admin_pricing':
        lines = [
            '<b>Ценообразование</b>',
            f"Текущий режим: <b>{current_pricing_mode}</b>",
            f"Бонусный процент: {int(BONUS_PERCENT * 100)}%",
            f"Допы: презентация {UPSELL_PRICES.get('prez', 0)} ₽, речь {UPSELL_PRICES.get('speech', 0)} ₽",
        ]
        for key, price_cfg in PRICES.items():
            name = ORDER_TYPES.get(key, {}).get('name', key)
            lines.append(
                f"{escape(name)} — базовая {price_cfg.get('base', 0)} ₽ (мин {price_cfg.get('min', 0)} ₽ / макс {price_cfg.get('max', 0)} ₽)"
            )
        buttons = [
            [InlineKeyboardButton('Режим', callback_data='admin_pricing_mode'), InlineKeyboardButton('Бонусы %', callback_data='admin_pricing_bonus')],
            [InlineKeyboardButton('Допы', callback_data='admin_pricing_upsells')]
        ]
        for key in PRICES.keys():
            name = ORDER_TYPES.get(key, {}).get('name', key)
            buttons.append([InlineKeyboardButton(name, callback_data=f'admin_pricing_type|{key}')])
        buttons.append([InlineKeyboardButton('⬅️ Админ-меню', callback_data='admin_menu')])
        await query.edit_message_text('<br>'.join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        return True
    if data == 'admin_pricing_mode':
        context.user_data['admin_state'] = {'action': 'set_pricing_mode'}
        await query.edit_message_text('Введите режим ценообразования: hard или light.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='admin_pricing')]]))
        return True
    if data == 'admin_pricing_bonus':
        context.user_data['admin_state'] = {'action': 'set_bonus_percent'}
        await query.edit_message_text('Введите новый процент бонусов (например, 5 означает 5%).', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='admin_pricing')]]))
        return True
    if data == 'admin_pricing_upsells':
        context.user_data['admin_state'] = {'action': 'set_upsell_prices'}
        await query.edit_message_text(
            'Введите цены допов в формате "prez=2000,speech=1000".',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='admin_pricing')]])
        )
        return True
    if data.startswith('admin_pricing_type|'):
        key = data.split('|', 1)[1]
        if key not in PRICES:
            await query.edit_message_text('Неизвестный тип работы.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='admin_pricing')]]))
            return True
        price_cfg = PRICES[key]
        name = ORDER_TYPES.get(key, {}).get('name', key)
        context.user_data['admin_state'] = {'action': 'set_price_table', 'type_key': key}
        await query.edit_message_text(
            f"Текущие значения для {name}: базовая {price_cfg.get('base', 0)}, мин {price_cfg.get('min', 0)}, макс {price_cfg.get('max', 0)}.\nВведите новые значения через запятую (например, 12000,9000,16000).",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='admin_pricing')]])
        )
        return True
    return False


async def process_admin_settings_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    query = update.callback_query
    if data == 'admin_settings':
        lines = [
            '<b>Настройки управления</b>',
            f"Менеджеры: {', '.join(SETTINGS.get('managers', [])) or 'нет'}",
            f"Статусы заказов: {', '.join(SETTINGS.get('status_options', []))}",
            f"Теги: {', '.join(SETTINGS.get('order_tags', []))}",
            f"Каналы оплаты: {', '.join(SETTINGS.get('payment_channels', []))}",
            f"Контакт администратора: {ADMIN_CONTACT}",
            f"Фоллоу-ап через: {SETTINGS.get('auto_follow_up_hours', 12)} ч",
            f"Заблокированных: {len(SETTINGS.get('blocked_users', []))}",
        ]
        buttons = [
            [InlineKeyboardButton('Менеджеры', callback_data='admin_settings_managers'), InlineKeyboardButton('Статусы', callback_data='admin_settings_statuses')],
            [InlineKeyboardButton('Теги', callback_data='admin_settings_tags'), InlineKeyboardButton('Каналы оплаты', callback_data='admin_settings_payments')],
            [InlineKeyboardButton('Контакт', callback_data='admin_settings_contact'), InlineKeyboardButton('Фоллоу-ап', callback_data='admin_settings_followup')],
            [InlineKeyboardButton('Заблокированные', callback_data='admin_settings_blocked')],
            [InlineKeyboardButton('⬅️ Админ-меню', callback_data='admin_menu')]
        ]
        await query.edit_message_text('<br>'.join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        return True
    if data == 'admin_settings_managers':
        managers = SETTINGS.setdefault('managers', [])
        buttons = [
            [InlineKeyboardButton(f'❌ {manager}', callback_data=f'admin_settings_remove_manager|{idx}')]
            for idx, manager in enumerate(managers)
        ]
        buttons.append([InlineKeyboardButton('Добавить менеджера', callback_data='admin_settings_add_manager')])
        buttons.append([InlineKeyboardButton('⬅️ Назад', callback_data='admin_settings')])
        text = 'Менеджеры: ' + (', '.join(managers) if managers else 'не назначены.')
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return True
    if data.startswith('admin_settings_remove_manager|'):
        idx = int(data.split('|', 1)[1])
        managers = SETTINGS.setdefault('managers', [])
        if 0 <= idx < len(managers):
            managers.pop(idx)
            save_settings()
        await process_admin_settings_action(update, context, 'admin_settings_managers')
        return True
    if data == 'admin_settings_add_manager':
        context.user_data['admin_state'] = {'action': 'add_manager'}
        await query.edit_message_text('Введите имя или контакт менеджера.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='admin_settings_managers')]]))
        return True
    if data == 'admin_settings_statuses':
        statuses = SETTINGS.setdefault('status_options', [])
        buttons = [
            [InlineKeyboardButton(f'❌ {status}', callback_data=f'admin_settings_remove_status|{idx}')]
            for idx, status in enumerate(statuses)
        ]
        buttons.append([InlineKeyboardButton('Добавить статус', callback_data='admin_settings_add_status')])
        buttons.append([InlineKeyboardButton('⬅️ Назад', callback_data='admin_settings')])
        text = 'Статусы заказов: ' + (', '.join(statuses) if statuses else 'не заданы.')
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return True
    if data.startswith('admin_settings_remove_status|'):
        idx = int(data.split('|', 1)[1])
        statuses = SETTINGS.setdefault('status_options', [])
        if 0 <= idx < len(statuses) and len(statuses) > 1:
            statuses.pop(idx)
            save_settings()
        await process_admin_settings_action(update, context, 'admin_settings_statuses')
        return True
    if data == 'admin_settings_add_status':
        context.user_data['admin_state'] = {'action': 'add_status'}
        await query.edit_message_text('Введите новый статус.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='admin_settings_statuses')]]))
        return True
    if data == 'admin_settings_tags':
        tags = SETTINGS.setdefault('order_tags', [])
        buttons = [
            [InlineKeyboardButton(f'❌ {tag}', callback_data=f'admin_settings_remove_tag|{idx}')]
            for idx, tag in enumerate(tags)
        ]
        buttons.append([InlineKeyboardButton('Добавить тег', callback_data='admin_settings_add_tag')])
        buttons.append([InlineKeyboardButton('⬅️ Назад', callback_data='admin_settings')])
        text = 'Доступные теги: ' + (', '.join(tags) if tags else 'не настроены.')
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return True
    if data.startswith('admin_settings_remove_tag|'):
        idx = int(data.split('|', 1)[1])
        tags = SETTINGS.setdefault('order_tags', [])
        if 0 <= idx < len(tags):
            tags.pop(idx)
            save_settings()
        await process_admin_settings_action(update, context, 'admin_settings_tags')
        return True
    if data == 'admin_settings_add_tag':
        context.user_data['admin_state'] = {'action': 'add_tag_setting'}
        await query.edit_message_text('Введите новый тег.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='admin_settings_tags')]]))
        return True
    if data == 'admin_settings_payments':
        channels = SETTINGS.setdefault('payment_channels', [])
        buttons = [
            [InlineKeyboardButton(f'❌ {channel}', callback_data=f'admin_settings_remove_channel|{idx}')]
            for idx, channel in enumerate(channels)
        ]
        buttons.append([InlineKeyboardButton('Добавить канал', callback_data='admin_settings_add_channel')])
        buttons.append([InlineKeyboardButton('⬅️ Назад', callback_data='admin_settings')])
        text = 'Каналы оплаты: ' + (', '.join(channels) if channels else 'не заданы.')
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return True
    if data.startswith('admin_settings_remove_channel|'):
        idx = int(data.split('|', 1)[1])
        channels = SETTINGS.setdefault('payment_channels', [])
        if 0 <= idx < len(channels):
            channels.pop(idx)
            save_settings()
        await process_admin_settings_action(update, context, 'admin_settings_payments')
        return True
    if data == 'admin_settings_add_channel':
        context.user_data['admin_state'] = {'action': 'add_payment_channel'}
        await query.edit_message_text('Введите новый канал оплаты.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='admin_settings_payments')]]))
        return True
    if data == 'admin_settings_contact':
        context.user_data['admin_state'] = {'action': 'set_admin_contact'}
        await query.edit_message_text('Введите ссылку или контакт администратора.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='admin_settings')]]))
        return True
    if data == 'admin_settings_followup':
        context.user_data['admin_state'] = {'action': 'set_followup_hours'}
        await query.edit_message_text('Введите количество часов до автоматического напоминания.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='admin_settings')]]))
        return True
    if data == 'admin_settings_blocked':
        blocked = SETTINGS.get('blocked_users', [])
        lines = ['Заблокированные пользователи:' + (' ' + ', '.join(blocked) if blocked else ' нет.')] 
        buttons = [
            [InlineKeyboardButton(f'Разблокировать {uid}', callback_data=f'admin_settings_unblock|{uid}')]
            for uid in blocked
        ]
        buttons.append([InlineKeyboardButton('⬅️ Назад', callback_data='admin_settings')])
        await query.edit_message_text('<br>'.join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        return True
    if data.startswith('admin_settings_unblock|'):
        uid = data.split('|', 1)[1]
        blocked = SETTINGS.setdefault('blocked_users', [])
        if uid in blocked:
            blocked.remove(uid)
            save_settings()
        await process_admin_settings_action(update, context, 'admin_settings_blocked')
        return True
    return False


async def process_admin_notifications_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    query = update.callback_query
    if data == 'admin_notifications':
        lines = [
            '<b>Уведомления</b>',
            'Рассылайте сообщения клиентам прямо из бота.'
        ]
        buttons = [
            [InlineKeyboardButton('📢 Рассылка всем', callback_data='admin_notify_broadcast')],
            [InlineKeyboardButton('💳 Напомнить должникам', callback_data='admin_notify_pending')],
            [InlineKeyboardButton('✉️ Сообщение пользователю', callback_data='admin_notify_direct')],
            [InlineKeyboardButton('⬅️ Админ-меню', callback_data='admin_menu')]
        ]
        await query.edit_message_text('<br>'.join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        return True
    if data == 'admin_notify_broadcast':
        context.user_data['admin_state'] = {'action': 'broadcast_all'}
        await query.edit_message_text('Введите текст рассылки. Он будет отправлен всем пользователям с заказами.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='admin_notifications')]]))
        return True
    if data == 'admin_notify_pending':
        context.user_data['admin_state'] = {'action': 'broadcast_pending'}
        await query.edit_message_text('Введите текст напоминания. Оно уйдет пользователям с неподтвержденной оплатой.', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='admin_notifications')]]))
        return True
    if data == 'admin_notify_direct':
        context.user_data['admin_state'] = {'action': 'direct_message_manual'}
        await query.edit_message_text('Введите сообщение в формате "user_id|Текст".', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Назад', callback_data='admin_notifications')]]))
        return True
    return False


async def process_admin_export_action(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    query = update.callback_query
    chat_id = query.message.chat_id if query.message else ADMIN_CHAT_ID
    if data == 'admin_export':
        lines = ['<b>Экспорт данных</b>', 'Выберите формат выгрузки.']
        if pd is None:
            lines.append('⚠️ Установите пакет pandas, чтобы включить экспорт в CSV.')
        buttons = [
            [InlineKeyboardButton('📄 CSV заказы', callback_data='admin_export_csv')],
            [InlineKeyboardButton('📁 JSON заказы', callback_data='admin_export_json')],
            [InlineKeyboardButton('🎁 Бонусы', callback_data='admin_export_bonuses')],
            [InlineKeyboardButton('🧾 Логи', callback_data='admin_export_logs')],
            [InlineKeyboardButton('⬅️ Админ-меню', callback_data='admin_menu')]
        ]
        await query.edit_message_text('<br>'.join(lines), reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)
        return True
    if data == 'admin_export_csv':
        if pd is None:
            await query.answer('CSV экспорт недоступен: pandas не установлен.', show_alert=True)
            return True
        rows = [{'user_id': uid, **order} for uid, orders in ORDERS.items() for order in orders]
        if not rows:
            await query.answer('Нет данных для экспорта.', show_alert=True)
            return True
        df = pd.DataFrame(rows)
        export_file = os.path.join(DATA_DIR, 'orders_export.csv')
        df.to_csv(export_file, index=False)
        with open(export_file, 'rb') as f:
            await context.bot.send_document(chat_id, document=f, filename='orders_export.csv')
        os.remove(export_file)
        await query.answer('Файл отправлен.')
        return True
    if data == 'admin_export_json':
        export_file = os.path.join(DATA_DIR, 'orders_export.json')
        with open(export_file, 'w', encoding='utf-8') as f:
            json.dump(ORDERS, f, ensure_ascii=False, indent=2)
        with open(export_file, 'rb') as f:
            await context.bot.send_document(chat_id, document=f, filename='orders_export.json')
        os.remove(export_file)
        await query.answer('JSON выгружен.')
        return True
    if data == 'admin_export_bonuses':
        if pd is None:
            await query.answer('CSV экспорт недоступен: pandas не установлен.', show_alert=True)
            return True
        rows = []
        for uid, info in BONUSES.items():
            rows.append({'user_id': uid, 'balance': info.get('balance', 0), 'operations': len(info.get('history', []))})
        if not rows:
            await query.answer('Бонусов пока нет.', show_alert=True)
            return True
        df = pd.DataFrame(rows)
        export_file = os.path.join(DATA_DIR, 'bonuses_export.csv')
        df.to_csv(export_file, index=False)
        with open(export_file, 'rb') as f:
            await context.bot.send_document(chat_id, document=f, filename='bonuses_export.csv')
        os.remove(export_file)
        await query.answer('Бонусы выгружены.')
        return True
    if data == 'admin_export_logs':
        export_file = os.path.join(DATA_DIR, 'logs_export.txt')
        with open(export_file, 'w', encoding='utf-8') as f:
            for uid, logs in USER_LOGS.items():
                for entry in logs:
                    f.write(f"{uid}\t{entry['timestamp']}\t{entry['action']}\n")
        with open(export_file, 'rb') as f:
            await context.bot.send_document(chat_id, document=f, filename='logs_export.txt')
        os.remove(export_file)
        await query.answer('Логи отправлены.')
        return True
    return False

ORDER_TYPES = {
    'samostoyatelnye': {
        'name': 'Самостоятельные, контрольные, эссе',
        'icon': '📝',
        'description': 'Быстрые задания: эссе, контрольные, рефераты. Идеально для студентов! Уже 5000+ выполнено 🔥',
        'details': 'Объем до 20 страниц. Быстрое выполнение с гарантией качества.',
        'examples': ['Эссе по литературе', 'Контрольная по математике', 'Реферат по истории']
    },
    'kursovaya_teoreticheskaya': {
        'name': 'Курсовая теоретическая',
        'icon': '📘',
        'description': 'Глубокий анализ литературы и теории. Получите отличную оценку без стресса! 📈',
        'details': 'Теоретическая основа, аналитика источников и четкая структура по ГОСТ.',
        'examples': ['Теория маркетинга', 'Обзор психологии развития']
    },
    'kursovaya_s_empirikov': {
        'name': 'Курсовая с эмпирикой',
        'icon': '📊',
        'description': 'Теория + данные, анализ. Клиенты говорят: "Лучшая помощь!" ⭐',
        'details': 'Включает опросы, статистику, рекомендации.',
        'examples': ['Исследование рынка', 'Анализ поведения потребителей']
    },
    'diplomnaya': {
        'name': 'Дипломная работа',
        'icon': '🎓',
        'description': 'Полный цикл для успешной защиты. Скидка 10% на первый диплом! 💼',
        'details': 'Глубокий анализ, эмпирика, презентация.',
        'examples': ['Социальная адаптация', 'Экономический анализ компании']
    },
    'magisterskaya': {
        'name': 'Магистерская диссертация',
        'icon': '🔍',
        'description': 'Инновационное исследование. 100% оригинальность гарантирована! 🌟',
        'details': 'Научная новизна, методология, публикации.',
        'examples': ['Разработка моделей AI', 'Комплексные исследования экологии']
    }
}

UPSELL_TITLES = {
    'prez': 'Презентация',
    'speech': 'Речь'
}

FAQ_ITEMS = [
    {'question': 'Как сделать заказ?', 'answer': 'Выберите "Сделать заказ" и следуйте шагам. Можно заказать несколько работ сразу!'},
    {'question': 'Как рассчитывается стоимость?', 'answer': 'Зависит от типа, срочности и сложности. Используйте калькулятор для точной цены!'},
    {'question': 'Как работает реферальная программа?', 'answer': 'Поделитесь ссылкой — получите 5% от заказов друзей как бонус.'},
    {'question': 'Гарантии качества?', 'answer': 'Антиплагиат, правки бесплатно 14 дней, поддержка до защиты.'},
    {'question': 'Скидки?', 'answer': '5-15% для постоянных, 10% на первый, рефералы.'},
    {'question': 'Отслеживание заказа?', 'answer': 'В профиле статусы, уведомления от менеджера.'}
]

current_pricing_mode = SETTINGS.get('pricing_mode', 'light')

# Состояния
SELECT_MAIN_MENU, SELECT_ORDER_TYPE, VIEW_ORDER_DETAILS, INPUT_TOPIC, SELECT_DEADLINE, INPUT_REQUIREMENTS, UPLOAD_FILES, INPUT_CONTACT, ADD_UPSSELL, ADD_ANOTHER_ORDER, CONFIRM_CART, ADMIN_MENU, PROFILE_MENU, SHOW_PRICE_LIST, PRICE_CALCULATOR, SELECT_CALC_DEADLINE, SELECT_CALC_COMPLEXITY, SHOW_FAQ, FAQ_DETAILS, SHOW_ORDERS, LEAVE_FEEDBACK, INPUT_FEEDBACK = range(22)

# Логирование действий пользователя
def log_user_action(user_id, username, action):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    USER_LOGS.setdefault(str(user_id), []).append({'timestamp': timestamp, 'action': action, 'username': username})
    save_json(USER_LOGS_FILE, USER_LOGS)
    logger.info(f"Пользователь {user_id} ({username}): {action}")

async def answer_callback(query):
    """Безопасно отвечает на callback-запрос, чтобы избежать ошибок повторного ответа."""
    if not query:
        return
    try:
        await query.answer()
    except TelegramError as exc:
        error_text = str(exc).lower()
        if "query is too old" in error_text or "query id is invalid" in error_text:
            logger.debug("Callback уже обработан: %s", exc)
        else:
            raise

async def ask_for_topic(update: Update, context: ContextTypes.DEFAULT_TYPE, via_callback: bool = False):
    topic = context.user_data.get('topic')
    text_lines = ["Введите тему заказа."]
    if topic:
        text_lines.append(f"Текущая тема: {topic}")
    text_lines.append(
        f"Чтобы вернуться к выбору типа, используйте кнопку \"{BACK_BUTTON_TEXT}\" или команду /back."
    )
    markup = ReplyKeyboardMarkup([[BACK_BUTTON_TEXT]], resize_keyboard=True, one_time_keyboard=True)
    message_text = '\n'.join(text_lines)
    if via_callback:
        chat_id = update.effective_chat.id
        await context.bot.send_message(chat_id, message_text, reply_markup=markup)
    else:
        await update.message.reply_text(message_text, reply_markup=markup)
    return INPUT_TOPIC

async def show_deadline_options(update: Update, context: ContextTypes.DEFAULT_TYPE, via_callback: bool = False):
    today = datetime.now()
    days_left = context.user_data.get('days_left')
    text = "Выберите срок сдачи (дольше = дешевле + бонус!):"
    if days_left:
        text += f"\nТекущий выбранный срок: {days_left} дней."
    keyboard = []
    for i in range(1, 31, 5):
        row = []
        for j in range(i, min(i + 5, 31)):
            date = today + timedelta(days=j)
            button_text = f"{date.day} {date.strftime('%b')} ({j} дней)"
            row.append(InlineKeyboardButton(button_text, callback_data=f'deadline_{j}'))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(BACK_BUTTON_TEXT, callback_data='back_topic')])
    markup = InlineKeyboardMarkup(keyboard)
    if via_callback:
        await context.bot.send_message(update.effective_chat.id, text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)
    return SELECT_DEADLINE

async def prompt_requirements_input(update: Update, context: ContextTypes.DEFAULT_TYPE, via_callback: bool = False):
    requirements = context.user_data.get('requirements')
    lines = ["Введите дополнительные требования (или /skip)."]
    if requirements and requirements not in ('Нет', ''):
        lines.append(f"Текущие требования: {requirements}")
    lines.append(
        f"Чтобы вернуться к выбору срока, используйте кнопку \"{BACK_BUTTON_TEXT}\" или команду /back."
    )
    markup = ReplyKeyboardMarkup([[BACK_BUTTON_TEXT]], resize_keyboard=True, one_time_keyboard=True)
    text = '\n'.join(lines)
    if via_callback:
        await context.bot.send_message(update.effective_chat.id, text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)
    return INPUT_REQUIREMENTS

async def prompt_contact_input(update: Update, context: ContextTypes.DEFAULT_TYPE, via_callback: bool = False):
    prompt_lines = [
        "Укажите контакт, куда менеджеру написать (Telegram, ВКонтакте, почта). Это обязательное поле."
    ]
    current_contact = context.user_data.get('current_contact')
    last_contact = context.user_data.get('last_contact')
    if current_contact:
        prompt_lines.append(f"Текущий контакт: {current_contact}")
    elif last_contact:
        prompt_lines.append(f"Последний указанный контакт: {last_contact}")
    prompt_lines.append(
        f"Чтобы вернуться к файлам, используйте кнопку \"{BACK_BUTTON_TEXT}\" или команду /back."
    )
    markup = ReplyKeyboardMarkup([[BACK_BUTTON_TEXT]], resize_keyboard=True, one_time_keyboard=True)
    text = '\n'.join(prompt_lines)
    if via_callback:
        await context.bot.send_message(update.effective_chat.id, text, reply_markup=markup)
    else:
        await update.message.reply_text(text, reply_markup=markup)
    return INPUT_CONTACT

# Расчет цены
def calculate_price(order_type_key, days_left, complexity_factor=1.0):
    if order_type_key not in PRICES:
        logger.error(f"Неизвестный тип: {order_type_key}")
        return 0
    base = PRICES[order_type_key]['base']
    price = int(base * complexity_factor)
    if current_pricing_mode == 'hard':
        if days_left < 7:
            price *= 1.3
        elif days_left < 15:
            price *= 1.15
    else:
        if days_left < 3:
            price *= 1.3
        elif days_left < 7:
            price *= 1.15
    return int(price)

# Обработчик ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")
    if ADMIN_CHAT_ID:
        await context.bot.send_message(ADMIN_CHAT_ID, f"Ошибка: {context.error}")

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    log_user_action(user.id, user.username, "/start")
    args = update.message.text.split()
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={user.id}"
    context.user_data['ref_link'] = ref_link
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if referrer_id != user.id:
            REFERALS.setdefault(str(referrer_id), []).append(user.id)
            save_json(REFERRALS_FILE, REFERALS)
            await context.bot.send_message(referrer_id, f"🎉 Новый реферал: {user.first_name}")
    welcome = (
        f"👋 Добро пожаловать, {user.first_name}! Работаем со всеми учебными работами, "
        "кроме технических дисциплин с чертежами. Уже 5000+ клиентов и более 6 лет опыта! 10% скидка на первый заказ 🔥\n"
        f"Поделитесь ссылкой для бонусов: {ref_link}\n"
        "Это ваша реферальная ссылка: если по ней оформляют заказ, вы получаете бонусы!"
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
        [InlineKeyboardButton("📞 Администратор", url=ADMIN_CONTACT)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        query = update.callback_query
        await answer_callback(query)
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
    await answer_callback(query)
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

# Выбор типа заказа
async def select_order_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback(query)
    data = query.data if query else None
    user = update.effective_user
    log_user_action(user.id, user.username, "Выбор типа заказа")
    if data and data.startswith('type_'):
        return await view_order_details(update, context)
    if data == 'back_to_main':
        return await main_menu(update, context)
    text = "Выберите тип работы (добавьте несколько в корзину для скидки!):"
    keyboard = [[InlineKeyboardButton(f"{val['icon']} {val['name']}", callback_data=f'type_{key}')] for key, val in ORDER_TYPES.items()]
    keyboard.append([InlineKeyboardButton("⬅️ Меню", callback_data='back_to_main')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    if query:
        try:
            await query.edit_message_text(text, reply_markup=reply_markup)
        except TelegramError as e:
            if "message is not modified" in str(e).lower():
                pass
            else:
                raise
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)
    return SELECT_ORDER_TYPE

# Подробности о типе заказа
async def view_order_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback(query)
    data = query.data
    if data.startswith('order_'):
        key = data[6:]
        context.user_data['current_order_type'] = key
        await query.edit_message_text("Отлично! Теперь введите тему ниже.")
        return await ask_for_topic(update, context, via_callback=True)
    elif data == 'select_order_type':
        return await select_order_type(update, context)
    elif data.startswith('type_'):
        key = data[5:]
        if key not in ORDER_TYPES:
            await query.edit_message_text("Ошибка: неизвестный тип.")
            return SELECT_ORDER_TYPE
        val = ORDER_TYPES[key]
        text = f"{val['icon']} *{val['name']}*\n\n{val['description']}\n{val['details']}\nПримеры: {', '.join(val['examples'])}\n\nЗаказать? (Добавьте презентацию/речь для полного пакета!)"
        keyboard = [
            [InlineKeyboardButton("✅ Заказать", callback_data=f'order_{key}')],
            [InlineKeyboardButton("Назад", callback_data='select_order_type')]
        ]
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        return VIEW_ORDER_DETAILS

# Ввод темы
async def input_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.strip()
    if message_text == BACK_BUTTON_TEXT:
        await update.message.reply_text("Возвращаемся к выбору типа.", reply_markup=ReplyKeyboardRemove())
        return await select_order_type(update, context)
    if not context.user_data.get('current_order_type'):
        await update.message.reply_text("Пожалуйста, выберите тип работы сначала.", reply_markup=ReplyKeyboardRemove())
        return await select_order_type(update, context)
    context.user_data['topic'] = message_text
    user = update.effective_user
    log_user_action(user.id, user.username, f"Тема: {message_text}")
    await update.message.reply_text("Тема сохранена.", reply_markup=ReplyKeyboardRemove())
    return await show_deadline_options(update, context)

# Выбор срока
async def select_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback(query)
    data = query.data
    if data.startswith('deadline_'):
        days = int(data[9:])
        context.user_data['days_left'] = days
        await query.edit_message_text(f"Срок {days} дней выбран. Уточните требования.")
        return await prompt_requirements_input(update, context, via_callback=True)
    elif data == 'back_topic':
        await query.edit_message_text("Возвращаемся к вводу темы.")
        return await ask_for_topic(update, context, via_callback=True)
    elif data.startswith('type_'):
        return await view_order_details(update, context)
    return SELECT_DEADLINE

# Ввод требований
async def input_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.strip()
    if message_text == BACK_BUTTON_TEXT:
        await update.message.reply_text("Возвращаемся к выбору срока.", reply_markup=ReplyKeyboardRemove())
        return await show_deadline_options(update, context)
    context.user_data['requirements'] = message_text
    await update.message.reply_text("Требования сохранены.", reply_markup=ReplyKeyboardRemove())
    return await prompt_file_upload(update, context)

async def skip_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['requirements'] = 'Нет'
    await update.message.reply_text("Требования пропущены.", reply_markup=ReplyKeyboardRemove())
    return await prompt_file_upload(update, context)

async def prompt_file_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    via_callback: bool = False,
    from_back: bool = False
):
    if not from_back or 'current_files' not in context.user_data:
        context.user_data['current_files'] = context.user_data.get('current_files', [])
    if not from_back:
        context.user_data.pop('current_contact', None)
    files_count = len(context.user_data.get('current_files', []))
    text_lines = [
        "Прикрепите файлы для заказа (если они есть). Отправьте все документы подряд.",
        "Когда закончите, нажмите /done. Если файлов нет, нажмите /skip.",
        "Чтобы вернуться и изменить требования, используйте команду /back."
    ]
    if files_count:
        text_lines.insert(1, f"Уже загружено файлов: {files_count}.")
    text = '\n'.join(text_lines)
    if via_callback and update.callback_query:
        query = update.callback_query
        await answer_callback(query)
        await query.edit_message_text(text)
    elif update.message:
        await update.message.reply_text(text)
    else:
        await context.bot.send_message(update.effective_chat.id, text)
    return UPLOAD_FILES

async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    files = context.user_data.setdefault('current_files', [])
    files.append({
        'type': 'document',
        'file_id': document.file_id,
        'file_name': document.file_name or 'Файл без названия',
        'mime_type': document.mime_type,
    })
    await update.message.reply_text(
        f"Файл {document.file_name or 'без названия'} сохранен. Отправьте следующий или нажмите /done."
    )
    return UPLOAD_FILES

async def handle_photo_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    files = context.user_data.setdefault('current_files', [])
    files.append({
        'type': 'photo',
        'file_id': photo.file_id,
        'file_unique_id': photo.file_unique_id,
        'caption': update.message.caption,
    })
    await update.message.reply_text("Фото сохранено. Отправьте следующее или нажмите /done.")
    return UPLOAD_FILES

async def files_text_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.strip()
    if message_text == BACK_BUTTON_TEXT:
        return await back_from_files(update, context)
    await update.message.reply_text(
        "Пожалуйста, прикрепите файл или используйте /done, когда закончите. Если файлов нет, нажмите /skip."
    )
    return UPLOAD_FILES

async def skip_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['current_files'] = []
    await update.message.reply_text("Пропускаем прикрепление файлов.")
    return await request_contact(update, context)

async def finish_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('current_files'):
        await update.message.reply_text("Файлы сохранены.")
    else:
        await update.message.reply_text("Хорошо, продолжаем без файлов.")
    return await request_contact(update, context)

async def request_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await answer_callback(query)
        return await prompt_contact_input(update, context, via_callback=True)
    return await prompt_contact_input(update, context)

async def input_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.text.strip()
    if contact == BACK_BUTTON_TEXT:
        await update.message.reply_text("Возвращаемся к файлам.", reply_markup=ReplyKeyboardRemove())
        return await prompt_file_upload(update, context, from_back=True)
    if not contact:
        await update.message.reply_text("Контакт обязателен. Пожалуйста, укажите, куда менеджеру написать.")
        return INPUT_CONTACT
    context.user_data['current_contact'] = contact
    context.user_data['last_contact'] = contact
    await update.message.reply_text("Контакт сохранен.", reply_markup=ReplyKeyboardRemove())
    return await add_upsell(update, context)

async def back_from_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Возвращаемся к выбору типа.", reply_markup=ReplyKeyboardRemove())
    return await select_order_type(update, context)

async def back_from_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Возвращаемся к выбору срока.", reply_markup=ReplyKeyboardRemove())
    return await show_deadline_options(update, context)

async def back_from_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Возвращаемся к требованиям.")
    return await prompt_requirements_input(update, context)

async def back_from_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Возвращаемся к файлам.", reply_markup=ReplyKeyboardRemove())
    return await prompt_file_upload(update, context, from_back=True)

# Добавление допуслуг
async def add_upsell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Добавить услуги? (Клиенты, добавляющие, получают 5% скидки на следующий заказ!)\n"
        f"Чтобы вернуться и изменить контакт, используйте кнопку \"{BACK_BUTTON_TEXT}\"."
    )
    prez_price = UPSELL_PRICES.get('prez', 0)
    speech_price = UPSELL_PRICES.get('speech', 0)
    keyboard = [
        [InlineKeyboardButton(f"Презентация (+{prez_price}₽)", callback_data='add_prez')],
        [InlineKeyboardButton(f"Речь (+{speech_price}₽)", callback_data='add_speech')],
        [InlineKeyboardButton(BACK_BUTTON_TEXT, callback_data='back_contact')],
        [InlineKeyboardButton("Без допов", callback_data='no_upsell')]
    ]
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        query = update.callback_query
        await answer_callback(query)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_UPSSELL

# Обработчик допуслуг
async def upsell_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback(query)
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
    elif data == 'back_contact':
        await query.edit_message_text("Возвращаемся к контактам.")
        return await request_contact(update, context)
    elif data == 'no_upsell':
        return await process_order(update, context)
    text = "Добавить еще? (Полный пакет экономит время!)" if added else "Уже добавлено. Добавить еще?"
    prez_price = UPSELL_PRICES.get('prez', 0)
    speech_price = UPSELL_PRICES.get('speech', 0)
    keyboard = [
        [InlineKeyboardButton(f"Презентация (+{prez_price}₽)", callback_data='add_prez')],
        [InlineKeyboardButton(f"Речь (+{speech_price}₽)", callback_data='add_speech')],
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
    days_left = context.user_data.get('days_left', 14)
    requirements = context.user_data.get('requirements', 'Нет')
    upsells = list(context.user_data.get('upsells', set()))
    attachments = list(context.user_data.get('current_files', []))
    contact = context.user_data.get('current_contact') or context.user_data.get('last_contact', '')
    price = calculate_price(type_key, days_left)
    extra = sum(UPSELL_PRICES.get(code, 0) for code in upsells)
    price += extra
    order = {
        'type': type_key,
        'topic': topic,
        'deadline_days': days_left,
        'requirements': requirements,
        'upsells': upsells,
        'price': price,
        'status': 'новый',
        'attachments': attachments,
        'contact': contact,
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    ensure_order_payment_fields(order)
    context.user_data.setdefault('cart', []).append(order)
    context.user_data.pop('upsells', None)
    context.user_data.pop('requirements', None)
    context.user_data.pop('days_left', None)
    context.user_data.pop('topic', None)
    context.user_data.pop('current_order_type', None)
    context.user_data.pop('current_files', None)
    context.user_data.pop('current_contact', None)
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
    await answer_callback(query)
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
    text = "Ваша корзина (подтвердите для специального бонуса!):\n"
    total = 0
    for i, order in enumerate(cart, 1):
        order_name = ORDER_TYPES.get(order['type'], {}).get('name', 'Неизвестно')
        contact = order.get('contact') or context.user_data.get('last_contact', 'Контакт не указан')
        attachments_info = ''
        if order.get('attachments'):
            attachments_info = f" (файлов: {len(order['attachments'])})"
        text += (
            f"{i}. {order_name} - {order['topic']} - {order['price']} ₽{attachments_info}\n"
            f"   Контакт: {contact}\n"
        )
        total += order['price']
    if len(cart) > 1:
        discount = total * 0.1
        total -= discount
        text += f"Скидка за несколько заказов: -{discount} ₽\n"
    text += f"Итого: {total} ₽\nПодтвердить?"
    keyboard = [
        [InlineKeyboardButton("Подтвердить", callback_data='place_order')],
        [InlineKeyboardButton("Отменить", callback_data='cancel_cart')]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM_CART

async def confirm_cart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback(query)
    data = query.data
    if data == 'place_order':
        user = update.effective_user
        user_id = str(user.id)
        cart_orders = context.user_data.get('cart', [])
        if not cart_orders:
            await query.edit_message_text("Корзина пуста.")
            return await main_menu(update, context)
        user_orders = ORDERS.setdefault(user_id, [])
        order_id = len(user_orders) + 1
        for order in cart_orders:
            order['order_id'] = order_id
            user_orders.append(order)
            order_id += 1
        save_json(ORDERS_FILE, ORDERS)
        text = (
            f"Заказ оформлен! С вами свяжется [администратор]({ADMIN_CONTACT}) в ближайшее время. "
            "Проверьте профиль для статуса."
        )
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
        if ADMIN_CHAT_ID:
            user_link = f"https://t.me/{user.username}" if user.username else f"tg://user?id={user.id}"
            href_user_link = escape(user_link, quote=True)
            user_name = escape(user.full_name or user.username or user_id)
            summary_lines = [
                "🆕 <b>Новый заказ</b>",
                f"Пользователь: <a href=\"{href_user_link}\">{user_name}</a> (ID: {user.id})",
                f"Всего позиций: {len(cart_orders)}"
            ]
            for order in cart_orders:
                order_name = ORDER_TYPES.get(order['type'], {}).get('name', order['type'])
                topic = escape(order.get('topic', 'Без темы'))
                requirements = escape(order.get('requirements', 'Нет'))
                contact_html = format_contact_link(order.get('contact'))
                upsells_list = ', '.join(UPSELL_TITLES.get(code, code) for code in order.get('upsells', []))
                upsells_display = escape(upsells_list) if upsells_list else 'Нет'
                attachments_count = len(order.get('attachments') or [])
                order_summary = [
                    f"<b>#{order['order_id']}</b> {escape(order_name)} — {topic}",
                    f"Срок: {order.get('deadline_days', 'N/A')} дней | Цена: {order.get('price', 0)} ₽",
                    f"Контакт: {contact_html}",
                    f"Требования: {requirements if requirements else 'Нет'}",
                    f"Допы: {upsells_display}",
                ]
                if attachments_count:
                    order_summary.append(f"Файлы: {attachments_count} (отправлены отдельно)")
                summary_lines.append('<br>'.join(order_summary))
            admin_message = '<br><br>'.join(summary_lines)
            await context.bot.send_message(
                ADMIN_CHAT_ID,
                admin_message,
                parse_mode=ParseMode.HTML
            )
            for order in cart_orders:
                attachments = order.get('attachments') or []
                if not attachments:
                    continue
                order_name = ORDER_TYPES.get(order['type'], {}).get('name', order['type'])
                for idx, file_data in enumerate(attachments, 1):
                    caption_parts = [
                        f"<b>Заказ #{order['order_id']}</b> — {escape(order_name)}",
                        f"Контакт: {format_contact_link(order.get('contact'))}"
                    ]
                    if file_data.get('file_name'):
                        caption_parts.append(f"Файл: {escape(file_data['file_name'])}")
                    caption_parts.append(f"#{idx} из {len(attachments)}")
                    caption = '<br>'.join(caption_parts)
                    if file_data.get('type') == 'photo':
                        await context.bot.send_photo(
                            ADMIN_CHAT_ID,
                            photo=file_data['file_id'],
                            caption=caption,
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        await context.bot.send_document(
                            ADMIN_CHAT_ID,
                            document=file_data['file_id'],
                            caption=caption,
                            parse_mode=ParseMode.HTML
                        )
        context.user_data.pop('cart', None)
        return await main_menu(update, context, "Спасибо! Хотите заказать еще?")
    elif data == 'cancel_cart':
        context.user_data.pop('cart', None)
        return await main_menu(update, context, "Корзина отменена. Посмотрите еще?")
    return CONFIRM_CART

# Показ прайс-листа
async def show_price_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback(query)
    data = query.data
    if data.startswith('price_detail_'):
        key = data[13:]
        val = ORDER_TYPES.get(key, {})
        if not val:
            await query.edit_message_text("Ошибка: неизвестный тип.")
            return SHOW_PRICE_LIST
        prices = PRICES.get(key, {'min': 0, 'max': 0})
        text = f"{val.get('icon', '')} *{val.get('name', '')}*\n\n{val.get('description', '')}\n{val.get('details', '')}\nПримеры: {', '.join(val.get('examples', []))}\nЦена: {prices['min']}-{prices['max']} ₽\n\nЗакажите со скидкой!"
        keyboard = [
            [InlineKeyboardButton("Рассчитать", callback_data='price_calculator')],
            [InlineKeyboardButton("Заказать", callback_data=f'type_{key}')],
            [InlineKeyboardButton("Назад", callback_data='price_list')]
        ]
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        return SHOW_PRICE_LIST
    elif data == 'price_calculator':
        return await price_calculator(update, context)
    elif data == 'back_to_main':
        return await main_menu(update, context)
    user = update.effective_user
    log_user_action(user.id, user.username, "Прайс-лист")
    text = "💲 Прайс-лист (10% скидка сегодня! 🔥):\n\n"
    for key, val in ORDER_TYPES.items():
        prices = PRICES.get(key, {'base': 0})
        text += f"{val['icon']} *{val['name']}* — от {prices['base']} ₽\n"
    keyboard = [[InlineKeyboardButton(f"Подробности {val['name']}", callback_data=f'price_detail_{key}')] for key, val in ORDER_TYPES.items()]
    keyboard.append([InlineKeyboardButton("🧮 Рассчитать цену", callback_data='price_calculator')])
    keyboard.append([InlineKeyboardButton("⬅️ Меню", callback_data='back_to_main')])
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    return SHOW_PRICE_LIST

# Калькулятор цен
async def price_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback(query)
    data = query.data
    if data.startswith('calc_type_'):
        key = data[10:]
        context.user_data['calc_type'] = key
        text = f"Тип: {ORDER_TYPES.get(key, {}).get('name', 'Неизвестно')}\nВыберите срок (дольше = дешевле):"
        keyboard = [
            [InlineKeyboardButton("3 дня (+30%)", callback_data='calc_dead_3')],
            [InlineKeyboardButton("7 дней (+15%)", callback_data='calc_dead_7'), InlineKeyboardButton("14 дней (базовая)", callback_data='calc_dead_14')],
            [InlineKeyboardButton("30 дней (скидка!)", callback_data='calc_dead_30')],
            [InlineKeyboardButton("Назад", callback_data='price_calculator')]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
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
    await answer_callback(query)
    data = query.data
    if data.startswith('calc_dead_'):
        days = int(data[10:])
        context.user_data['calc_days'] = days
        text = f"Срок: {days} дней\nВыберите сложность:"
        keyboard = [
            [InlineKeyboardButton("Простая (базовая)", callback_data='calc_comp_1.0')],
            [InlineKeyboardButton("Средняя (+10%)", callback_data='calc_comp_1.1'), InlineKeyboardButton("Сложная (+30%)", callback_data='calc_comp_1.3')],
            [InlineKeyboardButton("Назад", callback_data=f'calc_type_{context.user_data["calc_type"]}')]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return SELECT_CALC_COMPLEXITY
    return SELECT_CALC_DEADLINE

async def calc_select_complexity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback(query)
    data = query.data
    if data.startswith('calc_comp_'):
        comp = float(data[10:])
        key = context.user_data.get('calc_type')
        days = context.user_data.get('calc_days', 14)
        price = calculate_price(key, days, comp)
        name = ORDER_TYPES.get(key, {}).get('name', 'Неизвестно')
        text = f"Расчет: {name}\nСрок: {days} дней\nСложность: {int((comp-1)*100)}%\nЦена: {price} ₽ (Скидка сегодня!)\n\nЗаказать?"
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
    await answer_callback(query)
    data = query.data
    user = update.effective_user
    user_id = str(user.id)
    if data == 'my_orders':
        return await show_orders(update, context)
    elif data == 'leave_feedback':
        await query.edit_message_text("Введите ваш отзыв:")
        return INPUT_FEEDBACK
    elif data == 'back_to_main':
        return await main_menu(update, context)
    log_user_action(user.id, user.username, "Профиль")
    orders_count = len(ORDERS.get(user_id, []))
    feedbacks_count = len(FEEDBACKS.get(user_id, []))
    refs_count = len(REFERALS.get(user_id, []))
    ref_link = context.user_data.get('ref_link', 'Нет ссылки')
    bonus_balance = get_user_bonus_balance(user_id)
    pending_bonus = get_pending_bonus(user_id)
    profile_lines = [
        f"👤 Профиль {user.first_name}",
        "",
        f"Заказов: {orders_count}",
        f"Отзывов: {feedbacks_count}",
        f"Рефералов: {refs_count}",
        f"Бонусы: {bonus_balance} ₽"
    ]
    if pending_bonus:
        profile_lines.append(f"Ожидает зачисления после подтверждения оплаты: {pending_bonus} ₽")
    profile_lines.append(f"Реф. ссылка: {ref_link}")
    profile_lines.append("")
    profile_lines.append("Приглашайте друзей за бонусы!")
    text = '\n'.join(profile_lines)
    keyboard = [
        [InlineKeyboardButton("📋 Мои заказы", callback_data='my_orders')],
        [InlineKeyboardButton("⭐ Оставить отзыв", callback_data='leave_feedback')],
        [InlineKeyboardButton("⬅️ Меню", callback_data='back_to_main')]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return PROFILE_MENU

# Показ заказов
async def show_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback(query)
    data = query.data
    if data == 'profile':
        return await show_profile(update, context)
    user_id = str(update.effective_user.id)
    user_orders = ORDERS.get(user_id, [])
    if not user_orders:
        text = "Пока нет заказов. Сделайте заказ сейчас!"
    else:
        text = "Ваши заказы:\n"
        changed = False
        for order in user_orders:
            name = ORDER_TYPES.get(order.get('type'), {}).get('name', 'Неизвестно')
            if ensure_order_payment_fields(order):
                changed = True
            payment_state = order.get('payment_state', 'не оплачен')
            text += f"#{order.get('order_id', 'N/A')}: {name} - {order.get('status', 'новый')} | Оплата: {payment_state}\n"
        if changed:
            save_json(ORDERS_FILE, ORDERS)
    keyboard = [[InlineKeyboardButton("Назад", callback_data='profile')]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return SHOW_ORDERS

# Ввод отзыва
async def input_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    feedback = update.message.text
    FEEDBACKS.setdefault(user_id, []).append(feedback)
    save_json(FEEDBACKS_FILE, FEEDBACKS)
    await update.message.reply_text("Спасибо за отзыв! Добавлены бонусные баллы.")
    return await show_profile(update, context)

# Показ FAQ
async def show_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback(query)
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
        [
            InlineKeyboardButton("📊 Дашборд", callback_data='admin_dashboard'),
            InlineKeyboardButton("📋 Заказы", callback_data='admin_orders')
        ],
        [
            InlineKeyboardButton("💳 Оплаты", callback_data='admin_payments'),
            InlineKeyboardButton("🎯 Пользователи", callback_data='admin_users')
        ],
        [
            InlineKeyboardButton("💰 Цены и бонусы", callback_data='admin_pricing'),
            InlineKeyboardButton("⚙️ Настройки", callback_data='admin_settings')
        ],
        [
            InlineKeyboardButton("📨 Уведомления", callback_data='admin_notifications'),
            InlineKeyboardButton("📤 Экспорт", callback_data='admin_export')
        ],
        [InlineKeyboardButton("⬅️ В меню бота", callback_data='back_to_main')]
    ]
    text = build_admin_dashboard_text()
    if update.callback_query:
        query = update.callback_query
        await answer_callback(query)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return ADMIN_MENU

# Админ старт
async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("Доступ запрещен!")
        return
    user = update.effective_user
    log_user_action(user.id, user.username, "Админ-панель")
    return await show_admin_menu(update, context)

def build_admin_order_keyboard(uid: str, order_id_str: str, order: dict) -> InlineKeyboardMarkup:
    uid_str = str(uid)
    buttons = [
        [
            InlineKeyboardButton("Статус", callback_data=f'ao_status|{uid_str}|{order_id_str}'),
            InlineKeyboardButton("Цена", callback_data=f'ao_price|{uid_str}|{order_id_str}')
        ],
        [
            InlineKeyboardButton("Срок", callback_data=f'ao_deadline|{uid_str}|{order_id_str}'),
            InlineKeyboardButton("Заметка", callback_data=f'ao_note|{uid_str}|{order_id_str}')
        ],
        [
            InlineKeyboardButton("Назначить", callback_data=f'ao_assign|{uid_str}|{order_id_str}'),
            InlineKeyboardButton("Теги", callback_data=f'ao_tags|{uid_str}|{order_id_str}')
        ],
        [
            InlineKeyboardButton("Платежи", callback_data=f'ao_payments|{uid_str}|{order_id_str}'),
            InlineKeyboardButton("Счета", callback_data=f'ao_invoice|{uid_str}|{order_id_str}')
        ],
    ]
    if not order.get('prepayment_confirmed'):
        buttons.append([
            InlineKeyboardButton("Подтвердить предоплату", callback_data=f'admin_confirm_prepay|{uid_str}|{order_id_str}')
        ])
    if not order.get('full_payment_confirmed'):
        buttons.append([
            InlineKeyboardButton("Подтвердить оплату", callback_data=f'admin_confirm_full|{uid_str}|{order_id_str}')
        ])
    buttons.append([InlineKeyboardButton("Отменить заказ", callback_data=f'admin_cancel|{uid_str}|{order_id_str}')])
    buttons.append([InlineKeyboardButton("Удалить заказ", callback_data=f'admin_delete|{uid_str}|{order_id_str}')])
    buttons.append([InlineKeyboardButton("👤 Открыть профиль", url=f"tg://user?id={uid_str}")])
    buttons.append([InlineKeyboardButton("⬅️ К списку", callback_data='admin_orders')])
    return InlineKeyboardMarkup(buttons)

# Обработчик админ-меню
async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    shared_routes = {
        'back_to_main': main_menu,
        'make_order': select_order_type,
        'price_list': show_price_list,
        'price_calculator': price_calculator,
        'profile': show_profile,
        'faq': show_faq,
    }
    if data in shared_routes:
        context.user_data.pop('admin_state', None)
        return await shared_routes[data](update, context)
    await answer_callback(query)
    if data in ('admin_menu', 'admin_dashboard'):
        context.user_data.pop('admin_state', None)
        return await show_admin_menu(update, context)
    if await process_admin_order_action(update, context, data):
        return ADMIN_MENU
    if await process_admin_user_action(update, context, data):
        return ADMIN_MENU
    if await process_admin_pricing_action(update, context, data):
        return ADMIN_MENU
    if await process_admin_settings_action(update, context, data):
        return ADMIN_MENU
    if await process_admin_notifications_action(update, context, data):
        return ADMIN_MENU
    if await process_admin_export_action(update, context, data):
        return ADMIN_MENU
    await query.edit_message_text(
        'Неизвестная команда. Возвращаюсь в админ-меню.',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('⬅️ Админ-меню', callback_data='admin_menu')]])
    )
    return ADMIN_MENU

# Обработчик сообщений админа
async def admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('admin_state')
    if not state:
        await update.message.reply_text('Используйте кнопки админ-панели.')
        return ADMIN_MENU
    action = state.get('action')
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    global BONUS_PERCENT, current_pricing_mode, UPSELL_PRICES, ADMIN_CONTACT
    try:
        if action == 'search_orders':
            filter_info = {'type': 'search', 'value': text, 'title': f'📋 Поиск: {text}', 'back': 'admin_orders'}
            context.user_data['admin_orders_filter'] = filter_info
            context.user_data.pop('admin_state', None)
            extra = build_orders_extra_buttons(filter_info)
            await admin_show_order_list(update, context, filter_info['title'], compile_order_filter(filter_info), back_callback='admin_orders', extra_buttons=extra)
            return ADMIN_MENU
        if action == 'custom_status':
            uid = state['uid']
            order_id = state['order_id']
            order = find_order(uid, order_id)
            if not order:
                await update.message.reply_text('Заказ не найден.')
                return ADMIN_MENU
            order['status'] = text
            add_status_history(order, text, get_admin_display_name(update))
            save_json(ORDERS_FILE, ORDERS)
            context.user_data.pop('admin_state', None)
            detail = build_order_details(uid, order)
            keyboard = build_admin_order_keyboard(uid, order_id, order)
            await context.bot.send_message(chat_id, f'✅ Статус обновлен.<br><br>{detail}', parse_mode=ParseMode.HTML, reply_markup=keyboard)
            return ADMIN_MENU
        if action == 'set_price':
            uid = state['uid']
            order_id = state['order_id']
            value = int(text)
            order = find_order(uid, order_id)
            if not order:
                await update.message.reply_text('Заказ не найден.')
                return ADMIN_MENU
            order['price'] = value
            order['bonus_total'] = int(value * BONUS_PERCENT)
            add_price_history(order, value, 'manual_update', get_admin_display_name(update))
            save_json(ORDERS_FILE, ORDERS)
            context.user_data.pop('admin_state', None)
            detail = build_order_details(uid, order)
            keyboard = build_admin_order_keyboard(uid, order_id, order)
            await context.bot.send_message(chat_id, f'💰 Стоимость обновлена.<br><br>{detail}', parse_mode=ParseMode.HTML, reply_markup=keyboard)
            return ADMIN_MENU
        if action == 'set_deadline':
            uid = state['uid']
            order_id = state['order_id']
            days = int(text)
            order = find_order(uid, order_id)
            if not order:
                await update.message.reply_text('Заказ не найден.')
                return ADMIN_MENU
            order['deadline_days'] = days
            add_status_history(order, f'обновлен срок {days} дн', get_admin_display_name(update))
            save_json(ORDERS_FILE, ORDERS)
            context.user_data.pop('admin_state', None)
            detail = build_order_details(uid, order)
            keyboard = build_admin_order_keyboard(uid, order_id, order)
            await context.bot.send_message(chat_id, f'⏱ Срок обновлен.<br><br>{detail}', parse_mode=ParseMode.HTML, reply_markup=keyboard)
            return ADMIN_MENU
        if action == 'add_note':
            uid = state['uid']
            order_id = state['order_id']
            order = find_order(uid, order_id)
            if not order:
                await update.message.reply_text('Заказ не найден.')
                return ADMIN_MENU
            add_manager_note(order, text, get_admin_display_name(update))
            save_json(ORDERS_FILE, ORDERS)
            context.user_data.pop('admin_state', None)
            detail = build_order_details(uid, order)
            keyboard = build_admin_order_keyboard(uid, order_id, order)
            await context.bot.send_message(chat_id, f'📝 Заметка сохранена.<br><br>{detail}', parse_mode=ParseMode.HTML, reply_markup=keyboard)
            return ADMIN_MENU
        if action == 'assign_manager':
            uid = state['uid']
            order_id = state['order_id']
            order = find_order(uid, order_id)
            if not order:
                await update.message.reply_text('Заказ не найден.')
                return ADMIN_MENU
            order['assigned_manager'] = text
            save_json(ORDERS_FILE, ORDERS)
            context.user_data.pop('admin_state', None)
            detail = build_order_details(uid, order)
            keyboard = build_admin_order_keyboard(uid, order_id, order)
            await context.bot.send_message(chat_id, f'👔 Менеджер назначен.<br><br>{detail}', parse_mode=ParseMode.HTML, reply_markup=keyboard)
            return ADMIN_MENU
        if action == 'add_tag':
            uid = state['uid']
            order_id = state['order_id']
            order = find_order(uid, order_id)
            if not order:
                await update.message.reply_text('Заказ не найден.')
                return ADMIN_MENU
            tags = order.setdefault('admin_tags', [])
            if text not in tags:
                tags.append(text)
            save_json(ORDERS_FILE, ORDERS)
            context.user_data.pop('admin_state', None)
            detail = build_order_details(uid, order)
            keyboard = build_admin_order_keyboard(uid, order_id, order)
            await context.bot.send_message(chat_id, f'🏷 Тег добавлен.<br><br>{detail}', parse_mode=ParseMode.HTML, reply_markup=keyboard)
            return ADMIN_MENU
        if action == 'set_payment_amount':
            uid = state['uid']
            order_id = state['order_id']
            stage = state['stage']
            amount = int(text)
            order = find_order(uid, order_id)
            if not order:
                await update.message.reply_text('Заказ не найден.')
                return ADMIN_MENU
            entry = {
                'type': f'{stage}_amount_manual',
                'amount': amount,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'admin': get_admin_display_name(update)
            }
            order.setdefault('payment_history', []).append(entry)
            if stage == 'prepay':
                order['prepayment_amount'] = amount
            else:
                order['full_payment_amount'] = amount
            save_json(ORDERS_FILE, ORDERS)
            context.user_data.pop('admin_state', None)
            detail = build_order_details(uid, order)
            keyboard = build_admin_order_keyboard(uid, order_id, order)
            await context.bot.send_message(chat_id, f'💳 Сумма обновлена.<br><br>{detail}', parse_mode=ParseMode.HTML, reply_markup=keyboard)
            return ADMIN_MENU
        if action == 'add_invoice':
            uid = state['uid']
            order_id = state['order_id']
            order = find_order(uid, order_id)
            if not order:
                await update.message.reply_text('Заказ не найден.')
                return ADMIN_MENU
            order.setdefault('invoice_links', []).append(text)
            save_json(ORDERS_FILE, ORDERS)
            context.user_data.pop('admin_state', None)
            detail = build_order_details(uid, order)
            keyboard = build_admin_order_keyboard(uid, order_id, order)
            await context.bot.send_message(chat_id, f'📨 Ссылка добавлена.<br><br>{detail}', parse_mode=ParseMode.HTML, reply_markup=keyboard)
            return ADMIN_MENU
        if action == 'search_user':
            matches = []
            lower = text.lower()
            for uid in ORDERS.keys():
                if lower in uid.lower():
                    matches.append(uid)
                    continue
                logs = USER_LOGS.get(uid, [])
                if logs and logs[-1].get('username') and lower in logs[-1]['username'].lower():
                    matches.append(uid)
            if matches:
                keyboard = [
                    [InlineKeyboardButton(match_uid, callback_data=f'admin_user|{match_uid}')]
                    for match_uid in matches[:20]
                ]
                keyboard.append([InlineKeyboardButton('⬅️ Назад', callback_data='admin_users')])
                await update.message.reply_text('Совпадения найдены:', reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await update.message.reply_text('Совпадений не найдено.')
            context.user_data.pop('admin_state', None)
            return ADMIN_MENU
        if action == 'adjust_bonus':
            uid = state['uid']
            amount = int(text)
            bonuses = BONUSES.setdefault(uid, {'balance': 0, 'history': []})
            bonuses['balance'] += amount
            bonuses.setdefault('history', []).append({
                'order_id': None,
                'amount': amount,
                'stage': 'manual',
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'admin': get_admin_display_name(update)
            })
            save_json(BONUSES_FILE, BONUSES)
            context.user_data.pop('admin_state', None)
            await update.message.reply_text(f'Баланс пользователя {uid}: {bonuses["balance"]} ₽')
            return ADMIN_MENU
        if action == 'direct_message_single':
            uid = state['uid']
            context.user_data.pop('admin_state', None)
            try:
                await context.bot.send_message(int(uid), text)
                await update.message.reply_text('Сообщение отправлено.')
            except TelegramError as exc:
                await update.message.reply_text(f'Не удалось отправить: {exc}')
            return ADMIN_MENU
        if action == 'broadcast_all':
            context.user_data.pop('admin_state', None)
            sent = 0
            for uid in set(ORDERS.keys()):
                try:
                    await context.bot.send_message(int(uid), text)
                    sent += 1
                except TelegramError as exc:
                    logger.warning('Не удалось отправить рассылку %s: %s', uid, exc)
            await update.message.reply_text(f'Рассылка завершена. Отправлено {sent} сообщений.')
            return ADMIN_MENU
        if action == 'broadcast_pending':
            context.user_data.pop('admin_state', None)
            recipients = {uid for uid, order in iter_all_orders() if not order.get('full_payment_confirmed')}
            sent = 0
            for uid in recipients:
                try:
                    await context.bot.send_message(int(uid), text)
                    sent += 1
                except TelegramError as exc:
                    logger.warning('Не удалось отправить напоминание %s: %s', uid, exc)
            await update.message.reply_text(f'Отправлено напоминаний: {sent}.')
            return ADMIN_MENU
        if action == 'direct_message_manual':
            context.user_data.pop('admin_state', None)
            if '|' not in text:
                await update.message.reply_text('Используйте формат user_id|сообщение.')
                return ADMIN_MENU
            uid, message = text.split('|', 1)
            try:
                await context.bot.send_message(int(uid.strip()), message.strip())
                await update.message.reply_text('Сообщение отправлено.')
            except TelegramError as exc:
                await update.message.reply_text(f'Не удалось отправить: {exc}')
            return ADMIN_MENU
        if action == 'set_pricing_mode':
            mode = text.lower().strip()
            if mode not in ('hard', 'light'):
                await update.message.reply_text('Укажите hard или light.')
                return ADMIN_MENU
            current_pricing_mode = mode
            SETTINGS['pricing_mode'] = mode
            save_settings()
            context.user_data.pop('admin_state', None)
            await update.message.reply_text(f'Режим установлен: {mode}')
            return ADMIN_MENU
        if action == 'set_bonus_percent':
            value = float(text.replace(',', '.')) / 100
            BONUS_PERCENT = value
            SETTINGS['bonus_percent'] = value
            save_settings()
            context.user_data.pop('admin_state', None)
            await update.message.reply_text(f'Бонусный процент: {int(value * 100)}%')
            return ADMIN_MENU
        if action == 'set_upsell_prices':
            parts = text.replace(' ', '').split(',')
            prices = {}
            for part in parts:
                if '=' not in part:
                    continue
                key, value = part.split('=', 1)
                prices[key] = int(value)
            if not prices:
                await update.message.reply_text('Не удалось распознать цены.')
                return ADMIN_MENU
            UPSELL_PRICES.update(prices)
            SETTINGS['upsell_prices'] = UPSELL_PRICES
            save_settings()
            context.user_data.pop('admin_state', None)
            await update.message.reply_text('Цены допов обновлены.')
            return ADMIN_MENU
        if action == 'set_price_table':
            type_key = state['type_key']
            values = [int(part.strip()) for part in text.split(',')]
            if len(values) != 3:
                await update.message.reply_text('Введите три значения: базовая, мин, макс.')
                return ADMIN_MENU
            PRICES[type_key]['base'], PRICES[type_key]['min'], PRICES[type_key]['max'] = values
            save_json(PRICES_FILE, PRICES)
            context.user_data.pop('admin_state', None)
            await update.message.reply_text('Тариф обновлен.')
            return ADMIN_MENU
        if action == 'add_manager':
            SETTINGS.setdefault('managers', []).append(text)
            save_settings()
            context.user_data.pop('admin_state', None)
            await update.message.reply_text('Менеджер добавлен.')
            return ADMIN_MENU
        if action == 'add_status':
            SETTINGS.setdefault('status_options', []).append(text)
            save_settings()
            context.user_data.pop('admin_state', None)
            await update.message.reply_text('Статус добавлен.')
            return ADMIN_MENU
        if action == 'add_tag_setting':
            SETTINGS.setdefault('order_tags', []).append(text)
            save_settings()
            context.user_data.pop('admin_state', None)
            await update.message.reply_text('Тег добавлен.')
            return ADMIN_MENU
        if action == 'add_payment_channel':
            SETTINGS.setdefault('payment_channels', []).append(text)
            save_settings()
            context.user_data.pop('admin_state', None)
            await update.message.reply_text('Канал добавлен.')
            return ADMIN_MENU
        if action == 'set_admin_contact':
            ADMIN_CONTACT = text
            SETTINGS['admin_contact'] = text
            save_settings()
            context.user_data.pop('admin_state', None)
            await update.message.reply_text('Контакт администратора обновлен.')
            return ADMIN_MENU
        if action == 'set_followup_hours':
            hours = int(text)
            SETTINGS['auto_follow_up_hours'] = hours
            save_settings()
            context.user_data.pop('admin_state', None)
            await update.message.reply_text(f'Фоллоу-ап установлен на {hours} ч.')
            return ADMIN_MENU
    except ValueError:
        await update.message.reply_text('Не удалось обработать введенные данные.')
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
            INPUT_TOPIC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, input_topic),
                CommandHandler('back', back_from_topic)
            ],
            SELECT_DEADLINE: [CallbackQueryHandler(select_deadline)],
            INPUT_REQUIREMENTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, input_requirements),
                CommandHandler('skip', skip_requirements),
                CommandHandler('back', back_from_requirements)
            ],
            UPLOAD_FILES: [
                MessageHandler(filters.Document.ALL, handle_document_upload),
                MessageHandler(filters.PHOTO, handle_photo_upload),
                MessageHandler(filters.TEXT & ~filters.COMMAND, files_text_reminder),
                CommandHandler('skip', skip_files),
                CommandHandler('done', finish_files),
                CommandHandler('back', back_from_files)
            ],
            INPUT_CONTACT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, input_contact),
                CommandHandler('back', back_from_contact)
            ],
            ADD_UPSSELL: [CallbackQueryHandler(upsell_handler)],
            ADD_ANOTHER_ORDER: [CallbackQueryHandler(add_another_handler)],
            CONFIRM_CART: [CallbackQueryHandler(confirm_cart_handler)],
            ADMIN_MENU: [CallbackQueryHandler(admin_menu_handler), MessageHandler(filters.TEXT & ~filters.COMMAND, admin_message)],
            PROFILE_MENU: [CallbackQueryHandler(show_profile)],
            SHOW_PRICE_LIST: [CallbackQueryHandler(show_price_list)],
            PRICE_CALCULATOR: [CallbackQueryHandler(price_calculator)],
            SELECT_CALC_DEADLINE: [CallbackQueryHandler(calc_select_deadline)],
            SELECT_CALC_COMPLEXITY: [CallbackQueryHandler(calc_select_complexity)],
            SHOW_FAQ: [CallbackQueryHandler(show_faq)],
            FAQ_DETAILS: [CallbackQueryHandler(show_faq)],
            SHOW_ORDERS: [CallbackQueryHandler(show_orders)],
            INPUT_FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_feedback)],
        },
        fallbacks=[CommandHandler('start', start), CommandHandler('admin', admin_start)],
    )
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
