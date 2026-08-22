#!/usr/bin/env python3
"""
ماژول دیتابیس برای ذخیره‌سازی مشتریان، تنظیمات و تراکنش‌ها
"""

import sqlite3
import json
import os
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# مسیر دیتابیس - از Railway persistent storage یا متغیر محیطی استفاده میکنه
# Railway: اگر Volume دارید، DATA_DIR=/data تنظیم کنید
# در غیر این صورت، دیتابیس در مسیر پروژه ذخیره میشه
POSSIBLE_PATHS = [
    Path(os.environ.get("DATA_DIR", "")),  # Railway Volume
    Path("/data"),  # Railway default persistent
    Path(os.path.expanduser("~/.vpn-bot/data")),  # Home directory
    Path("data"),  # Fallback to project directory
]

DB_DIR = None
for path in POSSIBLE_PATHS:
    if path and path != Path(""):
        try:
            path.mkdir(parents=True, exist_ok=True)
            # تست نوشتن
            test_file = path / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            DB_DIR = path
            break
        except (PermissionError, OSError) as e:
            logger.warning(f"Cannot write to {path}: {e}")
            continue

if DB_DIR is None:
    DB_DIR = Path("data")
    DB_DIR.mkdir(exist_ok=True)

DB_PATH = DB_DIR / "bot_database.db"
logger.info(f"Database path: {DB_PATH}")
logger.info(f"Data directory: {DB_DIR}")


