#!/usr/bin/env python3
"""
ماژول پشتیبان‌گیری خودکار از دیتابیس
"""

import os
import shutil
import logging
import asyncio
from datetime import datetime
from pathlib import Path
from database import db

logger = logging.getLogger(__name__)

# مسیر پشتیبان‌ها
BACKUP_DIR = Path("backups")
BACKUP_DIR.mkdir(exist_ok=True)


class BackupManager:
    """کلاس مدیریت پشتیبان‌گیری"""

    def __init__(self):
        pass

    def create_backup(self):
        """ایجاد پشتیبان از دیتابیس"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"backup_{timestamp}.db"
            backup_path = BACKUP_DIR / backup_filename

            # کپی دیتابیس
            source_path = db.db_path
            if source_path.exists():
                shutil.copy2(source_path, backup_path)
                backup_size = backup_path.stat().st_size

                # ذخیره رکورد پشتیبان
                result = db.save_backup_record(str(backup_path), backup_size)

                logger.info(f"Backup created: {backup_filename} ({backup_size} bytes)")
                return {
                    "success": True,
                    "file": str(backup_path),
                    "filename": backup_filename,
                    "size": backup_size,
                    "backup_id": result.get("id"),
                }
            else:
                logger.error("Database file not found")
                return {"success": False, "error": "Database file not found"}

        except Exception as e:
            logger.error(f"Error creating backup: {e}")
            return {"success": False, "error": str(e)}

    def restore_backup(self, backup_path):
        """بازیابی دیتابیس از پشتیبان"""
        try:
            backup_path = Path(backup_path)
            if not backup_path.exists():
                return {"success": False, "error": "Backup file not found"}

            # کپی به عنوان پشتیبان از وضعیت فعلی
            current_backup = BACKUP_DIR / f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            if db.db_path.exists():
                shutil.copy2(db.db_path, current_backup)

            # بازیابی
            shutil.copy2(backup_path, db.db_path)

            logger.info(f"Database restored from {backup_path.name}")
            return {
                "success": True,
                "message": f"Database restored from {backup_path.name}",
                "pre_restore_backup": str(current_backup),
            }

        except Exception as e:
            logger.error(f"Error restoring backup: {e}")
            return {"success": False, "error": str(e)}

    def list_backups(self):
        """لیست پشتیبان‌های موجود"""
        backups = []
        for backup_file in sorted(BACKUP_DIR.glob("backup_*.db"), reverse=True):
            backups.append({
                "filename": backup_file.name,
                "path": str(backup_file),
                "size": backup_file.stat().st_size,
                "created": datetime.fromtimestamp(backup_file.stat().st_mtime).isoformat(),
            })
        return backups

    def delete_old_backups(self, keep_count=10):
        """حذف پشتیبان‌های قدیمی"""
        backups = sorted(BACKUP_DIR.glob("backup_*.db"), key=lambda x: x.stat().st_mtime)
        if len(backups) > keep_count:
            for backup in backups[:len(backups) - keep_count]:
                backup.unlink()
                logger.info(f"Deleted old backup: {backup.name}")


async def send_backup_to_admin(bot, admin_id):
    """ارسال پشتیبان به ادمین"""
    if not bot or not admin_id:
        logger.error("Bot or admin_id not set")
        return {"success": False, "error": "Bot or admin_id not set"}

    try:
        backup_mgr = BackupManager()
        
        # ایجاد پشتیبان
        backup_result = backup_mgr.create_backup()
        if not backup_result.get("success"):
            return backup_result

        backup_path = backup_result["file"]
        backup_size = backup_result["size"]
        backup_id = backup_result.get("backup_id")

        # ارسال فایل به ادمین
        with open(backup_path, "rb") as f:
            await bot.send_document(
                chat_id=admin_id,
                document=f,
                caption=f"🔒 **پشتیبان خودکار دیتابیس**\n\n"
                        f"📅 تاریخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"📊 حجم: {backup_size:,} بایت\n"
                        f"📁 فایل: {backup_result['filename']}\n\n"
                        f"برای بازیابی، فایل را ذخیره کرده و دستور /restore استفاده کنید.",
                parse_mode="Markdown",
            )

        # علامت‌گذاری آپلود شده
        if backup_id:
            db.mark_backup_uploaded(backup_id)

        # حذف پشتیبان‌های قدیمی
        backup_mgr.delete_old_backups()

        logger.info(f"Backup sent to admin {admin_id}")
        return {"success": True, "filename": backup_result["filename"]}

    except Exception as e:
        logger.error(f"Error sending backup to admin: {e}")
        return {"success": False, "error": str(e)}


class AutoBackupScheduler:
    """زمان‌بند پشتیبان‌گیری خودکار"""

    def __init__(self, admin_id, interval_hours=3):
        self.admin_id = admin_id
        self.interval_hours = interval_hours
        self.is_running = False
        self.task = None
        self.bot = None  # bot will be set after application starts

    def set_bot(self, bot):
        """تنظیم bot بعد از شروع application"""
        self.bot = bot

    async def start(self):
        """شروع پشتیبان‌گیری خودکار"""
        if self.is_running:
            logger.warning("Auto backup scheduler is already running")
            return

        self.is_running = True
        self.task = asyncio.create_task(self._run_scheduler())
        logger.info(f"Auto backup scheduler started (every {self.interval_hours} hours)")

    async def stop(self):
        """توقف پشتیبان‌گیری خودکار"""
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Auto backup scheduler stopped")

    async def _run_scheduler(self):
        """حلقه اصلی زمان‌بند"""
        # اولین پشتیبان بعد از 10 دقیقه (نه فوری)
        await asyncio.sleep(600)
        
        while self.is_running:
            try:
                if not self.bot:
                    logger.warning("Bot not available for backup, skipping...")
                    await asyncio.sleep(300)
                    continue
                    
                # ایجاد و ارسال پشتیبان
                logger.info("Creating automatic backup...")
                result = await send_backup_to_admin(self.bot, self.admin_id)

                if result.get("success"):
                    logger.info(f"Automatic backup completed: {result.get('filename')}")
                else:
                    logger.error(f"Automatic backup failed: {result.get('error')}")

                # انتظار تا پشتیبان بعدی
                await asyncio.sleep(self.interval_hours * 3600)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in auto backup scheduler: {e}")
                await asyncio.sleep(300)  # 5 دقیقه صبر در صورت خطا


# نمونه singleton (فقط برای BackupManager)
backup_manager = BackupManager()
