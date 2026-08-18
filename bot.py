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
) = range(7)

# ─── پلن‌های اشتراک ───
PLANS = {
    "basic": {
        "name": "پایه",
        "price": 50000,
        "data_limit": 30,  # گیگابایت
        "duration": 30,    # روز
        "description": "۳۰ گیگ | ۳۰ روز",
    },
    "standard": {
        "name": "استاندارد",
        "price": 80000,
        "data_limit": 60,
        "duration": 30,
        "description": "۶۰ گیگ | ۳۰ روز",
    },
    "premium": {
        "name": "پریمیوم",
        "price": 120000,
        "data_limit": 100,
        "duration": 30,
        "description": "۱۰۰ گیگ | ۳۰ روز",
    },
    "unlimited": {
        "name": "نامحدود",
        "price": 200000,
        "data_limit": 0,  # 0 = نامحدود
        "duration": 30,
        "description": "نامحدود | ۳۰ روز",
    },
}


# ═══════════════════════════════════════════════════════════════════════
# ساخت نمونه کلاینت Hidify
# ═══════════════════════════════════════════════════════════════════════

hidify = HidifyClient(HIDIFY_PANEL_URL, HIDIFY_API_KEY, HIDIFY_PROXY_PATH)


# ═══════════════════════════════════════════════════════════════════════
# مدیریت اطلاعات کاربران ربات
# ═══════════════════════════════════════════════════════════════════════

