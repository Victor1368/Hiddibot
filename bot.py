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
PAYMENT_GATEWAY = os.getenv("PAYMENT_GATEWAY", "zarinpal")

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
    ENTERING_USERNAME,
) = range(4)

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
    keyboard = [
        [KeyboardButton("🛒 خرید اشتراک")],
        [KeyboardButton("🔄 تمدید اشتراک"), KeyboardButton("📊 وضعیت اشتراک")],
        [KeyboardButton("🔗 لینک اتصال"), KeyboardButton("❓ راهنما")],
    ]
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

لطفاً یکی از گزینه‌ها را انتخاب کنید:
"""
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    return CHOOSING


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

    # ساخت لینک اشتراک
    user_uuid = user_data.get("hidify_uuid", "")
    proxy_path = HIDIFY_PROXY_PATH
    subscription_url = f"{HIDIFY_PANEL_URL}/{proxy_path}/{user_uuid}/"

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
    await query.edit_message_text("⏳ در حال ساخت اشتراک...")

    result = hidify.create_user(
        name=username,
        usage_limit_gb=plan["data_limit"] if plan["data_limit"] > 0 else None,
        package_days=plan["duration"],
        enable=True
    )

    if "error" in result:
        await query.edit_message_text(f"❌ خطا در ساخت اشتراک:\n{result['error']}")
        return CHOOSING

    # ذخیره اطلاعات کاربر
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

    # بروزرسانی تراکنش
    from payment import load_transactions, save_transactions
    transactions = load_transactions()
    if order_id in transactions:
        transactions[order_id]["status"] = "completed"
        transactions[order_id]["ref_id"] = verify_result.get("ref_id") or verify_result.get("track_id")
        save_transactions(transactions)

    price_formatted = f"{plan['price']:,}".replace(",", "،")
    await query.edit_message_text(
        f"✅ **پرداخت موفق! اشتراک فعال شد!**\n\n"
        f"📋 پلن: {plan['name']}\n"
        f"📊 حجم: {plan['data_limit'] if plan['data_limit'] > 0 else 'نامحدود'} گیگابایت\n"
        f"⏰ مدت: {plan['duration']} روز\n"
        f"💰 قیمت: {price_formatted} تومان\n\n"
        f"برای دریافت لینک اتصال، روی دکمه «🔗 لینک اتصال» کلیک کنید.",
        parse_mode="Markdown",
    )
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
    else:
        await update.message.reply_text(
            "لطفاً از منوی زیر یکی از گزینه‌ها را انتخاب کنید:"
        )


async def copy_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """کپی لینک"""
    query = update.callback_query
    await query.answer("لینک کپی شد! ✅", show_alert=True)


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
                CallbackQueryHandler(confirm_purchase, pattern="^(confirm_purchase|cancel)$"),
                CallbackQueryHandler(verify_payment_callback, pattern="^(verify_payment|cancel)$"),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    # اضافه کردن هندلرها
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", show_status))
    application.add_handler(CommandHandler("link", get_link))

    # هندلر تمدید (خارج از ConversationHandler)
    application.add_handler(CallbackQueryHandler(handle_renew, pattern="^renew_"))
    application.add_handler(CallbackQueryHandler(copy_link_callback, pattern="^copy_link$"))

    # هندلر پیام‌های متنی
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # اجرا
    logger.info("Bot started successfully!")
    print("Bot is running...")
    print("Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
