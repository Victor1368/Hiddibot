#!/usr/bin/env python3
"""
ماژول دیتابیس برای ذخیره‌سازی مشتریان، تنظیمات و تراکنش‌ها
"""

import sqlite3
import json
import os
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# مسیر دیتابیس
DB_DIR = Path("data")
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / "bot_database.db"


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
                status TEXT DEFAULT 'pending',
                ref_id TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(telegram_id)
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
    # مدیریت تراکنش‌ها
    # ═══════════════════════════════════════════════════════════════

    def save_transaction(self, order_id, user_id, username, plan_name, amount, gateway, tracking_code, status="pending"):
        """ذخیره تراکنش"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO transactions
                (order_id, user_id, username, plan_name, amount, gateway, tracking_code, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (order_id, user_id, username, plan_name, amount, gateway, tracking_code, status, now, now))
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


# نمونه singleton
db = Database()
