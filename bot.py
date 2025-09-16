import os
import sys
import logging
import json
import uuid
import html
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters, ConversationHandler
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
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
USER_LOGS_FILE = os.path.join(DATA_DIR, 'user_logs.json')
BONUSES_FILE = os.path.join(DATA_DIR, 'bonuses.json')
USERS_FILE = os.path.join(DATA_DIR, 'users.json')

# Функции загрузки/сохранения с обработкой ошибок
def load_json(file_path, default=None):
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        legacy_path = os.path.join(os.getcwd(), os.path.basename(file_path))
        if os.path.exists(legacy_path):
            with open(legacy_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки {file_path}: {e}")
    if isinstance(default, dict):
        return dict(default)
    if isinstance(default, list):
        return list(default)
    return default or {}

def save_json(file_path, data):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка сохранения {file_path}: {e}")

# Глобальные данные
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
USERS = load_json(USERS_FILE, {})

STATUS_MAP = {
    'new': 'Новый заказ',
    'in_progress': 'В работе',
    'awaiting_payment': 'Ожидает оплаты',
    'paid': 'Оплачен',
    'completed': 'Выполнен',
    'cancelled': 'Отменён'
}
STATUS_FLOW = ['new', 'in_progress', 'awaiting_payment', 'paid', 'completed', 'cancelled']
STATUS_NOTIFICATIONS = {
    'in_progress': '✅ Ваш заказ #{order_id} принят в работу.',
    'awaiting_payment': '💳 По заказу #{order_id} ожидается оплата. Менеджер свяжется с вами.',
    'paid': '💰 Заказ #{order_id} оплачен. Подготовим работу в ближайшее время!',
    'completed': '🎉 Заказ #{order_id} готов! Проверьте материалы и оставьте отзыв.',
    'cancelled': '⚠️ Заказ #{order_id} отменён. Если нужна помощь — напишите нам.'
}

BONUS_EXPIRATION_DAYS = 30
MAX_BONUS_USAGE_RATE = 0.5
BONUS_EARNING_RATE = 0.2
REFERRAL_BONUS_RATE = 0.05
MIN_ORDER_AMOUNT_FOR_REFERRAL = 3000
MAX_LOG_ENTRIES_PER_USER = 200
ACTIVE_STATUSES = {'new', 'in_progress', 'awaiting_payment'}


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def ensure_bonus_record(user_id: int) -> Dict:
    record = BONUSES.setdefault(str(user_id), {'balance': 0, 'history': []})
    history = record.get('history')
    if not isinstance(history, list):
        history = []
    cleaned_history = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        entry = dict(entry)
        entry.setdefault('id', str(uuid.uuid4()))
        entry.setdefault('timestamp', datetime.now().isoformat())
        entry_type = entry.get('type', 'credit')
        entry['type'] = entry_type
        if entry_type == 'credit':
            amount = max(0, int(entry.get('amount', 0)))
            entry['amount'] = amount
            entry.setdefault('remaining', amount)
            entry.setdefault('expires_at', (datetime.now() + timedelta(days=BONUS_EXPIRATION_DAYS)).isoformat())
            entry['remaining'] = max(0, int(entry.get('remaining', amount)))
        else:
            entry['amount'] = int(entry.get('amount', 0))
        cleaned_history.append(entry)
    record['history'] = cleaned_history
    balance = 0
    for entry in record['history']:
        if entry.get('type') == 'credit' and not entry.get('expired'):
            balance += max(0, int(entry.get('remaining', entry.get('amount', 0))))
    record['balance'] = max(0, int(balance))
    return record


def ensure_user_profile(user_id: int, username: Optional[str], first_name: Optional[str]) -> Dict:
    profile = USERS.setdefault(str(user_id), {})
    if username:
        profile['username'] = username
    if first_name:
        profile['first_name'] = first_name
    profile.setdefault('created_at', datetime.now().isoformat())
    profile['last_seen'] = datetime.now().isoformat()
    return profile


def save_all_data():
    save_json(ORDERS_FILE, ORDERS)
    save_json(PRICES_FILE, PRICES)
    save_json(BONUSES_FILE, BONUSES)
    save_json(REFERRALS_FILE, REFERALS)
    save_json(USERS_FILE, USERS)
    save_json(USER_LOGS_FILE, USER_LOGS)


def get_user_link(user_id: int, username: Optional[str] = None) -> str:
    if username:
        return f"https://t.me/{username}"
    return f"tg://user?id={user_id}"


def format_currency(value: float) -> str:
    return f"{int(value):,}".replace(',', ' ')


async def send_or_edit(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None, parse_mode: Optional[str] = None):
    if update.callback_query:
        query = update.callback_query
        try:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except TelegramError as e:
            if "message is not modified" not in str(e).lower():
                raise
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    else:
        chat_id = update.effective_chat.id if update.effective_chat else ADMIN_CHAT_ID
        await context.bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)


async def expire_bonuses_if_needed(user_id: int, context: Optional[ContextTypes.DEFAULT_TYPE] = None, notify: bool = True):
    record = ensure_bonus_record(user_id)
    now = datetime.now()
    expired_total = 0
    for entry in record['history']:
        if entry.get('type') != 'credit' or entry.get('expired'):
            continue
        expires_at = parse_dt(entry.get('expires_at'))
        remaining = max(0, int(entry.get('remaining', entry.get('amount', 0))))
        if remaining <= 0:
            continue
        if expires_at and expires_at < now:
            entry['expired'] = True
            entry['remaining'] = 0
            expired_total += remaining
            record['history'].append({
                'id': str(uuid.uuid4()),
                'type': 'expire',
                'amount': -remaining,
                'timestamp': now.isoformat(),
                'reason': 'Бонусы сгорели спустя 30 дней без использования',
                'source_id': entry['id']
            })
    if expired_total:
        record['balance'] = max(0, record['balance'] - expired_total)
        save_json(BONUSES_FILE, BONUSES)
        if notify and context:
            try:
                await context.bot.send_message(int(user_id), f"⚠️ {expired_total}₽ бонусов сгорели, так как их не использовали в течение 30 дней.")
            except TelegramError:
                pass


async def add_bonus(user_id: int, amount: int, reason: str, context: Optional[ContextTypes.DEFAULT_TYPE], order_id: Optional[int] = None, admin_id: Optional[int] = None, expires_in_days: int = BONUS_EXPIRATION_DAYS, notify_user: bool = True) -> int:
    amount = max(0, int(amount))
    if amount <= 0:
        return 0
    record = ensure_bonus_record(user_id)
    expires_at = (datetime.now() + timedelta(days=expires_in_days)).isoformat()
    entry_id = str(uuid.uuid4())
    entry = {
        'id': entry_id,
        'type': 'credit',
        'amount': amount,
        'remaining': amount,
        'timestamp': datetime.now().isoformat(),
        'expires_at': expires_at,
        'reason': reason,
        'order_id': order_id,
        'admin_id': admin_id
    }
    record['history'].append(entry)
    record['balance'] = max(0, record['balance'] + amount)
    save_json(BONUSES_FILE, BONUSES)
    if notify_user and context:
        try:
            text = f"🎁 Вам начислено {amount}₽ бонусов. Причина: {reason}. Бонусы действуют {BONUS_EXPIRATION_DAYS} дней."
            await context.bot.send_message(int(user_id), text)
        except TelegramError:
            pass
    return amount


