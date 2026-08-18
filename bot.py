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
import httpx
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
# ماژول اتصال به Hidify
# ═══════════════════════════════════════════════════════════════════════

class HidifyClient:
    """کلاینت اتصال به پنل Hidify"""

    def __init__(self, panel_url: str, api_key: str):
        self.panel_url = panel_url.rstrip("/")
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, endpoint: str, data: dict = None) -> dict:
        """ارسال درخواست به API"""
        url = f"{self.panel_url}{endpoint}"
        async with httpx.AsyncClient(verify=False) as client:
            try:
                if method == "GET":
                    response = await client.get(url, headers=self.headers, params=data)
                elif method == "POST":
                    response = await client.post(url, headers=self.headers, json=data)
                elif method == "PUT":
                    response = await client.put(url, headers=self.headers, json=data)
                elif method == "DELETE":
                    response = await client.delete(url, headers=self.headers)
                else:
                    return {"error": "Invalid method"}

                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Hidify API error: {e.response.status_code} - {e.response.text}")
                return {"error": str(e)}
            except Exception as e:
                logger.error(f"Hidify connection error: {e}")
                return {"error": str(e)}

    async def get_users(self) -> list:
        """دریافت لیست کاربران"""
        return await self._request("GET", "/api/user/")

    async def get_user(self, username: str) -> dict:
        """دریافت اطلاعات یک کاربر"""
        return await self._request("GET", f"/api/user/{username}")

    async def create_user(self, username: str, data_limit: int, expire: int) -> dict:
        """
        ساخت کاربر جدید
        data_limit: حجم به بایت (0 = نامحدود)
        expire: تاریخ انقضا به ثانیه (timestamp)
        """
        payload = {
            "username": username,
            "data_limit": data_limit * 1024 * 1024 * 1024 if data_limit > 0 else 0,  # GB to Bytes
            "expire": expire,
            "note": f"Created via Telegram Bot - {datetime.now().isoformat()}",
        }
        return await self._request("POST", "/api/user/", payload)

    async def update_user(self, username: str, data_limit: int = None, expire: int = None) -> dict:
        """بروزرسانی اطلاعات کاربر"""
        payload = {}
        if data_limit is not None:
            payload["data_limit"] = data_limit * 1024 * 1024 * 1024 if data_limit > 0 else 0
        if expire is not None:
            payload["expire"] = expire
        return await self._request("PUT", f"/api/user/{username}", payload)

    async def delete_user(self, username: str) -> dict:
        """حذف کاربر"""
        return await self._request("DELETE", f"/api/user/{username}")

    async def get_user_subscription(self, username: str) -> str:
        """دریافت لینک اشتراک کاربر"""
        result = await self._request("GET", f"/api/user/{username}/subscription")
        if "subscription_url" in result:
            return result["subscription_url"]
        return None

    async def get_user_tokens(self, username: str) -> list:
        """دریافت توکن‌های اتصال کاربر"""
        result = await self._request("GET", f"/api/user/{username}/token")
        if isinstance(result, list):
            return result
        return []

    async def get_inbounds(self) -> list:
        """دریافت لیست inbound‌های موجود"""
        return await self._request("GET", "/api/inbound/")


