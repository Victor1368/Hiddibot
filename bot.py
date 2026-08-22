#!/usr/bin/env python3
"""
ربات تلگرام مدیریت VPN با اتصال به Hidify
"""

import os
import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from hidify import HidifyClient
from payment import PaymentManager
from admin_manager import (
    load_cards, add_card, update_card, delete_card, get_active_card, get_all_cards,
    load_plans, add_plan, update_plan, delete_plan, get_active_plans, get_all_plans, get_plan,
)
from database import db
from backup import BackupManager, AutoBackupScheduler, send_backup_to_admin
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ─── بارگذاری متغیرهای محیطی ───
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
HIDIFY_PANEL_URL = os.getenv("HIDIFY_PANEL_URL")
HIDIFY_API_KEY = os.getenv("HIDIFY_API_KEY")
HIDIFY_PROXY_PATH = os.getenv("HIDIFY_PROXY_PATH")
USER_PROXY_PATH = os.getenv("USER_PROXY_PATH", HIDIFY_PROXY_PATH)
PAYMENT_GATEWAY = os.getenv("PAYMENT_GATEWAY", "zarinpal")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CARD_NUMBER = os.getenv("CARD_NUMBER", "")
CARD_HOLDER = os.getenv("CARD_HOLDER", "")
BANK_NAME = os.getenv("BANK_NAME", "")

# ─── تنظیم لاگینگ ───
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── مسیر ذخیره‌سازی اطلاعات کاربران ───
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# ─── وضعیت‌های مکالمه ───
(
    CHOOSING,
    SELECTING_PLAN,
    CONFIRMING_PURCHASE,
    SELECTING_PAYMENT,
    ENTERING_CARD_NUMBER,
    ENTERING_CARD_HOLDER,
    ENTERING_TRACKING_CODE,
    # وضعیت‌های مدیریت ادمین
    ADMIN_MENU,
    ADMIN_CARDS_MENU,
    ADMIN_ADD_CARD_NUMBER,
    ADMIN_ADD_CARD_HOLDER,
    ADMIN_ADD_CARD_BANK,
    ADMIN_PLANS_MENU,
    ADMIN_ADD_PLAN_NAME,
    ADMIN_ADD_PLAN_PRICE,
    ADMIN_ADD_PLAN_DATA,
    ADMIN_ADD_PLAN_DURATION,
    ADMIN_RESTORE_FILE,
    SELECTING_NAME_TYPE,
    ENTERING_CUSTOM_NAME,
    RENEWING,
) = range(21)


# ─── دریافت پلن‌ها ───
def get_plans() -> dict:
    """دریافت پلن‌های فعال"""
    return get_active_plans()


# ═══════════════════════════════════════════════════════════════════════
# ساخت نمونه کلاینت Hidify
# ═══════════════════════════════════════════════════════════════════════

hidify = HidifyClient(HIDIFY_PANEL_URL, HIDIFY_API_KEY, HIDIFY_PROXY_PATH)


# ═══════════════════════════════════════════════════════════════════════
# مدیریت اطلاعات کاربران ربات (دیتابیس)
# ═══════════════════════════════════════════════════════════════════════

def get_user_data(telegram_user_id: int) -> dict:
    """دریافت اطلاعات کاربر از دیتابیس"""
    user = db.get_user(telegram_user_id)
    if user:
        # تبدیل به فرمت قدیمی برای سازگاری
        return {
            "telegram_id": user.get("telegram_id"),
            "username": user.get("username"),
            "hidify_uuid": user.get("hidify_uuid"),
            "plan": user.get("plan_id"),
            "data_limit": user.get("data_limit", 0),
            "expire_at": user.get("expire_at"),
            "created_at": user.get("created_at"),
        }
    return {}


def save_user_data(telegram_user_id: int, data: dict):
    """ذخیره اطلاعات کاربر در دیتابیس"""
    db.save_user(
        telegram_id=telegram_user_id,
        username=data.get("username", f"tg_{telegram_user_id}"),
        hidify_uuid=data.get("hidify_uuid", ""),
        plan_id=data.get("plan", ""),
        data_limit=data.get("data_limit", 0),
        expire_at=data.get("expire_at"),
    )


# ═══════════════════════════════════════════════════════════════════════
# هندلرهای ربات
# ═══════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /start - شروع ربات"""
    user = update.effective_user
    
    # منوی معمولی
    keyboard = [
        [KeyboardButton("🛒 خرید اشتراک")],
        [KeyboardButton("🔄 تمدید اشتراک"), KeyboardButton("📊 وضعیت اشتراک")],
        [KeyboardButton("🔗 لینک اتصال"), KeyboardButton("❓ راهنمای ربات")],
        [KeyboardButton("📚 آموزش‌ها (بزودی)")],
    ]
    
    # اضافه کردن دکمه ادمین
    if user.id == ADMIN_ID:
        keyboard.append([KeyboardButton("🔧 پنل مدیریت")])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    welcome_text = f"""
سلام {user.first_name}! 👋

به ربات مدیریت VPN خوش آمدید!

از منوی زیر می‌توانید:
• 🛒 خرید اشتراک جدید
• 🔄 تمدید اشتراک
• 📊 مشاهده وضعیت اشتراک
• 🔗 دریافت لینک اتصال
• ❓ راهنمای ربات
• 📚 آموزش‌ها (بزودی)
"""
    
    if user.id == ADMIN_ID:
        welcome_text += "• 🔧 پنل مدیریت\n"
    
    welcome_text += "\nلطفاً یکی از گزینه‌ها را انتخاب کنید:"
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    return CHOOSING


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لغو مکالمه"""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "❌ عملیات لغو شد.\n\n"
            "برای شروع مجدد، دکمه «🛒 خرید اشتراک» رو بزنید."
        )
    else:
        await update.message.reply_text(
            "❌ عملیات لغو شد.\n\n"
            "برای شروع مجدد، دکمه «🛒 خرید اشتراک» رو بزنید."
        )
    return ConversationHandler.END


async def timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ timeout مکالمه """
    await update.message.reply_text(
        "⏰ زمان مکالمه تمام شد.\n\n"
        "برای شروع مجدد، دکمه «🛒 خرید اشتراک» رو بزنید."
    )
    return ConversationHandler.END


async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به منوی اصلی"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    keyboard = [
        [KeyboardButton("🛒 خرید اشتراک")],
        [KeyboardButton("🔄 تمدید اشتراک"), KeyboardButton("📊 وضعیت اشتراک")],
        [KeyboardButton("🔗 لینک اتصال"), KeyboardButton("❓ راهنمای ربات")],
        [KeyboardButton("📚 آموزش‌ها (بزودی)")],
    ]
    if user.id == ADMIN_ID:
        keyboard.append([KeyboardButton("🔧 پنل مدیریت")])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await query.edit_message_text("🏠 منوی اصلی")
    await context.bot.send_message(
        chat_id=user.id,
        text="لطفاً یکی از گزینه‌ها را انتخاب کنید:",
        reply_markup=reply_markup
    )
    return CHOOSING


