import asyncio
import html
import logging
import sqlite3
import secrets
from functools import wraps

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError, BadRequest
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters,
)

from config import (
    BOT_TOKEN, ADMIN_IDS, WELCOME_BONUS, REFERRAL_REWARD,
    DAILY_BONUS, DATABASE_FILE, GIVEAWAY_CHANNEL_URL,
)
from database import (
    init_db, get_user, get_all_users, mark_user_verified,
    claim_welcome_bonus, claim_daily_bonus, add_coins, deduct_coins,
    get_coin_transactions, get_dashboard_stats, add_redeem_code,
    delete_redeem_code, get_redeem_codes, get_redeem_history,
    get_backup_history, get_setting, record_backup,
    get_giveaway_result, get_giveaway_state,
)
from admin import (
    is_admin, format_admin_dashboard, get_user_details,
    format_user_details, add_user_coins, deduct_user_coins,
    format_user_transactions,
)
from keyboards import (
    main_menu_keyboard, admin_panel_keyboard, admin_back_keyboard,
    admin_user_management_keyboard, admin_coin_management_keyboard,
    admin_redeem_keyboard, backup_recovery_keyboard,
    admin_statistics_keyboard, leaderboard_keyboard,
    required_chats_keyboard, profile_keyboard, redeem_code_keyboard,
)
from member import check_all_memberships, format_membership_message
from referrals import (
    process_referral_start, get_user_referral_link,
    complete_referral_verification,
)
from profile import get_profile_message
from leaderboard import format_leaderboard, get_leaderboard_page
from rewards import (
    get_rewards_message, choose_reward, confirm_reward_choice,
)
from redeem import redeem_user_code

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def is_private_chat(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.type == ChatType.PRIVATE)


def private_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_private_chat(update):
            return
        return await func(update, context)
    return wrapper


def is_authorized_admin(user_id):
    try:
        return int(user_id) in {int(x) for x in ADMIN_IDS} or is_admin(int(user_id))
    except (TypeError, ValueError):
        return False


async def get_bot_username(context):
    if not context.bot_data.get("bot_username"):
        context.bot_data["bot_username"] = (await context.bot.get_me()).username
    return context.bot_data["bot_username"]


def _ensure_ticket_table():
    """Create the ticket table safely without changing existing giveaway data."""
    with sqlite3.connect(DATABASE_FILE, timeout=15) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS giveaway_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                ticket_id TEXT NOT NULL UNIQUE,
                giveaway_id TEXT,
                final_rank INTEGER NOT NULL,
                reward_choice TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def _get_ticket(user_id):
    _ensure_ticket_table()
    with sqlite3.connect(DATABASE_FILE, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM giveaway_tickets WHERE user_id = ?", (int(user_id),)
        ).fetchone()
        return dict(row) if row else None


def _create_or_get_ticket(user_id, result):
    """Idempotently create one virtual ticket per confirmed winner."""
    _ensure_ticket_table()
    existing = _get_ticket(user_id)
    if existing:
        return existing
    ticket_id = "SF10K-" + secrets.token_hex(4).upper()
    giveaway_id = result.get("giveaway_id") if hasattr(result, "get") else None
    rank = int(result["final_rank"])
    choice = str(result["reward_choice"] or "").lower()
    with sqlite3.connect(DATABASE_FILE, timeout=15) as conn:
        conn.execute("""
            INSERT OR IGNORE INTO giveaway_tickets
            (user_id, ticket_id, giveaway_id, final_rank, reward_choice)
            VALUES (?, ?, ?, ?, ?)
        """, (int(user_id), ticket_id, str(giveaway_id or ""), rank, choice))
        conn.commit()
    return _get_ticket(user_id)


def _giveaway_is_finalized():
    try:
        state = get_giveaway_state("finalized", "0")
        return str(state).strip().lower() in {"1", "true", "yes", "finalized"}
    except Exception:
        logger.exception("Could not read giveaway finalization state")
    return False


def _result_value(result, key, default=None):
    if result is None:
        return default
    aliases = {"choice_confirmed": "selection_confirmed"}
    try:
        value = result[key]
    except (KeyError, IndexError, TypeError):
        alias = aliases.get(key)
        if not alias:
            return default
        try:
            value = result[alias]
        except (KeyError, IndexError, TypeError):
            return default
    return default if value is None else value


