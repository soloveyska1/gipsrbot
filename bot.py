import os
import sys
import logging
import json
from datetime import datetime, timedelta
from html import escape
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
        f"Контакт: {format_contact_link(order.get('contact'))}",
        f"Требования: {escape(order.get('requirements', 'Нет'))}",
    ]
    if order.get('upsells'):
        upsells_readable = ', '.join(UPSELL_TITLES.get(code, code) for code in order['upsells'])
        lines.append(f"Допы: {escape(upsells_readable)}")
    else:
        lines.append("Допы: нет")
    lines.append(f"Файлов: {len(order.get('attachments') or [])}")
    if order.get('created_at'):
        lines.append(f"Создан: {escape(order['created_at'])}")
    return '<br>'.join(lines)

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

current_pricing_mode = 'light'

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
    return SELECT_MAIN_MENU

# Выбор типа заказа
async def select_order_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await answer_callback(query)
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
    await answer_callback(query)
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
    await answer_callback(query)
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
    return await prompt_file_upload(update, context)

async def skip_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['requirements'] = 'Нет'
    return await prompt_file_upload(update, context)

async def prompt_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['current_files'] = []
    context.user_data.pop('current_contact', None)
    text = (
        "Прикрепите файлы для заказа (если они есть). Отправьте все документы подряд.\n"
        "Когда закончите, нажмите /done. Если файлов нет, нажмите /skip."
    )
    if update.message:
        await update.message.reply_text(text)
    elif update.callback_query:
        query = update.callback_query
        await answer_callback(query)
        await query.edit_message_text(text)
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
    context.user_data.pop('current_contact', None)
    prompt = (
        "Укажите контакт, куда менеджеру написать (Telegram, ВКонтакте, почта). Это обязательное поле."
    )
    last_contact = context.user_data.get('last_contact')
    if last_contact:
        prompt += f"\nРанее вы указывали: {last_contact}. Можно отправить его снова или написать другой."
    if update.message:
        await update.message.reply_text(prompt)
    elif update.callback_query:
        query = update.callback_query
        await answer_callback(query)
        await query.edit_message_text(prompt)
    return INPUT_CONTACT

