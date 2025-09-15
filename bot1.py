import os
import sys
import logging
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters, ConversationHandler
)
from telegram.constants import ParseMode
from dotenv import load_dotenv
import re

# Загрузка переменных окружения
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')

# Проверка обязательных переменных окружения
if not TELEGRAM_BOT_TOKEN:
    print("ОШИБКА: Не найден TELEGRAM_BOT_TOKEN в переменных окружения!")
    print("Создайте файл .env и добавьте в него:")
    print("TELEGRAM_BOT_TOKEN=ваш_токен_бота")
    print("ADMIN_CHAT_ID=ваш_telegram_id")
    sys.exit(1)

if not ADMIN_CHAT_ID:
    print("ОШИБКА: Не найден ADMIN_CHAT_ID в переменных окружения!")
    print("Добавьте в файл .env строку:")
    print("ADMIN_CHAT_ID=ваш_telegram_id")
    sys.exit(1)

try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
except ValueError:
    print(f"ОШИБКА: ADMIN_CHAT_ID должен быть числом, получено: {ADMIN_CHAT_ID}")
    sys.exit(1)

# Настройка базовых директорий
# Используем относительные пути от текущей директории
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.join(SCRIPT_DIR, "gipsr_bot", "clients")
DATA_DIR = os.path.join(SCRIPT_DIR, "gipsr_bot", "data")
LOGS_DIR = os.path.join(SCRIPT_DIR, "gipsr_bot", "logs")
ASSETS_DIR = os.path.join(SCRIPT_DIR, "gipsr_bot", "assets")

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Создание необходимых директорий
for directory in [BASE_DIR, os.path.join(BASE_DIR, 'feedbacks'), DATA_DIR, LOGS_DIR, ASSETS_DIR]:
    try:
        os.makedirs(directory, exist_ok=True)
        logger.info(f"Создана директория: {directory}")
    except Exception as e:
        logger.error(f"Ошибка при создании директории {directory}: {e}")

# Логирование в файл
file_handler = logging.FileHandler(os.path.join(LOGS_DIR, 'bot.log'))
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

# Файлы для хранения данных
PRICES_FILE = os.path.join(DATA_DIR, 'prices.json')
REFERRALS_FILE = os.path.join(DATA_DIR, 'referrals.json')
ORDERS_FILE = os.path.join(DATA_DIR, 'orders.json')
FEEDBACKS_FILE = os.path.join(DATA_DIR, 'feedbacks.json')

# Типы заказов
ORDER_TYPES = {
    'self': {
        'name': 'Самостоятельная работа',
        'icon': '📝',
        'description': 'Идеально для небольших заданий, эссе, контрольных работ. Выполняется быстро и качественно.',
        'details': 'Самостоятельные работы включают небольшие эссе, задания по предметам, тесты и контрольные. Обычно объемом до 20 страниц.',
        'examples': ['Эссе по философии', 'Контрольная по экономике', 'Реферат по истории']
    },
    'course_theory': {
        'name': 'Курсовая работа (теоретическая)',
        'icon': '📘',
        'description': 'Теоретическая курсовая работа с глубоким анализом литературы и источников.',
        'details': 'Теоретическая курсовая включает анализ научной литературы, построение теоретических моделей без эмпирической части.',
        'examples': ['Анализ теоретических подходов к социальной работе', 'Обзор методологий исследования', 'Теоретические основы психологии развития']
    },
    'course_empirical': {
        'name': 'Курсовая работа (теория + эмпирика)',
        'icon': '📊',
        'description': 'Курсовая с эмпирической частью, анализом данных и практическими рекомендациями.',
        'details': 'Эмпирическая курсовая работа включает как теоретическую часть, так и практическое исследование с анализом полученных данных.',
        'examples': ['Исследование социальной адаптации мигрантов', 'Анализ эффективности методов психотерапии', 'Опрос по уровню удовлетворенности клиентов']
    },
    'vkr': {
        'name': 'ВКР',
        'icon': '🎓',
        'description': 'Выпускная квалификационная работа для завершения обучения с полным циклом исследования.',
        'details': 'ВКР - это итоговая научная работа для получения диплома бакалавра. Включает глубокий теоретический анализ и объемное эмпирическое исследование.',
        'examples': ['Комплексное исследование социально-психологической адаптации', 'Проектирование системы социальной поддержки', 'Анализ эффективности социальных программ']
    },
    'master': {
        'name': 'Магистерская диссертация',
        'icon': '🔍',
        'description': 'Глубокое научное исследование для магистратуры с инновационным подходом.',
        'details': 'Магистерская диссертация - это научное исследование высокого уровня, демонстрирующее способность к самостоятельной научной работе.',
        'examples': ['Разработка методологии оценки эффективности социальных программ', 'Комплексное исследование психологических аспектов', 'Проектирование инновационных методов работы']
    }
}

# Режимы ценообразования
PRICING_MODES = {
    'hard': {
        'name': 'Hard Mode',
        'icon': '💲',
        'description': '<7 дней: +30%, 8-14 дней: +15%, >14 дней: базовая цена.'
    },
    'light': {
        'name': 'Light Mode',
        'icon': '💰',
        'description': '<3 дней: +30%, >=7 дней: базовая цена.'
    }
}

# FAQ
FAQ_ITEMS = [
    {
        'question': 'Как сделать заказ?',
        'answer': 'Для заказа работы выберите пункт "📝 Сделать заказ" в главном меню. Затем следуйте инструкциям: выберите тип работы, введите тему, укажите дедлайн и дополнительные требования. После подтверждения заказа с вами свяжется менеджер для уточнения деталей.'
    },
    {
        'question': 'Как рассчитывается стоимость?',
        'answer': 'Стоимость зависит от трех основных факторов: тип работы, срочность выполнения и сложность темы. Базовые цены указаны в прайс-листе. При срочном выполнении (менее 7 дней) применяется наценка 15-30%. Для получения точной стоимости воспользуйтесь калькулятором цен в разделе "Прайс-лист".'
    },
    {
        'question': 'Как работает реферальная программа?',
        'answer': 'В разделе "Мой профиль" вы найдете вашу персональную реферальную ссылку. Поделитесь ею с друзьями, и когда они закажут работу по вашей ссылке, вы получите бонус в размере 5% от стоимости их заказа. Бонусы можно использовать для оплаты своих заказов.'
    },
    {
        'question': 'Какие гарантии качества работы?',
        'answer': 'Мы гарантируем высокое качество всех работ. Каждая работа проходит проверку на плагиат и соответствие требованиям. После выполнения работы предоставляется бесплатное внесение правок в течение 14 дней. В случае необходимости мы обеспечиваем полную поддержку до успешной защиты работы.'
    },
    {
        'question': 'Могу ли я получить скидку?',
        'answer': 'Да, у нас действует система скидок: 5% при заказе от 10 000 руб., 10% при заказе от 20 000 руб. Постоянные клиенты получают персональные скидки до 15%. Также действуют сезонные акции и специальные предложения, о которых вы можете узнать у менеджера.'
    },
    {
        'question': 'Как отслеживать процесс выполнения заказа?',
        'answer': 'В разделе "Мой профиль" вы можете видеть статус всех ваших заказов. Также наш менеджер будет регулярно информировать вас о ходе выполнения работы. Вы всегда можете запросить промежуточные результаты для оценки работы.'
    }
]

# Глобальные переменные
current_pricing_mode = 'light'
user_orders = {}
user_ids = set()
user_feedbacks = {}

# Состояния для ConversationHandler
(
    START,
    SELECT_MAIN_MENU,
    SELECT_ORDER_TYPE,
    VIEW_ORDER_DETAILS,
    INPUT_TOPIC,
    INPUT_DEADLINE,
    INPUT_REQUIREMENTS,
    CALCULATE_PRICE,
    CONFIRM_ORDER,
    ADMIN_MENU,
    PROFILE_MENU,
    SHOW_PRICE_LIST,
    PRICE_CALCULATOR,
    SHOW_FAQ,
    FAQ_DETAILS,
    SHOW_ORDERS,
    LEAVE_FEEDBACK,
    INPUT_FEEDBACK
) = range(18)

