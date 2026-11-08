import logging
import os
import sqlite3
from datetime import datetime

from config import DATABASE_FILE, BACKUP_DIR, TIMEZONE, ADMIN_IDS

logger = logging.getLogger(__name__)


def create_backup():
    """Create a consistent SQLite backup, including committed WAL data."""
    source = destination = None
    backup_path = None
    try:
        if not os.path.isfile(DATABASE_FILE):
            logger.warning("Database file not found; backup skipped.")
            return None
        os.makedirs(BACKUP_DIR, exist_ok=True)
        timestamp = datetime.now(TIMEZONE).strftime("%Y-%m-%d_%H-%M-%S")
        backup_path = os.path.join(BACKUP_DIR, f"giveaway_backup_{timestamp}.db")
        source = sqlite3.connect(DATABASE_FILE, timeout=30)
        destination = sqlite3.connect(backup_path, timeout=30)
        source.backup(destination)
        integrity = destination.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise sqlite3.DatabaseError("Backup integrity check failed.")
        destination.close(); destination = None
        source.close(); source = None
        if not os.path.isfile(backup_path) or os.path.getsize(backup_path) == 0:
            raise OSError("Backup file is missing or empty.")
        logger.info("Database backup created: %s", backup_path)
        return backup_path
    except Exception:
        logger.exception("Database backup failed.")
        if backup_path and os.path.exists(backup_path):
            try: os.remove(backup_path)
            except OSError: pass
        return None
    finally:
        if destination is not None: destination.close()
        if source is not None: source.close()


def list_backups():
    try:
        if not os.path.isdir(BACKUP_DIR): return []
        items = []
        for filename in os.listdir(BACKUP_DIR):
            if not (filename.startswith("giveaway_backup_") and filename.endswith(".db")): continue
            path = os.path.join(BACKUP_DIR, filename)
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                items.append({"filename": filename, "path": path, "size": os.path.getsize(path), "modified": os.path.getmtime(path)})
        return sorted(items, key=lambda x: x["modified"], reverse=True)
    except Exception:
        logger.exception("Could not list database backups.")
        return []


def restore_backup(backup_path):
    """Restore only a valid backup; stop the bot before calling this function."""
    temporary_path = DATABASE_FILE + ".restore_tmp"
    source = destination = validation = None
    try:
        if not backup_path or not os.path.isfile(backup_path):
            return {"success": False, "message": "❌ Selected backup file was not found."}
        backup_real = os.path.realpath(backup_path)
        backup_dir_real = os.path.realpath(BACKUP_DIR)
        if os.path.commonpath([backup_real, backup_dir_real]) != backup_dir_real:
            return {"success": False, "message": "⛔ Invalid backup path."}
        if os.path.getsize(backup_real) <= 0:
            return {"success": False, "message": "❌ The selected backup file is empty."}
        validation = sqlite3.connect(backup_real, timeout=30)
        integrity = validation.execute("PRAGMA integrity_check").fetchone()
        users_table = validation.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        if not integrity or integrity[0] != "ok" or not users_table:
            return {"success": False, "message": "❌ Backup validation failed. Restore cancelled."}
        validation.close(); validation = None
        os.makedirs(os.path.dirname(DATABASE_FILE) or ".", exist_ok=True)
        os.makedirs(BACKUP_DIR, exist_ok=True)
        safety_backup = create_backup() if os.path.isfile(DATABASE_FILE) else None
        if os.path.isfile(DATABASE_FILE) and not safety_backup:
            return {"success": False, "message": "❌ Safety backup could not be created. Restore cancelled."}
        if os.path.exists(temporary_path): os.remove(temporary_path)
        source = sqlite3.connect(backup_real, timeout=30)
        destination = sqlite3.connect(temporary_path, timeout=30)
        source.backup(destination)
        destination.close(); destination = None
        source.close(); source = None
        validation = sqlite3.connect(temporary_path, timeout=30)
        integrity = validation.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            return {"success": False, "message": "❌ Restored copy failed validation."}
        validation.close(); validation = None
        # The bot must be stopped: replacing an open SQLite DB is unsafe.
        for suffix in ("-wal", "-shm"):
            sidecar = DATABASE_FILE + suffix
            if os.path.exists(sidecar):
                try: os.remove(sidecar)
                except OSError: logger.warning("Could not remove SQLite sidecar: %s", sidecar)
        os.replace(temporary_path, DATABASE_FILE)
        return {"success": True, "message": "✅ <b>Database Restored Successfully!</b>\n\nSelected backup restored. Restart the bot.", "safety_backup": safety_backup}
    except Exception:
        logger.exception("Database restore failed.")
        return {"success": False, "message": "❌ Restore failed. Check the hosting logs."}
    finally:
        for connection in (source, destination, validation):
            if connection is not None:
                try: connection.close()
                except Exception: pass
        if os.path.exists(temporary_path):
            try: os.remove(temporary_path)
            except OSError: pass


async def send_backup_to_admins(bot, backup_path):
    if not backup_path or not os.path.isfile(backup_path): return False
    sent = 0
    for admin_id in ADMIN_IDS:
        try:
            with open(backup_path, "rb") as backup_file:
                await bot.send_document(chat_id=admin_id, document=backup_file, filename=os.path.basename(backup_path), caption="🗄️ <b>SF ARMY Database Backup</b>\n\nYour database backup file is attached.", parse_mode="HTML")
            sent += 1
        except Exception:
            logger.exception("Could not send backup to admin %s", admin_id)
    return sent > 0


async def scheduled_backup_job(context):
    backup_path = create_backup()
    if not backup_path:
        logger.error("Scheduled backup failed; no file was created.")
        return
    await send_backup_to_admins(context.bot, backup_path)