async def deduct_bonus(user_id: int, amount: int, reason: str, context: Optional[ContextTypes.DEFAULT_TYPE], admin_id: Optional[int] = None, notify_user: bool = True) -> int:
    amount = max(0, int(amount))
    if amount <= 0:
        return 0
    record = ensure_bonus_record(user_id)
    available = record['balance']
    if available <= 0:
        return 0
    to_deduct = min(amount, available)
    remaining = to_deduct
    now = datetime.now().isoformat()
    for entry in record['history']:
        if remaining <= 0:
            break
        if entry.get('type') != 'credit' or entry.get('expired'):
            continue
        entry_remaining = max(0, int(entry.get('remaining', entry.get('amount', 0))))
        if entry_remaining <= 0:
            continue
        take = min(entry_remaining, remaining)
        entry['remaining'] = entry_remaining - take
        record['history'].append({
            'id': str(uuid.uuid4()),
            'type': 'debit',
            'amount': -take,
            'timestamp': now,
            'reason': reason,
            'source_id': entry['id'],
            'admin_id': admin_id
        })
        remaining -= take
    record['balance'] = max(0, record['balance'] - (to_deduct - remaining))
    save_json(BONUSES_FILE, BONUSES)
    deducted = to_deduct - remaining
    if deducted > 0 and notify_user and context:
        try:
            await context.bot.send_message(int(user_id), f"ℹ️ С вашего бонусного счёта списано {deducted}₽. Причина: {reason}. Остаток: {record['balance']}₽.")
        except TelegramError:
            pass
    return deducted


def get_bonus_balance(user_id: int) -> int:
    record = ensure_bonus_record(user_id)
    return max(0, int(record.get('balance', 0)))


def get_bonus_history(user_id: int, limit: int = 5) -> List[Dict]:
    record = ensure_bonus_record(user_id)
    history = sorted(record['history'], key=lambda x: parse_dt(x.get('timestamp')) or datetime.now(), reverse=True)
    return history[:limit]


def normalize_orders():
    changed = False
    status_aliases = {
        'нов': 'new',
        'новый': 'new',
        'новая': 'new',
        'новый заказ': 'new',
        'в работе': 'in_progress',
        'в обработке': 'in_progress',
        'ожидает оплаты': 'awaiting_payment',
        'ожидание оплаты': 'awaiting_payment',
        'оплачен': 'paid',
        'оплачено': 'paid',
        'готово': 'completed',
        'выполнен': 'completed',
        'выполнено': 'completed',
        'отменён': 'cancelled',
        'отменен': 'cancelled',
        'отменено': 'cancelled'
    }
    for user_id, orders in list(ORDERS.items()):
        if not isinstance(orders, list):
            continue
        normalized_orders = []
        for order in orders:
            if not isinstance(order, dict):
                continue
            order = dict(order)
            if 'order_key' not in order:
                order['order_key'] = str(uuid.uuid4())
                changed = True
            status = order.get('status', 'new')
            status_lower = str(status).lower()
            if status_lower in STATUS_MAP:
                order['status'] = status_lower
            elif status_lower in status_aliases:
                order['status'] = status_aliases[status_lower]
                changed = True
            elif status_lower not in STATUS_MAP:
                order['status'] = 'new'
                changed = True
            created = parse_dt(order.get('created_at')) or parse_dt(order.get('date'))
            if not created:
                created = datetime.now()
            order['created_at'] = created.isoformat()
            order['updated_at'] = order.get('updated_at', created.isoformat())
            original_price = int(order.get('original_price', order.get('price', 0)))
            order['original_price'] = original_price
            order['total_after_discount'] = int(order.get('total_after_discount', original_price))
            order['bonus_used'] = int(order.get('bonus_used', order.get('bonus', 0) or 0))
            order['amount_due'] = int(order.get('amount_due', order['total_after_discount'] - order['bonus_used']))
            order['discount_share'] = int(order.get('discount_share', 0))
            order['upsells'] = list(order.get('upsells', []))
            order['requirements'] = order.get('requirements', 'Нет')
            order['user_bonus_awarded'] = bool(order.get('user_bonus_awarded', False))
            order['user_bonus_amount'] = int(order.get('user_bonus_amount', 0))
            order['referral_bonus_awarded'] = bool(order.get('referral_bonus_awarded', False))
            order['referral_bonus_amount'] = int(order.get('referral_bonus_amount', 0))
            order['bonus_refunded'] = bool(order.get('bonus_refunded', False))
            history = order.get('status_history')
            if not isinstance(history, list) or not history:
                order['status_history'] = [{'status': order['status'], 'timestamp': order['updated_at'], 'updated_by': user_id}]
                changed = True
            else:
                fixed_history = []
                for item in history:
                    if not isinstance(item, dict):
                        continue
                    status_code = item.get('status', order['status'])
                    status_lower = str(status_code).lower()
                    if status_lower in STATUS_MAP:
                        status_code = status_lower
                    elif status_lower in status_aliases:
                        status_code = status_aliases[status_lower]
                        changed = True
                    fixed_history.append({
                        'status': status_code,
                        'timestamp': item.get('timestamp', order['updated_at']),
                        'updated_by': item.get('updated_by', user_id)
                    })
                order['status_history'] = fixed_history or [{'status': order['status'], 'timestamp': order['updated_at'], 'updated_by': user_id}]
            order['user_id'] = int(order.get('user_id', int(user_id)))
            normalized_orders.append(order)
        ORDERS[user_id] = normalized_orders
    if changed:
        save_json(ORDERS_FILE, ORDERS)


def list_all_orders() -> List[Tuple[int, Dict]]:
    results: List[Tuple[int, Dict]] = []
    for user_id, orders in ORDERS.items():
        if not isinstance(orders, list):
            continue
        for order in orders:
            if isinstance(order, dict):
                results.append((int(user_id), order))
    return results


def find_order(user_id: int, identifier: str) -> Optional[Dict]:
    orders = ORDERS.get(str(user_id), [])
    for order in orders:
        if order.get('order_key') == identifier or str(order.get('order_id')) == str(identifier):
            return order
    return None


def format_admin_order_brief(user_id: int, order: Dict) -> str:
    status = STATUS_MAP.get(order.get('status', 'new'), order.get('status', 'new'))
    created = parse_dt(order.get('created_at'))
    created_text = created.strftime('%d.%m %H:%M') if created else ''
    name = ORDER_TYPES.get(order.get('type'), {}).get('name', order.get('type', 'Заказ'))
    return f"#{order.get('order_id')} · {name} · {status} · {created_text}"


