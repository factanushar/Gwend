from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from config import WELCOME_BONUS

from database import (
    get_user,
    mark_user_verified,
)

from keyboards import (
    main_menu_keyboard,
    get_membership_keyboard,
)

from member import (
    check_all_memberships,
    format_membership_message,
)

from bonuses import (
    claim_welcome_bonus_for_user,
    claim_daily_bonus_for_user,
)

from rewards import get_rewards_message

from referrals import (
    process_referral_start,
    complete_referral_verification,
    get_user_referral_link,
)

from profile import get_profile_message
from leaderboard import format_leaderboard
from redeem import redeem_user_code


# ==========================================
# PRIVATE CHAT CHECK
# ==========================================

def is_private_chat(update: Update) -> bool:
    chat = update.effective_chat

    return (
        chat is not None
        and chat.type == ChatType.PRIVATE
    )


# ==========================================
# START COMMAND
# ==========================================

async def start_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_private_chat(update):
        return

    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    start_parameter = (
        context.args[0] if context.args else None
    )

    process_referral_start(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        start_parameter=start_parameter,
    )

    db_user = get_user(user.id)

    if not db_user or not db_user.get("verified"):
        result = await check_all_memberships(
            context.bot,
            user.id,
        )

        if result["verified"]:
            await finish_verification(
                update,
                context,
                user.id,
            )
            return

        await message.reply_text(
            format_membership_message(result),
            reply_markup=get_membership_keyboard(
                result["missing"]
            ),
            parse_mode="HTML",
        )
        return

    await message.reply_text(
        "🦅 <b>Welcome to SF ARMY 10K Giveaway Bot!</b>\n\n"
        "Choose an option from the menu below.",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


# ==========================================
# FINISH VERIFICATION
# ==========================================

async def finish_verification(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
):
    if not is_private_chat(update):
        return

    mark_user_verified(user_id)

    referral_result = complete_referral_verification(
        user_id
    )

    welcome_result = claim_welcome_bonus_for_user(
        user_id
    )

    messages = [
        "✅ <b>Membership Verified Successfully!</b>",
        "",
        "🎉 Welcome to SF ARMY!",
    ]

    if welcome_result.get("success"):
        messages.extend([
            "",
            f"🎁 Welcome Bonus: <b>+{WELCOME_BONUS} Coins</b>",
        ])

    if referral_result:
        inviter_id = referral_result.get("inviter_id")
        reward_coins = referral_result.get(
            "reward_coins", 0
        )

        messages.extend([
            "",
            "🎉 <b>Referral Verified Successfully!</b>",
            f"🪙 Referral Reward: <b>{reward_coins} Coins</b>",
        ])

        # Notify the inviter privately.
        if inviter_id:
            try:
                await context.bot.send_message(
                    chat_id=inviter_id,
                    text=(
                        "🎉 <b>Your referral has been verified!</b>\n\n"
                        f"👤 User ID: <code>{user_id}</code>\n"
                        f"🪙 Reward: <b>+{reward_coins} Coins</b>"
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                # Do not interrupt verification if notification fails.
                pass

    reply_target = update.effective_message

    if update.callback_query:
        reply_target = update.callback_query.message

    if reply_target:
        await reply_target.reply_text(
            "\n".join(messages),
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML",
        )


# ==========================================
# VERIFY MEMBERSHIP CALLBACK
# ==========================================

async def verify_membership_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_private_chat(update):
        return

    query = update.callback_query

    if not query:
        return

    await query.answer()

    user_id = query.from_user.id

    result = await check_all_memberships(
        context.bot,
        user_id,
    )

    if result["verified"]:
        await finish_verification(
            update,
            context,
            user_id,
        )
        return

    await query.edit_message_text(
        format_membership_message(result),
        reply_markup=get_membership_keyboard(
            result["missing"]
        ),
        parse_mode="HTML",
    )


# ==========================================
# MY PROFILE
# ==========================================

async def profile_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_private_chat(update):
        return

    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    bot_info = await context.bot.get_me()

    text = get_profile_message(
        user_id=user.id,
        bot_username=bot_info.username,
    )

    await message.reply_text(
        text,
        parse_mode="MarkdownV2",
    )


# ==========================================
# LEADERBOARD
# ==========================================

async def leaderboard_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_private_chat(update):
        return

    message = update.effective_message

    if not message:
        return

    await message.reply_text(
        format_leaderboard(page=0),
        parse_mode="HTML",
    )


# ==========================================
# MY REFERRAL LINK
# ==========================================

async def referral_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_private_chat(update):
        return

    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    bot_info = await context.bot.get_me()

    referral_link = get_user_referral_link(
        user_id=user.id,
        bot_username=bot_info.username,
    )

    await message.reply_text(
        "🔗 <b>Your Personal Referral Link</b>\n\n"
        f"<code>{referral_link}</code>\n\n"
        "👥 Invite your friends using this link.\n"
        "🎁 Referral rewards are credited after successful verification.",
        parse_mode="HTML",
    )


# ==========================================
# DAILY BONUS
# ==========================================

async def daily_bonus_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_private_chat(update):
        return

    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    membership = await check_all_memberships(
        context.bot,
        user.id,
    )

    if not membership["verified"]:
        await message.reply_text(
            format_membership_message(membership),
            reply_markup=get_membership_keyboard(
                membership["missing"]
            ),
            parse_mode="HTML",
        )
        return

    db_user = get_user(user.id)

    if not db_user or not db_user.get("verified"):
        await message.reply_text(
            "⚠️ Please complete membership verification first."
        )
        return

    result = claim_daily_bonus_for_user(user.id)

    await message.reply_text(
        result["message"],
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


# ==========================================
# REWARDS
# ==========================================

async def rewards_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_private_chat(update):
        return

    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    await message.reply_text(
        get_rewards_message(user.id),
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


# ==========================================
# REDEEM CODE PROMPT
# ==========================================

async def redeem_prompt_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_private_chat(update):
        return

    message = update.effective_message

    if not message:
        return

    context.user_data["awaiting_redeem_code"] = True

    await message.reply_text(
        "🎟️ <b>Redeem Code</b>\n\n"
        "Send your redeem code in your next message.\n\n"
        "❌ Send /cancel to cancel.",
        parse_mode="HTML",
    )


# ==========================================
# REDEEM CODE TEXT
# ==========================================

async def redeem_text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_private_chat(update):
        return

    if not context.user_data.get(
        "awaiting_redeem_code"
    ):
        return

    user = update.effective_user
    message = update.effective_message

    if not user or not message or not message.text:
        return

    code = message.text.strip()

    if code.startswith("/"):
        return

    context.user_data.pop(
        "awaiting_redeem_code",
        None,
    )

    membership = await check_all_memberships(
        context.bot,
        user.id,
    )

    if not membership["verified"]:
        await message.reply_text(
            format_membership_message(membership),
            reply_markup=get_membership_keyboard(
                membership["missing"]
            ),
            parse_mode="HTML",
        )
        return

    result = redeem_user_code(
        user_id=user.id,
        code=code,
    )

    await message.reply_text(
        result["message"],
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


# ==========================================
# CANCEL
# ==========================================

async def cancel_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not is_private_chat(update):
        return

    message = update.effective_message

    if not message:
        return

    context.user_data.pop(
        "awaiting_redeem_code",
        None,
    )

    await message.reply_text(
        "❌ Action cancelled.",
        reply_markup=main_menu_keyboard(),
    )


# ==========================================
# REGISTER HANDLERS
# ==========================================

def register_user_handlers(application):
    """Register user commands and menus."""

    private_chat = filters.ChatType.PRIVATE

    application.add_handler(
        CommandHandler(
            "start",
            start_handler,
            filters=private_chat,
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_handler,
            filters=private_chat,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            verify_membership_callback,
            pattern=r"^verify_membership$",
        )
    )

    menu_handlers = [
        (r"^👤 My Profile$", profile_handler),
        (r"^🏆 Leaderboard$", leaderboard_handler),
        (r"^🔗 My Referral Link$", referral_handler),
        (r"^🎁 Daily Bonus$", daily_bonus_handler),
        (r"^🎁 Rewards$", rewards_handler),
        (r"^🎟️ Redeem Code$", redeem_prompt_handler),
    ]

    for pattern, handler in menu_handlers:
        application.add_handler(
            MessageHandler(
                private_chat
                & filters.Regex(pattern),
                handler,
            )
        )

    application.add_handler(
        MessageHandler(
            private_chat
            & filters.TEXT
            & ~filters.COMMAND,
            redeem_text_handler,
        )
    )

    print(
        "Private-chat-only user handlers registered successfully."
    )