# Функции для работы с ценами
def load_prices():
    try:
        if os.path.exists(PRICES_FILE):
            with open(PRICES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        default_prices = {
            'self': {'base': 1500, 'min': 1000, 'max': 3000},
            'course_theory': {'base': 7000, 'min': 5000, 'max': 10000},
            'course_empirical': {'base': 11000, 'min': 8000, 'max': 15000},
            'vkr': {'base': 32000, 'min': 25000, 'max': 45000},
            'master': {'base': 42000, 'min': 35000, 'max': 60000}
        }
        save_prices(default_prices)
        return default_prices
    except Exception as e:
        logger.error(f"Ошибка при загрузке цен: {e}")
        return {
            'self': {'base': 1500, 'min': 1000, 'max': 3000},
            'course_theory': {'base': 7000, 'min': 5000, 'max': 10000},
            'course_empirical': {'base': 11000, 'min': 8000, 'max': 15000},
            'vkr': {'base': 32000, 'min': 25000, 'max': 45000},
            'master': {'base': 42000, 'min': 35000, 'max': 60000}
        }

def save_prices(prices):
    try:
        with open(PRICES_FILE, 'w', encoding='utf-8') as f:
            json.dump(prices, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка при сохранении цен: {e}")

PRICES = load_prices()

# Функции для работы с рефералами
def load_referrals():
    try:
        if os.path.exists(REFERRALS_FILE):
            with open(REFERRALS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Ошибка при загрузке рефералов: {e}")
        return {}

def save_referrals(data):
    try:
        with open(REFERRALS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка при сохранении рефералов: {e}")

referrals = load_referrals()

# Функции для работы с заказами
def load_orders():
    try:
        if os.path.exists(ORDERS_FILE):
            with open(ORDERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Ошибка при загрузке заказов: {e}")
        return {}

def save_orders(data):
    try:
        with open(ORDERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка при сохранении заказов: {e}")

# Функции для работы с отзывами
def load_feedbacks():
    try:
        if os.path.exists(FEEDBACKS_FILE):
            with open(FEEDBACKS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Ошибка при загрузке отзывов: {e}")
        return {}

def save_feedbacks(data):
    try:
        with open(FEEDBACKS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка при сохранении отзывов: {e}")

user_feedbacks = load_feedbacks()

# Расчет цены
def calculate_price(order_type_key, days_left, complexity_factor=1.0):
    try:
        prices = PRICES.get(order_type_key, {'base': 0})
        base_price = prices.get('base', 0)
        base_price = int(base_price * complexity_factor)

        if current_pricing_mode == 'hard':
            if days_left <= 7:
                return int(base_price * 1.3)
            elif 8 <= days_left <= 14:
                return int(base_price * 1.15)
            else:
                return base_price
        else:
            if days_left <= 3:
                return int(base_price * 1.3)
            elif 4 <= days_left <= 6:
                return int(base_price * 1.15)
            else:
                return base_price
    except Exception as e:
        logger.error(f"Ошибка при расчете цены: {e}")
        return PRICES.get(order_type_key, {'base': 0}).get('base', 0)

# Стилизованное сообщение
def generate_styled_message(title, content, footer=None):
    message = f"*{title}*\n\n{content}"
    if footer:
        message += f"\n\n_{footer}_"
    return message

# Обработчик ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка при обработке обновления: {context.error}")
    try:
        error_message = f"⚠️ *Ошибка в боте*\n\nError: {context.error}\n"
        if update and update.effective_user:
            error_message += f"User: @{update.effective_user.username} (ID: {update.effective_user.id})\n"
        if update and update.effective_message:
            error_message += f"Message: {update.effective_message.text[:50]}...\n"
        
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=error_message,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение об ошибке админу: {e}")
    
    try:
        if update and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Извините, произошла ошибка. Попробуйте снова или используйте /start."
            )
    except:
        pass

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_ids.add(user.id)
    
    # Отправляем уведомление админу о новом пользователе
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"👤 *Новый пользователь в боте*\n\n"
                 f"Имя: {user.first_name} {user.last_name or ''}\n"
                 f"Username: @{user.username or 'отсутствует'}\n"
                 f"ID: `{user.id}`\n"
                 f"Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления админа о новом пользователе: {e}")
    
    text = update.message.text
    args = text.split()

    try:
        bot = await context.bot.get_me()
        bot_username = bot.username
    except Exception as e:
        logger.error(f"Ошибка получения данных бота: {e}")
        bot_username = "Kladovaya_GIPSR_bot"

    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if referrer_id != user.id:
            referrals.setdefault(str(referrer_id), [])
            if user.id not in referrals[str(referrer_id)]:
                referrals[str(referrer_id)].append(user.id)
                save_referrals(referrals)
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 Ваш реферал {user.first_name} (@{user.username or 'без имени'}) присоединился!"
                    )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления рефереру: {e}")

    ref_link = f"https://t.me/{bot_username}?start={user.id}"
    context.user_data['ref_link'] = ref_link

    welcome_message = (
        f"🎓 *Добро пожаловать в Кладовую ГИПСР, {user.first_name}!*\n\n"
        f"✨ *Что мы предлагаем:*\n"
        f"• Качественные академические работы любой сложности\n"
        f"• Гарантия уникальности от 75%\n"
        f"• Бесплатные правки в течение 14 дней\n"
        f"• Поддержка до успешной защиты\n"
        f"• Конфиденциальность и безопасность\n\n"
        f"💡 *Как сделать заказ:*\n"
        f"1️⃣ Нажмите «Сделать заказ»\n"
        f"2️⃣ Выберите тип работы\n"
        f"3️⃣ Укажите тему и срок\n"
        f"4️⃣ Получите точную стоимость\n"
        f"5️⃣ Менеджер свяжется с вами\n\n"
        f"🎁 *Бонусы:*\n"
        f"• Скидка 10% на первый заказ\n"
        f"• Реферальная программа - 5% от заказов друзей\n"
        f"• Накопительные скидки для постоянных клиентов\n\n"
        f"📱 *Выберите действие:*"
    )
    return await main_menu(update, context, welcome_message)

# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📋 *Основные команды:*\n\n"
        "/start - Главное меню\n"
        "/help - Список команд\n"
        "/order - Новый заказ\n"
        "/profile - Личный кабинет\n"
        "/price - Прайс-лист\n"
        "/faq - Часто задаваемые вопросы\n"
        "/admin - Панель администратора\n\n"
        "Свяжитесь с менеджером через главное меню при необходимости."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# Команда /price
async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    orders_count = len(user_orders.get(user_id, []))
    discount = 0
    if orders_count >= 5:
        discount = 15
    elif orders_count >= 3:
        discount = 10
    elif orders_count >= 1:
        discount = 5
    
    text = "🎓 *ПРАЙС-ЛИСТ КЛАДОВОЙ ГИПСР*\n\n"
    
    if discount > 0:
        text += f"🎉 *Ваша персональная скидка: {discount}%*\n\n"
    
    text += "📍 *Актуальные цены на 2024 год:*\n\n"
    
    for key, val in PRICES.items():
        order_type = ORDER_TYPES.get(key, {})
        base_price = val.get('base', 0)
        if discount > 0:
            discounted_price = int(base_price * (1 - discount/100))
            text += f"{order_type.get('icon', '')} *{order_type.get('name', key)}*\n"
            text += f"   ├ ~{base_price:,}~ *{discounted_price:,} руб.*\n"
            text += f"   └ 🎯 Срок: от 3 дней\n\n"
        else:
            text += f"{order_type.get('icon', '')} *{order_type.get('name', key)}*\n"
            text += f"   ├ 💰 *{base_price:,} руб.*\n"
            text += f"   └ 🎯 Срок: от 3 дней\n\n"
    
    text += "🎁 *Специальные предложения:*\n"
    text += "• Скидка 10% на первый заказ\n"
    text += "• Приведи друга - получи 500₽ бонус\n"
    text += "• Заказ от 2 работ = скидка 15%\n"

    keyboard = [
        [InlineKeyboardButton("🧮 Рассчитать точную цену", callback_data='price_calculator')],
        [InlineKeyboardButton("🎯 Быстрый заказ", callback_data='make_order')],
        [InlineKeyboardButton("🏠 Главное меню", callback_data='back_to_main')]
    ]
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    return SHOW_PRICE_LIST

# Команда /faq
async def faq_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "❓ *Часто задаваемые вопросы*\n\nВыберите вопрос:\n"
    keyboard = [[InlineKeyboardButton(f"{idx+1}. {item['question']}", callback_data=f'faq_{idx}')] for idx, item in enumerate(FAQ_ITEMS)]
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data='back_to_main')])
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    return SHOW_FAQ

# Команда /order
async def order_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await select_order_type(update, context)

# Команда /profile
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    orders = user_orders.get(str(user.id), []) or load_orders().get(str(user.id), [])
    
    try:
        bot = await context.bot.get_me()
        bot_username = bot.username
    except Exception as e:
        logger.error(f"Ошибка получения данных бота: {e}")
        bot_username = "Kladovaya_GIPSR_bot"
    
    ref_link = f"https://t.me/{bot_username}?start={user.id}"
    context.user_data['ref_link'] = ref_link
    
    ref_count = len(referrals.get(str(user.id), []))
    bonus = sum(int(order.get('price', 0) * 0.05) for ref_id in referrals.get(str(user.id), []) for order in user_orders.get(str(ref_id), []))

    text = (
        f"👤 *Личный кабинет*\n\n"
        f"*Имя:* {user.first_name}\n"
        f"*Username:* @{user.username if user.username else 'отсутствует'}\n"
        f"*ID:* `{user.id}`\n\n"
        f"*Реферальная программа:*\n"
        f"- Приглашено: {ref_count}\n"
        f"- Бонус: {bonus} руб.\n"
        f"- Ссылка: `{ref_link}`\n\n"
    )

    if orders:
        text += "*Ваши заказы:*\n"
        recent_orders = sorted(orders, key=lambda x: x.get('date', ''), reverse=True)[:3]
        for o in recent_orders:
            text += f"- Заказ #{o.get('order_id', 'N/A')}: {o.get('type')} | Статус: {o.get('status')}\n"
        if len(orders) > 3:
            text += f"\n_...и еще {len(orders) - 3} заказов_\n"
    else:
        text += "У вас пока нет заказов."

    keyboard = [
        [InlineKeyboardButton("📋 Все заказы", callback_data='show_all_orders')],
        [InlineKeyboardButton("📝 Новый заказ", callback_data='make_order')],
        [InlineKeyboardButton("✍️ Оставить отзыв", callback_data='leave_feedback')],
        [InlineKeyboardButton("🏠 Главное меню", callback_data='back_to_main')]
    ]

    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PROFILE_MENU

# Главное меню
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, custom_message=None):
    try:
        user = update.effective_user
        keyboard = [
            [InlineKeyboardButton("📝 Сделать заказ", callback_data='make_order')],
            [InlineKeyboardButton("💲 Прайс-лист", callback_data='price_list'),
             InlineKeyboardButton("👤 Мой профиль", callback_data='profile')],
            [InlineKeyboardButton("❓ FAQ", callback_data='faq')],
            [InlineKeyboardButton("📞 Администратор", url='https://t.me/Thisissaymoon')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = custom_message or f"👋 *Привет, {user.first_name}!*\n\nВыберите раздел:"

        if update.callback_query:
            await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        return SELECT_MAIN_MENU
    except Exception as e:
        logger.error(f"Ошибка в main_menu: {e}")
        return SELECT_MAIN_MENU

# Обработчик главного меню
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == 'make_order':
        return await select_order_type(update, context)
    elif choice == 'price_list':
        return await show_price_list(update, context)
    elif choice == 'profile':
        return await show_profile(update, context)
    elif choice == 'faq':
        return await show_faq(update, context)
    elif choice == 'back_to_main':
        return await main_menu(update, context)
    
    await query.message.reply_text("Неизвестный выбор.")
    return SELECT_MAIN_MENU

# Прайс-лист
async def show_price_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Подсчет скидки для постоянного клиента
    user_id = str(update.effective_user.id)
    orders_count = len(user_orders.get(user_id, []))
    discount = 0
    if orders_count >= 5:
        discount = 15
    elif orders_count >= 3:
        discount = 10
    elif orders_count >= 1:
        discount = 5
    
    text = "🎓 *ПРАЙС-ЛИСТ КЛАДОВОЙ ГИПСР*\n\n"
    
    if discount > 0:
        text += f"🎉 *Ваша персональная скидка: {discount}%*\n\n"
    
    text += "📍 *Актуальные цены на 2024 год:*\n\n"
    
    for key, val in PRICES.items():
        order_type = ORDER_TYPES.get(key, {})
        base_price = val.get('base', 0)
        if discount > 0:
            discounted_price = int(base_price * (1 - discount/100))
            text += f"{order_type.get('icon', '')} *{order_type.get('name', key)}*\n"
            text += f"   ├ ~{base_price:,}~ *{discounted_price:,} руб.*\n"
            text += f"   └ 🎯 Срок: от 3 дней\n\n"
        else:
            text += f"{order_type.get('icon', '')} *{order_type.get('name', key)}*\n"
            text += f"   ├ 💰 *{base_price:,} руб.*\n"
            text += f"   └ 🎯 Срок: от 3 дней\n\n"
    
    text += "🎁 *Специальные предложения:*\n"
    text += "• Скидка 10% на первый заказ\n"
    text += "• Приведи друга - получи 500₽ бонус\n"
    text += "• Заказ от 2 работ = скидка 15%\n\n"
    text += "🔥 *Почему выбирают нас:*\n"
    text += "• 100% гарантия сдачи\n"
    text += "• Бесплатная доработка\n"
    text += "• Антиплагиат от 75%\n"

    keyboard = [
        [InlineKeyboardButton("🧮 Рассчитать точную цену", callback_data='price_calculator')],
        [InlineKeyboardButton("🎯 Быстрый заказ", callback_data='make_order')],
        [InlineKeyboardButton("🏠 Главное меню", callback_data='back_to_main')]
    ]
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    return SHOW_PRICE_LIST

# Калькулятор стоимости
async def price_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Отправляем уведомление админу
    user = update.effective_user
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"🧮 *Пользователь открыл калькулятор*\n\n"
                 f"Имя: {user.first_name}\n"
                 f"Username: @{user.username or 'отсутствует'}\n"
                 f"ID: `{user.id}`\n"
                 f"Время: {datetime.now().strftime('%H:%M')}",
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        pass
    
    text = (
        "🎆 *ИНТЕРАКТИВНЫЙ КАЛЬКУЛЯТОР ЦЕН*\n\n"
        "🎁 *СПЕЦИАЛЬНОЕ ПРЕДЛОЖЕНИЕ!*\n"
        "При заказе сегодня - скидка 10%!\n\n"
        "👇 *Шаг 1: Выберите тип работы*\n\n"
        "Какую работу вы хотите заказать?"
    )
    
    keyboard = []
    for key, val in ORDER_TYPES.items():
        price = PRICES[key]['base']
        # Показываем цену прямо в кнопке
        button_text = f"{val['icon']} {val['name']} | {price:,}₽"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f'calc_{key}')])
    
    keyboard.append([InlineKeyboardButton("🎁 Пакетное предложение (2+ работы)", callback_data='calc_package')])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='back_to_price')])
    
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    return PRICE_CALCULATOR