class Database:
    """کلاس مدیریت دیتابیس"""

    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self.init_db()

    def get_connection(self):
        """دریافت اتصال دیتابیس"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def init_db(self):
        """ایجاد جداول دیتابیس"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # جدول مشتریان
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                hidify_uuid TEXT,
                plan_id TEXT,
                data_limit REAL DEFAULT 0,
                expire_at INTEGER,
                created_at TEXT,
                updated_at TEXT
            )
        """)

        # جدول اشتراک‌ها
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                hidify_uuid TEXT,
                plan_id TEXT,
                plan_name TEXT,
                account_name TEXT,
                account_comment TEXT,
                data_limit REAL DEFAULT 0,
                data_used REAL DEFAULT 0,
                duration INTEGER DEFAULT 30,
                start_date TEXT,
                expire_date TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            )
        """)

        # جدول تراکنش‌ها
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                plan_name TEXT,
                amount INTEGER,
                gateway TEXT,
                tracking_code TEXT,
                account_name TEXT,
                account_comment TEXT,
                status TEXT DEFAULT 'pending',
                ref_id TEXT,
                subscription_id INTEGER,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id),
                FOREIGN KEY (subscription_id) REFERENCES subscriptions(id)
            )
        """)

        # جدول تنظیمات
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            )
        """)

        # جدول پشتیبان‌ها
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backup_file TEXT,
                backup_size INTEGER,
                created_at TEXT,
                uploaded BOOLEAN DEFAULT 0
            )
        """)

        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")

    def auto_restore(self):
        """بازیابی خودکار از آخرین پشتیبان اگر دیتابیس خالی باشد"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # بررسی تعداد کاربران
            cursor.execute("SELECT COUNT(*) FROM users")
            count = cursor.fetchone()[0]
            conn.close()
            
            if count > 0:
                logger.info(f"Database has {count} users, no restore needed")
                return {"restored": False, "reason": "database_not_empty"}
            
            logger.info("Database is empty, looking for backups...")
            
            # جستجو برای فایل‌های پشتیبان
            backup_dirs = [
                Path("backups"),
                Path("/data/backups"),
                DB_DIR / "backups",
                Path(os.path.expanduser("~/.vpn-bot/data/backups")),
            ]
            
            all_backups = []
            for backup_dir in backup_dirs:
                if backup_dir.exists():
                    for f in backup_dir.glob("backup_*.db"):
                        all_backups.append(f)
            
            if not all_backups:
                logger.info("No backup files found")
                return {"restored": False, "reason": "no_backups_found"}
            
            # مرتب‌سازی بر اساس تاریخ (جدیدترین اول)
            all_backups.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            latest_backup = all_backups[0]
            
            logger.info(f"Restoring from backup: {latest_backup.name}")
            
            # کپی پشتیبان به مسیر دیتابیس فعلی
            import shutil
            shutil.copy2(latest_backup, self.db_path)
            
            # بررسی نتیجه
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            restored_count = cursor.fetchone()[0]
            conn.close()
            
            logger.info(f"Restored {restored_count} users from {latest_backup.name}")
            return {
                "restored": True,
                "backup_file": latest_backup.name,
                "users_restored": restored_count,
            }
            
        except Exception as e:
            logger.error(f"Error in auto_restore: {e}")
            return {"restored": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════
    # مدیریت مشتریان
    # ═══════════════════════════════════════════════════════════════

    def save_user(self, telegram_id, username, hidify_uuid, plan_id, data_limit, expire_at=None):
        """ذخیره یا بروزرسانی اطلاعات کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        try:
            # بررسی وجود کاربر
            cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
            existing = cursor.fetchone()

            if existing:
                # بروزرسانی
                cursor.execute("""
                    UPDATE users SET
                        username = ?,
                        hidify_uuid = ?,
                        plan_id = ?,
                        data_limit = ?,
                        expire_at = COALESCE(?, expire_at),
                        updated_at = ?
                    WHERE telegram_id = ?
                """, (username, hidify_uuid, plan_id, data_limit, expire_at, now, telegram_id))
            else:
                # درج جدید
                cursor.execute("""
                    INSERT INTO users (telegram_id, username, hidify_uuid, plan_id, data_limit, expire_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (telegram_id, username, hidify_uuid, plan_id, data_limit, expire_at, now, now))

            conn.commit()
            logger.info(f"User {telegram_id} saved successfully")
            return {"success": True}
        except Exception as e:
            logger.error(f"Error saving user {telegram_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_user(self, telegram_id):
        """دریافت اطلاعات کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
        except Exception as e:
            logger.error(f"Error getting user {telegram_id}: {e}")
            return None
        finally:
            conn.close()

    def get_all_users(self):
        """دریافت تمام کاربران"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting all users: {e}")
            return []
        finally:
            conn.close()

    def delete_user(self, telegram_id):
        """حذف کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
            conn.commit()
            logger.info(f"User {telegram_id} deleted")
            return {"success": True}
        except Exception as e:
            logger.error(f"Error deleting user {telegram_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # مدیریت اشتراک‌ها
    # ═══════════════════════════════════════════════════════════════

    def save_subscription(self, telegram_id, hidify_uuid, plan_id, plan_name, data_limit, duration, data_used=0, status="active", account_name=None, account_comment=None):
        """ذخیره اشتراک جدید"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        expire_date = (datetime.now() + timedelta(days=duration)).isoformat()

        try:
            cursor.execute("""
                INSERT INTO subscriptions
                (telegram_id, hidify_uuid, plan_id, plan_name, account_name, account_comment, data_limit, data_used, duration, start_date, expire_date, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (telegram_id, hidify_uuid, plan_id, plan_name, account_name, account_comment, data_limit, data_used, duration, now, expire_date, status, now, now))
            conn.commit()
            subscription_id = cursor.lastrowid
            logger.info(f"Subscription {subscription_id} saved for user {telegram_id}")
            return {"success": True, "subscription_id": subscription_id}
        except Exception as e:
            logger.error(f"Error saving subscription: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_user_subscriptions(self, telegram_id, status=None):
        """دریافت اشتراک‌های کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            if status:
                cursor.execute("""
                    SELECT * FROM subscriptions
                    WHERE telegram_id = ? AND status = ?
                    ORDER BY created_at DESC
                """, (telegram_id, status))
            else:
                cursor.execute("""
                    SELECT * FROM subscriptions
                    WHERE telegram_id = ?
                    ORDER BY created_at DESC
                """, (telegram_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting subscriptions for user {telegram_id}: {e}")
            return []
        finally:
            conn.close()

    def get_active_subscription(self, telegram_id):
        """دریافت اشتراک فعال کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM subscriptions
                WHERE telegram_id = ? AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
            """, (telegram_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting active subscription for user {telegram_id}: {e}")
            return None
        finally:
            conn.close()

    def update_subscription(self, subscription_id, **kwargs):
        """بروزرسانی اشتراک"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        try:
            updates = []
            values = []
            for key, value in kwargs.items():
                updates.append(f"{key} = ?")
                values.append(value)
            updates.append("updated_at = ?")
            values.append(now)
            values.append(subscription_id)

            query = f"UPDATE subscriptions SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, values)
            conn.commit()
            logger.info(f"Subscription {subscription_id} updated")
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating subscription {subscription_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def cancel_subscription(self, subscription_id):
        """لغو اشتراک"""
        return self.update_subscription(subscription_id, status="cancelled")

    # ═══════════════════════════════════════════════════════════════
    # مدیریت تراکنش‌ها
    # ═══════════════════════════════════════════════════════════════

    def save_transaction(self, order_id, user_id, username, plan_name, amount, gateway, tracking_code, status="pending", account_name=None, account_comment=None):
        """ذخیره تراکنش"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO transactions
                (order_id, user_id, username, plan_name, amount, gateway, tracking_code, account_name, account_comment, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (order_id, user_id, username, plan_name, amount, gateway, tracking_code, account_name, account_comment, status, now, now))
            conn.commit()
            logger.info(f"Transaction {order_id} saved")
            return {"success": True}
        except Exception as e:
            logger.error(f"Error saving transaction {order_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def update_transaction(self, order_id, status, ref_id=None):
        """بروزرسانی وضعیت تراکنش"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        try:
            if ref_id:
                cursor.execute("""
                    UPDATE transactions SET status = ?, ref_id = ?, updated_at = ?
                    WHERE order_id = ?
                """, (status, ref_id, now, order_id))
            else:
                cursor.execute("""
                    UPDATE transactions SET status = ?, updated_at = ?
                    WHERE order_id = ?
                """, (status, now, order_id))
            conn.commit()
            logger.info(f"Transaction {order_id} updated to {status}")
            return {"success": True}
        except Exception as e:
            logger.error(f"Error updating transaction {order_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_user_transactions(self, user_id):
        """دریافت تراکنش‌های کاربر"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM transactions WHERE user_id = ?
                ORDER BY created_at DESC
            """, (user_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting transactions for user {user_id}: {e}")
            return []
        finally:
            conn.close()

    def get_transaction_by_order_id(self, order_id):
        """دریافت تراکنش بر اساس order_id"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM transactions WHERE order_id = ?
            """, (order_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting transaction {order_id}: {e}")
            return None
        finally:
            conn.close()

    def get_pending_transactions(self):
        """دریافت تراکنش‌های در انتظار"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM transactions WHERE status = 'pending'
                ORDER BY created_at DESC
            """)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting pending transactions: {e}")
            return []
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # مدیریت تنظیمات
    # ═══════════════════════════════════════════════════════════════

    def save_setting(self, key, value):
        """ذخیره تنظیم"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        try:
            # تبدیل dict/list به JSON
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)

            cursor.execute("""
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, str(value), now))
            conn.commit()
            logger.info(f"Setting {key} saved")
            return {"success": True}
        except Exception as e:
            logger.error(f"Error saving setting {key}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_setting(self, key, default=None):
        """دریافت تنظیم"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                value = row["value"]
                # تلاش برای تبدیل از JSON
                try:
                    return json.loads(value)
                except:
                    return value
            return default
        except Exception as e:
            logger.error(f"Error getting setting {key}: {e}")
            return default
        finally:
            conn.close()

    def get_all_settings(self):
        """دریافت تمام تنظیمات"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM settings")
            rows = cursor.fetchall()
            result = {}
            for row in rows:
                try:
                    result[row["key"]] = json.loads(row["value"])
                except:
                    result[row["key"]] = row["value"]
            return result
        except Exception as e:
            logger.error(f"Error getting all settings: {e}")
            return {}
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # مدیریت پشتیبان‌ها
    # ═══════════════════════════════════════════════════════════════

    def save_backup_record(self, backup_file, backup_size):
        """ذخیره رکورد پشتیبان"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        try:
            cursor.execute("""
                INSERT INTO backups (backup_file, backup_size, created_at, uploaded)
                VALUES (?, ?, ?, 0)
            """, (backup_file, backup_size, now))
            conn.commit()
            return {"success": True, "id": cursor.lastrowid}
        except Exception as e:
            logger.error(f"Error saving backup record: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def mark_backup_uploaded(self, backup_id):
        """علامت‌گذاری پشتیبان به عنوان آپلود شده"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("UPDATE backups SET uploaded = 1 WHERE id = ?", (backup_id,))
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error marking backup as uploaded: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def get_backups(self, limit=10):
        """دریافت لیست پشتیبان‌ها"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM backups ORDER BY created_at DESC LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting backups: {e}")
            return []
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # آمار
    # ═══════════════════════════════════════════════════════════════

    def get_stats(self):
        """دریافت آمار دیتابیس"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            stats = {}

            # تعداد کاربران
            cursor.execute("SELECT COUNT(*) as count FROM users")
            stats["total_users"] = cursor.fetchone()["count"]

            # تعداد تراکنش‌ها
            cursor.execute("SELECT COUNT(*) as count FROM transactions")
            stats["total_transactions"] = cursor.fetchone()["count"]

            # تراکنش‌های در انتظار
            cursor.execute("SELECT COUNT(*) as count FROM transactions WHERE status = 'pending'")
            stats["pending_transactions"] = cursor.fetchone()["count"]

            # تراکنش‌های تایید شده
            cursor.execute("SELECT COUNT(*) as count FROM transactions WHERE status = 'completed'")
            stats["completed_transactions"] = cursor.fetchone()["count"]

            # تراکنش‌های رد شده
            cursor.execute("SELECT COUNT(*) as count FROM transactions WHERE status = 'rejected'")
            stats["rejected_transactions"] = cursor.fetchone()["count"]

            # درآمد کل
            cursor.execute("SELECT COALESCE(SUM(amount), 0) as total FROM transactions WHERE status = 'completed'")
            stats["total_revenue"] = cursor.fetchone()["total"]

            # تعداد پشتیبان‌ها
            cursor.execute("SELECT COUNT(*) as count FROM backups")
            stats["total_backups"] = cursor.fetchone()["count"]

            return stats
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # مهاجرت از JSON به دیتابیس
    # ═══════════════════════════════════════════════════════════════

    def migrate_from_json(self):
        """مهاجرت اطلاعات از فایل‌های JSON به دیتابیس"""
        data_dir = Path("data")
        migrated = 0

        # مهاجرت کاربران
        for user_file in data_dir.glob("*.json"):
            if user_file.name in ["transactions.json", "cards.json", "plans.json"]:
                continue

            try:
                with open(user_file, "r", encoding="utf-8") as f:
                    user_data = json.load(f)

                telegram_id = int(user_file.stem)
                self.save_user(
                    telegram_id=telegram_id,
                    username=user_data.get("username", f"tg_{telegram_id}"),
                    hidify_uuid=user_data.get("hidify_uuid", ""),
                    plan_id=user_data.get("plan", ""),
                    data_limit=user_data.get("data_limit", 0),
                    expire_at=user_data.get("expire_at"),
                )
                migrated += 1
                logger.info(f"Migrated user {telegram_id}")
            except Exception as e:
                logger.error(f"Error migrating {user_file}: {e}")

        # مهاجرت تراکنش‌ها
        transactions_file = data_dir / "transactions.json"
        if transactions_file.exists():
            try:
                with open(transactions_file, "r", encoding="utf-8") as f:
                    transactions = json.load(f)

                for order_id, trans in transactions.items():
                    self.save_transaction(
                        order_id=order_id,
                        user_id=trans.get("user_id", 0),
                        username=trans.get("username", ""),
                        plan_name=trans.get("plan_name", ""),
                        amount=trans.get("amount", 0),
                        gateway=trans.get("gateway", ""),
                        tracking_code=trans.get("tracking_code", ""),
                        status=trans.get("status", "pending"),
                    )
                    migrated += 1
                logger.info(f"Migrated {len(transactions)} transactions")
            except Exception as e:
                logger.error(f"Error migrating transactions: {e}")

        logger.info(f"Migration complete: {migrated} records migrated")
        return {"success": True, "migrated": migrated}

    # ═══════════════════════════════════════════════════════════════
    # مهاجرت خودکار در شروع
    # ═══════════════════════════════════════════════════════════════

    def auto_migrate_on_startup(self):
        """مهاجرت خودکار اگر دیتابیس خالی باشد و فایل‌های JSON وجود داشته باشد"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # بررسی آیا دیتابیس خالی است
            cursor.execute("SELECT COUNT(*) as count FROM users")
            user_count = cursor.fetchone()["count"]

            if user_count > 0:
                logger.info(f"Database has {user_count} users, skipping auto-migration")
                return {"success": True, "skipped": True, "reason": "database_not_empty"}

            # بررسی وجود فایل‌های JSON
            data_dir = Path("data")
            json_files = list(data_dir.glob("*.json"))
            if not json_files:
                logger.info("No JSON files found, skipping auto-migration")
                return {"success": True, "skipped": True, "reason": "no_json_files"}

            # اجرای مهاجرت
            logger.info(f"Found {len(json_files)} JSON files, starting auto-migration...")
            result = self.migrate_from_json()
            logger.info(f"Auto-migration completed: {result.get('migrated', 0)} records migrated")
            return result

        except Exception as e:
            logger.error(f"Error in auto-migration: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    def migrate_add_columns(self):
        """اضافه کردن ستون‌های جدید به جداول قدیمی"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # بررسی وجود ستون‌ها در subscriptions
            cursor.execute("PRAGMA table_info(subscriptions)")
            columns = [row[1] for row in cursor.fetchall()]
            if "account_name" not in columns:
                cursor.execute("ALTER TABLE subscriptions ADD COLUMN account_name TEXT")
                logger.info("Added account_name column to subscriptions")
            if "account_comment" not in columns:
                cursor.execute("ALTER TABLE subscriptions ADD COLUMN account_comment TEXT")
                logger.info("Added account_comment column to subscriptions")
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"Error migrating columns: {e}")
            return {"success": False, "error": str(e)}
        finally:
            conn.close()

    # ═══════════════════════════════════════════════════════════════
    # خروجی گرفتن از دیتابیس
    # ═══════════════════════════════════════════════════════════════

    def export_to_json(self, export_dir=None):
        """خروجی گرفتن از دیتابیس به فایل‌های JSON"""
        if export_dir is None:
            export_dir = Path("data/export")
        else:
            export_dir = Path(export_dir)
        export_dir.mkdir(parents=True, exist_ok=True)

        try:
            # خروجی کاربران
            users = self.get_all_users()
            for user in users:
                user_file = export_dir / f"user_{user['telegram_id']}.json"
                with open(user_file, "w", encoding="utf-8") as f:
                    json.dump(user, f, ensure_ascii=False, indent=2)

            # خروجی تراکنش‌ها
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions")
            transactions = {row["order_id"]: dict(row) for row in cursor.fetchall()}
            conn.close()

            trans_file = export_dir / "transactions.json"
            with open(trans_file, "w", encoding="utf-8") as f:
                json.dump(transactions, f, ensure_ascii=False, indent=2)

            # خروجی اشتراک‌ها
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM subscriptions")
            subscriptions = [dict(row) for row in cursor.fetchall()]
            conn.close()

            subs_file = export_dir / "subscriptions.json"
            with open(subs_file, "w", encoding="utf-8") as f:
                json.dump(subscriptions, f, ensure_ascii=False, indent=2)

            # خروجی تنظیمات
            settings = self.get_all_settings()
            settings_file = export_dir / "settings.json"
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)

            logger.info(f"Export completed to {export_dir}")
            return {
                "success": True,
                "export_dir": str(export_dir),
                "users": len(users),
                "transactions": len(transactions),
                "subscriptions": len(subscriptions),
            }

        except Exception as e:
            logger.error(f"Error exporting data: {e}")
            return {"success": False, "error": str(e)}

    # ═══════════════════════════════════════════════════════════════
    # ورودی گرفتن به دیتابیس
    # ═══════════════════════════════════════════════════════════════

    def import_from_json(self, import_dir=None):
        """ورودی گرفتن از فایل‌های JSON به دیتابیس"""
        if import_dir is None:
            import_dir = Path("data/export")
        else:
            import_dir = Path(import_dir)

        if not import_dir.exists():
            return {"success": False, "error": "Import directory not found"}

        imported = 0

        try:
            # ورودی کاربران
            for user_file in import_dir.glob("user_*.json"):
                try:
                    with open(user_file, "r", encoding="utf-8") as f:
                        user = json.load(f)
                    self.save_user(
                        telegram_id=user.get("telegram_id"),
                        username=user.get("username", ""),
                        hidify_uuid=user.get("hidify_uuid", ""),
                        plan_id=user.get("plan_id", user.get("plan", "")),
                        data_limit=user.get("data_limit", 0),
                        expire_at=user.get("expire_at"),
                    )
                    imported += 1
                except Exception as e:
                    logger.error(f"Error importing {user_file}: {e}")

            # ورودی تراکنش‌ها
            trans_file = import_dir / "transactions.json"
            if trans_file.exists():
                with open(trans_file, "r", encoding="utf-8") as f:
                    transactions = json.load(f)
                for order_id, trans in transactions.items():
                    self.save_transaction(
                        order_id=order_id,
                        user_id=trans.get("user_id", 0),
                        username=trans.get("username", ""),
                        plan_name=trans.get("plan_name", ""),
                        amount=trans.get("amount", 0),
                        gateway=trans.get("gateway", ""),
                        tracking_code=trans.get("tracking_code", ""),
                        status=trans.get("status", "pending"),
                    )
                    imported += 1

            # ورودی اشتراک‌ها
            subs_file = import_dir / "subscriptions.json"
            if subs_file.exists():
                with open(subs_file, "r", encoding="utf-8") as f:
                    subscriptions = json.load(f)
                for sub in subscriptions:
                    conn = self.get_connection()
                    cursor = conn.cursor()
                    try:
                        cursor.execute("""
                            INSERT OR REPLACE INTO subscriptions
                            (telegram_id, hidify_uuid, plan_id, plan_name, data_limit, data_used,
                             duration, start_date, expire_date, status, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            sub.get("telegram_id"),
                            sub.get("hidify_uuid", ""),
                            sub.get("plan_id", ""),
                            sub.get("plan_name", ""),
                            sub.get("data_limit", 0),
                            sub.get("data_used", 0),
                            sub.get("duration", 30),
                            sub.get("start_date"),
                            sub.get("expire_date"),
                            sub.get("status", "active"),
                            sub.get("created_at"),
                            sub.get("updated_at"),
                        ))
                        conn.commit()
                        imported += 1
                    except Exception as e:
                        logger.error(f"Error importing subscription: {e}")
                    finally:
                        conn.close()

            logger.info(f"Import completed: {imported} records imported")
            return {"success": True, "imported": imported}

        except Exception as e:
            logger.error(f"Error importing data: {e}")
            return {"success": False, "error": str(e)}


# نمونه singleton
db = Database()