def format_admin_order_details(user_id: int, order: Dict) -> str:
    name = ORDER_TYPES.get(order.get('type'), {}).get('name', order.get('type', 'Заказ'))
    status = STATUS_MAP.get(order.get('status', 'new'), order.get('status', 'new'))
    created = parse_dt(order.get('created_at'))
    created_text = created.strftime('%d.%m.%Y %H:%M') if created else ''
    deadline_days = order.get('deadline_days')
    topic = html.escape(str(order.get('topic', 'Без темы')))
    requirements = html.escape(str(order.get('requirements', 'Нет требований')))
    upsells = order.get('upsells', [])
    amount_due = order.get('amount_due', order.get('total_after_discount', order.get('original_price', 0)))
    bonus_used = order.get('bonus_used', 0)
    discount = order.get('discount_share', 0)
    text = [
        f"📄 Заказ #{order.get('order_id')} · {html.escape(name)}",
        f"Статус: {html.escape(status)}",
        f"Создан: {created_text}",
        f"Срок в днях: {deadline_days}",
        f"Тема: {topic}",
        f"Требования: {requirements}",
        f"Доп. услуги: {html.escape(', '.join(upsells)) if upsells else 'Нет'}",
        f"Изначально: {order.get('original_price', 0)}₽",
        f"Скидка: -{discount}₽" if discount else "Скидка: 0₽",
        f"Оплачено бонусами: {bonus_used}₽",
        f"К оплате клиентом: {amount_due}₽",
    ]
    if order.get('user_bonus_awarded'):
        text.append(f"Клиенту начислено бонусов: {order.get('user_bonus_amount', 0)}₽")
    if order.get('referral_bonus_awarded'):
        text.append(f"Рефереру начислено: {order.get('referral_bonus_amount', 0)}₽")
    history_lines = []
    for item in sorted(order.get('status_history', []), key=lambda x: parse_dt(x.get('timestamp')) or datetime.now()):
        status_label = STATUS_MAP.get(item.get('status'), item.get('status'))
        ts = parse_dt(item.get('timestamp'))
        ts_text = ts.strftime('%d.%m %H:%M') if ts else ''
        history_lines.append(f"{ts_text} · {html.escape(str(status_label))} · {html.escape(str(item.get('updated_by')))}")
    if history_lines:
        text.append("История статусов:")
        text.extend(history_lines)
    return "\n".join(text)


def build_admin_dashboard_text() -> str:
    orders = list_all_orders()
    total_orders = len(orders)
    active_orders = sum(1 for _, order in orders if order.get('status') in ACTIVE_STATUSES)
    completed_orders = sum(1 for _, order in orders if order.get('status') == 'completed')
    last_created = None
    if orders:
        last_created = max((parse_dt(order.get('created_at')) for _, order in orders), default=None)
    users_count = len(USERS)
    total_bonus = sum(get_bonus_balance(int(uid)) for uid in USERS.keys())
    text = [
        "🔐 Админ-панель",
        f"Всего заказов: {total_orders}",
        f"Активных заказов: {active_orders}",
        f"Выполненных заказов: {completed_orders}",
        f"Пользователей: {users_count}",
        f"Бонусов на счетах: {total_bonus}₽"
    ]
    if last_created:
        text.append(f"Последний заказ: {last_created.strftime('%d.%m.%Y %H:%M')}")
    return "\n".join(text)


async def admin_show_orders(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str = 'all'):
    orders = list_all_orders()
    context.user_data['admin_orders_mode'] = mode
    if mode == 'active':
        orders = [(uid, order) for uid, order in orders if order.get('status') in ACTIVE_STATUSES]
    elif mode == 'recent':
        orders = sorted(orders, key=lambda item: parse_dt(item[1].get('created_at')) or datetime.min, reverse=True)[:10]
    else:
        orders = sorted(orders, key=lambda item: parse_dt(item[1].get('created_at')) or datetime.min, reverse=True)[:15]
    if not orders:
        text = "Заказов пока нет."
    else:
        text_lines = ["📦 Список заказов:"]
        for user_id, order in orders:
            status = STATUS_MAP.get(order.get('status', 'new'), order.get('status', 'new'))
            created = parse_dt(order.get('created_at'))
            created_text = created.strftime('%d.%m %H:%M') if created else ''
            profile = USERS.get(str(user_id), {})
            username = profile.get('username') or order.get('user_username')
            link = get_user_link(user_id, username)
            name = ORDER_TYPES.get(order.get('type'), {}).get('name', order.get('type', 'Заказ'))
            text_lines.append(
                f"<b>#{order.get('order_id')}</b> · {html.escape(name)} · {html.escape(status)} · {created_text} · "
                f"<a href=\"{link}\">Чат</a>"
            )
        text = "\n".join(text_lines)
    keyboard_rows = []
    for user_id, order in orders:
        status = STATUS_MAP.get(order.get('status', 'new'), order.get('status', 'new'))
        keyboard_rows.append([
            InlineKeyboardButton(
                f"#{order.get('order_id')} · {status}",
                callback_data=f"admin_order:{user_id}:{order.get('order_key')}"
            )
        ])
    keyboard_rows.append([InlineKeyboardButton("⬅️ Меню", callback_data='admin_menu')])
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard_rows),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )
    return ADMIN_MENU


async def admin_show_order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, order_key: str):
    order = find_order(user_id, order_key)
    if not order:
        await update.callback_query.edit_message_text("Заказ не найден.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data='admin_orders')]]))
        return ADMIN_MENU
    profile = USERS.get(str(user_id), {})
    username = profile.get('username') or order.get('user_username')
    link = get_user_link(user_id, username)
    text = format_admin_order_details(user_id, order)
    keyboard_rows = [
        [InlineKeyboardButton("💬 Открыть чат", url=link)]
    ]
    current_status = order.get('status', 'new')
    for status_code in STATUS_FLOW:
        if status_code == current_status:
            continue
        keyboard_rows.append([
            InlineKeyboardButton(
                STATUS_MAP.get(status_code, status_code),
                callback_data=f"admin_status:{user_id}:{order.get('order_key')}:{status_code}"
            )
        ])
    keyboard_rows.append([InlineKeyboardButton("⬅️ К заказам", callback_data='admin_orders')])
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard_rows),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )
    return ADMIN_MENU