# Расчет цены в калькуляторе
async def calculate_price_in_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'calc_package':
        # Пакетное предложение
        text = (
            "🎁 *ПАКЕТНОЕ ПРЕДЛОЖЕНИЕ*\n\n"
            "🔥 *Закажите 2+ работ и получите:*\n\n"
            "✅ Скидка 15% на все работы\n"
            "✅ Приоритетное выполнение\n"
            "✅ Один менеджер на весь заказ\n\n"
            "💰 *Примеры экономии:*\n\n"
            "📚 Курсовая + Самостоятельная:\n"
            "~12,500₽~ → *10,625₽* (экономия 1,875₽)\n\n"
            "🎓 Курсовая + ВКР:\n"
            "~43,000₽~ → *36,550₽* (экономия 6,450₽)\n\n"
            "🎆 Полный комплект (все 5 типов):\n"
            "~93,500₽~ → *79,475₽* (экономия 14,025₽!)\n\n"
            "📞 *Оформить пакет?*"
        )
        keyboard = [
            [InlineKeyboardButton("🚀 Оформить пакет", callback_data='make_order')],
            [InlineKeyboardButton("🔄 К выбору работ", callback_data='price_calculator')],
            [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_price')]
        ]
        await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        return PRICE_CALCULATOR
    
    order_type_key = query.data.replace('calc_', '')
    if order_type_key not in ORDER_TYPES:
        await query.message.reply_text("Неизвестный тип работы.")
        return PRICE_CALCULATOR

    order_type_info = ORDER_TYPES[order_type_key]
    price_info = PRICES[order_type_key]
    context.user_data['calc_type'] = order_type_key
    
    text = (
        f"🎆 *КАЛЬКУЛЯТОР ЦЕН*\n\n"
        f"{order_type_info['icon']} *{order_type_info['name']}*\n\n"
        f"📍 Базовая цена: *{price_info['base']:,} руб.*\n\n"
        f"🕐 *Шаг 2: Выберите срок выполнения*\n\n"
        f"Чем больше времени - тем ниже цена:"
    )
    
    # Создаем кнопки с ценами
    keyboard = []
    deadlines = [(3, '🔴 Срочно (3 дня)'), 
                 (7, '🟡 Быстро (7 дней)'),
                 (14, '🟢 Оптимально (14 дней)'),
                 (30, '🔵 Комфортно (30 дней)')]
    
    for days, label in deadlines:
        price = calculate_price(order_type_key, days)
        if days <= 7:
            price_text = f"{label} | {price:,}₽ (+{int((price/price_info['base']-1)*100)}%)"
        else:
            price_text = f"{label} | {price:,}₽"
        keyboard.append([InlineKeyboardButton(price_text, callback_data=f'deadline_{order_type_key}_{days}')])
    
    keyboard.append([InlineKeyboardButton("🔄 Другая работа", callback_data='price_calculator')])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='back_to_price')])
    
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    return PRICE_CALCULATOR