def get_user_data(telegram_user_id: int) -> dict:
    """دریافت اطلاعات کاربر از فایل"""
    user_file = DATA_DIR / f"{telegram_user_id}.json"
    if user_file.exists():
        with open(user_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_user_data(telegram_user_id: int, data: dict):
    """ذخیره اطلاعات کاربر در فایل"""
    user_file = DATA_DIR / f"{telegram_user_id}.json"
    with open(user_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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
        [KeyboardButton("🔗 لینک اتصال"), KeyboardButton("❓ راهنما")],
    ]
    
    # اضافه کردن دکمه ادمین
    if user.id == ADMIN_ID:
        keyboard.append([KeyboardButton("📊 آمار ادمین")])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    welcome_text = f"""
سلام {user.first_name}! 👋

به ربات مدیریت VPN خوش آمدید!

از منوی زیر می‌توانید:
• 🛒 خرید اشتراک جدید
• 🔄 تمدید اشتراک
• 📊 مشاهده وضعیت اشتراک
• 🔗 دریافت لینک اتصال
• ❓ راهنما
"""
    
    if user.id == ADMIN_ID:
        welcome_text += "• 📊 آمار ادمین\n"
    
    welcome_text += "\nلطفاً یکی از گزینه‌ها را انتخاب کنید:"
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    return CHOOSING


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لغو مکالمه"""
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
    keyboard = []
    for plan_id, plan in PLANS.items():
        price_formatted = f"{plan['price']:,}".replace(",", "،")
        keyboard.append([
            InlineKeyboardButton(
                f"{plan['name']} - {plan['description']} - {price_formatted} تومان",
                callback_data=f"plan_{plan_id}",
            )
        ])
    keyboard.append([InlineKeyboardButton("❌ انصراف", callback_data="cancel")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🛒 **پلن‌های اشتراک:**\n\nلطفاً یکی از پلن‌های زیر را انتخاب کنید:",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )
    return SELECTING_PLAN


async def plan_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """انتخاب پلن"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING

    plan_id = query.data.replace("plan_", "")
    if plan_id not in PLANS:
        await query.edit_message_text("❌ پلن نامعتبر!")
        return CHOOSING

    plan = PLANS[plan_id]
    context.user_data["selected_plan"] = plan_id

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
            InlineKeyboardButton("❌ انصراف", callback_data="cancel"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return CONFIRMING_PURCHASE


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
    if not plan_id or plan_id not in PLANS:
        await query.edit_message_text("❌ خطا در انتخاب پلن!")
        return CHOOSING

    plan = PLANS[plan_id]
    price_formatted = f"{plan['price']:,}".replace(",", "،")

    text = f"""
💳 **انتخاب روش پرداخت**

📋 پلن: {plan['name']}
💰 مبلغ: {price_formatted} تومان

لطفاً روش پرداخت را انتخاب کنید:
"""

    keyboard = [
        [InlineKeyboardButton("💳 درگاه آنلاین", callback_data="pay_online")],
        [InlineKeyboardButton("💵 کارت به کارت", callback_data="pay_card")],
        [InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    return SELECTING_PAYMENT


async def handle_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش انتخاب روش پرداخت"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return CHOOSING

    plan_id = context.user_data.get("selected_plan")
    plan = PLANS.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

    if query.data == "pay_online":
        # پرداخت آنلاین
        return await confirm_purchase(update, context)

    elif query.data == "pay_card":
        # کارت به کارت
        text = f"""
💵 **پرداخت کارت به کارت**

📋 پلن: {plan.get('name', 'نامشخص')}
💰 مبلغ: {price_formatted} تومان

📌 **اطلاعات کارت:**
```
{CARD_NUMBER}
```
👤 **نام صاحب کارت:** {CARD_HOLDER}
🏦 **بانک:** {BANK_NAME}

⚠️ **نکات مهم:**
• دقیقاً مبلغ بالا را واریز کنید
• بعد از واریز، شماره پیگیری را وارد کنید
• رسید پرداخت برای ادمین ارسال میشود

لطفاً بعد از واریز، شماره پیگیری (۱۰ یا ۱۲ رقمی) را وارد کنید:
"""
        await query.edit_message_text(text, parse_mode="Markdown")
        return ENTERING_TRACKING_CODE

    return SELECTING_PAYMENT


async def enter_tracking_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت شماره پیگیری"""
    tracking_code = update.message.text.strip()

    # بررسی شماره پیگیری
    if not tracking_code.isdigit() or len(tracking_code) < 10:
        await update.message.reply_text(
            "❌ شماره پیگیری نامعتبر است!\n\n"
            "لطفاً شماره پیگیری ۱۰ یا ۱۲ رقمی را وارد کنید:"
        )
        return ENTERING_TRACKING_CODE

    context.user_data["tracking_code"] = tracking_code
    user = update.effective_user
    plan_id = context.user_data.get("selected_plan")
    plan = PLANS.get(plan_id, {})
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

    # تایید اطلاعات
    text = f"""
✅ **تایید پرداخت کارت به کارت**

📋 پلن: {plan.get('name', 'نامشخص')}
💰 مبلغ: {price_formatted} تومان
🔢 شماره پیگیری: {tracking_code}

آیا اطلاعات صحیح است؟
"""
    keyboard = [
        [InlineKeyboardButton("✅ تایید و ارسال", callback_data="confirm_card_payment")],
        [InlineKeyboardButton("❌ انصراف", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
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

    user = update.effective_user
    plan_id = context.user_data.get("selected_plan")
    plan = PLANS.get(plan_id, {})
    tracking_code = context.user_data.get("tracking_code", "")
    price_formatted = f"{plan.get('price', 0):,}".replace(",", "،")

    # ذخیره تراکنش کارت به کارت
    from payment import load_transactions, save_transactions
    order_id = f"card_{user.id}_{int(datetime.now().timestamp())}"
    transactions = load_transactions()
    transactions[order_id] = {
        "user_id": user.id,
        "username": user.username or user.first_name,
        "plan_name": plan.get("name", "نامشخص"),
        "amount": plan.get("price", 0),
        "gateway": "card_to_card",
        "tracking_code": tracking_code,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
    }
    save_transactions(transactions)

    # ارسال پیام به ادمین
    admin_text = f"""
🔔 **رسید پرداخت جدید**

👤 **کاربر:** {user.first_name}
🆔 **آیدی:** `{user.id}`
💬 **یوزرنیم:** @{user.username or 'ندارد'}

📋 **پلن:** {plan.get('name', 'نامشخص')}
💰 **مبلغ:** {price_formatted} تومان
🔢 **شماره پیگیری:** `{tracking_code}`

⏰ **زمان:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

    keyboard = [
        [InlineKeyboardButton("✅ تایید", callback_data=f"admin_approve_{user.id}_{plan_id}")],
        [InlineKeyboardButton("❌ رد", callback_data=f"admin_reject_{user.id}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if ADMIN_ID:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=admin_text,
                reply_markup=reply_markup,
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.error(f"Error sending to admin: {e}")

    # پیام به کاربر
    await query.edit_message_text(
        f"✅ **رسید پرداخت ارسال شد!**\n\n"
        f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
        f"💰 مبلغ: {price_formatted} تومان\n"
        f"🔢 شماره پیگیری: {tracking_code}\n\n"
        f"⏳ پرداخت شما در حال بررسی است.\n"
        f"پس از تایید ادمین، اشتراک شما فعال میشود.\n\n"
        f"💬 پشتیبانی: @admin",
        parse_mode="Markdown",
    )
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
    if not plan_id or plan_id not in PLANS:
        await query.edit_message_text("❌ خطا در انتخاب پلن!")
        return CHOOSING

    plan = PLANS[plan_id]
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
    """نمایش وضعیت اشتراک"""
    user = update.effective_user
    user_data = get_user_data(user.id)

    if not user_data:
        await update.message.reply_text(
            "❌ شما هنوز اشتراکی ندارید!\n\n"
            "برای خرید اشتراک، روی «🛒 خرید اشتراک» کلیک کنید."
        )
        return

    # دریافت اطلاعات از Hidify
    user_uuid = user_data.get("hidify_uuid", "")
    hidify_user = hidify.get_user(user_uuid)

    if "error" in hidify_user:
        await update.message.reply_text(f"❌ خطا در دریافت اطلاعات:\n{hidify_user['error']}")
        return

    # محاسبه حجم مصرفی
    used_data = hidify_user.get("current_usage_GB", 0)
    used_gb = round(used_data, 2)

    data_limit = user_data.get("data_limit", 0)
    if data_limit > 0:
        remaining_gb = round(data_limit - used_gb, 2)
        data_text = f"📊 حجم مصرفی: {used_gb} گیگ از {data_limit} گیگ\n"
        data_text += f"📊 حجم باقیمانده: {remaining_gb} گیگ\n"
    else:
        data_text = f"📊 حجم مصرفی: {used_gb} گیگ (نامحدود)\n"

    # وضعیت
    is_active = hidify_user.get("is_active", False)
    status_text = "🟢 وضعیت: فعال\n" if is_active else "🔴 وضعیت: غیرفعال\n"

    plan = PLANS.get(user_data.get("plan", ""), {})
    plan_name = plan.get("name", "نامشخص")

    text = f"""
📊 **وضعیت اشتراک شما**

{status_text}
📋 پلن: {plan_name}
{data_text}
"""
    await update.message.reply_text(text, parse_mode="Markdown")


async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت لینک اشتراک"""
    user = update.effective_user
    user_data = get_user_data(user.id)

    if not user_data:
        await update.message.reply_text(
            "❌ شما هنوز اشتراکی ندارید!\n\n"
            "برای خرید اشتراک، روی «🛒 خرید اشتراک» کلیک کنید."
        )
        return

    # ساخت لینک اشتراک با پروکسی پچ کاربر
    user_uuid = user_data.get("hidify_uuid", "")
    subscription_url = f"{HIDIFY_PANEL_URL}/{USER_PROXY_PATH}/{user_uuid}/"

    text = f"""
🔗 **لینک اشتراک شما:**

`{subscription_url}`

⚠️ **نکات مهم:**
• این لینک را با کسی به اشتراک نگذارید
• برای اتصال، این لینک را در اپلیکیشن VPN کپی کنید
• در صورت مشکل، لینک را مجدداً دریافت کنید
"""
    keyboard = [
        [
            InlineKeyboardButton(
                "📋 کپی لینک",
                callback_data="copy_link",
            )
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        text, reply_markup=reply_markup, parse_mode="Markdown"
    )


async def renew_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تمدید اشتراک"""
    user = update.effective_user
    user_data = get_user_data(user.id)

    if not user_data:
        await update.message.reply_text(
            "❌ شما هنوز اشتراکی ندارید!\n\n"
            "برای خرید اشتراک، روی «🛒 خرید اشتراک» کلیک کنید."
        )
        return

    # نمایش پلن‌های تمدید
    keyboard = []
    for plan_id, plan in PLANS.items():
        price_formatted = f"{plan['price']:,}".replace(",", "،")
        keyboard.append([
            InlineKeyboardButton(
                f"🔄 {plan['name']} - {plan['description']} - {price_formatted} تومان",
                callback_data=f"renew_{plan_id}",
            )
        ])
    keyboard.append([InlineKeyboardButton("❌ انصراف", callback_data="cancel")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔄 **تمدید اشتراک:**\n\n"
        "پلن مورد نظر برای تمدید را انتخاب کنید:",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


async def handle_renew(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش درخواست تمدید"""
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ عملیات لغو شد.")
        return

    if not query.data.startswith("renew_"):
        return

    plan_id = query.data.replace("renew_", "")
    if plan_id not in PLANS:
        await query.edit_message_text("❌ پلن نامعتبر!")
        return

    plan = PLANS[plan_id]
    user = update.effective_user
    user_data = get_user_data(user.id)

    if not user_data:
        await query.edit_message_text("❌ اطلاعات کاربر یافت نشد!")
        return

    await query.edit_message_text("⏳ در حال تمدید اشتراک...")

    # محاسبه تاریخ انقضای جدید
    current_expire = user_data.get("expire_at", int(datetime.now().timestamp()))
    if current_expire < int(datetime.now().timestamp()):
        # اگر منقضی شده، از الان شروع شود
        new_expire = int((datetime.now() + timedelta(days=plan["duration"])).timestamp())
    else:
        # اگر هنوز فعال است، به مدت اضافه شود
        new_expire = current_expire + (plan["duration"] * 86400)

    # بروزرسانی در Hidify
    user_uuid = user_data.get("hidify_uuid", "")
    result = hidify.update_user(
        user_uuid,
        usage_limit_GB=plan["data_limit"] if plan["data_limit"] > 0 else None,
        package_days=plan["duration"]
    )

    if "error" in result:
        await query.edit_message_text(f"❌ خطا در تمدید اشتراک:\n{result['error']}")
        return

    # بروزرسانی اطلاعات محلی
    user_data["plan"] = plan_id
    user_data["expire_at"] = new_expire
    user_data["data_limit"] = plan["data_limit"]
    save_user_data(user.id, user_data)

    price_formatted = f"{plan['price']:,}".replace(",", "،")
    await query.edit_message_text(
        f"✅ **اشتراک شما با موفقیت تمدید شد!**\n\n"
        f"📋 پلن: {plan['name']}\n"
        f"📊 حجم: {plan['data_limit'] if plan['data_limit'] > 0 else 'نامحدود'} گیگابایت\n"
        f"⏰ مدت: {plan['duration']} روز\n"
        f"💰 قیمت: {price_formatted} تومان\n\n"
        f"برای دریافت لینک اتصال، روی دکمه «🔗 لینک اتصال» کلیک کنید.",
        parse_mode="Markdown",
    )


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
    plan = PLANS[plan_id]
    username = f"tg_{user.id}"

    # نمایش پیام در حال ساخت
    try:
        await query.edit_message_text("⏳ در حال ساخت اشتراک...")
    except Exception as e:
        logger.error(f"Error editing message: {e}")

    # ساخت کاربر در Hidify
    try:
        result = hidify.create_user(
            name=username,
            usage_limit_gb=plan["data_limit"] if plan["data_limit"] > 0 else None,
            package_days=plan["duration"],
            enable=True
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

    # ذخیره اطلاعات کاربر
    try:
        user_uuid = result.get("uuid", "")
        user_data = {
            "telegram_id": user.id,
            "username": username,
            "hidify_uuid": user_uuid,
            "plan": plan_id,
            "created_at": datetime.now().isoformat(),
            "data_limit": plan["data_limit"],
        }
        save_user_data(user.id, user_data)
        logger.info(f"User data saved: {user.id} -> {user_uuid}")
    except Exception as e:
        logger.error(f"Error saving user data: {e}")
        # ادامه بده حتی اگه ذخیره نشد

    # بروزرسانی تراکنش
    try:
        from payment import load_transactions, save_transactions
        transactions = load_transactions()
        if order_id in transactions:
            transactions[order_id]["status"] = "completed"
            transactions[order_id]["ref_id"] = verify_result.get("ref_id") or verify_result.get("track_id")
            save_transactions(transactions)
    except Exception as e:
        logger.error(f"Error updating transaction: {e}")
        # ادامه بده حتی اگه تراکنش آپدیت نشد

    # نمایش پیام موفقیت
    price_formatted = f"{plan['price']:,}".replace(",", "،")
    try:
        await query.edit_message_text(
            f"✅ **پرداخت موفق! اشتراک فعال شد!**\n\n"
            f"📋 پلن: {plan['name']}\n"
            f"📊 حجم: {plan['data_limit'] if plan['data_limit'] > 0 else 'نامحدود'} گیگابایت\n"
            f"⏰ مدت: {plan['duration']} روز\n"
            f"💰 قیمت: {price_formatted} تومان\n\n"
            f"برای دریافت لینک اتصال، روی دکمه «🔗 لینک اتصال» کلیک کنید.",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error sending success message: {e}")
        # تلاش برای ارسال پیام جدید
        try:
            await context.bot.send_message(
                chat_id=user.id,
                text=f"✅ **پرداخت موفق! اشتراک فعال شد!**\n\n"
                     f"📋 پلن: {plan['name']}\n"
                     f"📊 حجم: {plan['data_limit'] if plan['data_limit'] > 0 else 'نامحدود'} گیگابایت\n"
                     f"⏰ مدت: {plan['duration']} روز\n"
                     f"💰 قیمت: {price_formatted} تومان\n\n"
                     f"برای دریافت لینک اتصال، روی دکمه «🔗 لینک اتصال» کلیک کنید.",
                parse_mode="Markdown",
            )
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
    elif text == "❓ راهنما":
        return await help_command(update, context)
    elif text == "📊 آمار ادمین" and update.effective_user.id == ADMIN_ID:
        return await admin_stats(update, context)
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

    plan = PLANS.get(plan_id, {})
    username = f"tg_{user_id}"

    # ساخت اشتراک در Hidify
    try:
        result = hidify.create_user(
            name=username,
            usage_limit_gb=plan.get("data_limit") if plan.get("data_limit", 0) > 0 else None,
            package_days=plan.get("duration", 30),
            enable=True
        )
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        await query.edit_message_text(f"❌ خطا در ساخت اشتراک:\n{str(e)[:200]}")
        return

    if "error" in result:
        await query.edit_message_text(f"❌ خطا در ساخت اشتراک:\n{result['error'][:200]}")
        return

    # ذخیره اطلاعات کاربر
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
    except Exception as e:
        logger.error(f"Error saving user data: {e}")

    # بروزرسانی تراکنش
    try:
        from payment import load_transactions, save_transactions
        transactions = load_transactions()
        for tid, trans in transactions.items():
            if trans.get("user_id") == user_id and trans.get("status") == "pending":
                transactions[tid]["status"] = "completed"
                save_transactions(transactions)
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

    # پیام به کاربر
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ **پرداخت تایید شد! اشتراک فعال شد!**\n\n"
                 f"📋 پلن: {plan.get('name', 'نامشخص')}\n"
                 f"📊 حجم: {plan.get('data_limit', 0) if plan.get('data_limit', 0) > 0 else 'نامحدود'} گیگ\n"
                 f"⏰ مدت: {plan.get('duration', 30)} روز\n\n"
                 f"برای دریافت لینک اتصال، روی دکمه «🔗 لینک اتصال» کلیک کنید.",
            parse_mode="Markdown",
        )
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
        from payment import load_transactions, save_transactions
        transactions = load_transactions()
        for tid, trans in transactions.items():
            if trans.get("user_id") == user_id and trans.get("status") == "pending":
                transactions[tid]["status"] = "rejected"
                save_transactions(transactions)
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


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """آمار ربات برای ادمین"""
    user = update.effective_user

    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ شما ادمین نیستید!")
        return

    # شمارش کاربران
    user_files = list(DATA_DIR.glob("*.json"))
    total_users = len(user_files)

    # شمارش تراکنش‌ها
    try:
        from payment import load_transactions
        transactions = load_transactions()
        pending = sum(1 for t in transactions.values() if t.get("status") == "pending")
        completed = sum(1 for t in transactions.values() if t.get("status") == "completed")
        rejected = sum(1 for t in transactions.values() if t.get("status") == "rejected")
    except:
        pending = completed = rejected = 0

    # دریافت اطلاعات Hidify
    try:
        users = hidify.get_users()
        hidify_users = len(users) if isinstance(users, list) else 0
    except:
        hidify_users = 0

    text = f"""
📊 **آمار ربات**

👥 **کاربران ربات:** {total_users}
🌐 **کاربران Hidify:** {hidify_users}

💰 **تراکنش‌ها:**
• ⏳ در انتظار: {pending}
• ✅ تایید شده: {completed}
• ❌ رد شده: {rejected}
"""
    await update.message.reply_text(text, parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════════════
# اجرای ربات
# ═══════════════════════════════════════════════════════════════════════

def main():
    """راه‌اندازی ربات"""
    # ساخت Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Conversation Handler برای فرآیند خرید
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^🛒 خرید اشتراک$"), show_plans),
        ],
        states={
            CHOOSING: [
                MessageHandler(filters.Regex("^🛒 خرید اشتراک$"), show_plans),
                MessageHandler(filters.Regex("^🔄 تمدید اشتراک$"), renew_subscription),
                MessageHandler(filters.Regex("^📊 وضعیت اشتراک$"), show_status),
                MessageHandler(filters.Regex("^🔗 لینک اتصال$"), get_link),
                MessageHandler(filters.Regex("^❓ راهنما$"), help_command),
            ],
            SELECTING_PLAN: [
                CallbackQueryHandler(plan_selected),
            ],
            CONFIRMING_PURCHASE: [
                CallbackQueryHandler(select_payment_method, pattern="^(confirm_purchase|cancel)$"),
                CallbackQueryHandler(verify_payment_callback, pattern="^(verify_payment|cancel)$"),
                CallbackQueryHandler(confirm_card_payment, pattern="^(confirm_card_payment|cancel)$"),
            ],
            SELECTING_PAYMENT: [
                CallbackQueryHandler(handle_payment_method),
            ],
            ENTERING_TRACKING_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_tracking_code),
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

    # هندلر تمدید (خارج از ConversationHandler)
    application.add_handler(CallbackQueryHandler(handle_renew, pattern="^renew_"))
    application.add_handler(CallbackQueryHandler(copy_link_callback, pattern="^copy_link$"))

    # هندلرهای ادمین
    application.add_handler(CallbackQueryHandler(admin_approve_payment, pattern="^admin_approve_"))
    application.add_handler(CallbackQueryHandler(admin_reject_payment, pattern="^admin_reject_"))

    # هندلر پیام‌های متنی
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # اجرا
    logger.info("Bot started successfully!")
    print("Bot is running...")
    print("Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