async def back_to_select_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به لیست پلن‌ها"""
    query = update.callback_query
    await query.answer()
    return await show_plans(update, context)


async def back_to_confirm_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به صفحه تایید خرید"""
    query = update.callback_query
    await query.answer()
    
    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    if not plan_id or plan_id not in plans:
        return await back_to_menu(update, context)
    
    plan = plans[plan_id]
    price_formatted = f"{plan['price']:,}".replace(",", "،")
    text = f"""
📋 **انتخاب پلن:** {plan['name']}

• حجم: {plan['data_limit'] if plan['data_limit'] > 0 else 'نامحدود'} گیگابایت
• مدت: {plan['duration']} روز
• قیمت: {price_formatted} تومان

آیا مایل به خرید این پلن هستید؟
"""
    keyboard = [
        [
            InlineKeyboardButton("✅ تایید خرید", callback_data="confirm_purchase"),
            InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_select_plan"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return CONFIRMING_PURCHASE


async def back_to_select_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به انتخاب روش پرداخت"""
    query = update.callback_query
    await query.answer()
    
    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    if not plan_id or plan_id not in plans:
        return await back_to_menu(update, context)
    
    plan = plans[plan_id]
    price_formatted = f"{plan['price']:,}".replace(",", "،")
    text = f"""
💳 **انتخاب روش پرداخت**

📋 پلن: {plan['name']}
💰 مبلغ: {price_formatted} تومان

لطفاً روش پرداخت را انتخاب کنید:
"""
    keyboard = [
        [InlineKeyboardButton("💳 درگاه آنلاین (بزودی)", callback_data="coming_soon")],
        [InlineKeyboardButton("💵 کارت به کارت", callback_data="pay_card")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_confirm_purchase"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return SELECTING_PAYMENT


async def back_to_enter_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به مرحله وارد کردن کد پیگیری"""
    query = update.callback_query
    await query.answer()
    
    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")
    
    # دریافت کارت فعال
    active_card = get_active_card()
    card_number = active_card.get("card_number", CARD_NUMBER)
    card_holder = active_card.get("card_holder", CARD_HOLDER)
    bank_name = active_card.get("bank_name", BANK_NAME)

    text = f"""
💵 **پرداخت کارت به کارت**

📋 پلن: {plan.get('name', 'نامشخص')}
💰 مبلغ: {price_formatted} تومان

📌 **اطلاعات کارت:**
```
{card_number}
```
👤 **نام صاحب کارت:** {card_holder}
🏦 **بانک:** {bank_name}

⚠️ **نکات مهم:**
• دقیقاً مبلغ بالا را واریز کنید
• بعد از واریز، رسید پرداخت را ارسال کنید
• رسید پرداخت برای ادمین ارسال میشود

لطفاً بعد از واریز:
• متن 📝 رسید یا اسکرین‌شات 📷 رسید را ارسال کنید
"""
    keyboard = [
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_select_payment"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return ENTERING_TRACKING_CODE


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /help - راهنما"""
    help_text = """
📖 **راهنمای ربات VPN**

**🛒 خرید اشتراک:**
یکی از پلن‌های موجود را انتخاب کنید و پس از پرداخت، اشتراک شما فعال می‌شود.

**🔄 تمدید اشتراک:**
اشتراک فعلی خود را برای یک دوره دیگر تمدید کنید.

**📊 وضعیت اشتراک:**
اطلاعات کامل اشتراک شامل حجم مصرفی، تاریخ انقضا و ...

**🔗 لینک اتصال:**
لینک اشتراک خود را برای اتصال دریافت کنید.

⚠️ **نکات مهم:**
• لینک اشتراک را با کسی به اشتراک نگذارید
• در صورت بروز مشکل با پشتیبانی تماس بگیرید
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def show_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش پلن‌های اشتراک"""
    plans = get_plans()
    
    if not plans:
        await update.message.reply_text(
            "❌ هیچ پلن فعالی وجود ندارد!\n\n"
            "لطفاً با پشتیبانی تماس بگیرید."
        )
        return CHOOSING

    keyboard = []
    for plan_id, plan in plans.items():
        price_formatted = f"{plan['price']:,}".replace(",", "،")
        keyboard.append([
            InlineKeyboardButton(
                f"{plan['name']} - {plan['description']} - {price_formatted} تومان",
                callback_data=f"plan_{plan_id}",
            )
        ])
    keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "🛒 **پلن‌های اشتراک:**\n\nلطفاً یکی از پلن‌های زیر را انتخاب کنید:"
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
    return SELECTING_PLAN


async def plan_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """انتخاب پلن"""
    query = update.callback_query
    await query.answer()

    # اگر دکمه بازگشت زده شده
    if query.data == "back_to_menu":
        return await back_to_menu(update, context)

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING

    plan_id = query.data.replace("plan_", "")
    plans = get_plans()
    if plan_id not in plans:
        await query.edit_message_text("❌ پلن نامعتبر!")
        return CHOOSING

    plan = plans[plan_id]
    context.user_data["selected_plan"] = plan_id

    price_formatted = f"{plan['price']:,}".replace(",", "،")
    text = (
        f"📋 پلن انتخاب شده: {plan['name']}\n\n"
        f"• حجم: {plan['data_limit'] if plan['data_limit'] > 0 else 'نامحدود'} گیگابایت\n"
        f"• مدت: {plan['duration']} روز\n"
        f"• قیمت: {price_formatted} تومان\n\n"
        f"📝 نام اکانت خود را انتخاب کنید:"
    )
    keyboard = [
        [InlineKeyboardButton("🔄 انتخاب خودکار(آیدی تلگرام)", callback_data="name_telegram_id")],
        [InlineKeyboardButton("✏️ نام دلخواه", callback_data="name_custom")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_select_plan")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)
    return SELECTING_NAME_TYPE


async def select_name_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """انتخاب نوع نام اکانت"""
    query = update.callback_query
    await query.answer()

    if query.data == "back_to_select_plan":
        # بازگشت به لیست پلن‌ها
        return await back_to_select_plan(update, context)

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING

    user = update.effective_user
    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

    if query.data == "name_telegram_id":
        # استفاده از آیدی تلگرام
        context.user_data["account_name"] = f"tg_{user.id}"
        context.user_data["account_comment"] = None

        text = (
            f"📋 پلن انتخاب شده: {plan.get('name', 'نامشخص')}\n\n"
            f"• حجم: {plan.get('data_limit', 0) if plan.get('data_limit', 0) > 0 else 'نامحدود'} گیگابایت\n"
            f"• مدت: {plan.get('duration', 0)} روز\n"
            f"• قیمت: {price_formatted} تومان\n\n"
            f"📝 نام اکانت: tg_{user.id}\n\n"
            f"آیا مایل به خرید این پلن هستید?"
        )
        keyboard = [
            [
                InlineKeyboardButton("✅ تایید خرید", callback_data="confirm_purchase"),
                InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_name_selection"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup)
        return CONFIRMING_PURCHASE

    elif query.data == "name_custom":
        # نام دلخواه
        text = (
            "✏️ نام دلخواه خود را وارد کنید:\n\n"
            "⚠️ این نام در پنل Hidify نمایش داده خواهد شد.\n\n"
            "💡 نمونه: علی، محمد، user123"
        )
        keyboard = [
            [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_name_selection")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup)
        return ENTERING_CUSTOM_NAME

    return SELECTING_NAME_TYPE


async def enter_custom_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت نام دلخواه"""
    user = update.effective_user
    custom_name = update.message.text.strip()

    if not custom_name:
        await update.message.reply_text("❌ لطفاً نامی وارد کنید.")
        return ENTERING_CUSTOM_NAME

    # ذخیره نام دلخواه
    context.user_data["account_name"] = custom_name
    context.user_data["account_comment"] = str(user.id)

    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

    text = (
        f"📋 پلن انتخاب شده: {plan.get('name', 'نامشخص')}\n\n"
        f"• حجم: {plan.get('data_limit', 0) if plan.get('data_limit', 0) > 0 else 'نامحدود'} گیگابایت\n"
        f"• مدت: {plan.get('duration', 0)} روز\n"
        f"• قیمت: {price_formatted} تومان\n\n"
        f"📝 نام اکانت: {custom_name}\n"
        f"🆔 آیدی تلگرام: {user.id}\n\n"
        f"آیا مایل به خرید این پلن هستید?"
    )
    keyboard = [
        [
            InlineKeyboardButton("✅ تایید خرید", callback_data="confirm_purchase"),
            InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_name_selection"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)
    return CONFIRMING_PURCHASE


async def back_to_name_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به انتخاب نوع نام"""
    query = update.callback_query
    await query.answer()

    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

    text = (
        f"📋 پلن انتخاب شده: {plan.get('name', 'نامشخص')}\n\n"
        f"• حجم: {plan.get('data_limit', 0) if plan.get('data_limit', 0) > 0 else 'نامحدود'} گیگابایت\n"
        f"• مدت: {plan.get('duration', 0)} روز\n"
        f"• قیمت: {price_formatted} تومان\n\n"
        f"📝 نام اکانت خود را انتخاب کنید:"
    )
    keyboard = [
        [InlineKeyboardButton("🔄 انتخاب خودکار(آیدی تلگرام)", callback_data="name_telegram_id")],
        [InlineKeyboardButton("✏️ نام دلخواه", callback_data="name_custom")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_select_plan")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)
    return SELECTING_NAME_TYPE


async def select_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """انتخاب روش پرداخت"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING

    if query.data != "confirm_purchase":
        return CONFIRMING_PURCHASE

    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    if not plan_id or plan_id not in plans:
        await query.edit_message_text("❌ خطا در انتخاب پلن!")
        return CHOOSING

    plan = plans[plan_id]
    price_formatted = f"{plan['price']:,}".replace(",", "،")

    text = f"""
💳 **انتخاب روش پرداخت**

📋 پلن: {plan['name']}
💰 مبلغ: {price_formatted} تومان

لطفاً روش پرداخت را انتخاب کنید:
"""

    keyboard = [
        [InlineKeyboardButton("💳 درگاه آنلاین (بزودی)", callback_data="coming_soon")],
        [InlineKeyboardButton("💵 کارت به کارت", callback_data="pay_card")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_confirm_purchase"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return SELECTING_PAYMENT


async def handle_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب روش پرداخت"""
    query = update.callback_query
    await query.answer()

    if query.data == "back_to_confirm_purchase":
        return await back_to_confirm_purchase(update, context)

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING

    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

    if query.data == "coming_soon":
        # درگاه آنلاین بزودی
        await query.answer("⏳ این قابلیت بزودی اضافه خواهد شد!", show_alert=True)
        return SELECTING_PAYMENT

    elif query.data == "pay_online":
        # پرداخت آنلاین
        return await confirm_purchase(update, context)

    elif query.data == "pay_card":
        # کارت به کارت
        # دریافت کارت فعال
        active_card = get_active_card()
        card_number = active_card.get("card_number", CARD_NUMBER)
        card_holder = active_card.get("card_holder", CARD_HOLDER)
        bank_name = active_card.get("bank_name", BANK_NAME)

        text = f"""
💵 **پرداخت کارت به کارت**

📋 پلن: {plan.get('name', 'نامشخص')}
💰 مبلغ: {price_formatted} تومان

📌 **اطلاعات کارت:**
```
{card_number}
```
👤 **نام صاحب کارت:** {card_holder}
🏦 **بانک:** {bank_name}

⚠️ **نکات مهم:**
• دقیقاً مبلغ بالا را واریز کنید
• بعد از واریز، رسید پرداخت را ارسال کنید
• رسید پرداخت برای ادمین ارسال میشود

لطفاً بعد از واریز:
• 📝 **شماره پیگیری** را وارد کنید
• یا 📷 **اسکرین‌شات رسید** را ارسال کنید:
"""
        keyboard = [
            [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_select_payment"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return ENTERING_TRACKING_CODE

    return SELECTING_PAYMENT


async def enter_tracking_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت شماره پیگیری"""
    tracking_code = update.message.text.strip()

    # بررسی اینکه کد خالی نباشد
    if not tracking_code:
        await update.message.reply_text(
            "❌ لطفاً شماره پیگیری را وارد کنید:"
        )
        return ENTERING_TRACKING_CODE

    context.user_data["tracking_code"] = tracking_code
    context.user_data.pop("receipt_photo", None)  # پاک کردن عکس قبلی
    user = update.effective_user
    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

    # تایید اطلاعات
    text = (
        f"✅ تایید پرداخت کارت به کارت\n\n"
        f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
        f"💰 مبلغ: {price_formatted} تومان\n"
        f"🔢 شماره پیگیری: {tracking_code}\n\n"
        f"آیا اطلاعات صحیح است?"
    )
    keyboard = [
        [InlineKeyboardButton("✅ تایید و ارسال", callback_data="confirm_card_payment")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_enter_tracking"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)
    return CONFIRMING_PURCHASE


async def enter_tracking_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت عکس رسید پرداخت"""
    user = update.effective_user
    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    plan = plans.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

    # دریافت file_id عکس
    photo = update.message.photo[-1]  # بزرگترین سایز
    file_id = photo.file_id

    # ذخیره اطلاعات
    context.user_data["tracking_code"] = "اسکرین‌شات رسید"
    context.user_data["receipt_photo"] = file_id

    # تایید اطلاعات
    text = (
        f"✅ تایید پرداخت کارت به کارت\n\n"
        f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
        f"💰 مبلغ: {price_formatted} تومان\n"
        f"📷 رسید: اسکرین‌شات ارسال شد\n\n"
        f"آیا اطلاعات صحیح است?"
    )
    keyboard = [
        [InlineKeyboardButton("✅ تایید و ارسال", callback_data="confirm_card_payment")],
        [InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_enter_tracking"), InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup)
    return CONFIRMING_PURCHASE


async def confirm_card_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید پرداخت کارت به کارت"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING

    if query.data != "confirm_card_payment":
        return CONFIRMING_PURCHASE

    try:
        user = update.effective_user
        plan_id = context.user_data.get("selected_plan")
        plans = get_plans()
        plan = plans.get(plan_id, {})
        tracking_code = context.user_data.get("tracking_code", "")
        price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

        # ذخیره تراکنش کارت به کارت
        order_id = f"card_{user.id}_{int(datetime.now().timestamp())}"
        db.save_transaction(
            order_id=order_id,
            user_id=user.id,
            username=user.username or user.first_name,
            plan_name=plan.get("name", "نامشخص"),
            amount=plan.get("price", 0),
            gateway="card_to_card",
            tracking_code=tracking_code,
            status="pending",
            account_name=context.user_data.get("account_name", f"tg_{user.id}"),
            account_comment=context.user_data.get("account_comment"),
        )

        logger.info(f"Transaction saved for user {user.id}")
    except Exception as e:
        logger.error(f"Error saving transaction: {e}")
        try:
            await query.edit_message_text("❌ خطا در ثبت تراکنش. لطفاً دوباره تلاش کنید.")
        except:
            pass
        return CHOOSING

    # ارسال پیام به ادمین
    account_name = context.user_data.get("account_name", f"tg_{user.id}")
    admin_sent = False

    if ADMIN_ID and ADMIN_ID != 0:
        try:
            admin_text = (
                f"🔔 رسید پرداخت جدید\n\n"
                f"👤 کاربر: {user.first_name}\n"
                f"🆔 آیدی: {user.id}\n"
                f"💬 یوزرنیم: @{user.username or 'ندارد'}\n\n"
                f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
                f"💰 مبلغ: {price_formatted} تومان\n"
                f"🔢 شماره پیگیری: {tracking_code}\n"
                f"📝 نام اکانت: {account_name}\n\n"
                f"⏰ زمان: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            keyboard = [
                [InlineKeyboardButton("✅ تایید", callback_data=f"admin_approve_{user.id}_{plan_id}")],
                [InlineKeyboardButton("❌ رد", callback_data=f"admin_reject_{user.id}")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            receipt_photo = context.user_data.get("receipt_photo")
            if receipt_photo:
                await context.bot.send_photo(
                    chat_id=ADMIN_ID,
                    photo=receipt_photo,
                    caption=f"📷 رسید پرداخت از {user.first_name}",
                )
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=admin_text,
                    reply_markup=reply_markup,
                )
            else:
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=admin_text,
                    reply_markup=reply_markup,
                )
            admin_sent = True
            logger.info(f"Admin notification sent to {ADMIN_ID}")
        except Exception as e:
            logger.error(f"Error sending to admin: {e}")
    else:
        logger.warning("ADMIN_ID not set, skipping admin notification")

    # پاسخ به کاربر
    try:
        if admin_sent:
            await query.edit_message_text(
                f"✅ رسید پرداخت ارسال شد!\n\n"
                f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
                f"💰 مبلغ: {price_formatted} تومان\n"
                f"🔢 شماره پیگیری: {tracking_code}\n\n"
                f"⏳ پرداخت شما در حال بررسی است.\n"
                f"پس از تایید ادمین، اشتراک شما فعال میشود.\n\n"
                f"💬 پشتیبانی: @netup_top",
            )
        else:
            await query.edit_message_text(
                f"✅ رسید پرداخت ثبت شد!\n\n"
                f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
                f"💰 مبلغ: {price_formatted} تومان\n"
                f"🔢 شماره پیگیری: {tracking_code}\n\n"
                f"⚠️ با پشتیبانی تماس بگیرید: @netup_top",
            )
    except Exception as e:
        logger.error(f"Error editing user message: {e}")

    return CHOOSING


async def confirm_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید خرید و ارسال لینک پرداخت"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING

    if query.data != "confirm_purchase":
        return CONFIRMING_PURCHASE

    plan_id = context.user_data.get("selected_plan")
    plans = get_plans()
    if not plan_id or plan_id not in plans:
        await query.edit_message_text("❌ خطا در انتخاب پلن!")
        return CHOOSING

    plan = plans[plan_id]
    user = update.effective_user

    # ساخت درخواست پرداخت
    await query.edit_message_text("⏳ در حال ساخت درخواست پرداخت...")

    # آدرس بازگشت (وب‌سایت ربات)
    callback_url = f"https://t.me/{context.bot.username}"

    # ایجاد پرداخت
    payment = PaymentManager(PAYMENT_GATEWAY)
    payment_result = payment.create_payment(
        amount=plan["price"],
        user_id=user.id,
        plan_name=plan["name"],
        callback_url=callback_url,
    )

    if not payment_result.get("success"):
        await query.edit_message_text(
            f"❌ خطا در ساخت درخواست پرداخت:\n{payment_result.get('error', 'Unknown error')}"
        )
        return CHOOSING

    # ذخیره اطلاعات پرداخت
    order_id = payment_result.get("order_id", "")
    context.user_data["payment_order_id"] = order_id
    context.user_data["payment_amount"] = plan["price"]

    # ارسال لینک پرداخت
    pay_url = payment.get_pay_url(payment_result)
    price_formatted = f"{plan['price']:,}".replace(",", "،")

    keyboard = [
        [InlineKeyboardButton("💳 پرداخت", url=pay_url)],
        [InlineKeyboardButton("✅ پرداخت کردم", callback_data="verify_payment")],
        [InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"💳 **درخواست پرداخت ساخته شد!**\n\n"
        f"📋 پلن: {plan['name']}\n"
        f"💰 مبلغ: {price_formatted} تومان\n\n"
        f"روی دکمه «💳 پرداخت» کلیک کنید و پرداخت رو انجام بدید.\n"
        f"بعد از پرداخت، روی «✅ پرداخت کردم» کلیک کنید.",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )
    return CONFIRMING_PURCHASE


async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش وضعیت تمام اشتراک‌ها"""
    user = update.effective_user
    subscriptions = db.get_user_subscriptions(user.id)

    if not subscriptions:
        await update.message.reply_text(
            "❌ شما هنوز اشتراکی ندارید!\n\n"
            "برای خرید اشتراک، روی «🛒 خرید اشتراک» کلیک کنید."
        )
        return

    text = "📊 **وضعیت اشتراک‌های شما:**\n\n"

    for i, sub in enumerate(subscriptions, 1):
        status = sub.get("status", "unknown")
        if status == "active":
            status_icon = "🟢 فعال"
        elif status == "expired":
            status_icon = "🔴 منقضی"
        else:
            status_icon = "⚪ لغو شده"

        plan_name = sub.get("plan_name", "نامشخص")
        data_limit = sub.get("data_limit", 0)
        data_used = sub.get("data_used", 0)
        start_date = sub.get("start_date", "نامشخص")
        expire_date = sub.get("expire_date", "نامشخص")

        # نمایش حجم
        if data_limit > 0:
            remaining = round(data_limit - data_used, 2)
            data_text = f"📊 حجم: {data_used} از {data_limit} گیگ (باقیمانده: {remaining} گیگ)"
        else:
            data_text = f"📊 حجم: {data_used} گیگ (نامحدود)"

        # نمایش تاریخ شروع و انقضا
        try:
            start_fmt = datetime.fromisoformat(start_date).strftime("%Y/%m/%d")
        except:
            start_fmt = start_date[:10] if start_date else "نامشخص"
        try:
            expire_fmt = datetime.fromisoformat(expire_date).strftime("%Y/%m/%d")
        except:
            expire_fmt = expire_date[:10] if expire_date else "نامشخص"

        account_name = sub.get("account_name") or f"tg_{user.id}"
        text += f"**{i}. {plan_name}** - {status_icon}\n"
        text += f"   📝 نام اکانت: {account_name}\n"
        text += f"   {data_text}\n"
        text += f"   📅 شروع: {start_fmt} | انقضا: {expire_fmt}\n\n"

    # وضعیت کلی از Hidify
    user_data = get_user_data(user.id)
    if user_data:
        user_uuid = user_data.get("hidify_uuid", "")
        hidify_user = await hidify.get_user(user_uuid)
        if "error" not in hidify_user:
            is_active = hidify_user.get("is_active", False)
            used_gb = round(hidify_user.get("current_usage_GB", 0), 2)
            text += f"---\n"
            text += f"🌐 **وضعیت سرور:** {'🟢 فعال' if is_active else '🔴 غیرفعال'}\n"
            text += f"📊 **حجم کل مصرفی:** {used_gb} گیگ\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت لینک اشتراک‌ها"""
    user = update.effective_user
    subscriptions = db.get_user_subscriptions(user.id)

    if not subscriptions:
        await update.message.reply_text(
            "❌ شما هنوز اشتراکی ندارید!\n\n"
            "برای خرید اشتراک، روی «🛒 خرید اشتراک» کلیک کنید."
        )
        return

    text = "🔗 **لینک اشتراک‌های شما:**\n\n"

    for i, sub in enumerate(subscriptions, 1):
        uuid = sub.get("hidify_uuid", "")
        plan_name = sub.get("plan_name", "نامشخص")
        status = sub.get("status", "unknown")

        if not uuid:
            continue

        subscription_url = f"{HIDIFY_PANEL_URL}/{USER_PROXY_PATH}/{uuid}/"
        status_icon = "🟢" if status == "active" else "🔴"

        account_name = sub.get("account_name") or f"tg_{user.id}"
        text += f"**{i}. {status_icon} {plan_name}** - {account_name}\n"
        text += f"`{subscription_url}`\n\n"

    text += "⚠️ **نکات مهم:**\n"
    text += "• این لینک‌ها را با کسی به اشتراک نگذارید\n"
    text += "• برای اتصال، لینک را در اپلیکیشن VPN کپی کنید\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def renew_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تمدید اشتراک - نمایش اشتراک‌های موجود"""
    user = update.effective_user
    
    # دریافت اشتراک‌های کاربر از دیتابیس
    subscriptions = db.get_user_subscriptions(user.id)
    
    if not subscriptions:
        # بررسی اطلاعات قدیمی
        user_data = get_user_data(user.id)
        if not user_data or not user_data.get("hidify_uuid"):
            await update.message.reply_text(
                "❌ شما هنوز اشتراکی ندارید!\n\n"
                "برای خرید اشتراک، روی «🛒 خرید اشتراک» کلیک کنید."
            )
            return CHOOSING
        # اگر فقط یک اشتراک قدیمی داره، مستقیم به انتخاب پلن بره
        keyboard = []
        plans = get_plans()
        for plan_id, plan in plans.items():
            price_formatted = f"{plan['price']:,}".replace(",", "،")
            keyboard.append([
                InlineKeyboardButton(
                    f"🔄 {plan['name']} - {plan['description']} - {price_formatted} تومان",
                    callback_data=f"renew_plan_{plan_id}",
                )
            ])
        keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🔄 تمدید اشتراک:\n\n"
            "پلن مورد نظر برای تمدید را انتخاب کنید:",
            reply_markup=reply_markup,
        )
        return RENEWING
    
    # اگر چند اشتراک داره، لیست اشتراک‌ها رو نشون بده
    keyboard = []
    for sub in subscriptions:
        # محاسبه وضعیت اشتراک
        status_emoji = "🟢" if sub["status"] == "active" else "🔴"
        status_text = "فعال" if sub["status"] == "active" else "منقضی"
        
        # محاسبه حجم باقیمانده
        data_limit = sub.get("data_limit", 0)
        data_used = sub.get("data_used", 0)
        if data_limit and data_limit > 0:
            data_info = f"📊 {data_limit - data_used:.1f} از {data_limit} گیگ باقیمانده"
        else:
            data_info = "📊 نامحدود"
        
        # تاریخ انقضا
        expire_date = sub.get("expire_date", "")
        if expire_date:
            try:
                expire_dt = datetime.fromisoformat(expire_date)
                if expire_dt < datetime.now():
                    data_info = "🔴 منقضی شده"
            except:
                pass
        
        button_text = f"{status_emoji} {sub['plan_name']} - {status_text}\n{data_info}"
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"renew_sub_{sub['id']}",
            )
        ])
    
    keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔄 تمدید اشتراک:\n\n"
        "کدام اشتراک را می‌خواهید تمدید دهید?",
        reply_markup=reply_markup,
    )
    return RENEWING


async def handle_renew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش درخواست تمدید"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING
    
    # بازگشت به منوی اصلی
    if query.data == "back_to_menu":
        # نمایش منوی اصلی
        user = update.effective_user
        keyboard = [
            [KeyboardButton("🛒 خرید اشتراک")],
            [KeyboardButton("🔄 تمدید اشتراک"), KeyboardButton("📊 وضعیت اشتراک")],
            [KeyboardButton("🔗 لینک اتصال"), KeyboardButton("❓ راهنمای ربات")],
            [KeyboardButton("📚 آموزش‌ها (بزودی)")],
        ]
        if user.id == ADMIN_ID:
            keyboard.append([KeyboardButton("🔧 پنل مدیریت")])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await query.edit_message_text("منوی اصلی:", reply_markup=reply_markup)
        return CHOOSING
    
    # اگر اشتراک خاصی انتخاب شده (renew_sub_123)
    if query.data.startswith("renew_sub_"):
        sub_id = int(query.data.replace("renew_sub_", ""))
        context.user_data["renew_subscription_id"] = sub_id
        
        # نمایش پلن‌های تمدید
        plans = get_plans()
        keyboard = []
        for plan_id, plan in plans.items():
            price_formatted = f"{plan['price']:,}".replace(",", "،")
            keyboard.append([
                InlineKeyboardButton(
                    f"🔄 {plan['name']} - {plan['description']} - {price_formatted} تومان",
                    callback_data=f"renew_plan_{plan_id}",
                )
            ])
        keyboard.append([InlineKeyboardButton("◀️ بازگشت", callback_data="back_to_menu")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🔄 انتخاب پلن جدید:\n\n"
            "پلن مورد نظر برای تمدید را انتخاب کنید:",
            reply_markup=reply_markup,
        )
        return RENEWING
    
    # اگر پلن انتخاب شده (renew_plan_123)
    if not query.data.startswith("renew_plan_"):
        return RENEWING
    
    plan_id = query.data.replace("renew_plan_", "")
    plans = get_plans()
    if plan_id not in plans:
        try:
            await query.edit_message_text("❌ پلن نامعتبر!")
        except:
            await query.answer("❌ پلن نامعتبر!")
        return CHOOSING
    
    plan = plans[plan_id]
    user = update.effective_user
    
    # دریافت subscription_id از context
    sub_id = context.user_data.get("renew_subscription_id")
    target_sub = None
    user_uuid = ""
    
    # دریافت UUID از اشتراک
    if sub_id:
        # دریافت اطلاعات اشتراک از دیتابیس
        user_subscriptions = db.get_user_subscriptions(user.id)
        for s in user_subscriptions:
            if s["id"] == sub_id:
                target_sub = s
                break
        if not target_sub:
            try:
                await query.edit_message_text("❌ اشتراک مورد نظر یافت نشد!")
            except:
                await query.answer("❌ اشتراک یافت نشد!")
            return CHOOSING
        user_uuid = target_sub.get("hidify_uuid", "")
    else:
        user_data = get_user_data(user.id)
        if user_data:
            user_uuid = user_data.get("hidify_uuid", "")
        else:
            try:
                await query.edit_message_text("❌ اطلاعات کاربر یافت نشد!")
            except:
                await query.answer("❌ اطلاعات یافت نشد!")
            return CHOOSING
    
    if not user_uuid:
        try:
            await query.edit_message_text("❌ UUID کاربر یافت نشد!")
        except:
            await query.answer("❌ UUID یافت نشد!")
        return CHOOSING
    
    try:
        await query.edit_message_text("⏳ در حال تمدید اشتراک...")
    except:
        pass
    
    # بروزرسانی در Hidify
    try:
        result = await hidify.update_user(
            user_uuid,
            usage_limit_GB=plan["data_limit"] if plan["data_limit"] > 0 else None,
            package_days=plan["duration"]
        )
    except Exception as e:
        logger.error(f"Error updating user in Hidify: {e}")
        try:
            await query.edit_message_text(f"❌ خطا در اتصال به Hidify:\n{str(e)[:200]}")
        except:
            pass
        return CHOOSING
    
    if "error" in result:
        logger.error(f"Hidify update error: {result['error']}")
        try:
            await query.edit_message_text(f"❌ خطا در تمدید اشتراک:\n{result['error'][:200]}")
        except:
            pass
        return CHOOSING
    
    # محاسبه تاریخ انقضای جدید
    now_ts = int(datetime.now().timestamp())
    new_expire = now_ts + (plan["duration"] * 86400)

    # بروزرسانی اطلاعات کاربر
    user_data = get_user_data(user.id)
    if user_data:
        user_data["plan"] = plan_id
        user_data["expire_at"] = new_expire
        user_data["data_limit"] = plan["data_limit"]
        save_user_data(user.id, user_data)

    # بروزرسانی اشتراک در دیتابیس
    if sub_id:
        db.update_subscription(sub_id, {
            "plan_id": plan_id,
            "plan_name": plan["name"],
            "data_limit": plan["data_limit"],
            "duration": plan["duration"],
            "expire_date": datetime.fromtimestamp(new_expire).isoformat(),
            "status": "active",
        })
    else:
        # ذخیره اشتراک جدید
        # دریافت نام اکانت از اشتراک قبلی یا پیش‌فرض
        account_name = None
        account_comment = None
        if target_sub:
            account_name = target_sub.get("account_name")
            account_comment = target_sub.get("account_comment")
        db.save_subscription(
            telegram_id=user.id,
            hidify_uuid=user_uuid,
            plan_id=plan_id,
            plan_name=plan["name"],
            data_limit=plan["data_limit"],
            duration=plan["duration"],
            status="active",
            account_name=account_name or f"tg_{user.id}",
            account_comment=account_comment,
        )

    price_formatted = f"{plan['price']:,}".replace(",", "،")
    data_text = str(plan['data_limit']) if plan['data_limit'] > 0 else 'نامحدود'
    success_text = (
        f"✅ اشتراک شما با موفقیت تمدید شد!\n\n"
        f"📋 پلن: {plan['name']}\n"
        f"📊 حجم: {data_text} گیگابایت\n"
        f"⏰ مدت: {plan['duration']} روز\n"
        f"💰 قیمت: {price_formatted} تومان\n\n"
        f"برای دریافت لینک اتصال، روی دکمه «🔗 لینک اتصال» کلیک کنید."
    )
    try:
        await query.edit_message_text(success_text)
    except Exception as e:
        logger.error(f"Error sending success message: {e}")
        try:
            await query.answer("✅ تمدید موفقیت‌آمیز بود!")
        except:
            pass
    return CHOOSING


async def verify_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید پرداخت"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING

    if query.data != "verify_payment":
        return CONFIRMING_PURCHASE

    # بررسی آیا اشتراک قبلاً ساخته شده
    user = update.effective_user
    existing_data = get_user_data(user.id)
    if existing_data and existing_data.get("hidify_uuid"):
        await query.edit_message_text(
            "✅ اشتراک شما قبلاً فعال شده است!\n\n"
            "برای دریافت لینک اتصال، روی دکمه «🔗 لینک اتصال» کلیک کنید."
        )
        return CHOOSING

    await query.edit_message_text("⏳ در حال بررسی پرداخت...")

    order_id = context.user_data.get("payment_order_id", "")
    amount = context.user_data.get("payment_amount", 0)
    plan_id = context.user_data.get("selected_plan")

    if not order_id or not plan_id:
        await query.edit_message_text("❌ اطلاعات پرداخت یافت نشد!")
        return CHOOSING

    # تایید پرداخت
    payment = PaymentManager(PAYMENT_GATEWAY)
    verify_result = payment.verify_payment(
        authority=context.user_data.get("payment_authority"),
        amount=amount,
        payment_id=context.user_data.get("payment_id"),
        order_id=order_id,
    )

    if not verify_result.get("success"):
        keyboard = [
            [InlineKeyboardButton("🔄 تلاش مجدد", callback_data="confirm_purchase")],
            [InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"❌ **پرداخت تایید نشد!**\n\n"
            f"دلیل: {verify_result.get('error', 'نامشخص')}\n\n"
            f"اگر پرداخت رو انجام دادید، دوباره تلاش کنید.",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
        return CONFIRMING_PURCHASE

    # پرداخت موفق - ساخت اشتراک
    plans = get_plans()
    plan = plans[plan_id]
    
    # استفاده از نام انتخاب شده توسط کاربر
    username = context.user_data.get("account_name", f"tg_{user.id}")
    account_comment = context.user_data.get("account_comment")

    # نمایش پیام در حال ساخت
    try:
        await query.edit_message_text("⏳ در حال ساخت اشتراک...")
    except Exception as e:
        logger.error(f"Error editing message: {e}")

    # ساخت کاربر در Hidify
    try:
        result = await hidify.create_user(
            name=username,
            usage_limit_gb=plan["data_limit"] if plan["data_limit"] > 0 else None,
            package_days=plan["duration"],
            enable=True,
            comment=account_comment
        )
    except Exception as e:
        logger.error(f"Error creating user in Hidify: {e}")
        try:
            await query.edit_message_text(f"❌ خطا در ساخت اشتراک:\n{str(e)[:200]}")
        except:
            pass
        return CHOOSING

    if "error" in result:
        try:
            await query.edit_message_text(f"❌ خطا در ساخت اشتراک:\n{result['error'][:200]}")
        except:
            pass
        return CHOOSING

    # ذخیره اطلاعات کاربر و اشتراک
    try:
        user_uuid = result.get("uuid", "")

        # ذخیره اطلاعات کاربر
        user_data = {
            "telegram_id": user.id,
            "username": username,
            "hidify_uuid": user_uuid,
            "plan": plan_id,
            "created_at": datetime.now().isoformat(),
            "data_limit": plan["data_limit"],
        }
        save_user_data(user.id, user_data)

        # ذخیره اشتراک جدید
        db.save_subscription(
            telegram_id=user.id,
            hidify_uuid=user_uuid,
            plan_id=plan_id,
            plan_name=plan["name"],
            data_limit=plan["data_limit"],
            duration=plan["duration"],
            status="active",
            account_name=username,
            account_comment=account_comment,
        )
        logger.info(f"User data and subscription saved: {user.id} -> {user_uuid}")
    except Exception as e:
        logger.error(f"Error saving user data: {e}")
        # ادامه بده حتی اگه ذخیره نشد

    # بروزرسانی تراکنش
    try:
        db.update_transaction(
            order_id=order_id,
            status="completed",
            ref_id=verify_result.get("ref_id") or verify_result.get("track_id"),
        )
    except Exception as e:
        logger.error(f"Error updating transaction: {e}")
        # ادامه بده حتی اگه تراکنش آپدیت نشد

    # نمایش پیام موفقیت + لینک اتصال خودکار
    price_formatted = f"{plan['price']:,}".replace(",", "،")
    subscription_url = f"{HIDIFY_PANEL_URL}/{USER_PROXY_PATH}/{user_uuid}/"
    data_text = str(plan['data_limit']) if plan['data_limit'] > 0 else 'نامحدود'
    success_text = (
        f"✅ پرداخت موفق! اشتراک فعال شد!\n\n"
        f"📋 پلن: {plan['name']}\n"
        f"📊 حجم: {data_text} گیگابایت\n"
        f"⏰ مدت: {plan['duration']} روز\n"
        f"💰 قیمت: {price_formatted} تومان\n\n"
        f"🔗 لینک اتصال شما:\n"
        f"`{subscription_url}`\n\n"
        f"⚠️ این لینک را در اپلیکیشن VPN کپی کنید."
    )
    try:
        await query.edit_message_text(success_text)
    except Exception as e:
        logger.error(f"Error sending success message: {e}")
        try:
            await context.bot.send_message(chat_id=user.id, text=success_text)
        except:
            pass
    return CHOOSING


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش پیام‌های متنی"""
    text = update.message.text

    if text == "🛒 خرید اشتراک":
        return await show_plans(update, context)
    elif text == "🔄 تمدید اشتراک":
        return await renew_subscription(update, context)
    elif text == "📊 وضعیت اشتراک":
        return await show_status(update, context)
    elif text == "🔗 لینک اتصال":
        return await get_link(update, context)
    elif text == "❓ راهنمای ربات":
        return await help_command(update, context)
    elif text == "📚 آموزش‌ها (بزودی)":
        await update.message.reply_text("⏳ این بخش بزودی اضافه خواهد شد!")
    elif text == "🔧 پنل مدیریت" and update.effective_user.id == ADMIN_ID:
        return await admin_panel(update, context)
    else:
        await update.message.reply_text(
            "لطفاً از منوی زیر یکی از گزینه‌ها را انتخاب کنید:"
        )


async def copy_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """کپی لینک"""
    query = update.callback_query
    await query.answer("لینک کپی شد! ✅", show_alert=True)


# ═══════════════════════════════════════════════════════════════════════
# هندلرهای ادمین
# ═══════════════════════════════════════════════════════════════════════

async def admin_approve_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تایید پرداخت توسط ادمین"""
    query = update.callback_query
    await query.answer()

    # بررسی ادمین بودن
    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ شما ادمین نیستید!", show_alert=True)
        return

    data = query.data.replace("admin_approve_", "")
    parts = data.split("_")
    if len(parts) < 2:
        await query.edit_message_text("❌ داده نامعتبر!")
        return

    user_id = int(parts[0])
    plan_id = parts[1]

    plans = get_plans()
    plan = plans.get(plan_id, {})
    
    # دریافت اطلاعات تراکنش برای نام اکانت
    user_transactions = db.get_user_transactions(user_id)
    latest_transaction = user_transactions[0] if user_transactions else None
    
    if latest_transaction and latest_transaction.get("account_name"):
        username = latest_transaction["account_name"]
        account_comment = latest_transaction.get("account_comment")
    else:
        username = f"tg_{user_id}"
        account_comment = None

    # ساخت اشتراک در Hidify
    try:
        result = await hidify.create_user(
            name=username,
            usage_limit_gb=plan.get("data_limit") if plan.get("data_limit", 0) > 0 else None,
            package_days=plan.get("duration", 30),
            enable=True,
            comment=account_comment
        )
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        await query.edit_message_text(f"❌ خطا در ساخت اشتراک:\n{str(e)[:200]}")
        return

    if "error" in result:
        await query.edit_message_text(f"❌ خطا در ساخت اشتراک:\n{result['error'][:200]}")
        return

    # ذخیره اطلاعات کاربر و اشتراک
    try:
        user_uuid = result.get("uuid", "")
        user_data = {
            "telegram_id": user_id,
            "username": username,
            "hidify_uuid": user_uuid,
            "plan": plan_id,
            "created_at": datetime.now().isoformat(),
            "data_limit": plan.get("data_limit", 0),
        }
        save_user_data(user_id, user_data)

        # ذخیره اشتراک جدید در دیتابیس
        db.save_subscription(
            telegram_id=user_id,
            hidify_uuid=user_uuid,
            plan_id=plan_id,
            plan_name=plan.get("name", "نامشخص"),
            data_limit=plan.get("data_limit", 0),
            duration=plan.get("duration", 30),
            status="active",
            account_name=username,
            account_comment=account_comment,
        )
    except Exception as e:
        logger.error(f"Error saving user data: {e}")

    # بروزرسانی تراکنش
    try:
        # پیدا کردن تراکنش در انتظار کاربر
        pending = db.get_pending_transactions()
        for trans in pending:
            if trans.get("user_id") == user_id:
                db.update_transaction(trans["order_id"], "completed")
                break
    except Exception as e:
        logger.error(f"Error updating transaction: {e}")

    # پیام به ادمین
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")
    await query.edit_message_text(
        f"✅ **اشتراک فعال شد!**\n\n"
        f"👤 کاربر: `{user_id}`\n"
        f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
        f"📊 حجم: {plan.get('data_limit', 0) if plan.get('data_limit', 0) > 0 else 'نامحدود'} گیگ\n"
        f"💰 مبلغ: {price_formatted} تومان",
        parse_mode="Markdown",
    )

    # پیام به کاربر + لینک اتصال خودکار
    plan_data_limit = plan.get('data_limit', 0)
    plan_duration = plan.get('duration', 30)
    data_text = str(plan_data_limit) if plan_data_limit > 0 else 'نامحدود'
    subscription_url = f"{HIDIFY_PANEL_URL}/{USER_PROXY_PATH}/{user_uuid}/"
    user_text = (
        f"✅ پرداخت تایید شد! اشتراک فعال شد!\n\n"
        f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
        f"📊 حجم: {data_text} گیگ\n"
        f"⏰ مدت: {plan_duration} روز\n\n"
        f"🔗 لینک اتصال شما:\n"
        f"`{subscription_url}`\n\n"
        f"⚠️ این لینک را در اپلیکیشن VPN کپی کنید."
    )
    try:
        await context.bot.send_message(chat_id=user_id, text=user_text)
    except Exception as e:
        logger.error(f"Error sending message to user: {e}")


async def admin_reject_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """رد پرداخت توسط ادمین"""
    query = update.callback_query
    await query.answer()

    # بررسی ادمین بودن
    if update.effective_user.id != ADMIN_ID:
        await query.answer("❌ شما ادمین نیستید!", show_alert=True)
        return

    data = query.data.replace("admin_reject_", "")
    user_id = int(data)

    # بروزرسانی تراکنش
    try:
        # پیدا کردن تراکنش در انتظار کاربر
        pending = db.get_pending_transactions()
        for trans in pending:
            if trans.get("user_id") == user_id:
                db.update_transaction(trans["order_id"], "rejected")
                break
    except Exception as e:
        logger.error(f"Error updating transaction: {e}")

    # پیام به ادمین
    await query.edit_message_text(
        f"❌ **پرداخت رد شد**\n\n"
        f"👤 کاربر: `{user_id}`",
        parse_mode="Markdown",
    )

    # پیام به کاربر
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ **پرداخت شما تایید نشد!**\n\n"
                 "لطفاً با پشتیبانی تماس بگیرید.",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error sending message to user: {e}")


async def admin_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تست اتصال ادمین"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    await update.message.reply_text(
        f"✅ **اتصال ادمین فعال است!**\n\n"
        f"🆔 آیدی عددی شما: `{user.id}`\n"
        f"👤 نام: {user.first_name}\n"
        f"💬 یوزرنیم: @{user.username or 'ندارد'}\n\n"
        f"از این به بعد رسیدهای پرداخت کارت به کارت به اینجا ارسال میشود.",
        parse_mode="Markdown",
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پنل مدیریت ادمین"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    text = """
🔧 **پنل مدیریت**

از منوی زیر می‌توانید تنظیمات ربات را مدیریت کنید:
"""

    keyboard = [
        [InlineKeyboardButton("💳 مدیریت کارت‌ها", callback_data="admin_cards")],
        [InlineKeyboardButton("📦 مدیریت پلن‌ها", callback_data="admin_plans")],
        [InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats_btn")],
        [InlineKeyboardButton("🔒 پشتیبان‌گیری", callback_data="admin_backup")],
        [InlineKeyboardButton("🔄 بازیابی پشتیبان", callback_data="admin_restore")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return ADMIN_MENU


async def admin_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش منوی ادمین"""
    query = update.callback_query
    await query.answer()

    if query.data == "admin_back":
        await query.edit_message_text("❌ پنل مدیریت بسته شد.")
        return ConversationHandler.END

    if query.data == "admin_cards":
        return await show_cards_menu(update, context)

    if query.data == "admin_plans":
        return await show_plans_menu(update, context)

    if query.data == "admin_stats_btn":
        return await admin_stats(update, context)

    if query.data == "admin_backup":
        return await admin_backup_handler(update, context)

    if query.data == "admin_restore":
        return await admin_restore_handler(update, context)

    return ADMIN_MENU


# ═══════════════════════════════════════════════════════════════════════
# مدیریت کارت‌ها
# ═══════════════════════════════════════════════════════════════════════

async def show_cards_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی مدیریت کارت‌ها"""
    query = update.callback_query
    await query.answer()

    cards = get_all_cards()

    if not cards:
        text = "💳 **مدیریت کارت‌ها**\n\n⚠️ هنوز کارتی اضافه نشده است.\n\nکارت جدید اضافه کنید:"
    else:
        text = "💳 **مدیریت کارت‌ها**\n\n"
        for card_id, card in cards.items():
            status = "🟢" if card.get("is_active") else "🔴"
            text += f"{status} `{card_id}`\n"
            text += f"  📌 {card['card_number']}\n"
            text += f"  👤 {card['card_holder']}\n"
            text += f"  🏦 {card['bank_name']}\n\n"

    keyboard = [
        [InlineKeyboardButton("➕ افزودن کارت", callback_data="add_card")],
    ]

    # اضافه کردن دکمه‌های مدیریت برای هر کارت
    for card_id in cards:
        keyboard.append([
            InlineKeyboardButton(f"✏️ ویرایش {card_id}", callback_data=f"edit_card_{card_id}"),
            InlineKeyboardButton(f"🗑 حذف {card_id}", callback_data=f"del_card_{card_id}"),
        ])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return ADMIN_CARDS_MENU


async def cards_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش منوی کارت‌ها"""
    query = update.callback_query
    await query.answer()

    if query.data == "admin_back_menu":
        # بازگشت به پنل اصلی
        text = """
🔧 **پنل مدیریت**

از منوی زیر می‌توانید تنظیمات ربات را مدیریت کنید:
"""
        keyboard = [
            [InlineKeyboardButton("💳 مدیریت کارت‌ها", callback_data="admin_cards")],
            [InlineKeyboardButton("📦 مدیریت پلن‌ها", callback_data="admin_plans")],
            [InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats_btn")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return ADMIN_MENU

    if query.data == "add_card":
        await query.edit_message_text(
            "💳 **افزودن کارت جدید**\n\n"
            "شماره کارت (بدون خط تیره) را وارد کنید:\n"
            "مثال: `6104337912345678`"
        )
        return ADMIN_ADD_CARD_NUMBER

    if query.data.startswith("edit_card_"):
        card_id = query.data.replace("edit_card_", "")
        cards = get_all_cards()
        if card_id in cards:
            card = cards[card_id]
            text = f"""
✏️ **ویرایش کارت** `{card_id}`

📌 شماره: {card['card_number']}
👤 نام: {card['card_holder']}
🏦 بانک: {card['bank_name']}
{'🟢 فعال' if card.get('is_active') else '🔴 غیرفعال'}
"""
            keyboard = [
                [InlineKeyboardButton("🔄 تغییر وضعیت", callback_data=f"toggle_card_{card_id}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_cards")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return ADMIN_CARDS_MENU

    if query.data.startswith("toggle_card_"):
        card_id = query.data.replace("toggle_card_", "")
        cards = get_all_cards()
        if card_id in cards:
            current_status = cards[card_id].get("is_active", False)
            update_card(card_id, is_active=not current_status)
            status = "فعال" if not current_status else "غیرفعال"
            await query.answer(f"کارت {status} شد!", show_alert=True)
        return await show_cards_menu(update, context)

    if query.data.startswith("del_card_"):
        card_id = query.data.replace("del_card_", "")
        result = delete_card(card_id)
        if result.get("success"):
            await query.answer("کارت حذف شد!", show_alert=True)
        else:
            await query.answer(f"خطا: {result.get('error')}", show_alert=True)
        return await show_cards_menu(update, context)

    return ADMIN_CARDS_MENU


async def add_card_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت شماره کارت"""
    card_number = update.message.text.strip().replace("-", "")

    # بررسی شماره کارت
    if not card_number.isdigit() or len(card_number) < 16:
        await update.message.reply_text(
            "❌ شماره کارت نامعتبر است!\n\n"
            "لطفاً شماره ۱۶ رقمی کارت را وارد کنید:"
        )
        return ADMIN_ADD_CARD_NUMBER

    context.user_data["new_card_number"] = card_number
    await update.message.reply_text(
        "👤 **نام صاحب کارت را وارد کنید:**\n\n"
        "مثال: `علی رضایی`"
    )
    return ADMIN_ADD_CARD_HOLDER


async def add_card_holder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت نام صاحب کارت"""
    card_holder = update.message.text.strip()

    if len(card_holder) < 3:
        await update.message.reply_text(
            "❌ نام نامعتبر است!\n\n"
            "لطفاً نام کامل صاحب کارت را وارد کنید:"
        )
        return ADMIN_ADD_CARD_HOLDER

    context.user_data["new_card_holder"] = card_holder
    await update.message.reply_text(
        "🏦 **نام بانک را وارد کنید:**\n\n"
        "مثال: `بانک ملت`\n"
        "یا: `سپه`، `صادرات`، `تجارت`، `ملی` و ..."
    )
    return ADMIN_ADD_CARD_BANK


async def add_card_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت نام بانک"""
    bank_name = update.message.text.strip()

    card_number = context.user_data.get("new_card_number", "")
    card_holder = context.user_data.get("new_card_holder", "")

    # افزودن کارت
    result = add_card(card_number, card_holder, bank_name)

    if result.get("success"):
        await update.message.reply_text(
            f"✅ **کارت با موفقیت اضافه شد!**\n\n"
            f"📌 شماره: `{card_number}`\n"
            f"👤 نام: {card_holder}\n"
            f"🏦 بانک: {bank_name}\n\n"
            f"برای مدیریت کارت‌ها، از دستور /admin_panel استفاده کنید.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"❌ خطا در افزودن کارت:\n{result.get('error', 'نامشخص')}"
        )

    # پاک کردن اطلاعات موقت
    context.user_data.pop("new_card_number", None)
    context.user_data.pop("new_card_holder", None)

    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════
# مدیریت پلن‌ها
# ═══════════════════════════════════════════════════════════════════════

async def show_plans_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی مدیریت پلن‌ها"""
    query = update.callback_query
    await query.answer()

    plans = get_all_plans()

    if not plans:
        text = "📦 **مدیریت پلن‌ها**\n\n⚠️ هنوز پلنی اضافه نشده است.\n\nپلن جدید اضافه کنید:"
    else:
        text = "📦 **مدیریت پلن‌ها**\n\n"
        for plan_id, plan in plans.items():
            status = "🟢" if plan.get("is_active") else "🔴"
            price_formatted = f"{plan['price']:,}".replace(",", "،")
            text += f"{status} `{plan_id}`\n"
            text += f"  📋 {plan['name']}\n"
            text += f"  💰 {price_formatted} تومان\n"
            text += f"  📊 {plan.get('description', '')}\n\n"

    keyboard = [
        [InlineKeyboardButton("➕ افزودن پلن", callback_data="add_plan")],
    ]

    # اضافه کردن دکمه‌های مدیریت برای هر پلن
    for plan_id in plans:
        keyboard.append([
            InlineKeyboardButton(f"✏️ ویرایش {plan_id}", callback_data=f"edit_plan_{plan_id}"),
            InlineKeyboardButton(f"🗑 حذف {plan_id}", callback_data=f"del_plan_{plan_id}"),
        ])

    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return ADMIN_PLANS_MENU


async def plans_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش منوی پلن‌ها"""
    query = update.callback_query
    await query.answer()

    if query.data == "admin_back_menu":
        # بازگشت به پنل اصلی
        text = """
🔧 **پنل مدیریت**

از منوی زیر می‌توانید تنظیمات ربات را مدیریت کنید:
"""
        keyboard = [
            [InlineKeyboardButton("💳 مدیریت کارت‌ها", callback_data="admin_cards")],
            [InlineKeyboardButton("📦 مدیریت پلن‌ها", callback_data="admin_plans")],
            [InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats_btn")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return ADMIN_MENU

    if query.data == "add_plan":
        await query.edit_message_text(
            "📦 **افزودن پلن جدید**\n\n"
            "نام پلن را وارد کنید:\n"
            "مثال: ` Platinum `، ` VIP `، ` ویژه `"
        )
        return ADMIN_ADD_PLAN_NAME

    if query.data.startswith("edit_plan_"):
        plan_id = query.data.replace("edit_plan_", "")
        plans = get_all_plans()
        if plan_id in plans:
            plan = plans[plan_id]
            price_formatted = f"{plan['price']:,}".replace(",", "،")
            text = f"""
✏️ **ویرایش پلن** `{plan_id}`

📋 نام: {plan['name']}
💰 قیمت: {price_formatted} تومان
📊 حجم: {plan.get('data_limit', 0) if plan.get('data_limit', 0) > 0 else 'نامحدود'} گیگ
⏰ مدت: {plan.get('duration', 30)} روز
{'🟢 فعال' if plan.get('is_active') else '🔴 غیرفعال'}
"""
            keyboard = [
                [InlineKeyboardButton("🔄 تغییر وضعیت", callback_data=f"toggle_plan_{plan_id}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_plans")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
        return ADMIN_PLANS_MENU

    if query.data.startswith("toggle_plan_"):
        plan_id = query.data.replace("toggle_plan_", "")
        plans = get_all_plans()
        if plan_id in plans:
            current_status = plans[plan_id].get("is_active", False)
            update_plan(plan_id, is_active=not current_status)
            status = "فعال" if not current_status else "غیرفعال"
            await query.answer(f"پلن {status} شد!", show_alert=True)
        return await show_plans_menu(update, context)

    if query.data.startswith("del_plan_"):
        plan_id = query.data.replace("del_plan_", "")
        result = delete_plan(plan_id)
        if result.get("success"):
            await query.answer("پلن حذف شد!", show_alert=True)
        else:
            await query.answer(f"خطا: {result.get('error')}", show_alert=True)
        return await show_plans_menu(update, context)

    return ADMIN_PLANS_MENU


async def add_plan_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت نام پلن"""
    plan_name = update.message.text.strip()

    if len(plan_name) < 2:
        await update.message.reply_text(
            "❌ نام پلن نامعتبر است!\n\n"
            "لطفاً نام پلن را وارد کنید:"
        )
        return ADMIN_ADD_PLAN_NAME

    context.user_data["new_plan_name"] = plan_name
    await update.message.reply_text(
        "💰 **قیمت پلن (به تومان) را وارد کنید:**\n\n"
        "مثال: `50000`\n"
        "برای پلن رایگان، عدد `0` وارد کنید."
    )
    return ADMIN_ADD_PLAN_PRICE


async def add_plan_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت قیمت پلن"""
    price_text = update.message.text.strip()

    try:
        price = int(price_text)
        if price < 0:
            raise ValueError()
    except:
        await update.message.reply_text(
            "❌ قیمت نامعتبر است!\n\n"
            "لطفاً عدد صحیح وارد کنید:"
        )
        return ADMIN_ADD_PLAN_PRICE

    context.user_data["new_plan_price"] = price
    await update.message.reply_text(
        "📊 **حجم پلن (به گیگابایت) را وارد کنید:**\n\n"
        "مثال: `30`\n"
        "برای پلن نامحدود، عدد `0` وارد کنید."
    )
    return ADMIN_ADD_PLAN_DATA


async def add_plan_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت حجم پلن"""
    data_text = update.message.text.strip()

    try:
        data_limit = int(data_text)
        if data_limit < 0:
            raise ValueError()
    except:
        await update.message.reply_text(
            "❌ حجم نامعتبر است!\n\n"
            "لطفاً عدد صحیح وارد کنید:"
        )
        return ADMIN_ADD_PLAN_DATA

    context.user_data["new_plan_data"] = data_limit
    await update.message.reply_text(
        "⏰ **مدت پلن (به روز) را وارد کنید:**\n\n"
        "مثال: `30` (برای یک ماه)\n"
        "یا: `365` (برای یک سال)"
    )
    return ADMIN_ADD_PLAN_DURATION


async def add_plan_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت مدت پلن"""
    duration_text = update.message.text.strip()

    try:
        duration = int(duration_text)
        if duration < 1:
            raise ValueError()
    except:
        await update.message.reply_text(
            "❌ مدت نامعتبر است!\n\n"
            "لطفاً عدد صحیح وارد کنید:"
        )
        return ADMIN_ADD_PLAN_DURATION

    plan_name = context.user_data.get("new_plan_name", "")
    price = context.user_data.get("new_plan_price", 0)
    data_limit = context.user_data.get("new_plan_data", 0)

    # افزودن پلن
    result = add_plan(plan_name, price, data_limit, duration)

    if result.get("success"):
        price_formatted = f"{price:,}".replace(",", "،")
        data_text = f"{data_limit} گیگ" if data_limit > 0 else "نامحدود"
        await update.message.reply_text(
            f"✅ **پلن با موفقیت اضافه شد!**\n\n"
            f"📋 نام: {plan_name}\n"
            f"💰 قیمت: {price_formatted} تومان\n"
            f"📊 حجم: {data_text}\n"
            f"⏰ مدت: {duration} روز\n\n"
            f"برای مدیریت پلن‌ها، از دستور /admin_panel استفاده کنید.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"❌ خطا در افزودن پلن:\n{result.get('error', 'نامشخص')}"
        )

    # پاک کردن اطلاعات موقت
    context.user_data.pop("new_plan_name", None)
    context.user_data.pop("new_plan_price", None)
    context.user_data.pop("new_plan_data", None)

    return ConversationHandler.END


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """آمار ربات برای ادمین"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        if update.callback_query:
            await update.callback_query.answer("❌ شما ادمین نیستید!", show_alert=True)
        else:
            await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    # دریافت آمار از دیتابیس
    stats = db.get_stats()
    total_users = stats.get("total_users", 0)
    pending = stats.get("pending_transactions", 0)
    completed = stats.get("completed_transactions", 0)
    rejected = stats.get("rejected_transactions", 0)
    total_revenue = stats.get("total_revenue", 0)
    total_backups = stats.get("total_backups", 0)

    # دریافت اطلاعات Hidify
    try:
        users = await hidify.get_users()
        hidify_users = len(users) if isinstance(users, list) else 0
    except:
        hidify_users = 0

    # دریافت اطلاعات پلن‌ها و کارت‌ها
    try:
        plans = get_all_plans()
        active_plans = len([p for p in plans.values() if p.get("is_active")])
        cards = get_all_cards()
        active_cards = len([c for c in cards.values() if c.get("is_active")])
    except:
        active_plans = active_cards = 0

    revenue_formatted = f"{total_revenue:,}".replace(",", "،")
    text = f"""
📊 **آمار ربات**

👥 **کاربران ربات:** {total_users}
🌐 **کاربران Hidify:** {hidify_users}

📦 **پلن‌ها:** {active_plans} فعال
💳 **کارت‌ها:** {active_cards} فعال

💰 **تراکنش‌ها:**
• ⏳ در انتظار: {pending}
• ✅ تایید شده: {completed}
• ❌ رد شده: {rejected}

💵 **درآمد کل:** {revenue_formatted} تومان

🔒 **پشتیبان‌ها:** {total_backups} عدد
"""

    # ارسال پاسخ (چه از دکمه چه از دستور)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════════════
# پشتیبان‌گیری و بازیابی از پنل مدیریت
# ═══════════════════════════════════════════════════════════════════════

async def admin_backup_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پشتیبان‌گیری از پنل مدیریت"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⏳ در حال ایجاد پشتیبان...")

    backup_mgr = BackupManager()
    result = backup_mgr.create_backup()

    if result.get("success"):
        backup_size = result["size"]
        backup_file = result["filename"]

        # ارسال فایل پشتیبان
        with open(result["file"], "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_user.id,
                document=f,
                caption=f"🔒 پشتیبان موفق!\n\n"
                        f"📁 فایل: {backup_file}\n"
                        f"📊 حجم: {backup_size:,} بایت\n"
                        f"📅 تاریخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                        f"برای بازیابی، فایل را ذخیره کرده و از منوی مدیریت گزینه بازیابی پشتیبان را انتخاب کنید.",
            )

        # نمایش پنل مدیریت دوباره
        keyboard = [
            [InlineKeyboardButton("💳 مدیریت کارت‌ها", callback_data="admin_cards")],
            [InlineKeyboardButton("📦 مدیریت پلن‌ها", callback_data="admin_plans")],
            [InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats_btn")],
            [InlineKeyboardButton("🔒 پشتیبان‌گیری", callback_data="admin_backup")],
            [InlineKeyboardButton("🔄 بازیابی پشتیبان", callback_data="admin_restore")],
            [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="✅ پشتیبان با موفقیت ایجاد و ارسال شد!\n\n🔧 پنل مدیریت",
            reply_markup=reply_markup,
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=f"❌ خطا در ایجاد پشتیبان:\n{result.get('error', 'نامشخص')}\n\n🔧 پنل مدیریت",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back_menu")],
            ]),
        )

    return ADMIN_MENU


# وضعیت برای بازیابی پشتیبان
ADMIN_RESTORE_FILE = 90


async def admin_restore_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """درخواست بازیابی پشتیبان"""
    query = update.callback_query
    await query.answer()

    text = (
        "🔄 بازیابی پشتیبان\n\n"
        "⚠️ نکته مهم:\n"
        "• فایل پشتیبان (.db) را ارسال کنید\n"
        "• اطلاعات فعلی بازنویسی خواهد شد\n"
        "• یک پشتیبان از وضعیت فعلی ایجاد میشود\n\n"
        "📎 فایل پشتیبان را ارسال کنید:"
    )

    keyboard = [
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup)
    return ADMIN_RESTORE_FILE


async def handle_restore_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش فایل پشتیبان ارسال شده"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return ConversationHandler.END

    document = update.message.document
    if not document:
        await update.message.reply_text("❌ لطفاً فایل پشتیبان (.db) را ارسال کنید.")
        return ADMIN_RESTORE_FILE

    # بررسی پسوند فایل
    if not document.file_name.endswith('.db'):
        await update.message.reply_text(
            "❌ فایل نامعتبر است!\n\n"
            "فقط فایل‌های با پسوند .db پذیرفته میشوند."
        )
        return ADMIN_RESTORE_FILE

    await update.message.reply_text("⏳ در حال بازیابی پشتیبان...")

    try:
        # دانلود فایل
        file = await document.get_file()
        backup_path = Path("backups") / f"restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        backup_path.parent.mkdir(exist_ok=True)
        await file.download_to_drive(str(backup_path))

        # بازیابی
        backup_mgr = BackupManager()
        result = backup_mgr.restore_backup(str(backup_path))

        if result.get("success"):
            await update.message.reply_text(
                f"✅ بازیابی موفق!\n\n"
                f"📁 فایل بازیابی شده: {document.file_name}\n"
                f"💾 پشتیبان قبلی: {result.get('pre_restore_backup', 'نامشخص')}\n\n"
                f"🔄 ربات با تنظیمات جدید شروع به کار کرد."
            )
        else:
            await update.message.reply_text(
                f"❌ خطا در بازیابی:\n{result.get('error', 'نامشخص')}"
            )

    except Exception as e:
        logger.error(f"Error restoring backup: {e}")
        await update.message.reply_text(
            f"❌ خطا در پردازش فایل:\n{str(e)}"
        )

    # بازگشت به پنل مدیریت
    keyboard = [
        [InlineKeyboardButton("💳 مدیریت کارت‌ها", callback_data="admin_cards")],
        [InlineKeyboardButton("📦 مدیریت پلن‌ها", callback_data="admin_plans")],
        [InlineKeyboardButton("📊 آمار ربات", callback_data="admin_stats_btn")],
        [InlineKeyboardButton("🔒 پشتیبان‌گیری", callback_data="admin_backup")],
        [InlineKeyboardButton("🔄 بازیابی پشتیبان", callback_data="admin_restore")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔧 پنل مدیریت",
        reply_markup=reply_markup,
    )
    return ADMIN_MENU


# ═══════════════════════════════════════════════════════════════════════
# دستورات پشتیبان‌گیری
# ═══════════════════════════════════════════════════════════════════════

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور پشتیبان‌گیری دستی"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    await update.message.reply_text("⏳ در حال ایجاد پشتیبان...")

    backup_mgr = BackupManager()
    result = backup_mgr.create_backup()

    if result.get("success"):
        backup_size = result["size"]
        backup_file = result["filename"]

        # ارسال فایل پشتیبان
        with open(result["file"], "rb") as f:
            await context.bot.send_document(
                chat_id=user.id,
                document=f,
                caption=f"🔒 **پشتیبان موفق!**\n\n"
                        f"📁 فایل: {backup_file}\n"
                        f"📊 حجم: {backup_size:,} بایت\n"
                        f"📅 تاریخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                        f"برای بازیابی، فایل را ذخیره کرده و دستور /restore استفاده کنید.",
                parse_mode="Markdown",
            )
    else:
        await update.message.reply_text(
            f"❌ خطا در ایجاد پشتیبان:\n{result.get('error', 'نامشخص')}"
        )


async def backups_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لیست پشتیبان‌ها"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    backup_mgr = BackupManager()
    backups = backup_mgr.list_backups()

    if not backups:
        await update.message.reply_text("📋 هنوز پشتیبانی ایجاد نشده است.")
        return

    text = "📋 **لیست پشتیبان‌ها:**\n\n"
    for i, backup in enumerate(backups[:10], 1):
        size = backup["size"]
        created = backup["created"][:19]
        text += f"{i}. 📁 {backup['filename']}\n"
        text += f"   📊 {size:,} بایت\n"
        text += f"   📅 {created}\n\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def migrate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مهاجرت از JSON به دیتابیس"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    await update.message.reply_text("⏳ در حال مهاجرت اطلاعات...")

    result = db.migrate_from_json()

    if result.get("success"):
        migrated = result.get("migrated", 0)
        await update.message.reply_text(
            f"✅ **مهاجرت با موفقیت انجام شد!**\n\n"
            f"📊 تعداد رکوردهای مهاجرت شده: {migrated}\n\n"
            f"اطلاعات شما اکنون در دیتابیس ذخیره شده و دیگر پاک نمیشود.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"❌ خطا در مهاجرت:\n{result.get('error', 'نامشخص')}"
        )


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """خروجی گرفتن از دیتابیس"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    await update.message.reply_text("⏳ در حال خروجی گرفتن از دیتابیس...")

    result = db.export_to_json()

    if result.get("success"):
        export_dir = result.get("export_dir", "data/export")
        users = result.get("users", 0)
        transactions = result.get("transactions", 0)
        subscriptions = result.get("subscriptions", 0)

        await update.message.reply_text(
            f"✅ **خروجی با موفقیت ایجاد شد!**\n\n"
            f"📁 مسیر: `{export_dir}`\n\n"
            f"📊 آمار:\n"
            f"• 👥 کاربران: {users}\n"
            f"• 💰 تراکنش‌ها: {transactions}\n"
            f"• 📋 اشتراک‌ها: {subscriptions}\n\n"
            f"⚠️ فایل‌های JSON در پوشه `data/export` ذخیره شدند.\n"
            f"این فایل‌ها را در جای امنی نگه دارید.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"❌ خطا در خروجی گرفتن:\n{result.get('error', 'نامشخص')}"
        )


async def import_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ورودی گرفتن به دیتابیس"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    await update.message.reply_text("⏳ در حال ورودی گرفتن از فایل‌ها...")

    result = db.import_from_json()

    if result.get("success"):
        imported = result.get("imported", 0)
        await update.message.reply_text(
            f"✅ **ورودی با موفقیت انجام شد!**\n\n"
            f"📊 تعداد رکوردهای وارد شده: {imported}\n\n"
            f"اطلاعات با موفقیت به دیتابیس اضافه شد.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"❌ خطا در ورودی گرفتن:\n{result.get('error', 'نامشخص')}"
        )


# ═══════════════════════════════════════════════════════════════════════
# اجرای ربات
# ═══════════════════════════════════════════════════════════════════════

# بررسی متغیرهای محیطی
def check_env_variables():
    """بررسی متغیرهای محیطی ضروری"""
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not HIDIFY_PANEL_URL:
        missing.append("HIDIFY_PANEL_URL")
    if not HIDIFY_API_KEY:
        missing.append("HIDIFY_API_KEY")
    if not HIDIFY_PROXY_PATH:
        missing.append("HIDIFY_PROXY_PATH")
    
    if missing:
        logger.error(f"Missing environment variables: {', '.join(missing)}")
        return False
    return True


def main():
    """راه‌اندازی ربات"""
    # بررسی متغیرهای محیطی
    if not check_env_variables():
        logger.error("Bot cannot start due to missing environment variables!")
        print("ERROR: Missing environment variables. Check .env file.")
        return
    
    # بازیابی خودکار دیتابیس
    restore_result = db.auto_restore()
    if restore_result.get("restored"):
        logger.info(f"Database restored: {restore_result}")
    else:
        logger.info(f"Auto-restore skipped: {restore_result.get('reason', 'unknown')}")
    
    # مهاجرت ستون‌های جدید برای دیتابیس‌های قدیمی
    db.migrate_add_columns()
    
    if not ADMIN_ID or ADMIN_ID == 0:
        logger.warning("ADMIN_ID is not set! Admin features will not work.")
    
    # ساخت Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Conversation Handler برای فرآیند خرید
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^🛒 خرید اشتراک$"), show_plans),
            CommandHandler("admin_panel", admin_panel),
        ],
        states={
            CHOOSING: [
                MessageHandler(filters.Regex("^🛒 خرید اشتراک$"), show_plans),
                MessageHandler(filters.Regex("^🔄 تمدید اشتراک$"), renew_subscription),
                MessageHandler(filters.Regex("^📊 وضعیت اشتراک$"), show_status),
                MessageHandler(filters.Regex("^🔗 لینک اتصال$"), get_link),
                MessageHandler(filters.Regex("^❓ راهنمای ربات$"), help_command),
                MessageHandler(filters.Regex(r"^📚 آموزش\u200cها \(بزودی\)$"), help_command),
                MessageHandler(filters.Regex("^🔧 پنل مدیریت$"), admin_panel),
            ],
            SELECTING_PLAN: [
                CallbackQueryHandler(plan_selected),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
            ],
            SELECTING_NAME_TYPE: [
                CallbackQueryHandler(select_name_type),
            ],
            ENTERING_CUSTOM_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_custom_name),
                CallbackQueryHandler(back_to_name_selection, pattern="^back_to_name_selection$"),
            ],
            CONFIRMING_PURCHASE: [
                CallbackQueryHandler(select_payment_method, pattern="^(confirm_purchase|cancel)$"),
                CallbackQueryHandler(verify_payment_callback, pattern="^(verify_payment|cancel)$"),
                CallbackQueryHandler(confirm_card_payment, pattern="^(confirm_card_payment|cancel)$"),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(back_to_select_plan, pattern="^back_to_select_plan$"),
                CallbackQueryHandler(back_to_name_selection, pattern="^back_to_name_selection$"),
                CallbackQueryHandler(back_to_enter_tracking, pattern="^back_to_enter_tracking$"),
            ],
            SELECTING_PAYMENT: [
                CallbackQueryHandler(handle_payment_method),
                CallbackQueryHandler(back_to_confirm_purchase, pattern="^back_to_confirm_purchase$"),
            ],
            ENTERING_TRACKING_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_tracking_code),
                MessageHandler(filters.PHOTO, enter_tracking_photo),
                CallbackQueryHandler(confirm_card_payment, pattern="^(confirm_card_payment|cancel)$"),
                CallbackQueryHandler(back_to_select_payment, pattern="^back_to_select_payment$"),
            ],
            RENEWING: [
                CallbackQueryHandler(handle_renew, pattern="^renew_"),
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
            ],
            # وضعیت‌های مدیریت ادمین
            ADMIN_MENU: [
                CallbackQueryHandler(admin_menu_handler),
            ],
            ADMIN_CARDS_MENU: [
                CallbackQueryHandler(cards_menu_handler),
            ],
            ADMIN_ADD_CARD_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_card_number),
            ],
            ADMIN_ADD_CARD_HOLDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_card_holder),
            ],
            ADMIN_ADD_CARD_BANK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_card_bank),
            ],
            ADMIN_PLANS_MENU: [
                CallbackQueryHandler(plans_menu_handler),
            ],
            ADMIN_ADD_PLAN_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_name),
            ],
            ADMIN_ADD_PLAN_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_price),
            ],
            ADMIN_ADD_PLAN_DATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_data),
            ],
            ADMIN_ADD_PLAN_DURATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_plan_duration),
            ],
            ADMIN_RESTORE_FILE: [
                MessageHandler(filters.Document.ALL, handle_restore_file),
                CallbackQueryHandler(admin_menu_handler, pattern="^admin_back_menu$"),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^❌ لغو$"), cancel),
        ],
        conversation_timeout=300,  # 5 دقیقه timeout
    )

    # اضافه کردن هندلرها
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", show_status))
    application.add_handler(CommandHandler("link", get_link))
    application.add_handler(CommandHandler("admin_stats", admin_stats))
    application.add_handler(CommandHandler("admin_test", admin_test))
    application.add_handler(CommandHandler("admin_panel", admin_panel))

    # دستورات پشتیبان‌گیری و مدیریت داده‌ها
    application.add_handler(CommandHandler("backup", backup_command))
    application.add_handler(CommandHandler("backups", backups_list))
    application.add_handler(CommandHandler("migrate", migrate_command))
    application.add_handler(CommandHandler("export", export_command))
    application.add_handler(CommandHandler("import", import_command))

    # هندلر کپی لینک (خارج از ConversationHandler)
    application.add_handler(CallbackQueryHandler(copy_link_callback, pattern="^copy_link$"))

    # هندلرهای ادمین
    application.add_handler(CallbackQueryHandler(admin_approve_payment, pattern="^admin_approve_"))
    application.add_handler(CallbackQueryHandler(admin_reject_payment, pattern="^admin_reject_"))

    # هندلر پیام‌های متنی
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # ─── راه‌اندازی پشتیبان‌گیری خودکار ───
    backup_scheduler = AutoBackupScheduler(admin_id=ADMIN_ID)

    async def post_init(application):
        """تنظیمات بعد از شروع application"""
        backup_scheduler.set_bot(application.bot)
        await backup_scheduler.start()
        logger.info("Auto backup scheduler started")

    async def post_shutdown(application):
        """توقف قبل از بسته شدن"""
        await backup_scheduler.stop()
        logger.info("Auto backup scheduler stopped")

    application.post_init = post_init
    application.post_shutdown = post_shutdown

    # اجرا
    logger.info("Bot starting...")
    print("Bot is running...")
    print("Press Ctrl+C to stop.")

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