# Обработчик выбора срока в калькуляторе
async def handle_deadline_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('_')
    order_type_key = parts[1]
    days = int(parts[2])
    
    order_type_info = ORDER_TYPES[order_type_key]
    base_price = PRICES[order_type_key]['base']
    final_price = calculate_price(order_type_key, days)
    
    # Проверяем скидки пользователя
    user_id = str(update.effective_user.id)
    orders_count = len(user_orders.get(user_id, []))
    loyalty_discount = 0
    if orders_count >= 5:
        loyalty_discount = 15
    elif orders_count >= 3:
        loyalty_discount = 10
    elif orders_count >= 1:
        loyalty_discount = 5
    
    # Скидка для первого заказа
    if orders_count == 0:
        loyalty_discount = 10
        discount_text = "Скидка новому клиенту"
    else:
        discount_text = f"Ваша постоянная скидка"
    
    final_price_with_discount = int(final_price * (1 - loyalty_discount/100))
    
    text = (
        f"🎯 *ИТОГОВЫЙ РАСЧЕТ*\n\n"
        f"{order_type_info['icon']} *{order_type_info['name']}*\n"
        f"📅 Срок: {days} дней\n\n"
        f"💰 *Стоимость:*\n"
        f"Базовая цена: {base_price:,} руб.\n"
    )
    
    if days <= 7:
        urgency_percent = int((final_price/base_price - 1) * 100)
        text += f"Срочность (+{urgency_percent}%): {final_price - base_price:,} руб.\n"
    
    text += f"─────────────────\n"
    text += f"Итого: {final_price:,} руб.\n\n"
    
    if loyalty_discount > 0:
        text += f"🎁 *{discount_text}: {loyalty_discount}%*\n"
        text += f"🔥 *ФИНАЛЬНАЯ ЦЕНА: {final_price_with_discount:,} руб.*\n"
        text += f"💵 Вы экономите: {final_price - final_price_with_discount:,} руб.\n\n"
    
    text += (
        "✅ *Что входит в стоимость:*\n"
        "• Полное выполнение работы\n"
        "• Антиплагиат от 75%\n"
        "• Оформление по ГОСТ\n"
        "• Бесплатные правки 14 дней\n"
        "• Поддержка до защиты\n\n"
        "🚀 *Готовы заказать?*"
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ ЗАКАЗАТЬ СЕЙЧАС", callback_data=f'quick_order_{order_type_key}_{days}')],
        [InlineKeyboardButton("💬 Обсудить с менеджером", url='https://t.me/Thisissaymoon')],
        [InlineKeyboardButton("🔄 Изменить параметры", callback_data='price_calculator')],
        [InlineKeyboardButton("🏠 Главное меню", callback_data='back_to_main')]
    ]
    
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    # Отправляем уведомление админу
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"💸 *Пользователь рассчитал цену*\n\n"
                 f"Пользователь: {update.effective_user.first_name}\n"
                 f"Username: @{update.effective_user.username or 'отсутствует'}\n"
                 f"Работа: {order_type_info['name']}\n"
                 f"Срок: {days} дней\n"
                 f"Цена: {final_price_with_discount:,} руб.\n"
                 f"Время: {datetime.now().strftime('%H:%M')}",
            parse_mode=ParseMode.MARKDOWN
        )
    except:
        pass
    
    return PRICE_CALCULATOR

# Возврат к прайс-листу
async def back_to_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await show_price_list(update, context)

# FAQ
async def show_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "❓ *Часто задаваемые вопросы*\n\nВыберите вопрос:\n"
    keyboard = [[InlineKeyboardButton(f"{idx+1}. {item['question']}", callback_data=f'faq_{idx}')] for idx, item in enumerate(FAQ_ITEMS)]
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='back_to_main')])
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    return SHOW_FAQ

# Детали FAQ
async def show_faq_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    faq_idx = int(query.data.replace('faq_', ''))
    if faq_idx < 0 or faq_idx >= len(FAQ_ITEMS):
        await query.message.reply_text("Неизвестный вопрос.")
        return SHOW_FAQ

    faq_item = FAQ_ITEMS[faq_idx]
    text = f"❓ *{faq_item['question']}*\n\n{faq_item['answer']}"
    keyboard = [
        [InlineKeyboardButton("⬅️ Назад к FAQ", callback_data='back_to_faq')],
        [InlineKeyboardButton("🏠 Главное меню", callback_data='back_to_main')]
    ]
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    return FAQ_DETAILS

# Возврат к FAQ
async def back_to_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await show_faq(update, context)

# Выбор типа заказа
async def select_order_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query or update
    if query.callback_query:
        await query.answer()

    keyboard = [[InlineKeyboardButton(f"{val['icon']} {val['name']}", callback_data=f'type_{key}')] for key, val in ORDER_TYPES.items()]
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='back_to_main')])
    text = "📋 *Выберите тип работы:*\n\nНажмите для подробностей и стоимости:"

    if query.callback_query:
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    else:
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    return SELECT_ORDER_TYPE

# Обработчик выбора типа заказа
async def select_order_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    callback_data = query.data

    if callback_data == 'back_to_main':
        return await main_menu(update, context)
    if callback_data.startswith('type_') or callback_data.startswith('order_'):
        order_type_key = callback_data.replace('type_', '').replace('order_', '')
        return await view_order_details(update, context, order_type_key)
    await query.message.reply_text("Неизвестный тип заказа.")
    return SELECT_ORDER_TYPE

# Детали заказа
async def view_order_details(update: Update, context: ContextTypes.DEFAULT_TYPE, order_type_key):
    query = update.callback_query
    if order_type_key not in ORDER_TYPES:
        await query.message.reply_text("Неизвестный тип заказа.")
        return SELECT_ORDER_TYPE

    order_type_info = ORDER_TYPES[order_type_key]
    price_info = PRICES[order_type_key]
    context.user_data['order_type_key'] = order_type_key
    context.user_data['order_type'] = order_type_info['name']

    text = f"*{order_type_info['icon']} {order_type_info['name']}*\n\n{order_type_info['details']}\n\n"
    text += "*Примеры тем:*\n" + "\n".join(f"• {example}" for example in order_type_info['examples'])
    text += f"\n\n*Стоимость:* от {price_info['base']} руб.\n*Срок:* от 3 дней\n\nХотите заказать?"

    keyboard = [
        [InlineKeyboardButton("✅ Заказать", callback_data='continue_order')],
        [InlineKeyboardButton("⬅️ Другой тип", callback_data='back_to_order_type')],
        [InlineKeyboardButton("🏠 Главное меню", callback_data='back_to_main')]
    ]
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    return VIEW_ORDER_DETAILS