async def input_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.text.strip()
    if not contact:
        await update.message.reply_text("Контакт обязателен. Пожалуйста, укажите, куда менеджеру написать.")
        return INPUT_CONTACT
    context.user_data['current_contact'] = contact
    context.user_data['last_contact'] = contact
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
    attachments = list(context.user_data.get('current_files', []))
    contact = context.user_data.get('current_contact') or context.user_data.get('last_contact', '')
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
        'status': 'новый',
        'attachments': attachments,
        'contact': contact,
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
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
            "Заказ оформлен! С вами свяжется [администратор](https://t.me/Thisissaymoon) в ближайшее время. "
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
    text = f"👤 Профиль {user.first_name}\n\nЗаказов: {orders_count}\nОтзывов: {feedbacks_count}\nРефералов: {refs_count}\nРеф. ссылка: {ref_link}\n\nПриглашайте друзей за бонусы!"
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
        for order in user_orders:
            name = ORDER_TYPES.get(order.get('type'), {}).get('name', 'Неизвестно')
            text += f"#{order.get('order_id', 'N/A')}: {name} - {order.get('status', 'новый')}\n"
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
        [InlineKeyboardButton("📋 Заказы", callback_data='admin_orders')],
        [InlineKeyboardButton("👥 Пользователи", callback_data='admin_users'), InlineKeyboardButton("📊 Логи", callback_data='admin_logs')],
        [InlineKeyboardButton("💲 Цены", callback_data='admin_prices')],
        [InlineKeyboardButton("📤 Экспорт", callback_data='admin_export')],
        [InlineKeyboardButton("⬅️ Выход", callback_data='back_to_main')]
    ]
    text = "🔐 Админ-панель"
    if update.callback_query:
        query = update.callback_query
        await answer_callback(query)
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
    await answer_callback(query)
    data = query.data
    if data == 'admin_menu':
        return await show_admin_menu(update, context)
    if data == 'admin_orders':
        text_lines = []
        buttons = []
        for uid, ords in ORDERS.items():
            for ord_data in ords:
                text_lines.append(f"#{ord_data.get('order_id', 'N/A')} от {uid}: {ord_data.get('status', 'новый')}")
                buttons.append([
                    InlineKeyboardButton(
                        f"#{ord_data.get('order_id', 'N/A')} ({uid})",
                        callback_data=f"admin_order|{uid}|{ord_data.get('order_id', 'N/A')}"
                    )
                ])
        if not text_lines:
            text = "Заказы отсутствуют."
        else:
            text = "📋 Заказы:\n" + "\n".join(text_lines[:20])
        buttons.append([InlineKeyboardButton("Назад", callback_data='admin_menu')])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))
        return ADMIN_MENU
    if data.startswith('admin_order|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text("Некорректный идентификатор заказа.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data='admin_orders')]]))
            return ADMIN_MENU
        order = next((o for o in ORDERS.get(uid, []) if str(o.get('order_id')) == order_id_str), None)
        if not order:
            await query.edit_message_text("Заказ не найден.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data='admin_orders')]]))
            return ADMIN_MENU
        text = build_order_details(uid, order)
        keyboard = [
            [InlineKeyboardButton("Отменить заказ", callback_data=f'admin_cancel|{uid}|{order_id_str}')],
            [InlineKeyboardButton("Удалить заказ", callback_data=f'admin_delete|{uid}|{order_id_str}')],
            [InlineKeyboardButton("⬅️ К списку", callback_data='admin_orders')]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        return ADMIN_MENU
    if data.startswith('admin_cancel|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text("Некорректный идентификатор заказа.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data='admin_orders')]]))
            return ADMIN_MENU
        order = next((o for o in ORDERS.get(uid, []) if str(o.get('order_id')) == order_id_str), None)
        if not order:
            await query.edit_message_text("Заказ не найден.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data='admin_orders')]]))
            return ADMIN_MENU
        order['status'] = 'отменен'
        save_json(ORDERS_FILE, ORDERS)
        text = f"Статус заказа #{order_id_str} обновлен на 'отменен'."
        keyboard = [
            [InlineKeyboardButton("Посмотреть заказ", callback_data=f'admin_order|{uid}|{order_id_str}')],
            [InlineKeyboardButton("⬅️ К списку", callback_data='admin_orders')]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return ADMIN_MENU
    if data.startswith('admin_delete|'):
        try:
            _, uid, order_id_str = data.split('|', 2)
        except ValueError:
            await query.edit_message_text("Некорректный идентификатор заказа.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data='admin_orders')]]))
            return ADMIN_MENU
        orders_list = ORDERS.get(uid, [])
        new_list = [o for o in orders_list if str(o.get('order_id')) != order_id_str]
        if len(new_list) == len(orders_list):
            await query.edit_message_text("Заказ не найден.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data='admin_orders')]]))
            return ADMIN_MENU
        if new_list:
            ORDERS[uid] = new_list
        else:
            ORDERS.pop(uid, None)
        save_json(ORDERS_FILE, ORDERS)
        text = f"Заказ #{order_id_str} удален."
        keyboard = [
            [InlineKeyboardButton("⬅️ К списку", callback_data='admin_orders')],
            [InlineKeyboardButton("Админ-меню", callback_data='admin_menu')]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return ADMIN_MENU
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
            INPUT_REQUIREMENTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_requirements), CommandHandler('skip', skip_requirements)],
            UPLOAD_FILES: [
                MessageHandler(filters.Document.ALL, handle_document_upload),
                MessageHandler(filters.PHOTO, handle_photo_upload),
                MessageHandler(filters.TEXT & ~filters.COMMAND, files_text_reminder),
                CommandHandler('skip', skip_files),
                CommandHandler('done', finish_files)
            ],
            INPUT_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_contact)],
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
        fallbacks=[CommandHandler('start', start)],
    )
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)
    application.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()