# ساخت نمونه کلاینت
hidify = HidifyClient(HIDIFY_PANEL_URL, HIDIFY_API_KEY)


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
    """تایید خرید"""
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
    username = f"tg_{user.id}"

    # محاسبه تاریخ انقضا
    expire_time = int((datetime.now() + timedelta(days=plan["duration"])).timestamp())

    # ساخت کاربر در Hidify
    await query.edit_message_text("⏳ در حال ساخت اشتراک...")
    result = await hidify.create_user(username, plan["data_limit"], expire_time)

    if "error" in result:
        await query.edit_message_text(f"❌ خطا در ساخت اشتراک:\n{result['error']}")
        return CHOOSING

    # ذخیره اطلاعات کاربر
    user_data = {
        "telegram_id": user.id,
        "username": username,
        "hidify_username": username,
        "plan": plan_id,
        "created_at": datetime.now().isoformat(),
        "expire_at": expire_time,
        "data_limit": plan["data_limit"],
    }
    save_user_data(user.id, user_data)

    price_formatted = f"{plan['price']:,}".replace(",", "،")
    await query.edit_message_text(
        f"✅ **اشتراک شما با موفقیت فعال شد!**\n\n"
        f"📋 پلن: {plan['name']}\n"
        f"📊 حجم: {plan['data_limit'] if plan['data_limit'] > 0 else 'نامحدود'} گیگابایت\n"
        f"⏰ مدت: {plan['duration']} روز\n"
        f"💰 قیمت: {price_formatted} تومان\n\n"
        f"برای دریافت لینک اتصال، روی دکمه «🔗 لینک اتصال» کلیک کنید.",
        parse_mode="Markdown",
    )
    return CHOOSING


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
    hidify_user = await hidify.get_user(user_data.get("hidify_username", ""))

    if "error" in hidify_user:
        await update.message.reply_text(f"❌ خطا در دریافت اطلاعات:\n{hidify_user['error']}")
        return

    # محاسبه حجم مصرفی
    used_data = hidify_user.get("used_traffic", 0)
    used_gb = round(used_data / (1024 * 1024 * 1024), 2)

    data_limit = user_data.get("data_limit", 0)
    if data_limit > 0:
        remaining_gb = round(data_limit - used_gb, 2)
        data_text = f"📊 حجم مصرفی: {used_gb} گیگ از {data_limit} گیگ\n"
        data_text += f"📊 حجم باقیمانده: {remaining_gb} گیگ\n"
    else:
        data_text = f"📊 حجم مصرفی: {used_gb} گیگ (نامحدود)\n"

    # تاریخ انقضا
    expire_at = hidify_user.get("expire", 0)
    if expire_at:
        expire_date = datetime.fromtimestamp(expire_at)
        days_left = (expire_date - datetime.now()).days
        expire_text = f"⏰ تاریخ انقضا: {expire_date.strftime('%Y/%m/%d')}\n"
        expire_text += f"⏰ روزهای باقیمانده: {days_left} روز\n"
    else:
        expire_text = "⏰ تاریخ انقضا: نامحدود\n"

    # وضعیت
    is_active = hidify_user.get("is_active", False)
    status_text = "🟢 وضعیت: فعال\n" if is_active else "🔴 وضعیت: غیرفعال\n"

    plan = PLANS.get(user_data.get("plan", ""), {})
    plan_name = plan.get("name", "نامشخص")

    text = f"""
📊 **وضعیت اشتراک شما**

{status_text}
📋 پلن: {plan_name}
{data_text}{expire_text}
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

    # دریافت لینک اشتراک
    subscription_url = await hidify.get_user_subscription(
        user_data.get("hidify_username", "")
    )

    if not subscription_url:
        await update.message.reply_text("❌ خطا در دریافت لینک اشتراک!")
        return

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
    result = await hidify.update_user(
        user_data.get("hidify_username", ""),
        plan["data_limit"],
        new_expire,
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
                CallbackQueryHandler(confirm_purchase),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    # اضافه کردن هندلرها
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", show_status))
    application.add_handler(CommandHandler("link", get_link))

    # هندلر تمدید
    application.add_handler(CallbackQueryHandler(handle_renew, pattern="^renew_"))
    application.add_handler(CallbackQueryHandler(copy_link_callback, pattern="^copy_link$"))

    # هندلر پیام‌های متنی
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # اجرا
    logger.info("🚀 ربات شروع به کار کرد!")
    print("🚀 ربات تلگرام VPN در حال اجرا...")
    print("برای توقف، Ctrl+C را بزنید.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