# Обработчик деталей заказа
async def order_details_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == 'back_to_order_type':
        return await select_order_type(update, context)
    elif choice == 'back_to_main':
        return await main_menu(update, context)
    elif choice == 'continue_order':
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data='back_to_order_details')]]
        await query.message.edit_text(
            f"Вы выбрали: *{context.user_data['order_type']}*\n\nВведите тему работы:",
            parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return INPUT_TOPIC
    await query.message.reply_text("Неизвестный выбор.")
    return VIEW_ORDER_DETAILS

# Назад к деталям заказа
async def back_to_order_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await view_order_details(update, context, context.user_data['order_type_key'])

# Ввод темы
async def input_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == 'back_to_order_details':
            return await view_order_details(update, context, context.user_data['order_type_key'])
        return

    context.user_data['topic'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("3 дня", callback_data='3'), InlineKeyboardButton("7 дней", callback_data='7'), InlineKeyboardButton("14 дней", callback_data='14')],
        [InlineKeyboardButton("21 день", callback_data='21'), InlineKeyboardButton("30 дней", callback_data='30'), InlineKeyboardButton("Другой", callback_data='custom')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_topic')]
    ]
    await update.message.reply_text(
        "📅 *Выберите срок выполнения:*\n\nЧем больше времени, тем ниже стоимость.",
        parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return INPUT_DEADLINE

# Ввод дедлайна
async def input_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'back_to_topic':
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data='back_to_order_details')]]
        await query.message.edit_text(
            f"Вы выбрали: *{context.user_data['order_type']}*\n\nВведите тему работы:",
            parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return INPUT_TOPIC

    if query.data == 'custom':
        await query.message.edit_text(
            "Введите количество дней (число):",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data='back_to_deadline_select')]])
        )
        return INPUT_DEADLINE

    if query.data == 'back_to_deadline_select':
        keyboard = [
            [InlineKeyboardButton("3 дня", callback_data='3'), InlineKeyboardButton("7 дней", callback_data='7'), InlineKeyboardButton("14 дней", callback_data='14')],
            [InlineKeyboardButton("21 день", callback_data='21'), InlineKeyboardButton("30 дней", callback_data='30'), InlineKeyboardButton("Другой", callback_data='custom')],
            [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_topic')]
        ]
        await query.message.edit_text(
            "📅 *Выберите срок выполнения:*\n\nЧем больше времени, тем ниже стоимость.",
            parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return INPUT_DEADLINE

    try:
        days = int(query.data)
        deadline_date = datetime.now() + timedelta(days=days)
        context.user_data['deadline'] = deadline_date
        context.user_data['days_left'] = days
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data='back_to_deadline')]]
        await query.message.edit_text(
            f"📝 *Требования:*\n\nОпишите требования (объем, структура, источники и т.д.) или напишите 'Нет требований'.",
            parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return INPUT_REQUIREMENTS
    except ValueError:
        await query.message.reply_text("Введите число дней.")
        return INPUT_DEADLINE

# Ввод произвольного дедлайна
async def input_custom_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(update.message.text)
        if days < 1:
            await update.message.reply_text(
                "Введите положительное число дней.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data='back_to_deadline_select')]])
            )
            return INPUT_DEADLINE
        deadline_date = datetime.now() + timedelta(days=days)
        context.user_data['deadline'] = deadline_date
        context.user_data['days_left'] = days
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data='back_to_deadline')]]
        await update.message.reply_text(
            f"📝 *Требования:*\n\nОпишите требования или напишите 'Нет требований'.",
            parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return INPUT_REQUIREMENTS
    except ValueError:
        await update.message.reply_text(
            "Введите число дней.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data='back_to_deadline_select')]])
        )
        return INPUT_DEADLINE

# Назад к дедлайну
async def back_to_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("3 дня", callback_data='3'), InlineKeyboardButton("7 дней", callback_data='7'), InlineKeyboardButton("14 дней", callback_data='14')],
        [InlineKeyboardButton("21 день", callback_data='21'), InlineKeyboardButton("30 дней", callback_data='30'), InlineKeyboardButton("Другой", callback_data='custom')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_topic')]
    ]
    await query.message.edit_text(
        "📅 *Выберите срок выполнения:*\n\nЧем больше времени, тем ниже стоимость.",
        parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return INPUT_DEADLINE

# Ввод требований
async def input_requirements(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == 'back_to_deadline':
            return await back_to_deadline(update, context)
        return

    context.user_data['requirements'] = update.message.text
    return await calculate_price_step(update, context)

# Расчет цены
async def calculate_price_step(update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data
    order_type_key = data.get('order_type_key')
    days_left = data.get('days_left', 7)
    topic = data.get('topic', '')
    requirements = data.get('requirements', '')
    complexity_factor = 1.0 + 0.05 * (len(topic) > 50) + 0.1 * any(term in topic.lower() or term in requirements.lower() for term in ['анализ', 'исследование', 'сравнительный', 'методология', 'эмпирический'])

    price = calculate_price(order_type_key, days_left, complexity_factor)
    data['price'] = price
    data['complexity_factor'] = complexity_factor
    deadline = data.get('deadline')
    deadline_str = deadline.strftime('%d.%m.%Y') if deadline else "Не указан"

    text = (
        f"📋 *Ваш заказ:*\n\n"
        f"*Тип работы:* {data.get('order_type')}\n"
        f"*Тема:* {data.get('topic')}\n"
        f"*Срок:* {deadline_str} ({days_left} дней)\n"
        f"*Требования:*\n{data.get('requirements', 'Не указаны')}\n\n"
        f"*Стоимость:* {price} руб.\n\n"
        f"Подтвердите заказ:"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data='confirm_order')],
        [InlineKeyboardButton("🔄 Изменить", callback_data='change_order_data')],
        [InlineKeyboardButton("❌ Отменить", callback_data='cancel_order')]
    ]
    if update.callback_query:
        await update.callback_query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    return CALCULATE_PRICE

# Изменение данных заказа
async def change_order_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("📝 Тип работы", callback_data='change_type')],
        [InlineKeyboardButton("📋 Тема", callback_data='change_topic')],
        [InlineKeyboardButton("📅 Срок", callback_data='change_deadline')],
        [InlineKeyboardButton("📌 Требования", callback_data='change_requirements')],
        [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_price_calc')]
    ]
    await query.message.edit_text(
        "🔄 *Изменение заказа*\n\nВыберите, что изменить:",
        parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CALCULATE_PRICE

# Обработка изменения данных
async def handle_change_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == 'change_type':
        return await select_order_type(update, context)
    elif choice == 'change_topic':
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data='back_to_change_menu')]]
        await query.message.edit_text("Введите новую тему:", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        return INPUT_TOPIC
    elif choice == 'change_deadline':
        keyboard = [
            [InlineKeyboardButton("3 дня", callback_data='3'), InlineKeyboardButton("7 дней", callback_data='7'), InlineKeyboardButton("14 дней", callback_data='14')],
            [InlineKeyboardButton("21 день", callback_data='21'), InlineKeyboardButton("30 дней", callback_data='30'), InlineKeyboardButton("Другой", callback_data='custom')],
            [InlineKeyboardButton("⬅️ Назад", callback_data='back_to_change_menu')]
        ]
        await query.message.edit_text("📅 *Выберите новый срок:*", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        return INPUT_DEADLINE
    elif choice == 'change_requirements':
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data='back_to_change_menu')]]
        await query.message.edit_text("📝 *Введите новые требования:*", parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
        return INPUT_REQUIREMENTS
    elif choice == 'back_to_price_calc':
        return await calculate_price_step(update, context)
    elif choice == 'back_to_change_menu':
        return await change_order_data(update, context)
    return CALCULATE_PRICE

# Назад к расчету цены
async def back_to_price_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await calculate_price_step(update, context)

# Подтверждение заказа
async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = context.user_data
    user = update.effective_user
    client_name = user.username or f"user_{user.id}"
    order_type = data.get('order_type', 'Неизвестный тип')

    client_dir = os.path.join(BASE_DIR, client_name)
    os.makedirs(client_dir, exist_ok=True)
    orders_list = user_orders.get(str(user.id), [])
    order_id = len(orders_list) + 1
    order_path = os.path.join(client_dir, f"order_{order_id}.txt")

    order_data = {
        'order_id': order_id,
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'type': order_type,
        'topic': data.get('topic'),
        'deadline': data.get('deadline').strftime('%d.%m.%Y') if data.get('deadline') else "Не указан",
        'days_left': data.get('days_left'),
        'requirements': data.get('requirements', 'Не указаны'),
        'price': data.get('price'),
        'status': 'Новый заказ',
        'user_id': user.id,
        'user_name': user.first_name,
        'user_username': user.username
    }

    user_orders.setdefault(str(user.id), []).append(order_data)
    all_orders = load_orders()
    all_orders.setdefault(str(user.id), []).append(order_data)
    save_orders(all_orders)

    with open(order_path, 'w', encoding='utf-8') as f:
        f.write(f"Пользователь: {user.first_name} (@{user.username})\n")
        f.write(f"ID: {user.id}\n")
        f.write(f"Тип работы: {order_type}\n")
        f.write(f"Тема: {data.get('topic')}\n")
        f.write(f"Сроки: {order_data['deadline']} ({data.get('days_left')} дней)\n")
        f.write(f"Требования: {data.get('requirements', 'Не указаны')}\n")
        f.write(f"Стоимость: {data.get('price')} руб.\n")
        f.write(f"Статус: {order_data['status']}\n")

    # Сохраняем данные заказа в JSON вместо Excel (не требует pandas)
    orders_json_path = os.path.join(DATA_DIR, 'all_orders.json')
    try:
        if os.path.exists(orders_json_path):
            with open(orders_json_path, 'r', encoding='utf-8') as f:
                all_orders_list = json.load(f)
        else:
            all_orders_list = []
        
        order_data_json = {
            'Дата': order_data['date'],
            'Пользователь': f"{user.first_name} (@{user.username})",
            'ID': user.id,
            'Тип работы': order_type,
            'Тема': data.get('topic'),
            'Сроки': order_data['deadline'],
            'Дней осталось': data.get('days_left'),
            'Требования': data.get('requirements', 'Не указаны'),
            'Стоимость': data.get('price'),
            'Статус': 'Новый заказ'
        }
        
        all_orders_list.append(order_data_json)
        
        with open(orders_json_path, 'w', encoding='utf-8') as f:
            json.dump(all_orders_list, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка при сохранении заказа: {e}")

    try:
        admin_message = (
            f"🆕 *Новый заказ #{order_id}*\n\n"
            f"*От:* @{user.username} ({user.first_name})\n"
            f"*Тип:* {order_type}\n"
            f"*Тема:* {data.get('topic')}\n"
            f"*Дедлайн:* {order_data['deadline']} ({data.get('days_left')} дней)\n"
            f"*Требования:* {data.get('requirements', 'Не указаны')}\n"
            f"*Цена:* {data.get('price')} руб."
        )
        keyboard = [
            [InlineKeyboardButton("✅ Принять", callback_data=f'admin_accept_{user.id}_{order_id}')],
            [InlineKeyboardButton("❌ Отклонить", callback_data=f'admin_reject_{user.id}_{order_id}')],
            [InlineKeyboardButton("💲 Изменить цену", callback_data=f'admin_change_price_{user.id}_{order_id}')]
        ]
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=admin_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления админу: {e}")

    success_message = (
        f"✅ *Заказ оформлен!*\n\n"
        f"Номер: #{order_id}\n"
        f"Тип: {order_type}\n"
        f"Срок: {order_data['deadline']}\n"
        f"Стоимость: {data.get('price')} руб.\n\n"
        f"Менеджер свяжется с вами для деталей и оплаты."
    )
    keyboard = [
        [InlineKeyboardButton("👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_main")]
    ]
    await query.message.edit_text(success_message, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    for key in list(context.user_data.keys()):
        if key != 'ref_link':
            context.user_data.pop(key, None)
    return CONFIRM_ORDER

# Отмена заказа
async def cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    for key in list(context.user_data.keys()):
        if key != 'ref_link':
            context.user_data.pop(key, None)
    await query.message.edit_text(
        "❌ *Заказ отменен*\n\nОформите новый заказ в любое время.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Новый заказ", callback_data="make_order")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="back_to_main")]
        ])
    )
    return SELECT_MAIN_MENU