async def admin_update_order_status(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, order_key: str, new_status: str):
    order = find_order(user_id, order_key)
    if not order:
        await update.callback_query.edit_message_text("Заказ не найден.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data='admin_orders')]]))
        return ADMIN_MENU
    old_status = order.get('status', 'new')
    if new_status == old_status:
        await update.callback_query.answer("Статус уже установлен.", show_alert=True)
        return ADMIN_MENU
    order['status'] = new_status
    now_iso = datetime.now().isoformat()
    order['updated_at'] = now_iso
    order.setdefault('status_history', []).append({'status': new_status, 'timestamp': now_iso, 'updated_by': update.effective_user.id})
    save_json(ORDERS_FILE, ORDERS)
    user_id_int = int(user_id)
    profile = USERS.get(str(user_id_int), {})
    message_template = STATUS_NOTIFICATIONS.get(new_status)
    if message_template:
        try:
            await context.bot.send_message(user_id_int, message_template.format(order_id=order.get('order_id')))
        except TelegramError:
            pass
    if new_status in ('paid', 'completed'):
        await handle_paid_order(user_id_int, order, context)
    elif new_status == 'cancelled' and order.get('bonus_used', 0) and not order.get('bonus_refunded'):
        refunded = await add_bonus(user_id_int, order['bonus_used'], f"Возврат бонусов за отмену заказа #{order.get('order_id')}", context, order_id=order.get('order_id'))
        if refunded:
            order['bonus_refunded'] = True
            save_json(ORDERS_FILE, ORDERS)
    await update.callback_query.answer("Статус обновлён")
    return await admin_show_order_detail(update, context, user_id_int, order_key)


async def handle_paid_order(user_id: int, order: Dict, context: ContextTypes.DEFAULT_TYPE):
    amount_paid = max(0, int(order.get('amount_due', order.get('total_after_discount', order.get('original_price', 0)))))
    if amount_paid > 0 and not order.get('user_bonus_awarded'):
        reward = max(1, int(amount_paid * BONUS_EARNING_RATE))
        awarded = await add_bonus(user_id, reward, f"Бонус за оплату заказа #{order.get('order_id')}", context, order_id=order.get('order_id'))
        if awarded:
            order['user_bonus_awarded'] = True
            order['user_bonus_amount'] = awarded
    profile = USERS.get(str(user_id), {})
    referrer_id = profile.get('referrer_id')
    if referrer_id and referrer_id != user_id and not order.get('referral_bonus_awarded') and amount_paid >= MIN_ORDER_AMOUNT_FOR_REFERRAL:
        reward = max(1, int(amount_paid * REFERRAL_BONUS_RATE))
        awarded = await add_bonus(referrer_id, reward, f"Реферальный бонус за заказ #{order.get('order_id')}", context, order_id=order.get('order_id'))
        if awarded:
            order['referral_bonus_awarded'] = True
            order['referral_bonus_amount'] = awarded
    save_json(ORDERS_FILE, ORDERS)


async def admin_show_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    all_user_ids = set(USERS.keys()) | set(ORDERS.keys())
    rows = []
    for uid in all_user_ids:
        uid_int = int(uid)
        orders_count = len(ORDERS.get(uid, []))
        balance = get_bonus_balance(uid_int)
        refs = len(REFERALS.get(uid, []))
        profile = USERS.get(uid, {})
        name = profile.get('first_name', 'Без имени')
        username = profile.get('username')
        rows.append((uid_int, name, username, orders_count, balance, refs))
    rows.sort(key=lambda item: item[4], reverse=True)
    if not rows:
        text = "Пользователей пока нет."
    else:
        lines = ["👥 Клиенты и бонусы:"]
        for uid_int, name, username, orders_count, balance, refs in rows[:20]:
            link = get_user_link(uid_int, username)
            lines.append(
                f"<b>{html.escape(name)}</b> · ID {uid_int} · заказов: {orders_count} · бонусов: {balance}₽ · рефералов: {refs} · "
                f"<a href=\"{link}\">Чат</a>"
            )
        text = "\n".join(lines)
    keyboard = [
        [InlineKeyboardButton(f"{item[0]} · {item[4]}₽", callback_data=f"admin_user:{item[0]}")]
        for item in rows[:20]
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Меню", callback_data='admin_menu')])
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )
    return ADMIN_MENU


async def admin_show_user_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    uid_str = str(user_id)
    profile = USERS.get(uid_str, {})
    name = profile.get('first_name', 'Без имени')
    username = profile.get('username')
    link = get_user_link(user_id, username)
    await expire_bonuses_if_needed(user_id, context, notify=False)
    balance = get_bonus_balance(user_id)
    refs = len(REFERALS.get(uid_str, []))
    orders = ORDERS.get(uid_str, [])
    orders_sorted = sorted(orders, key=lambda o: parse_dt(o.get('created_at')) or datetime.min, reverse=True)
    lines = [
        f"<b>{html.escape(name)}</b> · ID {user_id}",
        f"Бонусов: {balance}₽", 
        f"Рефералов: {refs}",
        f"Заказов: {len(orders)}", 
        f"<a href=\"{link}\">Открыть чат</a>",
        "",
        "Последние заказы:" if orders else "Заказов пока нет"
    ]
    for order in orders_sorted[:5]:
        status = STATUS_MAP.get(order.get('status', 'new'), order.get('status', 'new'))
        created = parse_dt(order.get('created_at'))
        created_text = created.strftime('%d.%m %H:%M') if created else ''
        name_order = ORDER_TYPES.get(order.get('type'), {}).get('name', order.get('type', 'Заказ'))
        lines.append(f"#{order.get('order_id')} · {html.escape(name_order)} · {html.escape(status)} · {created_text}")
    history = get_bonus_history(user_id, limit=8)
    if history:
        lines.append("\nИстория бонусов:")
        for item in history:
            amount = item.get('amount', 0)
            ts = parse_dt(item.get('timestamp'))
            ts_text = ts.strftime('%d.%m %H:%M') if ts else ''
            reason = html.escape(str(item.get('reason', 'Без описания')))
            prefix = '+' if amount > 0 else ''
            lines.append(f"{ts_text} · {prefix}{amount}₽ · {reason}")
    text = "\n".join(lines)
    keyboard = [
        [InlineKeyboardButton("➕ Начислить", callback_data=f"admin_bonus_add:{user_id}"), InlineKeyboardButton("➖ Списать", callback_data=f"admin_bonus_sub:{user_id}")],
        [InlineKeyboardButton("⬅️ К списку", callback_data='admin_users')]
    ]
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )
    return ADMIN_MENU


async def admin_show_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["💲 Ценообразование:"]
    for key, settings in PRICES.items():
        name = ORDER_TYPES.get(key, {}).get('name', key)
        lines.append(
            f"{html.escape(name)} — база: {settings.get('base')}₽ · мин: {settings.get('min')}₽ · макс: {settings.get('max')}₽"
        )
    lines.append(f"\nТекущий режим наценок: {current_pricing_mode}")
    keyboard = [
        [InlineKeyboardButton(ORDER_TYPES.get(key, {}).get('name', key), callback_data=f"admin_price:{key}")]
        for key in ORDER_TYPES
    ]
    keyboard.append([InlineKeyboardButton(f"Режим: {current_pricing_mode}", callback_data='admin_price_mode')])
    keyboard.append([InlineKeyboardButton("⬅️ Меню", callback_data='admin_menu')])
    await update.callback_query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return ADMIN_MENU


async def admin_show_price_detail(update: Update, context: ContextTypes.DEFAULT_TYPE, type_key: str):
    settings = PRICES.get(type_key)
    if not settings:
        await update.callback_query.edit_message_text("Тип не найден.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data='admin_prices')]]))
        return ADMIN_MENU
    name = ORDER_TYPES.get(type_key, {}).get('name', type_key)
    text = (
        f"<b>{html.escape(name)}</b>\n"
        f"База: {settings.get('base')}₽\n"
        f"Минимум: {settings.get('min')}₽\n"
        f"Максимум: {settings.get('max')}₽"
    )
    keyboard = [
        [InlineKeyboardButton("База -1000", callback_data=f"admin_price_step:{type_key}:base:-1000"), InlineKeyboardButton("База +1000", callback_data=f"admin_price_step:{type_key}:base:1000")],
        [InlineKeyboardButton("Мин -500", callback_data=f"admin_price_step:{type_key}:min:-500"), InlineKeyboardButton("Мин +500", callback_data=f"admin_price_step:{type_key}:min:500")],
        [InlineKeyboardButton("Макс -1000", callback_data=f"admin_price_step:{type_key}:max:-1000"), InlineKeyboardButton("Макс +1000", callback_data=f"admin_price_step:{type_key}:max:1000")],
        [InlineKeyboardButton("Ввести базу", callback_data=f"admin_price_manual:{type_key}:base"), InlineKeyboardButton("Ввести мин", callback_data=f"admin_price_manual:{type_key}:min"), InlineKeyboardButton("Ввести макс", callback_data=f"admin_price_manual:{type_key}:max")],
        [InlineKeyboardButton("⬅️ Назад", callback_data='admin_prices')]
    ]
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    return ADMIN_MENU


def adjust_price_value(type_key: str, field: str, delta: int):
    settings = PRICES.get(type_key)
    if not settings:
        return False
    settings[field] = max(0, int(settings.get(field, 0)) + delta)
    # ensure consistency
    if settings.get('min') is None:
        settings['min'] = settings['base']
    if settings.get('max') is None:
        settings['max'] = settings['base']
    if settings['min'] > settings['base']:
        settings['base'] = settings['min']
    if settings['base'] > settings['max']:
        settings['max'] = settings['base']
    if settings['min'] > settings['max']:
        settings['max'] = settings['min']
    save_json(PRICES_FILE, PRICES)
    return True


async def admin_show_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    entries = []
    for uid, logs in USER_LOGS.items():
        for item in logs:
            ts = parse_dt(item.get('timestamp')) or datetime.min
            entries.append((ts, int(uid), item))
    entries.sort(key=lambda x: x[0], reverse=True)
    entries = entries[:30]
    if not entries:
        text = "Логи пока пусты."
    else:
        lines = ["📊 Последние действия:"]
        for ts, uid, item in entries:
            profile = USERS.get(str(uid), {})
            username = profile.get('username') or item.get('username')
            link = get_user_link(uid, username)
            ts_text = ts.strftime('%d.%m %H:%M')
            action = html.escape(str(item.get('action')))
            lines.append(f"{ts_text} · <a href=\"{link}\">ID {uid}</a> · {action}")
        text = "\n".join(lines)
    keyboard = [[InlineKeyboardButton("⬅️ Меню", callback_data='admin_menu')]]
    await update.callback_query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )
    return ADMIN_MENU


