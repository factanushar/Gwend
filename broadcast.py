import asyncio

from config import ADMIN_IDS
from database import get_all_users


def is_authorized_admin(user_id):
    """Check whether the user is an authorized admin."""
    try:
        return int(user_id) in {int(admin_id) for admin_id in ADMIN_IDS}
    except (TypeError, ValueError):
        return False


async def send_broadcast(bot, admin_id, message):
    """
    Send a text broadcast to all registered users.

    Returns a summary of successful and failed deliveries.
    """
    if not is_authorized_admin(admin_id):
        return {
            "success": False,
            "message": "⛔ You are not authorized to send broadcasts.",
            "sent": 0,
            "failed": 0,
            "total": 0,
        }

    message = str(message or "").strip()

    if not message:
        return {
            "success": False,
            "message": "❌ Broadcast message cannot be empty.",
            "sent": 0,
            "failed": 0,
            "total": 0,
        }

    try:
        users = get_all_users() or []
    except Exception:
        return {
            "success": False,
            "message": "❌ Could not retrieve the user list.",
            "sent": 0,
            "failed": 0,
            "total": 0,
        }

    sent = 0
    failed = 0
    total = len(users)

    for user in users:
        user_id = user.get("user_id")

        if not user_id:
            failed += 1
            continue

        try:
            await bot.send_message(
                chat_id=int(user_id),
                text=message,
            )
            sent += 1

        except Exception as error:
            failed += 1
            print(
                f"Broadcast failed for user {user_id}: "
                f"{type(error).__name__}"
            )

        # Avoid sending messages too rapidly.
        await asyncio.sleep(0.05)

    return {
        "success": True,
        "message": (
            "📢 <b>Broadcast Completed</b>\n\n"
            f"👥 Total Users: <b>{total}</b>\n"
            f"✅ Successfully Sent: <b>{sent}</b>\n"
            f"❌ Failed: <b>{failed}</b>"
        ),
        "sent": sent,
        "failed": failed,
        "total": total,
    }


async def send_broadcast_copy(bot, admin_id, source_chat_id, message_id):
    """
    Copy an existing Telegram message to all registered users.
    Useful for forwarding formatted announcements, photos, and other media.
    """
    if not is_authorized_admin(admin_id):
        return {
            "success": False,
            "message": "⛔ You are not authorized to send broadcasts.",
            "sent": 0,
            "failed": 0,
            "total": 0,
        }

    try:
        users = get_all_users() or []
    except Exception:
        return {
            "success": False,
            "message": "❌ Could not retrieve the user list.",
            "sent": 0,
            "failed": 0,
            "total": 0,
        }

    sent = 0
    failed = 0
    total = len(users)

    for user in users:
        user_id = user.get("user_id")

        if not user_id:
            failed += 1
            continue

        try:
            await bot.copy_message(
                chat_id=int(user_id),
                from_chat_id=source_chat_id,
                message_id=message_id,
            )
            sent += 1

        except Exception as error:
            failed += 1
            print(
                f"Broadcast copy failed for user {user_id}: "
                f"{type(error).__name__}"
            )

        await asyncio.sleep(0.05)

    return {
        "success": True,
        "message": (
            "📢 <b>Media Broadcast Completed</b>\n\n"
            f"👥 Total Users: <b>{total}</b>\n"
            f"✅ Successfully Sent: <b>{sent}</b>\n"
            f"❌ Failed: <b>{failed}</b>"
        ),
        "sent": sent,
        "failed": failed,
        "total": total,
    }