# Профиль
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    orders = user_orders.get(str(user.id), []) or load_orders().get(str(user.id), [])
    
    try:
        bot = await context.bot.get_me()
        bot_username = bot.username
    except Exception as e:
        logger.error(f"Ошибка получения данных бота: {e}")
        bot_username = "Kladovaya_GIPSR_bot"
    
    ref_link = f"https://t.me/{bot_username}?start={user.id}"
    context.user_data['ref_link'] = ref_link
    ref_count = len(referrals.get(str(user.id), []))
    bonus = sum(int(order.get('price', 0) * 0.05) for ref_id in referrals.get(str(user.id), []) for order in user_orders.get(str(ref_id), []))

    text = (
        f"👤 *Личный кабинет*\n\n"
        f"*Имя:* {user.first_name}\n"
        f"*Username:* @{user.username if user.username else 'отсутствует'}\n"
        f"*ID:* `{user.id}`\n\n"
        f"*Реферальная программа:*\n"
        f"- Приглашено: {ref_count}\n"
        f"- Бонус: {bonus} руб.\n"
        f"- Ссылка: `{ref_link}`\n\n"
    )

    if orders:
        text += "*Ваши заказы:*\n"
        recent_orders = sorted(orders, key=lambda x: x.get('date', ''), reverse=True)[:3]
        for o in recent_orders:
            text += f"- Заказ #{o.get('order_id', 'N/A')}: {o.get('type')} | Статус: {o.get('status')}\n"
        if len(orders) > 3:
            text += f"\n_...и еще {len(orders) - 3} заказов_\n"
    else:
        text += "У вас пока нет заказов."

    keyboard = [
        [InlineKeyboardButton("📋 Все заказы", callback_data='show_all_orders')],
        [InlineKeyboardButton("📝 Новый заказ", callback_data='make_order')],
        [InlineKeyboardButton("✍️ Оставить отзыв", callback_data='leave_feedback')],
        [InlineKeyboardButton("🏠 Главное меню", callback_data='back_to_main')]
    ]

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await context.bot.send_message(
            chat_id=user.id, text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
        )
    return PROFILE_MENU

# Все заказы
async def show_all_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    orders = user_orders.get(str(user.id), []) or load_orders().get(str(user.id), [])

    if not orders:
        text = "У вас пока нет заказов."
        keyboard = [[InlineKeyboardButton("⬅️ Назад к профилю", callback_data='back_to_profile')]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return SHOW_ORDERS

    orders = sorted(orders, key=lambda x: x.get('date', ''), reverse=True)
    text = "📋 *Все ваши заказы:*\n\n"
    for i, order in enumerate(orders):
        text += f"*Заказ #{order.get('order_id', 'N/A')}* ({order.get('date', '')[:10]})\n"
        text += f"Тип: {order.get('type', 'Неизвестный')}\n"
        text += f"Тема: {order.get('topic', 'Не указана')}\n"
        text += f"Статус: {order.get('status', 'Неизвестен')}\n"
        text += f"Цена: {order.get('price', 'Не указана')} руб.\n"
        if i < len(orders) - 1:
            text += "\n----------------------------\n\n"

    keyboard = [
        [InlineKeyboardButton("📝 Новый заказ", callback_data='make_order')],
        [InlineKeyboardButton("⬅️ Назад к профилю", callback_data='back_to_profile')]
    ]
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    return SHOW_ORDERS

# Назад к профилю
async def back_to_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await show_profile(update, context)

# Оставить отзыв
async def leave_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        "✍️ *Оставить отзыв*\n\n"
        "Напишите ваш отзыв о работе с нами в одном сообщении:"
    )
    keyboard = [[InlineKeyboardButton("⬅️ Назад к профилю", callback_data='back_to_profile')]]
    await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    return LEAVE_FEEDBACK

# Принять отзыв
async def input_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == 'back_to_profile':
            return await show_profile(update, context)
        return

    user = update.effective_user
    feedback_text = update.message.text
    feedback_data = {
        'user_id': user.id,
        'username': user.username,
        'name': user.first_name,
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'text': feedback_text
    }

    feedbacks = load_feedbacks()
    feedbacks.setdefault(str(user.id), []).append(feedback_data)
    save_feedbacks(feedbacks)

    client_name = user.username or f"user_{user.id}"
    feedback_dir = os.path.join(BASE_DIR, 'feedbacks')
    os.makedirs(feedback_dir, exist_ok=True)
    feedback_path = os.path.join(feedback_dir, f"{client_name}.txt")
    with open(feedback_path, 'a', encoding='utf-8') as f:
        f.write(f"--- Отзыв от {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n{feedback_text}\n\n")

    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📣 *Новый отзыв*\n\nОт: @{user.username} ({user.first_name})\n\n{feedback_text}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления админу об отзыве: {e}")

    text = "🙏 *Спасибо за отзыв!*\n\nМы ценим ваше мнение."
    keyboard = [
        [InlineKeyboardButton("👤 Профиль", callback_data='back_to_profile')],
        [InlineKeyboardButton("🏠 Главное меню", callback_data='back_to_main')]
    ]
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    return INPUT_FEEDBACK