async def _show_rewards(query, user_id):
    result = get_giveaway_result(user_id)
    finalized = _giveaway_is_finalized()
    rank = int(_result_value(result, "final_rank", 0) or 0)
    choice = _result_value(result, "reward_choice")
    confirmed = bool(_result_value(result, "choice_confirmed", 0))
    eligible_choice = bool(result) and finalized and (4 <= rank <= 10 or 34 <= rank <= 50)
    from keyboards import get_rewards_keyboard
    keyboard = get_rewards_keyboard(
        selected_choice=choice,
        confirmed=confirmed,
        allow_selection=eligible_choice,
    )
    await query.edit_message_text(
        get_rewards_message(user_id), parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


async def _notify_ticket_admins(context, user, result, ticket):
    choice = str(ticket.get("reward_choice", "")).lower()
    label = "Telegram Account" if choice == "telegram" else "WhatsApp Account"
    first_name = html.escape(user.first_name or "User")
    username = f"@{html.escape(user.username)}" if user.username else "Not set"
    text = (
        "🎟️ <b>GIVEAWAY REWARD TICKET CREATED</b>\n\n"
        f"👤 Winner: <b>{first_name}</b> ({username})\n"
        f"🆔 User ID: <code>{user.id}</code>\n"
        f"🏅 Rank: <b>#{ticket.get('final_rank')}</b>\n"
        f"🎁 Reward Choice: <b>{label}</b>\n"
        f"🎫 Ticket ID: <code>{html.escape(str(ticket.get('ticket_id')))}</code>\n"
        f"🆔 Giveaway ID: <code>{html.escape(str(ticket.get('giveaway_id') or 'N/A'))}</code>"
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=int(admin_id), text=text, parse_mode=ParseMode.HTML)
        except (TelegramError, TypeError, ValueError):
            logger.warning("Could not send reward ticket notification to admin %s", admin_id)


async def send_main_menu(message):
    await message.reply_text(
        "🏠 <b>SF ARMY 10K GIVEAWAY BOT</b>\n\nChoose an option from the menu below.",
        reply_markup=main_menu_keyboard(), parse_mode=ParseMode.HTML,
    )


async def send_giveaway_ended_message(target, bot=None, user_id=None):
    """Show the simple post-giveaway status and official results channel button."""
    text = (
        "🏁 <b>GIVEAWAY HAS ENDED!</b>\n\n"
        "🎁 <b>Giveaway rewards are now live.</b>\n"
        "🏆 Check the final qualified winners and reward updates in our official channel.\n\n"
        "💓🤍 Thank you for participating in the SF ARMY Giveaway!"
    )
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Open Giveaway Channel", url=GIVEAWAY_CHANNEL_URL)]])
    if hasattr(target, "reply_text"):
        await target.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup, disable_web_page_preview=True)
    elif bot is not None and user_id is not None:
        await bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.HTML, reply_markup=markup, disable_web_page_preview=True)


async def notify_referral(context, result, referred_user):
    if not result:
        return
    inviter_id = result.get("inviter_id")
    reward = result.get("reward_coins", REFERRAL_REWARD)
    if not inviter_id:
        return
    try:
        await context.bot.send_message(
            chat_id=inviter_id,
            text=(
                "🎉 <b>Referral Verified!</b>\n\n"
                f"👤 New Member: {html.escape(referred_user.first_name or 'User')}\n"
                f"🆔 User ID: <code>{referred_user.id}</code>\n"
                f"🪙 Reward Received: <b>{reward} Coins</b>"
            ), parse_mode=ParseMode.HTML,
        )
    except TelegramError:
        logger.info("Could not notify inviter %s", inviter_id)


async def complete_user_verification(user, context):
    mark_user_verified(user.id)
    referral_result = complete_referral_verification(user.id)
    await notify_referral(context, referral_result, user)
    try:
        return claim_welcome_bonus(user.id, WELCOME_BONUS)
    except Exception:
        logger.exception("Welcome bonus error")
        return False


@private_only
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, message = update.effective_user, update.effective_message
    if not user or not message:
        return
    process_referral_start(
        user_id=user.id, username=user.username,
        first_name=user.first_name or "", last_name=user.last_name or "",
        start_parameter=context.args[0] if context.args else None,
    )
    membership = await check_all_memberships(context.bot, user.id)
    if not membership["verified"]:
        await message.reply_text(
            format_membership_message(membership),
            reply_markup=required_chats_keyboard(), parse_mode=ParseMode.HTML,
        )
        return
    claimed = await complete_user_verification(user, context)
    if _giveaway_is_finalized():
        await send_giveaway_ended_message(message)
        return
    if claimed:
        await message.reply_text(
            f"🎉 Welcome bonus: <b>{WELCOME_BONUS} coins</b>!",
            parse_mode=ParseMode.HTML,
        )
    await send_main_menu(message)


@private_only
async def verify_membership_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    membership = await check_all_memberships(context.bot, query.from_user.id)
    if not membership["verified"]:
        await query.edit_message_text(
            format_membership_message(membership),
            reply_markup=required_chats_keyboard(), parse_mode=ParseMode.HTML,
        )
        return
    claimed = await complete_user_verification(query.from_user, context)
    if _giveaway_is_finalized():
        await query.edit_message_text(
            "🏁 <b>GIVEAWAY HAS ENDED!</b>\n\n"
            "🎁 <b>Giveaway rewards are now live.</b>\n"
            "🏆 Check the final qualified winners and reward updates in our official channel.\n\n"
            "💓🤍 Thank you for participating in the SF ARMY Giveaway!",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📢 Open Giveaway Channel", url=GIVEAWAY_CHANNEL_URL)]]),
            disable_web_page_preview=True,
        )
        return
    text = "✅ <b>Membership Verified Successfully!</b>"
    if claimed:
        text += f"\n\n🎁 Welcome Bonus: <b>{WELCOME_BONUS} Coins</b>"
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)
    await context.bot.send_message(
        chat_id=query.from_user.id, text="🏠 Select an option below:",
        reply_markup=main_menu_keyboard(),
    )


