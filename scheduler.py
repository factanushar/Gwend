from datetime import time
import html
import logging

from telegram.error import TelegramError

from config import TIMEZONE, BACKUP_HOUR, BACKUP_MINUTE, GIVEAWAY_CHANNEL_ID
from backup import scheduled_backup_job
from database import (
    giveaway_has_ended,
    finalize_giveaway_results,
    get_giveaway_state,
    get_giveaway_results,
    mark_giveaway_notification_status,
    set_giveaway_state,
)

logger = logging.getLogger(__name__)
BACKUP_JOB_NAME = "daily_database_backup"
GIVEAWAY_FINALIZE_JOB_NAME = "finalize_10k_giveaway"

NFT_REWARDS = {
    1: ("Star Notepad NFT", "https://t.me/nft/StarNotepad-42379"),
    2: ("Chill Flame NFT", "https://t.me/nft/ChillFlame-107767"),
    3: ("Ice Cream NFT", "https://t.me/nft/IceCream-327731"),
}


def _winner_reward(rank):
    if rank in NFT_REWARDS:
        name, link = NFT_REWARDS[rank]
        return f'<a href="{link}">{html.escape(name)}</a>'
    if 4 <= rank <= 10:
        return "Teddy + Telegram/WhatsApp account choice"
    if 11 <= rank <= 33:
        return "Teddy"
    if 34 <= rank <= 50:
        return "Telegram/WhatsApp account choice"
    return "No reward assigned"


def _format_winner_lines(winners):
    lines = [
        "🏆 <b>SF ARMY 10K GIVEAWAY — FINAL RESULTS</b>",
        "🎉 <b>Qualified Top 50 Users</b>",
        "",
    ]
    for winner in winners:
        rank = int(winner.get("final_rank") or 0)
        name = " ".join(x for x in [winner.get("first_name"), winner.get("last_name")] if x).strip() or "Unknown User"
        username = winner.get("username")
        label = f"@{username.lstrip('@')}" if username else f"ID: {winner.get('user_id')}"
        lines.append(
            f"<b>#{rank}</b> {html.escape(name)} — {html.escape(label)} "
            f"| 👥 {int(winner.get('verified_referrals') or 0)} referrals"
        )
    lines.extend(["", "💓🤍 Thank you to everyone who participated!"])
    return lines