# Команда /admin
async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("У вас нет доступа к панели администратора.")
        return
    
    # Подсчет статистики
    all_orders = load_orders()
    total_orders = sum(len(orders) for orders in all_orders.values())
    total_users = len(all_orders)
    new_orders = sum(1 for orders in all_orders.values() for order in orders if order.get('status') == 'Новый заказ')
    
    text = (
        "🎆 *ПРОДВИНУТАЯ АДМИН-ПАНЕЛЬ*\n\n"
        f"📊 *Общая статистика:*\n"
        f"• Заказов: {total_orders}\n"
        f"• Клиентов: {total_users}\n"
        f"• Новые: {new_orders}\n\n"
        "🎛️ *Управление ботом:*"
    )
    
    keyboard = [
        [InlineKeyboardButton("📋 Заказы", callback_data='admin_orders'),
         InlineKeyboardButton("👥 Клиенты", callback_data='admin_users')],
        [InlineKeyboardButton("💰 Цены", callback_data='admin_prices'),
         InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
        [InlineKeyboardButton("📢 Рассылка", callback_data='admin_broadcast'),
         InlineKeyboardButton("💻 Логи", callback_data='admin_logs')],
        [InlineKeyboardButton("🎁 Акции и скидки", callback_data='admin_promos')],
        [InlineKeyboardButton("⚙️ Настройки", callback_data='admin_settings')],
        [InlineKeyboardButton("❌ Выйти", callback_data='back_to_main_admin')]
    ]
    
    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_MENU

# Обработчик админ-меню
async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_CHAT_ID:
        await query.message.edit_text("У вас нет доступа.")
        return await main_menu(update, context)

    choice = query.data
    
    if choice == 'admin_orders':
        # Показать заказы
        all_orders = load_orders()
        text = "📋 *УПРАВЛЕНИЕ ЗАКАЗАМИ*\n\n"
        
        # Подсчет статусов
        statuses = {}
        for orders in all_orders.values():
            for order in orders:
                status = order.get('status', 'Неизвестен')
                statuses[status] = statuses.get(status, 0) + 1
        
        text += "📊 *По статусам:*\n"
        for status, count in statuses.items():
            text += f"• {status}: {count}\n"
        
        text += "\n🆕 *Последние 5 заказов:*\n\n"
        
        # Показать последние заказы
        recent_orders = []
        for uid, orders in all_orders.items():
            for order in orders:
                order['user_id'] = uid
                recent_orders.append(order)
        
        recent_orders = sorted(recent_orders, key=lambda x: x.get('date', ''), reverse=True)[:5]
        
        for order in recent_orders:
            text += f"🔸 #{order.get('order_id', 'N/A')} | {order.get('user_name', 'Unknown')}\n"
            text += f"   {order.get('type', 'N/A')} | {order.get('status', 'N/A')}\n\n"
        
        keyboard = [
            [InlineKeyboardButton("🆕 Новые заказы", callback_data="admin_new_orders")],
            [InlineKeyboardButton("✅ Принятые", callback_data="admin_accepted_orders")],
            [InlineKeyboardButton("📤 Экспорт Excel", callback_data="admin_export_orders")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]
        ]
        await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif choice == 'admin_users':
        # Управление пользователями
        all_users = user_ids.union({int(uid) for uid in load_orders().keys() if uid.isdigit()})
        text = "👥 *УПРАВЛЕНИЕ КЛИЕНТАМИ*\n\n"
        text += f"📊 *Всего пользователей:* {len(all_users)}\n\n"
        
        # Топ клиентов
        top_clients = []
        for uid in all_users:
            orders = load_orders().get(str(uid), [])
            if orders:
                total = sum(order.get('price', 0) for order in orders)
                top_clients.append({'id': uid, 'orders': len(orders), 'total': total, 'name': orders[0].get('user_name', 'Unknown')})
        
        top_clients = sorted(top_clients, key=lambda x: x['total'], reverse=True)[:5]
        
        text += "🏆 *Топ-5 клиентов:*\n"
        for idx, client in enumerate(top_clients, 1):
            text += f"{idx}. {client['name']} - {client['total']:,}₽ ({client['orders']} зак.)\n"
        
        keyboard = [
            [InlineKeyboardButton("🔍 Найти клиента", callback_data="admin_find_user")],
            [InlineKeyboardButton("📨 Отправить сообщение", callback_data="admin_message_user")],
            [InlineKeyboardButton("🚫 Черный список", callback_data="admin_blacklist")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]
        ]
        await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif choice == 'admin_prices':
        # Управление ценами
        text = "💰 *УПРАВЛЕНИЕ ЦЕНАМИ*\n\n"
        text += "📍 *Текущие цены:*\n\n"
        
        for key, val in PRICES.items():
            order_type = ORDER_TYPES.get(key, {})
            text += f"{order_type.get('icon', '')} {order_type.get('name', key)}: {val.get('base', 0):,}₽\n"
        
        text += f"\n🎆 *Режим:* {PRICING_MODES.get(current_pricing_mode, {}).get('name', '')}\n"
        
        keyboard = [
            [InlineKeyboardButton("✏️ Изменить цены", callback_data="admin_edit_prices")],
            [InlineKeyboardButton("🔄 Сменить режим", callback_data="admin_change_pricing_mode")],
            [InlineKeyboardButton("🎯 Скидки", callback_data="admin_discounts")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]
        ]
        await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

    elif choice == 'admin_stats':
        # Детальная статистика
        all_orders = load_orders()
        total_orders = sum(len(orders) for orders in all_orders.values())
        total_users = len(all_orders)
        order_types = {}
        total_revenue = 0
        today_revenue = 0
        today = datetime.now().strftime('%Y-%m-%d')
        
        for uid, orders in all_orders.items():
            for order in orders:
                order_types[order.get('type', 'Неизвестный')] = order_types.get(order.get('type', 'Неизвестный'), 0) + 1
                price = int(order.get('price', 0))
                total_revenue += price
                if order.get('date', '').startswith(today):
                    today_revenue += price
        
        text = "📊 *ДЕТАЛЬНАЯ СТАТИСТИКА*\n\n"
        text += f"📈 *Общие показатели:*\n"
        text += f"• Всего клиентов: {total_users}\n"
        text += f"• Всего заказов: {total_orders}\n"
        text += f"• Общая выручка: {total_revenue:,} руб.\n"
        text += f"• Средний чек: {int(total_revenue/total_orders) if total_orders else 0:,} руб.\n\n"
        
        text += f"💰 *Выручка сегодня:* {today_revenue:,} руб.\n\n"
        
        text += "*📝 По типам работ:*\n"
        for t, c in sorted(order_types.items(), key=lambda x: x[1], reverse=True):
            text += f"• {t}: {c} ({c/total_orders*100:.1f}%)\n"
        
        keyboard = [
            [InlineKeyboardButton("📤 Экспорт в Excel", callback_data="admin_export_stats")],
            [InlineKeyboardButton("📊 Графики", callback_data="admin_charts")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]
        ]
        await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif choice == 'admin_broadcast':
        # Рассылка сообщений
        text = (
            "📢 *РАССЫЛКА СООБЩЕНИЙ*\n\n"
            "Выберите тип рассылки:\n\n"
            "• *Всем пользователям* - отправить всем клиентам\n"
            "• *Активным* - только тем, кто заказывал\n"
            "• *Новым* - кто еще не заказывал\n"
        )
        keyboard = [
            [InlineKeyboardButton("📨 Всем пользователям", callback_data="broadcast_all")],
            [InlineKeyboardButton("✅ Активным клиентам", callback_data="broadcast_active")],
            [InlineKeyboardButton("🆕 Новым пользователям", callback_data="broadcast_new")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]
        ]
        await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif choice == 'admin_settings':
        # Настройки бота
        text = (
            "⚙️ *НАСТРОЙКИ БОТА*\n\n"
            "🔧 *Доступные настройки:*\n\n"
            "• Режим цен\n"
            "• Антиплагиат минимум\n"
            "• Срок бесплатных правок\n"
            "• Реферальный процент\n"
            "• Автоответы\n"
        )
        keyboard = [
            [InlineKeyboardButton("💲 Режим цен", callback_data="settings_pricing")],
            [InlineKeyboardButton("📝 Тексты и сообщения", callback_data="settings_messages")],
            [InlineKeyboardButton("🎁 Бонусы и скидки", callback_data="settings_bonuses")],
            [InlineKeyboardButton("🤖 Автоматизация", callback_data="settings_automation")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]
        ]
        await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif choice == 'admin_change_pricing_mode':
        global current_pricing_mode
        current_pricing_mode = 'hard' if current_pricing_mode == 'light' else 'light'
        mode_info = PRICING_MODES[current_pricing_mode]
        text = f"🔄 *Режим цен изменен*\n\n{mode_info['name']}: {mode_info['icon']} {mode_info['description']}"
        keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_prices")]]
        await query.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

    elif choice == 'back_to_main_admin':
        return await main_menu(update, context)

    elif choice == 'admin_menu':
        # Возврат к главному меню админа
        all_orders = load_orders()
        total_orders = sum(len(orders) for orders in all_orders.values())
        total_users = len(all_orders)
        new_orders = sum(1 for orders in all_orders.values() for order in orders if order.get('status') == 'Новый заказ')
        
        text = (
            "🎆 *ПРОДВИНУТАЯ АДМИН-ПАНЕЛЬ*\n\n"
            f"📊 *Общая статистика:*\n"
            f"• Заказов: {total_orders}\n"
            f"• Клиентов: {total_users}\n"
            f"• Новые: {new_orders}\n\n"
            "🎛️ *Управление ботом:*"
        )
        
        keyboard = [
            [InlineKeyboardButton("📋 Заказы", callback_data='admin_orders'),
             InlineKeyboardButton("👥 Клиенты", callback_data='admin_users')],
            [InlineKeyboardButton("💰 Цены", callback_data='admin_prices'),
             InlineKeyboardButton("📊 Статистика", callback_data='admin_stats')],
            [InlineKeyboardButton("📢 Рассылка", callback_data='admin_broadcast'),
             InlineKeyboardButton("💻 Логи", callback_data='admin_logs')],
            [InlineKeyboardButton("🎁 Акции и скидки", callback_data='admin_promos')],
            [InlineKeyboardButton("⚙️ Настройки", callback_data='admin_settings')],
            [InlineKeyboardButton("❌ Выйти", callback_data='back_to_main_admin')]
        ]
        
        await query.message.edit_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard)
        )
    return ADMIN_MENU