@private_only
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    if not user or not message:
        return
    try:
        username = await get_bot_username(context)
        text = get_profile_message(user_id=user.id, bot_username=username)
        # MarkdownV2 is used by profile.py. If its dynamic content causes a
        # Telegram parse error, retry without parse mode so the user still gets a reply.
        try:
            await message.reply_text(
                text, parse_mode=ParseMode.MARKDOWN_V2,
            )
        except BadRequest:
            logger.exception("Profile MarkdownV2 formatting failed; sending fallback")
            await message.reply_text(
                text.replace("\\", ""),
            )
    except Exception:
        logger.exception("Could not display user profile")
        await message.reply_text("⚠️ Profile could not be loaded. Please try again.")


@private_only
async def referral_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    # Ensure the user exists in the database even if an old menu button is used.
    process_referral_start(
        user_id=user.id, username=user.username,
        first_name=user.first_name or "", last_name=user.last_name or "",
        start_parameter=None,
    )
    username = await get_bot_username(context)
    link = get_user_referral_link(username, user.id)
    if not link:
        logger.error("Referral link could not be created for user_id=%s bot_username=%r", user.id, username)
        await update.effective_message.reply_text(
            "⚠️ Referral link abhi generate nahi ho paaya. Please /start dobara karke try karein."
        )
        return
    await update.effective_message.reply_text(
        "🔗 <b>YOUR REFERRAL LINK</b>\n\n"
        f"<code>{html.escape(link)}</code>\n\n"
        f"👥 Referral Reward: <b>{REFERRAL_REWARD} Coins</b>\n"
        "✅ Rewards are granted after the new member joins all required chats and verifies membership.",
        parse_mode=ParseMode.HTML,
    )


@private_only
async def daily_bonus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, message = update.effective_user, update.effective_message
    if not user or not message:
        return
    # A valid menu tap must not fail just because the user record was missing.
    process_referral_start(
        user_id=user.id, username=user.username,
        first_name=user.first_name or "", last_name=user.last_name or "",
        start_parameter=None,
    )
    membership = await check_all_memberships(context.bot, user.id)
    if not membership["verified"]:
        await message.reply_text(
            format_membership_message(membership),
            reply_markup=required_chats_keyboard(), parse_mode=ParseMode.HTML,
        )
        return
    mark_user_verified(user.id)
    try:
        claimed = claim_daily_bonus(user.id, DAILY_BONUS)
    except Exception:
        logger.exception("Daily bonus error")
        claimed = False
    if claimed:
        await message.reply_text(
            f"🎉 <b>Daily Bonus Claimed!</b>\n\n🪙 You received <b>{DAILY_BONUS} Coins</b>.",
            parse_mode=ParseMode.HTML,
        )
    else:
        # Membership failure is handled above, so a failed claim here should
        # distinguish a duplicate claim from an unexpected database/state issue.
        from database import get_user
        current_user = get_user(user.id) or {}
        if current_user.get("daily_bonus_date") == __import__("database").current_date():
            await message.reply_text(
                "⏳ <b>Daily Bonus Already Claimed!</b>\n\n"
                "Aap aaj ka bonus pehle hi le chuke hain. Kal dobara claim karein.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.reply_text(
                "⚠️ <b>Daily Bonus Claim Nahi Ho Paaya</b>\n\n"
                "Membership verified hai, lekin bonus save nahi hua. Please thodi der baad dobara try karein.",
                parse_mode=ParseMode.HTML,
            )


@private_only
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = get_leaderboard_page(0)
    await update.effective_message.reply_text(
        format_leaderboard(data["page"]), parse_mode=ParseMode.HTML,
        reply_markup=leaderboard_keyboard(page=data["page"], total_pages=data["total_pages"]),
    )


async def leaderboard_page_callback(query, page):
    data = get_leaderboard_page(page)
    await query.edit_message_text(
        format_leaderboard(data["page"]), parse_mode=ParseMode.HTML,
        reply_markup=leaderboard_keyboard(page=data["page"], total_pages=data["total_pages"]),
    )