def reset_admin_context(context: ContextTypes.DEFAULT_TYPE):
    """Очистка временных состояний при выходе из админ-потока."""
    for key in ('admin_state', 'target_user', 'price_edit'):
        context.user_data.pop(key, None)


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
        'description': 'Глубокий анализ литературы. Получите отличную оценку без стресса! 📈',
        'details': 'Теоретическая основа, анализ источников, структура по ГОСТ.',
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

for key in ORDER_TYPES.keys():
    info = PRICES.setdefault(key, {})
    default_base = {
        'samostoyatelnye': 2000,
        'kursovaya_teoreticheskaya': 8000,
        'kursovaya_s_empirikov': 12000,
        'diplomnaya': 35000,
        'magisterskaya': 35000,
    }.get(key, 1000)
    info['base'] = int(info.get('base', default_base))
    info['min'] = int(info.get('min', info['base']))
    info['max'] = int(info.get('max', max(info['base'], info['min'])))
    if info['min'] > info['base']:
        info['min'] = info['base']
    if info['max'] < info['base']:
        info['max'] = info['base']
save_json(PRICES_FILE, PRICES)
normalize_orders()

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
SELECT_MAIN_MENU, SELECT_ORDER_TYPE, VIEW_ORDER_DETAILS, INPUT_TOPIC, SELECT_DEADLINE, INPUT_REQUIREMENTS, ADD_UPSSELL, ADD_ANOTHER_ORDER, CONFIRM_CART, ADMIN_MENU, PROFILE_MENU, SHOW_PRICE_LIST, PRICE_CALCULATOR, SELECT_CALC_DEADLINE, SELECT_CALC_COMPLEXITY, SHOW_FAQ, FAQ_DETAILS, SHOW_ORDERS, LEAVE_FEEDBACK, INPUT_FEEDBACK = range(20)

# Логирование действий пользователя
def log_user_action(user_id, username, action):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entries = USER_LOGS.setdefault(str(user_id), [])
    log_entries.append({'timestamp': timestamp, 'action': action, 'username': username})
    if len(log_entries) > MAX_LOG_ENTRIES_PER_USER:
        del log_entries[:-MAX_LOG_ENTRIES_PER_USER]
    ensure_user_profile(user_id, username, None)
    save_json(USER_LOGS_FILE, USER_LOGS)
    save_json(USERS_FILE, USERS)
    logger.info(f"Пользователь {user_id} ({username}): {action}")

# Расчет цены
def calculate_price(order_type_key, days_left, complexity_factor=1.0):
    if order_type_key not in PRICES:
        logger.error(f"Неизвестный тип: {order_type_key}")
        return 0
    price_info = PRICES[order_type_key]
    base = price_info.get('base', 0)
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
    min_price = price_info.get('min', base)
    max_price = price_info.get('max', max(base, min_price))
    price = max(min_price, min(int(price), max_price))
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
    ensure_user_profile(user.id, user.username, user.first_name)
    if update.message and update.message.text:
        args = update.message.text.split()
    else:
        args = ['/start']
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={user.id}"
    context.user_data['ref_link'] = ref_link
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if referrer_id != user.id:
            profile = USERS.setdefault(str(user.id), {})
            if not profile.get('referrer_id'):
                profile['referrer_id'] = referrer_id
                refs = REFERALS.setdefault(str(referrer_id), [])
                if user.id not in refs:
                    refs.append(user.id)
                save_json(REFERRALS_FILE, REFERALS)
                save_json(USERS_FILE, USERS)
                try:
                    await context.bot.send_message(referrer_id, f"🎉 Новый реферал: {user.first_name or 'клиент'}")
                except TelegramError:
                    pass
    await expire_bonuses_if_needed(user.id, context, notify=False)
    bonus_balance = get_bonus_balance(user.id)
    welcome = (
        f"👋 Добро пожаловать, {user.first_name}! Заказывайте работы. Уже 5000+ клиентов! 10% скидка на первый заказ 🔥\n"
        f"📲 Поделитесь ссылкой для бонусов: {ref_link}\n"
        f"🎁 Бонусный баланс: {bonus_balance}₽"
    )
    await main_menu(update, context, welcome)

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
        await query.answer()
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
    await query.answer()
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
    await query.answer()
    data = query.data if query else None
    user = update.effective_user
    log_user_action(user.id, user.username, "Выбор типа заказа")
    if data == 'back_to_main':
        return await main_menu(update, context)
    text = "Выберите тип работы (добавьте несколько в корзину для скидки!):"
    keyboard = [[InlineKeyboardButton(f"{val['icon']} {val['name']}", callback_data=f'type_{key}')] for key, val in ORDER_TYPES.items()]
    keyboard.append([InlineKeyboardButton("⬅️ Меню", callback_data='back_to_main')])
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
    await query.answer()
    data = query.data
    if data.startswith('order_'):
        key = data[6:]
        context.user_data['current_order_type'] = key
        await query.edit_message_text("Введите тему:")
        return INPUT_TOPIC
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
    context.user_data['topic'] = update.message.text
    user = update.effective_user
    log_user_action(user.id, user.username, f"Тема: {update.message.text}")
    text = "Выберите срок сдачи (дольше = дешевле + бонус!):"
    today = datetime.now()
    keyboard = []
    for i in range(1, 31, 5):  
        row = []
        for j in range(i, min(i+5, 31)):
            date = today + timedelta(days=j)
            button_text = f"{date.day} {date.strftime('%b')} ({j} дней)"
            row.append(InlineKeyboardButton(button_text, callback_data=f'deadline_{j}'))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("Назад", callback_data=f'type_{context.user_data["current_order_type"]}')])
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_DEADLINE

# Выбор срока
async def select_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith('deadline_'):
        days = int(data[9:])
        context.user_data['days_left'] = days
        await query.edit_message_text("Введите дополнительные требования (или /skip):")
        return INPUT_REQUIREMENTS
    elif data.startswith('type_'):
        return await view_order_details(update, context)
    return SELECT_DEADLINE

# Ввод требований
async def input_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['requirements'] = update.message.text
    return await add_upsell(update, context)