# Действия администратора
async def admin_order_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_CHAT_ID:
        await query.message.edit_text("У вас нет доступа.")
        return ADMIN_MENU

    action_data = query.data.split('_')
    action, user_id, order_id = action_data[1], action_data[2], int(action_data[3])
    all_orders = load_orders()

    if user_id in all_orders:
        for order in all_orders[user_id]:
            if order.get('order_id') == order_id:
                if action == 'accept':
                    order['status'] = 'Принят'
                    try:
                        await context.bot.send_message(
                            chat_id=int(user_id),
                            text=f"✅ *Заказ #{order_id} принят!*\n\nТип: {order.get('type')}\nТема: {order.get('topic')}\nСтатус: Принят\n\nМенеджер свяжется с вами.",
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except Exception as e:
                        logger.error(f"Ошибка уведомления пользователя: {e}")
                    await query.message.edit_text(f"✅ Заказ #{order_id} принят.")
                elif action == 'reject':
                    order['status'] = 'Отклонен'
                    try:
                        await context.bot.send_message(
                            chat_id=int(user_id),
                            text=f"❌ *Заказ #{order_id} отклонен*\n\nТип: {order.get('type')}\nТема: {order.get('topic')}\nСтатус: Отклонен\n\nМенеджер свяжется с вами.",
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except Exception as e:
                        logger.error(f"Ошибка уведомления пользователя: {e}")
                    await query.message.edit_text(f"❌ Заказ #{order_id} отклонен.")
                elif action == 'change_price':
                    context.user_data['admin_edit_order'] = {'user_id': user_id, 'order_id': order_id, 'current_price': order.get('price')}
                    await query.message.edit_text(f"Текущая цена заказа #{order_id}: {order.get('price')} руб.\n\nВведите новую цену:")
                    return ADMIN_MENU
                break
        save_orders(all_orders)
        user_orders[user_id] = all_orders[user_id]
    else:
        await query.message.edit_text(f"Ошибка: Заказ #{order_id} не найден.")

    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]]
    await query.message.reply_text("Выберите действие:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU

# Изменение цены администратором
async def admin_change_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    edit_data = context.user_data.get('admin_edit_order', {})
    if not edit_data:
        await update.message.reply_text("Ошибка: Данные о заказе не найдены.")
        return ADMIN_MENU

    try:
        new_price = int(update.message.text)
        if new_price <= 0:
            await update.message.reply_text("Цена должна быть положительной.")
            return ADMIN_MENU

        user_id, order_id = edit_data['user_id'], edit_data['order_id']
        all_orders = load_orders()
        if user_id in all_orders:
            for order in all_orders[user_id]:
                if order.get('order_id') == order_id:
                    old_price = order.get('price')
                    order['price'] = new_price
                    try:
                        await context.bot.send_message(
                            chat_id=int(user_id),
                            text=f"💲 *Цена заказа #{order_id} изменена*\n\nТип: {order.get('type')}\nТема: {order.get('topic')}\nСтарая цена: {old_price} руб.\nНовая цена: {new_price} руб.\n\nМенеджер свяжется с вами.",
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except Exception as e:
                        logger.error(f"Ошибка уведомления пользователя: {e}")
                    save_orders(all_orders)
                    user_orders[user_id] = all_orders[user_id]
                    await update.message.reply_text(f"✅ Цена заказа #{order_id} изменена с {old_price} на {new_price} руб.")
                    del context.user_data['admin_edit_order']
                    break
        else:
            await update.message.reply_text(f"Ошибка: Заказ #{order_id} не найден.")
    except ValueError:
        await update.message.reply_text("Введите корректное число.")

    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="admin_menu")]]
    await update.message.reply_text("Выберите действие:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU

# Запуск бота
def main():
    logger.info("="*50)
    logger.info("Бот запускается...")
    logger.info(f"Bot token: {TELEGRAM_BOT_TOKEN[:10]}...{TELEGRAM_BOT_TOKEN[-5:]}")
    logger.info(f"Admin ID: {ADMIN_CHAT_ID}")
    logger.info(f"Platform: {platform.system()}")
    logger.info(f"BASE_DIR: {BASE_DIR}")
    logger.info(f"DATA_DIR: {DATA_DIR}")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Directories exist: BASE={os.path.exists(BASE_DIR)}, DATA={os.path.exists(DATA_DIR)}")
    logger.info("="*50)

    try:
        application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler('start', start),
                CommandHandler('order', order_command),
                CommandHandler('profile', profile_command),
                CommandHandler('admin', admin_start)
            ],
            states={
                SELECT_MAIN_MENU: [
                    CallbackQueryHandler(main_menu_handler),
                    CallbackQueryHandler(main_menu, pattern='^back_to_main$')
                ],
                SELECT_ORDER_TYPE: [CallbackQueryHandler(select_order_type_callback)],
                VIEW_ORDER_DETAILS: [CallbackQueryHandler(order_details_handler)],
                INPUT_TOPIC: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, input_topic),
                    CallbackQueryHandler(back_to_order_details, pattern='^back_to_order_details$')
                ],
                INPUT_DEADLINE: [
                    CallbackQueryHandler(input_deadline),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, input_custom_deadline)
                ],
                INPUT_REQUIREMENTS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, input_requirements),
                    CallbackQueryHandler(back_to_deadline, pattern='^back_to_deadline$')
                ],
                CALCULATE_PRICE: [
                    CallbackQueryHandler(confirm_order, pattern='^confirm_order$'),
                    CallbackQueryHandler(cancel_order, pattern='^cancel_order$'),
                    CallbackQueryHandler(change_order_data, pattern='^change_order_data$'),
                    CallbackQueryHandler(handle_change_data, pattern='^change_'),
                    CallbackQueryHandler(back_to_price_calc, pattern='^back_to_price_calc$')
                ],
                CONFIRM_ORDER: [
                    CallbackQueryHandler(main_menu_handler, pattern='^back_to_main$'),
                    CallbackQueryHandler(show_profile, pattern='^profile$')
                ],
                PROFILE_MENU: [
                    CallbackQueryHandler(show_all_orders, pattern='^show_all_orders$'),
                    CallbackQueryHandler(leave_feedback, pattern='^leave_feedback$'),
                    CallbackQueryHandler(main_menu_handler, pattern='^make_order$'),
                    CallbackQueryHandler(main_menu, pattern='^back_to_main$')
                ],
                SHOW_PRICE_LIST: [
                    CallbackQueryHandler(price_calculator, pattern='^price_calculator$'),
                    CallbackQueryHandler(main_menu, pattern='^back_to_main$')
                ],
                PRICE_CALCULATOR: [
                    CallbackQueryHandler(calculate_price_in_calculator, pattern='^calc_'),
                    CallbackQueryHandler(handle_deadline_selection, pattern='^deadline_'),
                    CallbackQueryHandler(select_order_type_callback, pattern='^order_'),
                    CallbackQueryHandler(back_to_price, pattern='^back_to_price$')
                ],
                SHOW_FAQ: [
                    CallbackQueryHandler(show_faq_details, pattern='^faq_'),
                    CallbackQueryHandler(main_menu, pattern='^back_to_main$')
                ],
                FAQ_DETAILS: [
                    CallbackQueryHandler(back_to_faq, pattern='^back_to_faq$'),
                    CallbackQueryHandler(main_menu, pattern='^back_to_main$')
                ],
                SHOW_ORDERS: [
                    CallbackQueryHandler(back_to_profile, pattern='^back_to_profile$'),
                    CallbackQueryHandler(main_menu_handler, pattern='^make_order$')
                ],
                LEAVE_FEEDBACK: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, input_feedback),
                    CallbackQueryHandler(back_to_profile, pattern='^back_to_profile$')
                ],
                INPUT_FEEDBACK: [
                    CallbackQueryHandler(back_to_profile, pattern='^back_to_profile$'),
                    CallbackQueryHandler(main_menu, pattern='^back_to_main$')
                ],
                ADMIN_MENU: [
                    CallbackQueryHandler(admin_menu_handler, pattern='^admin_'),
                    CallbackQueryHandler(admin_order_action, pattern='^admin_(accept|reject|change_price)_'),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_change_price),
                    CallbackQueryHandler(main_menu, pattern='^back_to_main_admin$')
                ]
            },
            fallbacks=[
                CommandHandler('start', start),
                CommandHandler('order', order_command),
                CommandHandler('profile', profile_command),
                CommandHandler('admin', admin_start),
                CommandHandler('help', help_command)
            ],
            name="main_conversation",
            persistent=False
        )
        application.add_handler(conv_handler)
        # Добавляем обработчики команд вне ConversationHandler
        application.add_handler(CommandHandler('help', help_command))
        application.add_handler(CommandHandler('order', order_command))
        application.add_handler(CommandHandler('profile', profile_command))
        application.add_handler(CommandHandler('price', price_command))
        application.add_handler(CommandHandler('faq', faq_command))
        application.add_handler(CommandHandler('admin', admin_start))
        
        # Добавляем обработчик ошибок
        application.add_error_handler(error_handler)
        
        logger.info("Все обработчики зарегистрированы")
        logger.info("Бот настроен, начинаем polling...")
        application.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске: {e}", exc_info=True)

if __name__ == '__main__':
    main()