@private_only
async def rewards_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    if user and message:
        from keyboards import get_rewards_keyboard
        result = get_giveaway_result(user.id)
        rank = int(_result_value(result, "final_rank", 0) or 0)
        finalized = _giveaway_is_finalized()
        confirmed = bool(_result_value(result, "choice_confirmed", 0))
        choice_allowed = bool(result) and finalized and (4 <= rank <= 10 or 34 <= rank <= 50)
        await message.reply_text(
            get_rewards_message(user.id),
            parse_mode=ParseMode.HTML,
            reply_markup=get_rewards_keyboard(
                selected_choice=_result_value(result, "reward_choice"),
                confirmed=confirmed,
                allow_selection=choice_allowed,
            ),
            disable_web_page_preview=True,
        )


@private_only
async def redeem_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["pending_redeem"] = True
    await update.effective_message.reply_text(
        "🎟️ <b>Redeem Code</b>\n\nSend your redeem code in the next message.",
        reply_markup=redeem_code_keyboard(), parse_mode=ParseMode.HTML,
    )


async def process_redeem_message(update, context, code):
    user = update.effective_user
    context.user_data.pop("pending_redeem", None)
    result = redeem_user_code(user_id=user.id, code=code)
    await update.effective_message.reply_text(result["message"], parse_mode=ParseMode.HTML)