async def publish_giveaway_channel_results(context, force=False):
    """Publish frozen Top 50 qualified results to the official giveaway channel."""
    state = str(get_giveaway_state("finalized", "0") or "0").strip().lower()
    if not giveaway_has_ended() and state not in {"1", "true", "yes", "finalized"}:
        return {"success": False, "reason": "giveaway_not_ended"}
    if state not in {"1", "true", "yes", "finalized"}:
        result = finalize_giveaway_results()
        if not result.get("success"):
            return {"success": False, "reason": result.get("reason", "finalization_failed")}
    sent = str(get_giveaway_state("channel_broadcast_sent", "0") or "0").lower()
    if sent in {"1", "true", "yes"} and not force:
        return {"success": True, "already_published": True, "winner_count": len(get_giveaway_results())}
    winners = get_giveaway_results()
    if not winners:
        return {"success": False, "reason": "no_qualified_winners_found"}
    lines = _format_winner_lines(winners)
    chunks, current = [], ""
    for line in lines:
        candidate = (current + "\n" + line).strip() if current else line
        if len(candidate) > 3600 and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    for index, chunk in enumerate(chunks, start=1):
        if len(chunks) > 1:
            chunk = f"📄 <b>Part {index}/{len(chunks)}</b>\n\n" + chunk
        await context.bot.send_message(
            chat_id=GIVEAWAY_CHANNEL_ID,
            text=chunk,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    set_giveaway_state("channel_broadcast_sent", "1")
    set_giveaway_state("channel_broadcast_sent_at", __import__("datetime").datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S"))
    return {"success": True, "already_published": False, "winner_count": len(winners), "parts": len(chunks)}


async def finalize_giveaway_job(context):
    """Finalize qualified Top 50 once the deadline passes and notify winners."""
    try:
        state = str(get_giveaway_state("finalized", "0") or "0").strip().lower()
        if giveaway_has_ended() and state not in {"1", "true", "yes", "finalized"}:
            result = finalize_giveaway_results()
            if not result.get("success") and result.get("reason") != "giveaway_not_ended":
                logger.error("Giveaway finalization failed: %s", result)
                return
            if result.get("success") and not result.get("already_finalized"):
                logger.info(
                    "Giveaway finalized: %s winners, %s qualified total.",
                    result.get("winner_count", 0), result.get("qualified_count", 0),
                )

        state = str(get_giveaway_state("finalized", "0") or "0").strip().lower()
        if state not in {"1", "true", "yes", "finalized"}:
            return

        for winner in get_giveaway_results():
            if str(winner.get("notification_status") or "pending").lower() == "sent":
                continue
            try:
                user_id = int(winner["user_id"])
                rank = int(winner["final_rank"])
                message = (
                    "🎉 <b>CONGRATULATIONS! YOU ARE A WINNER!</b>\n\n"
                    "🏆 <b>SF ARMY 10K SPECIAL GIVEAWAY</b>\n"
                    f"🏅 Your Final Rank: <b>#{rank}</b>\n"
                    f"🎁 Your Reward: {_winner_reward(rank)}\n\n"
                )
                if 4 <= rank <= 10 or 34 <= rank <= 50:
                    message += "📌 Open <b>My Rewards</b> in the bot to choose Telegram or WhatsApp and confirm your choice.\n"
                elif rank in NFT_REWARDS:
                    message += "ℹ️ Your NFT reward will be delivered by the administration.\n"
                else:
                    message += "ℹ️ Please follow the reward delivery instructions from the administration.\n"
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                mark_giveaway_notification_status(user_id, "sent")
            except (TelegramError, KeyError, TypeError, ValueError):
                logger.exception("Could not notify giveaway winner %s", winner.get("user_id"))
                try:
                    mark_giveaway_notification_status(int(winner["user_id"]), "failed")
                except Exception:
                    logger.exception("Could not record winner notification failure")
        try:
            publish_result = await publish_giveaway_channel_results(context)
            if not publish_result.get("success"):
                logger.warning("Giveaway channel broadcast not completed: %s", publish_result)
        except TelegramError:
            logger.exception("Could not publish giveaway results to channel; will retry on next scheduler run")
    except Exception:
        logger.exception("Scheduled giveaway finalization/notification failed")


def setup_scheduler(application):
    """Schedule daily backups and automatic giveaway finalization checks."""
    job_queue = application.job_queue
    if job_queue is None:
        raise RuntimeError(
            "JobQueue is unavailable. Install python-telegram-bot[job-queue] to enable scheduling."
        )

    for name in (BACKUP_JOB_NAME, GIVEAWAY_FINALIZE_JOB_NAME):
        for job in job_queue.get_jobs_by_name(name):
            job.schedule_removal()

    backup_time = time(
        hour=int(BACKUP_HOUR), minute=int(BACKUP_MINUTE), second=0, tzinfo=TIMEZONE
    )
    job_queue.run_daily(
        callback=scheduled_backup_job,
        time=backup_time,
        name=BACKUP_JOB_NAME,
    )
    job_queue.run_repeating(
        callback=finalize_giveaway_job,
        interval=60,
        first=5,
        name=GIVEAWAY_FINALIZE_JOB_NAME,
    )
    logger.info(
        "Daily backup scheduled at %02d:%02d (%s).",
        int(BACKUP_HOUR), int(BACKUP_MINUTE), TIMEZONE,
    )
    logger.info("Giveaway finalization check scheduled every 60 seconds.")