async def skip_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['requirements'] = 'Нет'
    return await add_upsell(update, context)

# Добавление допуслуг
async def add_upsell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "Добавить услуги? (Клиенты, добавляющие, получают 5% скидки на следующий заказ!)"
    keyboard = [
        [InlineKeyboardButton("Презентация (+2000₽)", callback_data='add_prez')],
        [InlineKeyboardButton("Речь (+1000₽)", callback_data='add_speech')],
        [InlineKeyboardButton("Без допов", callback_data='no_upsell')]
    ]
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_UPSSELL

# Обработчик допуслуг
async def upsell_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
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
    text = "Добавить еще? (Полный пакет экономит время!)" if added else "Уже добавлено. Добавить еще?"
    keyboard = [
        [InlineKeyboardButton("Презентация (+2000₽)", callback_data='add_prez')],
        [InlineKeyboardButton("Речь (+1000₽)", callback_data='add_speech')],
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
    price = calculate_price(type_key, days_left)
    extra = len(upsells) * 1000  
    price += extra
    order = {
        'type': type_key,
        'topic': topic,
        'deadline_days': days_left,
        'requirements': requirements,
        'upsells': upsells,
        'price': price,
        'status': 'новый'
    }
    context.user_data.setdefault('cart', []).append(order)
    context.user_data.pop('upsells', None)
    context.user_data.pop('requirements', None)
    context.user_data.pop('days_left', None)
    context.user_data.pop('topic', None)
    context.user_data.pop('current_order_type', None)
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
    await query.answer()
    data = query.data
    if data == 'add_another_yes':
        return await select_order_type(update, context)
    elif data == 'confirm_cart':
        return await confirm_cart(update, context)
    return ADD_ANOTHER_ORDER

# Подтверждение корзины
async def confirm_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cart = context.user_data.get('cart', [])
    if not cart:
        await send_or_edit(update, context, "Корзина пуста.")
        return await main_menu(update, context)
    user_id = update.effective_user.id
    total = sum(order['price'] for order in cart)
    discount = 0
    if len(cart) > 1:
        discount = int(total * 0.1)
    total_after_discount = max(0, total - discount)
    await expire_bonuses_if_needed(user_id, context, notify=False)
    balance = get_bonus_balance(user_id)
    max_bonus_allowed = min(balance, int(total_after_discount * MAX_BONUS_USAGE_RATE))
    context.user_data['cart_total'] = total
    context.user_data['cart_discount'] = discount
    context.user_data['cart_total_after_discount'] = total_after_discount
    context.user_data['max_bonus_allowed'] = max_bonus_allowed
    bonus_to_use = min(int(context.user_data.get('bonus_to_use', 0)), max_bonus_allowed)
    context.user_data['bonus_to_use'] = bonus_to_use
    payable = max(0, total_after_discount - bonus_to_use)
    lines = ["🛒 Корзина:"]
    for i, order in enumerate(cart, 1):
        order_name = ORDER_TYPES.get(order['type'], {}).get('name', 'Неизвестно')
        lines.append(f"{i}. {order_name} — {order['topic']} — {order['price']}₽")
    if discount:
        lines.append(f"Скидка за несколько заказов: -{discount}₽")
    lines.append(f"🎁 Доступно бонусов: {balance}₽ (можно применить до {max_bonus_allowed}₽)")
    lines.append(f"Используем бонусов сейчас: {bonus_to_use}₽")
    lines.append(f"💳 К оплате: {format_currency(payable)}₽")
    keyboard = [
        [InlineKeyboardButton("💳 Подтвердить", callback_data='place_order')],
    ]
    if max_bonus_allowed:
        if bonus_to_use:
            keyboard.append([InlineKeyboardButton("❌ Не использовать бонусы", callback_data='clear_bonus')])
        keyboard.append([InlineKeyboardButton("🎁 Изменить бонусы", callback_data='adjust_bonus')])
    keyboard.append([InlineKeyboardButton("Отменить", callback_data='cancel_cart')])
    await send_or_edit(update, context, "\n".join(lines), InlineKeyboardMarkup(keyboard))
    return CONFIRM_CART

async def confirm_cart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == 'place_order':
        user_id = str(update.effective_user.id)
        user_orders = ORDERS.setdefault(user_id, [])
        order_id = len(user_orders) + 1
        cart = context.user_data.get('cart', [])
        if not cart:
            await query.edit_message_text("Корзина пуста.")
            return await main_menu(update, context)
        total = context.user_data.get('cart_total', sum(order['price'] for order in cart))
        discount = context.user_data.get('cart_discount', 0)
        total_after_discount = context.user_data.get('cart_total_after_discount', max(0, total - discount))
        bonus_requested = context.user_data.get('bonus_to_use', 0)
        await expire_bonuses_if_needed(int(user_id), context, notify=False)
        max_bonus_allowed = min(get_bonus_balance(int(user_id)), int(total_after_discount * MAX_BONUS_USAGE_RATE))
        bonus_requested = min(int(bonus_requested), max_bonus_allowed)
        bonus_applied = await deduct_bonus(int(user_id), bonus_requested, 'Оплата заказа бонусами', context, notify_user=False)
        if bonus_applied < bonus_requested:
            bonus_requested = bonus_applied
        context.user_data['bonus_to_use'] = bonus_requested
        remaining_discount = discount
        remaining_bonus = bonus_requested
        denominator_bonus = total_after_discount if total_after_discount else 1
        now_iso = datetime.now().isoformat()
        summary_lines = ["Заказ оформлен!", "Статус: новый", ""]
        for idx, order in enumerate(cart, 1):
            order_total = order['price']
            if idx == len(cart):
                discount_share = remaining_discount
                bonus_share = remaining_bonus
            else:
                discount_share = int(round(discount * order_total / total)) if total else 0
                discount_share = min(remaining_discount, discount_share)
                remaining_discount -= discount_share
                after_discount = order_total - discount_share
                bonus_share = int(round(bonus_requested * after_discount / denominator_bonus)) if total_after_discount else 0
                bonus_share = min(remaining_bonus, bonus_share)
                remaining_bonus -= bonus_share
            final_price = order_total - discount_share
            amount_due = max(0, final_price - bonus_share)
            order['order_id'] = order_id
            order_id += 1
            order['original_price'] = order_total
            order['discount_share'] = discount_share
            order['total_after_discount'] = final_price
            order['bonus_used'] = bonus_share
            order['amount_due'] = amount_due
            order['status'] = 'new'
            order['status_history'] = [{'status': 'new', 'timestamp': now_iso, 'updated_by': user_id}]
            order['created_at'] = now_iso
            order['updated_at'] = now_iso
            order['order_key'] = order.get('order_key') or str(uuid.uuid4())
            order['notes'] = order.get('notes', '')
            order['user_bonus_awarded'] = False
            order['referral_bonus_awarded'] = False
            order['referral_bonus_amount'] = order.get('referral_bonus_amount', 0)
            order['user_bonus_amount'] = order.get('user_bonus_amount', 0)
            order['bonus_refunded'] = False
            order['user_id'] = int(user_id)
            user_orders.append(order)
            name = ORDER_TYPES.get(order['type'], {}).get('name', order['type'])
            summary_lines.append(
                f"#{order['order_id']} · {name}\n"
                f"Тема: {order.get('topic', 'Без темы')}\n"
                f"Сумма: {order_total}₽"
                f"{' - скидка ' + str(discount_share) + '₽' if discount_share else ''}"
                f"{' - бонусы ' + str(bonus_share) + '₽' if bonus_share else ''}\n"
                f"К оплате: {amount_due}₽\n"
            )
        save_json(ORDERS_FILE, ORDERS)
        context.user_data.pop('cart', None)
        context.user_data.pop('bonus_to_use', None)
        context.user_data.pop('cart_total', None)
        context.user_data.pop('cart_discount', None)
        context.user_data.pop('cart_total_after_discount', None)
        context.user_data.pop('max_bonus_allowed', None)
        summary_lines.append(f"Итого оплачено бонусами: {bonus_requested}₽")
        summary_lines.append(f"Ожидаем оплату: {max(0, total_after_discount - bonus_requested)}₽")
        await query.message.reply_text("\n".join(summary_lines))
        if ADMIN_CHAT_ID:
            try:
                profile = USERS.get(user_id, {})
                username = profile.get('username')
                link = get_user_link(int(user_id), username)
                admin_text = (
                    f"📥 Новый заказ от {user_id}\n"
                    f"Позиций: {len(cart)}\n"
                    f"Сумма после скидок: {total_after_discount}₽\n"
                    f"Бонусы использованы: {bonus_requested}₽\n"
                    f"Связаться: <a href=\"{link}\">написать клиенту</a>"
                )
                await context.bot.send_message(ADMIN_CHAT_ID, admin_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            except TelegramError:
                pass
        return await main_menu(update, context, "Спасибо! Мы уже видим ваш заказ.")
    elif data == 'cancel_cart':
        context.user_data.pop('cart', None)
        context.user_data.pop('bonus_to_use', None)
        return await main_menu(update, context, "Корзина отменена. Посмотрите еще?")
    elif data == 'adjust_bonus':
        max_bonus = context.user_data.get('max_bonus_allowed', 0)
        context.user_data['awaiting_bonus_amount'] = True
        await query.message.reply_text(
            "Введите сумму бонусов, которую хотите списать (доступно до "
            f"{max_bonus}₽, максимум 50% стоимости). Если передумали, отправьте 0."
        )
        return CONFIRM_CART
    elif data == 'clear_bonus':
        context.user_data['bonus_to_use'] = 0
        return await confirm_cart(update, context)
    return CONFIRM_CART


async def handle_bonus_amount_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_bonus_amount'):
        await update.message.reply_text("Чтобы изменить бонусы, воспользуйтесь кнопками в корзине.")
        return CONFIRM_CART
    raw = update.message.text.strip().replace('₽', '').replace(' ', '')
    if not raw.isdigit():
        await update.message.reply_text("Введите целое число — сумму бонусов в рублях.")
        return CONFIRM_CART
    amount = int(raw)
    max_bonus = int(context.user_data.get('max_bonus_allowed', 0))
    if amount > max_bonus:
        await update.message.reply_text(f"Нельзя использовать больше {max_bonus}₽. Попробуйте снова.")
        return CONFIRM_CART
    context.user_data['bonus_to_use'] = amount
    context.user_data.pop('awaiting_bonus_amount', None)
    await update.message.reply_text(f"Будет использовано {amount}₽ бонусов.")
    return await confirm_cart(update, context)

# Показ прайс-листа
async def show_price_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
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
    await query.answer()
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
    await query.answer()
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
    await query.answer()
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
    await query.answer()
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
    elif data == 'profile_bonus':
        await expire_bonuses_if_needed(user.id, context)
        balance = get_bonus_balance(user.id)
        history = get_bonus_history(user.id, limit=5)
        lines = [f"🎁 Ваш баланс: {balance}₽"]
        if history:
            lines.append("Последние операции:")
            for item in history:
                ts = parse_dt(item.get('timestamp'))
                ts_text = ts.strftime('%d.%m %H:%M') if ts else ''
                sign = '+' if item.get('amount', 0) > 0 else ''
                reason = item.get('reason', 'Без описания')
                lines.append(f"{ts_text}: {sign}{item.get('amount', 0)}₽ — {reason}")
        else:
            lines.append("Пока операций нет. Заказывайте работы и приглашайте друзей!")
        lines.append("Бонусы действуют 30 дней и могут покрыть до 50% стоимости заказа.")
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад", callback_data='profile')]
        ]
        await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))
        return PROFILE_MENU
    log_user_action(user.id, user.username, "Профиль")
    await expire_bonuses_if_needed(user.id, context, notify=False)
    orders_count = len(ORDERS.get(user_id, []))
    feedbacks_count = len(FEEDBACKS.get(user_id, []))
    refs_count = len(REFERALS.get(user_id, []))
    ref_link = context.user_data.get('ref_link', 'Нет ссылки')
    balance = get_bonus_balance(user.id)
    text = (
        f"👤 Профиль {user.first_name}\n\n"
        f"Заказов: {orders_count}\n"
        f"Отзывов: {feedbacks_count}\n"
        f"Рефералов: {refs_count}\n"
        f"Бонусов: {balance}₽\n"
        f"Реф. ссылка: {ref_link}\n\n"
        "Приглашайте друзей: бонусы начисляются только за оплаченные заказы."
    )
    keyboard = [
        [InlineKeyboardButton("📋 Мои заказы", callback_data='my_orders')],
        [InlineKeyboardButton("🎁 Бонусы", callback_data='profile_bonus')],
        [InlineKeyboardButton("⭐ Оставить отзыв", callback_data='leave_feedback')],
        [InlineKeyboardButton("⬅️ Меню", callback_data='back_to_main')]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return PROFILE_MENU

# Показ заказов
async def show_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == 'profile':
        return await show_profile(update, context)
    user_id = str(update.effective_user.id)
    user_orders = ORDERS.get(user_id, [])
    if not user_orders:
        text = "Пока нет заказов. Сделайте заказ сейчас!"
    else:
        text_lines = ["Ваши заказы:"]
        for order in sorted(user_orders, key=lambda x: x.get('created_at', ''), reverse=True):
            name = ORDER_TYPES.get(order.get('type'), {}).get('name', 'Неизвестно')
            status_code = order.get('status', 'new')
            status_label = STATUS_MAP.get(status_code, status_code)
            created = parse_dt(order.get('created_at'))
            created_text = created.strftime('%d.%m.%Y %H:%M') if created else ''
            amount_due = order.get('amount_due', order.get('price', 0))
            bonus_used = order.get('bonus_used', 0)
            text_lines.append(
                f"#{order.get('order_id', 'N/A')} · {name}\n"
                f"Статус: {status_label}\n"
                f"Создан: {created_text}\n"
                f"К оплате: {amount_due}₽"
                f"{' · использовано бонусов ' + str(bonus_used) + '₽' if bonus_used else ''}\n"
            )
        text = "\n".join(text_lines)
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
    await query.answer()
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
        [InlineKeyboardButton("📦 Заказы", callback_data='admin_orders')],
        [InlineKeyboardButton("🔥 Актуальные", callback_data='admin_orders_active'), InlineKeyboardButton("🆕 Последние", callback_data='admin_orders_recent')],
        [InlineKeyboardButton("👥 Пользователи и бонусы", callback_data='admin_users')],
        [InlineKeyboardButton("💲 Ценообразование", callback_data='admin_prices')],
        [InlineKeyboardButton("📊 Логи", callback_data='admin_logs'), InlineKeyboardButton("📤 Экспорт", callback_data='admin_export')],
        [InlineKeyboardButton("⬅️ Выход", callback_data='back_to_main')]
    ]
    context.user_data.setdefault('admin_orders_mode', 'all')
    text = build_admin_dashboard_text()
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU

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
    data = query.data
    # Позволяем из админ-панели сразу перейти к пользовательским разделам
    main_menu_routes = {
        'make_order': select_order_type,
        'price_list': show_price_list,
        'price_calculator': price_calculator,
        'profile': show_profile,
        'faq': show_faq,
        'back_to_main': main_menu,
    }
    if data in main_menu_routes:
        reset_admin_context(context)
        return await main_menu_routes[data](update, context)
    await query.answer()
    if data == 'admin_menu':
        return await show_admin_menu(update, context)
    if data == 'admin_orders':
        mode = context.user_data.get('admin_orders_mode', 'all')
        return await admin_show_orders(update, context, mode)
    if data == 'admin_orders_recent':
        return await admin_show_orders(update, context, 'recent')
    if data == 'admin_orders_active':
        return await admin_show_orders(update, context, 'active')
    if data.startswith('admin_order:'):
        _, user_id, order_key = data.split(':', 2)
        return await admin_show_order_detail(update, context, int(user_id), order_key)
    if data.startswith('admin_status:'):
        _, user_id, order_key, status_code = data.split(':', 3)
        return await admin_update_order_status(update, context, int(user_id), order_key, status_code)
    if data == 'admin_users':
        return await admin_show_users(update, context)
    if data.startswith('admin_user:'):
        _, user_id = data.split(':', 1)
        return await admin_show_user_detail(update, context, int(user_id))
    if data.startswith('admin_bonus_add:'):
        _, user_id = data.split(':', 1)
        context.user_data['admin_state'] = 'bonus_add'
        context.user_data['target_user'] = int(user_id)
        await query.message.reply_text("Введите сумму и причину начисления (пример: 1500;За отзыв).")
        return ADMIN_MENU
    if data.startswith('admin_bonus_sub:'):
        _, user_id = data.split(':', 1)
        context.user_data['admin_state'] = 'bonus_sub'
        context.user_data['target_user'] = int(user_id)
        await query.message.reply_text("Введите сумму и причину списания (пример: 500;Использовано неверно).")
        return ADMIN_MENU
    if data == 'admin_prices':
        return await admin_show_prices(update, context)
    if data.startswith('admin_price:'):
        _, type_key = data.split(':', 1)
        return await admin_show_price_detail(update, context, type_key)
    if data.startswith('admin_price_step:'):
        _, type_key, field, delta = data.split(':', 3)
        adjust_price_value(type_key, field, int(delta))
        return await admin_show_price_detail(update, context, type_key)
    if data.startswith('admin_price_manual:'):
        _, type_key, field = data.split(':', 2)
        context.user_data['admin_state'] = 'price_manual'
        context.user_data['price_edit'] = {'type': type_key, 'field': field}
        await query.message.reply_text(f"Введите новое значение для {field} ({type_key}) в рублях:")
        return ADMIN_MENU
    if data == 'admin_price_mode':
        context.user_data['admin_state'] = 'change_mode'
        await query.message.reply_text("Введите режим наценок (hard или light):")
        return ADMIN_MENU
    if data == 'admin_logs':
        return await admin_show_logs(update, context)
    if data == 'admin_export':
        df = pd.DataFrame([{'user_id': uid, **ord} for uid, ords in ORDERS.items() for ord in ords])
        export_file = os.path.join(DATA_DIR, 'orders_export.csv')
        df.to_csv(export_file, index=False)
        await context.bot.send_document(ADMIN_CHAT_ID or update.effective_chat.id, open(export_file, 'rb'))
        os.remove(export_file)
        await query.edit_message_text("📤 Экспорт отправлен!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data='admin_menu')]]))
        return ADMIN_MENU
    await query.edit_message_text("Неизвестная команда. Возвращаюсь в админ-меню.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data='admin_menu')]]))
    return ADMIN_MENU

# Обработчик сообщений админа
async def admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get('admin_state')
    if state == 'change_mode':
        global current_pricing_mode
        mode = update.message.text.lower().strip()
        if mode in ('hard', 'light'):
            current_pricing_mode = mode
            await update.message.reply_text(f"Режим наценок обновлён: {mode}")
            context.user_data.pop('admin_state', None)
            save_json(PRICES_FILE, PRICES)
            return ADMIN_MENU
        else:
            await update.message.reply_text("Укажите hard или light")
            return ADMIN_MENU
    if state in ('bonus_add', 'bonus_sub'):
        target_user = context.user_data.get('target_user')
        if not target_user:
            await update.message.reply_text("Не выбран пользователь.")
            return ADMIN_MENU
        parts = update.message.text.split(';', 1)
        amount_text = parts[0].strip().replace('₽', '').replace(' ', '')
        if not amount_text.isdigit():
            await update.message.reply_text("Введите сумму числом, пример: 1500;Причина")
            return ADMIN_MENU
        amount = int(amount_text)
        reason = parts[1].strip() if len(parts) > 1 else ('Корректировка бонусов' if state == 'bonus_add' else 'Списание бонусов')
        if state == 'bonus_add':
            await add_bonus(target_user, amount, reason, context, admin_id=update.effective_user.id)
            await update.message.reply_text(f"Начислено {amount}₽ пользователю {target_user}.")
        else:
            deducted = await deduct_bonus(target_user, amount, reason, context, admin_id=update.effective_user.id)
            await update.message.reply_text(f"Списано {deducted}₽ у пользователя {target_user}.")
        context.user_data.pop('admin_state', None)
        context.user_data.pop('target_user', None)
        return ADMIN_MENU
    if state == 'price_manual':
        edit_info = context.user_data.get('price_edit')
        if not edit_info:
            await update.message.reply_text("Не выбран параметр.")
            return ADMIN_MENU
        value_text = update.message.text.strip().replace('₽', '').replace(' ', '')
        if not value_text.isdigit():
            await update.message.reply_text("Введите число в рублях.")
            return ADMIN_MENU
        value = int(value_text)
        type_key = edit_info['type']
        field = edit_info['field']
        settings = PRICES.get(type_key)
        if not settings:
            await update.message.reply_text("Тип не найден.")
            context.user_data.pop('price_edit', None)
            context.user_data.pop('admin_state', None)
            return ADMIN_MENU
        settings[field] = value
        if settings.get('min') is None:
            settings['min'] = settings['base']
        if settings.get('max') is None:
            settings['max'] = settings['base']
        if settings['min'] > settings['base']:
            settings['base'] = settings['min']
        if settings['base'] > settings['max']:
            settings['max'] = settings['base']
        if settings['min'] > settings['max']:
            settings['max'] = settings['min']
        save_json(PRICES_FILE, PRICES)
        await update.message.reply_text("Значение обновлено.")
        context.user_data.pop('price_edit', None)
        context.user_data.pop('admin_state', None)
        return ADMIN_MENU
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
            INPUT_REQUIREMENTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_requirements), CommandHandler('skip', skip_requirements)],
            ADD_UPSSELL: [CallbackQueryHandler(upsell_handler)],
            ADD_ANOTHER_ORDER: [CallbackQueryHandler(add_another_handler)],
            CONFIRM_CART: [CallbackQueryHandler(confirm_cart_handler), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bonus_amount_message)],
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
        fallbacks=[CommandHandler('start', start)],
    )
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