@private_only
async def publish_results_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only one-time manual recovery for the missed channel results post."""
    user = update.effective_user
    message = update.effective_message
    if not user or not message or not is_authorized_admin(user.id):
        if message:
            await message.reply_text("⛔ Admin access only.")
        return
    from scheduler import publish_giveaway_channel_results
    try:
        result = await publish_giveaway_channel_results(context, force=False)
        if result.get("success"):
            await message.reply_text(
                "✅ <b>Giveaway results published successfully!</b>\n"
                f"🏆 Qualified winners posted: <b>{result.get('winner_count', 0)}</b>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.reply_text(
                "⚠️ Could not publish results.\n"
                f"Reason: <code>{html.escape(str(result.get('reason', 'unknown')))}</code>",
                parse_mode=ParseMode.HTML,
            )
    except Exception:
        logger.exception("Manual giveaway results publish failed")
        await message.reply_text("❌ Publishing failed. Check bot logs and channel admin permissions.")


@private_only
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_authorized_admin(user.id):
        await update.effective_message.reply_text("⛔ You are not authorized to access the admin panel.")
        return
    await update.effective_message.reply_text(
        "🛡️ <b>SF ARMY ADMIN PANEL</b>\n\nSelect an option below:",
        reply_markup=admin_panel_keyboard(), parse_mode=ParseMode.HTML,
    )


async def show_admin_dashboard(query, page=0):
    stats = get_dashboard_stats()
    if page == 0:
        text = format_admin_dashboard()
    else:
        text = (
            "📊 <b>ADMIN STATISTICS — PAGE 2</b>\n\n"
            f"👥 Verified Referrals: <b>{stats.get('verified_referrals', 0)}</b>\n"
            f"⏳ Pending Referrals: <b>{stats.get('pending_referrals', 0)}</b>\n\n"
            f"🎟️ Total Redeem Codes: <b>{stats.get('total_codes', 0)}</b>\n"
            f"🟢 Active Codes: <b>{stats.get('active_codes', 0)}</b>\n"
            f"🎁 Total Redemptions: <b>{stats.get('total_redemptions', 0)}</b>"
        )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML,
        reply_markup=admin_statistics_keyboard(page=page, total_pages=2))


async def begin_admin_action(query, context, action, prompt):
    context.user_data["admin_action"] = action
    await query.edit_message_text(prompt, parse_mode=ParseMode.HTML, reply_markup=admin_back_keyboard())


async def process_admin_message(update, context):
    user, message = update.effective_user, update.effective_message
    if not user or not message or not is_authorized_admin(user.id):
        return False
    action = context.user_data.get("admin_action")
    if not action:
        return False
    text = (message.text or "").strip()
    if not text:
        await message.reply_text("❌ Please send valid text.")
        return True

    if action == "broadcast":
        context.user_data.pop("admin_action", None)
        users = get_all_users()
        sent = failed = 0
        status = await message.reply_text(f"📢 Broadcasting to {len(users)} users...")
        for item in users:
            try:
                await context.bot.send_message(chat_id=item["user_id"], text=text)
                sent += 1
            except TelegramError:
                failed += 1
            await asyncio.sleep(0.04)
        await status.edit_text(f"✅ <b>Broadcast Finished</b>\n\n📨 Sent: <b>{sent}</b>\n⚠️ Failed: <b>{failed}</b>", parse_mode=ParseMode.HTML)
        return True

    if action in ("find_user", "check_balance", "transaction_history"):
        try:
            target_id = int(text)
        except ValueError:
            await message.reply_text("❌ Send a valid numeric Telegram user ID.")
            return True
        context.user_data.pop("admin_action", None)
        if action == "transaction_history":
            output = format_user_transactions(target_id)
        else:
            result = get_user_details(target_id)
            if not result.get("success"):
                await message.reply_text(result.get("message", "User not found."))
                return True
            output = format_user_details(result["user"])
        await message.reply_text(output, parse_mode=ParseMode.HTML, reply_markup=admin_back_keyboard())
        return True

    if action in ("add_coins", "deduct_coins"):
        try:
            parts = text.split()
            if len(parts) != 2:
                raise ValueError
            target_id, amount = int(parts[0]), int(parts[1])
            if amount <= 0:
                raise ValueError
        except ValueError:
            await message.reply_text("❌ Format: <code>123456789 100</code>", parse_mode=ParseMode.HTML)
            return True
        context.user_data.pop("admin_action", None)
        result = (add_user_coins(target_id, amount, user.id) if action == "add_coins"
                  else deduct_user_coins(target_id, amount, user.id))
        await message.reply_text(result.get("message", "⚠️ Action failed."), parse_mode=ParseMode.HTML, reply_markup=admin_back_keyboard())
        return True

    if action == "add_redeem_code":
        # Format: CODE MAX_USERS COINS_PER_USER; use 0 as unlimited.
        parts = text.split()
        if len(parts) != 3:
            await message.reply_text(
                "❌ Format: <code>SF10K 100 50</code>\n"
                "Order: CODE MAX_USERS COINS_PER_USER\n"
                "Use 0 for unlimited users.", parse_mode=ParseMode.HTML)
            return True
        code = parts[0].strip()
        try:
            max_users, reward = int(parts[1]), int(parts[2])
            if max_users < 0 or reward < 0 or (max_users == 0 and reward < 0):
                raise ValueError
        except ValueError:
            await message.reply_text("❌ Max users and coins must be non-negative whole numbers.")
            return True
        try:
            success = add_redeem_code(code=code, reward_coins=reward, added_by=user.id, max_users=max_users)
        except TypeError:
            await message.reply_text("⚠️ Your database.py doesn't support max_users yet. Replace it with the updated version first.")
            return True
        context.user_data.pop("admin_action", None)
        await message.reply_text(
            (f"✅ Code <code>{html.escape(code)}</code> added.\n👥 Max users: <b>{'Unlimited' if max_users == 0 else max_users}</b>\n🪙 Coins per user: <b>{reward}</b>"
             if success else "❌ Code could not be added. It may already exist."),
            parse_mode=ParseMode.HTML, reply_markup=admin_back_keyboard())
        return True

    if action == "delete_redeem_code":
        context.user_data.pop("admin_action", None)
        success = delete_redeem_code(text)
        await message.reply_text("✅ Redeem code deleted." if success else "❌ Code not found.", reply_markup=admin_back_keyboard())
        return True

    if action == "create_backup":
        if text.strip().upper() != "CONFIRM":
            await message.reply_text("⚠️ To create a backup, send exactly <code>CONFIRM</code>.", parse_mode=ParseMode.HTML)
            return True
        context.user_data.pop("admin_action", None)
        try:
            from backup import create_backup
            result = create_backup()
            path = result if isinstance(result, str) else getattr(result, "name", None)
            if not path:
                path = str(result)
            record_backup(path, backup_type="manual", created_by=user.id, status="success")
            await message.reply_text("✅ Backup created:\n<code>" + html.escape(path) + "</code>", parse_mode=ParseMode.HTML, reply_markup=admin_back_keyboard())
            try:
                with open(path, "rb") as file_obj:
                    await message.reply_document(file_obj, filename=path.rsplit("/", 1)[-1])
            except Exception:
                logger.exception("Backup created but could not be sent")
        except Exception as exc:
            logger.exception("Manual backup failed")
            try:
                record_backup("", backup_type="manual", created_by=user.id, status="failed", notes=str(exc))
            except Exception:
                logger.exception("Could not record failed backup")
            await message.reply_text("❌ Backup failed. Check server logs and backup.py.")
        return True

    if action == "restore_backup":
        context.user_data.pop("admin_action", None)
        try:
            from backup import list_backups, restore_backup
            backups = list_backups()
            if not backups:
                await message.reply_text("📂 No backup files are available.")
                return True
            selection = text.strip()
            chosen = next((b for b in backups if selection in (b.get("filename"), b.get("path"))), None)
            if not chosen:
                lines = ["♻️ <b>Choose a backup filename to restore:</b>"]
                lines.extend(f"<code>{html.escape(str(b.get('filename')))}</code> — {html.escape(str(b.get('modified', '')))}" for b in backups[:20])
                await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=admin_back_keyboard())
                context.user_data["admin_action"] = "restore_backup"
                return True
            ok = restore_backup(chosen.get("path") or chosen.get("filename"))
            await message.reply_text("✅ Backup restored. Restart the bot process if required." if ok else "❌ Restore failed. Check logs.", reply_markup=admin_back_keyboard())
        except Exception:
            logger.exception("Backup restore failed")
            await message.reply_text("❌ Restore failed. Check backup.py and server logs.")
        return True

    context.user_data.pop("admin_action", None)
    await message.reply_text("⚠️ Unknown admin action.", reply_markup=admin_back_keyboard())
    return True


@private_only
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    user, data = query.from_user, query.data or ""
    if data.startswith("admin_") or data == "admin_panel":
        if not is_authorized_admin(user.id):
            await query.answer("⛔ Admin access only.", show_alert=True)
            return
    # Answer callback exactly once. verify_membership_callback doesn't answer again.
    await query.answer()

    if data == "verify_membership":
        await verify_membership_callback(update, context)
        return
    if data == "main_menu":
        context.user_data.pop("admin_action", None)
        await query.message.reply_text(
            "🏠 <b>SF ARMY 10K GIVEAWAY BOT</b>\n\nChoose an option from the menu below.",
            reply_markup=main_menu_keyboard(), parse_mode=ParseMode.HTML,
        )
        return
    if data == "rewards":
        await _show_rewards(query, user.id)
        return
    if data == "reward_info":
        info_text = (
            "ℹ️ <b>SF ARMY 10K — REWARD INFO</b>\n\n"
            "🥇 <b>Rank #1:</b> Star Notepad NFT\n"
            "🔗 https://t.me/nft/StarNotepad-42379\n\n"
            "🥈 <b>Rank #2:</b> Chill Flame NFT\n"
            "🔗 https://t.me/nft/ChillFlame-107767\n\n"
            "🥉 <b>Rank #3:</b> Ice Cream NFT\n"
            "🔗 https://t.me/nft/IceCream-327731\n\n"
            "🎁 <b>Ranks #4–#10:</b> Teddy + Telegram/WhatsApp account choice\n"
            "🧸 <b>Ranks #11–#33:</b> Teddy\n"
            "📱 <b>Ranks #34–#50:</b> Telegram/WhatsApp account choice\n\n"
            "🔒 Account choice unlocks only after the final results are announced. "
            "After confirmation, the choice cannot be changed."
        )
        from keyboards import reward_info_keyboard
        await query.edit_message_text(
            info_text, parse_mode=ParseMode.HTML,
            reply_markup=reward_info_keyboard(), disable_web_page_preview=True,
        )
        return
    if data == "reward_select":
        if not _giveaway_is_finalized():
            await query.message.reply_text("Reward selection unlocks after final results are announced.")
            return
        result = get_giveaway_result(user.id)
        rank = int(_result_value(result, "final_rank", 0) or 0)
        if not result or not (4 <= rank <= 10 or 34 <= rank <= 50):
            await query.message.reply_text("Your rank does not have a Telegram/WhatsApp choice.")
            return
        if bool(_result_value(result, "choice_confirmed", 0)):
            await query.message.reply_text("Your choice is already locked.")
            return
        from keyboards import get_reward_choice_keyboard
        await query.edit_message_text(
            get_rewards_message(user.id), parse_mode=ParseMode.HTML,
            reply_markup=get_reward_choice_keyboard(_result_value(result, "reward_choice")),
            disable_web_page_preview=True,
        )
        return
    if data in ("reward_choose_telegram", "reward_choose_whatsapp"):
        if not _giveaway_is_finalized():
            await query.message.reply_text("Reward selection is not unlocked yet.")
            return
        choice = "telegram" if data.endswith("telegram") else "whatsapp"
        saved = choose_reward(user.id, choice)
        if not saved.get("success"):
            await query.message.reply_text(saved.get("message", "Could not save choice."))
            return
        from keyboards import get_reward_choice_keyboard
        await query.edit_message_text(
            get_rewards_message(user.id), parse_mode=ParseMode.HTML,
            reply_markup=get_reward_choice_keyboard(choice),
            disable_web_page_preview=True,
        )
        return
    if data == "reward_confirm":
        if not _giveaway_is_finalized():
            await query.message.reply_text("Reward selection is not unlocked yet.")
            return
        result_before = get_giveaway_result(user.id)
        rank = int(_result_value(result_before, "final_rank", 0) or 0)
        if not result_before or not (4 <= rank <= 10 or 34 <= rank <= 50):
            await query.message.reply_text("This reward choice is not available for your rank.")
            return
        already_confirmed = bool(_result_value(result_before, "choice_confirmed", 0))
        if not already_confirmed:
            confirmed_result = confirm_reward_choice(user.id)
            if not confirmed_result.get("success"):
                await query.message.reply_text(confirmed_result.get("message", "Could not confirm choice."))
                return
        result_after = get_giveaway_result(user.id)
        if not bool(_result_value(result_after, "choice_confirmed", 0)):
            await query.message.reply_text("Confirmation could not be verified. Please try again.")
            return
        ticket_before = _get_ticket(user.id)
        ticket = _create_or_get_ticket(user.id, result_after)
        # Notify admins only for the first creation; repeat taps cannot duplicate alerts.
        if ticket and not ticket_before:
            try:
                await _notify_ticket_admins(context, user, result_after, ticket)
            except Exception:
                logger.exception("Reward ticket admin notification failed")
        from keyboards import get_reward_locked_keyboard
        await query.edit_message_text(
            get_rewards_message(user.id) + "\n\n🎫 <b>Your Virtual Ticket</b>\n"
            f"Ticket ID: <code>{html.escape(str(ticket.get('ticket_id', 'N/A')))}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_reward_locked_keyboard(),
            disable_web_page_preview=True,
        )
        return
    if data == "reward_locked":
        await query.message.reply_text("Your reward choice is locked.")
        return
    if data == "admin_panel":
        context.user_data.pop("admin_action", None)
        await query.edit_message_text("🛡️ <b>SF ARMY ADMIN PANEL</b>\n\nSelect an option below:", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
        return
    if data == "admin_dashboard":
        await show_admin_dashboard(query, 0); return
    if data.startswith("admin_dashboard_page:"):
        try: page = int(data.split(":", 1)[1])
        except ValueError: page = 0
        await show_admin_dashboard(query, max(0, min(page, 1))); return
    if data == "admin_manage_users":
        await query.edit_message_text("👥 <b>USER MANAGEMENT</b>\n\nChoose an action:", parse_mode=ParseMode.HTML, reply_markup=admin_user_management_keyboard()); return
    if data == "admin_coin_management":
        await query.edit_message_text("🪙 <b>COIN MANAGEMENT</b>\n\nChoose an action:", parse_mode=ParseMode.HTML, reply_markup=admin_coin_management_keyboard()); return
    if data == "admin_redeem_manager":
        await query.edit_message_text("🎟️ <b>REDEEM CODE MANAGER</b>\n\nChoose an action:", parse_mode=ParseMode.HTML, reply_markup=admin_redeem_keyboard()); return
    if data == "admin_backup_recovery":
        await query.edit_message_text("💾 <b>BACKUP & RECOVERY</b>\n\nChoose an action:", parse_mode=ParseMode.HTML, reply_markup=backup_recovery_keyboard()); return
    if data == "admin_backup_history":
        try:
            from backup import list_backups
            backups = list_backups()
        except Exception:
            logger.exception("Could not list backup files")
            backups = []
        if backups:
            lines = ["📂 <b>BACKUP FILE HISTORY</b>", ""]
            for item in backups[:15]:
                lines.append(f"🗂️ <code>{html.escape(str(item.get('filename', 'Unknown')))}</code>\n🕒 {html.escape(str(item.get('modified', 'Unknown')))} | 📦 {item.get('size', 0)} bytes")
            text = "\n\n".join(lines)
        else:
            history = get_backup_history(limit=10)
            text = "📂 <b>BACKUP HISTORY</b>\n\nNo backup files found." if not history else "📂 <b>BACKUP HISTORY</b>\n\n" + "\n".join(html.escape(str(x.get("created_at", "Unknown"))) + " — " + html.escape(str(x.get("status", "Unknown"))) for x in history)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_back_keyboard()); return

    actions = {
        "admin_broadcast": ("broadcast", "📢 <b>Broadcast Message</b>\n\nSend the message to broadcast to registered users."),
        "admin_find_user": ("find_user", "🔍 <b>Find User</b>\n\nSend the user's Telegram ID."),
        "admin_check_balance": ("check_balance", "💰 <b>Check Balance</b>\n\nSend the user's Telegram ID."),
        "admin_add_coins": ("add_coins", "➕ <b>Add Coins</b>\n\nSend: <code>123456789 100</code>"),
        "admin_deduct_coins": ("deduct_coins", "➖ <b>Deduct Coins</b>\n\nSend: <code>123456789 100</code>"),
        "admin_transaction_history": ("transaction_history", "📜 <b>Transaction History</b>\n\nSend the user's Telegram ID."),
        "admin_add_redeem_code": ("add_redeem_code", "🎟️ <b>Add Redeem Code</b>\n\nSend: <code>SF10K 100 50</code>\nFormat: CODE MAX_USERS COINS_PER_USER\nUse 0 for unlimited users."),
        "admin_delete_redeem_code": ("delete_redeem_code", "🗑️ <b>Delete Redeem Code</b>\n\nSend the exact code."),
        "admin_create_backup": ("create_backup", "💾 Send <code>CONFIRM</code> to create and send a database backup."),
        "admin_restore_backup": ("restore_backup", "♻️ Send a backup filename to restore. Send any text to list available backups."),
    }
    if data in actions:
        action, prompt = actions[data]
        await begin_admin_action(query, context, action, prompt); return
    if data == "admin_available_codes":
        codes = get_redeem_codes(status="active")
        lines = ["🎟️ <b>AVAILABLE CODES</b>", ""]
        for item in codes[:50]:
            max_users = item.get("max_users")
            try:
                redeemed = sum(1 for h in get_redeem_history() if h.get("code") == item.get("code"))
            except Exception:
                redeemed = 0
            cap = "Unlimited" if max_users is None else str(max_users)
            lines.append(f"🔑 <code>{html.escape(str(item.get('code', 'Unknown')))}</code>\n🪙 Reward: <b>{item.get('reward_coins', 0)}</b> coins\n👥 Redeemed: <b>{redeemed}/{cap}</b>")
        await query.edit_message_text("\n\n".join(lines) if codes else "🎟️ No active codes found.", parse_mode=ParseMode.HTML, reply_markup=admin_back_keyboard()); return
    if data == "admin_redeem_history":
        history = get_redeem_history()
        lines = ["📜 <b>REDEMPTION HISTORY</b>", ""]
        for item in history[:20]:
            lines.append(f"👤 User: <code>{item.get('user_id', 'Unknown')}</code>\n🎟️ Code: <code>{html.escape(str(item.get('code', 'Unknown')))}</code>\n🕒 {html.escape(str(item.get('redeemed_at', 'Unknown')))}")
        await query.edit_message_text("\n\n".join(lines) if history else "📜 No redemption history found.", parse_mode=ParseMode.HTML, reply_markup=admin_back_keyboard()); return
    if data == "my_referral_link":
        username = await get_bot_username(context)
        link = get_user_referral_link(username, user.id)
        await query.message.reply_text("🔗 <b>Your Referral Link</b>\n\n" + (f"<code>{html.escape(link)}</code>\n\n🪙 Referral Reward: <b>{REFERRAL_REWARD} Coins</b>" if link else "⚠️ Please use /start first."), parse_mode=ParseMode.HTML); return
    if data == "rewards_coming_soon":
        await _show_rewards(query, user.id); return
    if data.startswith("leaderboard_page:"):
        try: page = int(data.split(":", 1)[1])
        except ValueError: page = 0
        await leaderboard_page_callback(query, page); return
    if data == "leaderboard_current_page":
        return
    if data == "cancel_redeem":
        context.user_data.pop("pending_redeem", None)
        await query.edit_message_text("❌ Redeem cancelled."); return
    if data == "cancel_action":
        context.user_data.pop("admin_action", None)
        context.user_data.pop("pending_redeem", None)
        await query.edit_message_text("❌ Action cancelled.", reply_markup=admin_back_keyboard()); return
    # Callback was already answered at the start of this router.
    await query.message.reply_text("⚠️ This button has no connected action yet.")


@private_only
async def private_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message, user = update.effective_message, update.effective_user
    if not message or not user or not message.text:
        return
    text = message.text.strip()

    # Match the reply-keyboard labels robustly (Telegram emoji variation selectors
    # can differ between clients). Handle menu taps before stale redeem/admin input
    # states so a tap on Referral Link always opens the referral link.
    def normalize_button(value):
        return " ".join(str(value or "").replace("\ufe0f", "").split()).casefold()

    menu = {
        "👤 My Profile": profile_command,
        "🏆 Leaderboard": leaderboard_command,
        "🔗 My Referral Link": referral_command,
        "🎁 Daily Bonus": daily_bonus_command,
        "🎟️ Redeem Code": redeem_start,
        "🎁 Rewards": rewards_command,
    }
    normalized_menu = {normalize_button(label): handler for label, handler in menu.items()}
    normalized_text = normalize_button(text)
    handler = normalized_menu.get(normalized_text)
    # Compatibility with older keyboards that used slightly different button text.
    if handler is None and "referral" in normalized_text and "link" in normalized_text:
        handler = referral_command
    elif handler is None and "daily" in normalized_text and "bonus" in normalized_text:
        handler = daily_bonus_command
    if handler:
        # Clear stale redeem state when the user explicitly chooses a menu item.
        context.user_data.pop("pending_redeem", None)
        await handler(update, context)
        return

    if is_authorized_admin(user.id):
        if await process_admin_message(update, context):
            return
    if context.user_data.get("pending_redeem"):
        await process_redeem_message(update, context, text)
        return


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while processing update", exc_info=context.error)


async def post_init(application: Application):
    try:
        from scheduler import setup_scheduler
        setup_scheduler(application)
        logger.info("Daily backup scheduler initialized.")
    except Exception:
        logger.exception("Backup scheduler could not start; check scheduler.py and backup.py")


def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise RuntimeError("Please configure BOT_TOKEN in config.py.")
    init_db()
    _ensure_ticket_table()
    logger.info("Database initialized: %s", DATABASE_FILE)
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("publish_results", publish_results_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("referral", referral_command))
    application.add_handler(CommandHandler("daily", daily_bonus_command))
    application.add_handler(CommandHandler("redeem", redeem_start))
    application.add_handler(CallbackQueryHandler(callback_router))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, private_text_handler))
    application.add_error_handler(error_handler)
    logger.info("SF ARMY 10K Giveaway Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == "__main__":
    main()
