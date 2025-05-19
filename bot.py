import logging
import re
import random
from telegram import Update, ChatMember, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

chat_messages = {}
chat_message_counters = {}
used_messages = {}
reaction_counters = {}

# Giveaway state per chat
giveaway_state = {}  # {chat_id: {"active": bool, "participants": set(user_id), "message_id": int, "participant_data": {user_id: (username, name)}}}

REACTION_EMOJIS = ['😂', '💩', '👍', '❤️']

def get_new_random_interval():
    return random.choice([5, 6, 7])

def get_new_reaction_interval():
    return random.choice([9, 13, 16, 20])

def weighted_old_message(messages):
    n = len(messages)
    if n == 0:
        return None
    weights = [n - i for i in range(n)]
    chosen = random.choices(messages, weights=weights, k=1)[0]
    return chosen

# Check admin
async def is_admin(context, chat_id, user_id):
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('🐒')

async def give(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    chat_id = message.chat_id
    user = message.from_user

    admin = await is_admin(context, chat_id, user.id)
    state = giveaway_state.get(chat_id, {"active": False, "participants": set(), "participant_data": {}})
    if not admin:
        await message.reply_text(
            'Команду <b>/give</b> могут использовать <b>только администраторы этого чата</b>',
            parse_mode="HTML"
        )
        return

    # If already active, can't start a new one
    if state.get("active", False):
        await message.reply_text(
            '<b>Невозможно запустить раздачу</b> пока запущена другая!',
            parse_mode="HTML"
        )
        return

    # Start new giveaway
    giveaway_state[chat_id] = {
        "active": True,
        "participants": set(),
        "participant_data": {},
        "message_id": None
    }
    text = (
        "<b>Раздача запущена!</b>\n\n"
        "<b>Отправьте любое сообщение</b> чтобы присоединиться к раздаче\n"
        f"<b>Участников:</b> 0\n\n"
        "Администратору необходимо отправить команду <b>/end</b> чтобы <b>завершить раздачу и я выбрал случайного победителя</b>"
    )
    sent = await message.reply_text(text, parse_mode="HTML")
    giveaway_state[chat_id]["message_id"] = sent.message_id

async def end(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    chat_id = message.chat_id
    user = message.from_user

    admin = await is_admin(context, chat_id, user.id)
    state = giveaway_state.get(chat_id)
    if not admin:
        # Try delete, ignore if already deleted
        try:
            await message.delete()
        except Exception:
            pass
        return

    if not state or not state.get("active", False):
        await message.reply_text(
            "Я <b>не могу завершить раздачу</b> так как она еще не запущена!\n\nЗапустите раздачу с помощью команды <b>/give</b>",
            parse_mode="HTML"
        )
        return

    participants = list(state["participants"])
    participant_data = state["participant_data"]
    giveaway_state[chat_id] = {"active": False, "participants": set(), "participant_data": {}, "message_id": None}

    if not participants:
        await message.reply_text(
            "Никто не присоединился к раздаче.",
            parse_mode="HTML"
        )
        return

    winner_id = random.choice(participants)
    username, name = participant_data[winner_id]
    winner_display = f"@{username}" if username else name
    winner_id_str = f"{winner_id}"

    text = (
        "🎉 <b>Раздача завершена!</b>\n\n"
        f"Победитель: <b>{winner_display}</b> (<code>{winner_id_str}</code>)"
    )
    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    text = message.text
    user = message.from_user
    chat_id = message.chat_id

    # == Giveaway logic ==
    state = giveaway_state.get(chat_id)
    if state and state.get("active", False):
        # Not from bot, not command, and not already joined
        if not user.is_bot and not (text and text.startswith('/')):
            # Check if user is admin: admins do not participate
            is_user_admin = await is_admin(context, chat_id, user.id)
            if is_user_admin:
                pass  # Do not add admin to giveaway
            elif user.id not in state["participants"]:
                state["participants"].add(user.id)
                state["participant_data"][user.id] = (user.username, user.full_name)
                # Edit giveaway message with new count
                participants_count = len(state["participants"])
                msg_id = state.get("message_id")
                text_to_edit = (
                    "<b>Раздача запущена!</b>\n\n"
                    "<b>Отправьте любое сообщение</b> чтобы присоединиться к раздаче\n"
                    f"<b>Участников:</b> {participants_count}\n\n"
                    "Администратору необходимо отправить команду <b>/end</b> чтобы <b>завершить раздачу и я выбрал случайного победителя</b>"
                )
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=msg_id,
                        text=text_to_edit,
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

    if chat_id not in chat_messages:
        chat_messages[chat_id] = []
        chat_message_counters[chat_id] = (0, get_new_random_interval())
    if chat_id not in used_messages:
        used_messages[chat_id] = set()
    if chat_id not in reaction_counters:
        reaction_counters[chat_id] = (0, get_new_reaction_interval())
    current_count, target_count = chat_message_counters[chat_id]
    reaction_count, reaction_target = reaction_counters[chat_id]

    # --- Реакция
    if not user.is_bot and text:
        reaction_count += 1
        if reaction_count >= reaction_target:
            try:
                await message.react(random.choice(REACTION_EMOJIS))
            except Exception as e:
                logger.warning(f"Failed to react: {e}")
            reaction_count = 0
            reaction_target = get_new_reaction_interval()
        reaction_counters[chat_id] = (reaction_count, reaction_target)

    # --- Ответ на сообщение бота ---
    if (
        message.reply_to_message is not None and
        message.reply_to_message.from_user is not None and
        message.reply_to_message.from_user.is_bot
    ):
        eligible_messages = [
            (i, m)
            for i, m in enumerate(chat_messages[chat_id][:-1])
            if i not in used_messages[chat_id]
        ]
        if not eligible_messages:
            used_messages[chat_id].clear()
            eligible_messages = [
                (i, m) for i, m in enumerate(chat_messages[chat_id][:-1])
            ]
        if eligible_messages:
            idx, random_message = weighted_old_message(eligible_messages)
            if random.random() < 0.4:
                await message.reply_text(random_message)
            else:
                await context.bot.send_message(chat_id=chat_id, text=random_message)
            used_messages[chat_id].add(idx)
        return

    # --- NFT ссылка ---
    nft_pattern = r"(https://t\.me/nft/|t\.me/nft/)(\w+)-(\d+)"
    match = re.search(nft_pattern, text or "")
    if match:
        nft_url = match.group(0)
        gift_name = match.group(2)
        gift_number = match.group(3)
        response_text = f'<a href="{nft_url}">🎁</a> {gift_name} #{gift_number}'
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Посмотреть 🎁", url=nft_url)],
            [InlineKeyboardButton("Продать подарки", url="https://t.me/tonnel_network_bot/gifts?startapp=ref_1267171169")]
        ])
        await context.bot.send_message(chat_id=chat_id, text=response_text, reply_markup=keyboard, parse_mode="HTML")
        await message.delete()
        return

    # --- Обычное сообщение ---
    if not user.is_bot and text:
        chat_messages[chat_id].append(text)
        if len(chat_messages[chat_id]) > 200:
            removed = len(chat_messages[chat_id]) - 200
            chat_messages[chat_id] = chat_messages[chat_id][-200:]
            used_messages[chat_id] = set(
                i - removed for i in used_messages[chat_id] if i - removed >= 0
            )

        current_count += 1
        if current_count >= target_count and len(chat_messages[chat_id]) > 1:
            eligible_messages = [
                (i, m)
                for i, m in enumerate(chat_messages[chat_id][:-1])
                if i not in used_messages[chat_id]
            ]
            if not eligible_messages:
                used_messages[chat_id].clear()
                eligible_messages = [
                    (i, m) for i, m in enumerate(chat_messages[chat_id][:-1])
                ]
            if eligible_messages:
                idx, random_message = weighted_old_message(eligible_messages)
                if random.choice([True, False]):
                    await message.reply_text(random_message)
                else:
                    await context.bot.send_message(chat_id=chat_id, text=random_message)
                used_messages[chat_id].add(idx)
            current_count = 0
            target_count = get_new_random_interval()
        chat_message_counters[chat_id] = (current_count, target_count)

    # --- Проверка на админа для ссылок ---
    chat_member = await context.bot.get_chat_member(chat_id, user.id)
    is_admin_flag = chat_member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]

    if (re.search(r'http://|https://', text or "")) and not is_admin_flag:
        await message.delete()

def main() -> None:
    application = ApplicationBuilder().token("7998421928:AAGs7WUfu-2lRzAOY7H8aU-iesEK7RB63B0").build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("give", give))
    application.add_handler(CommandHandler("end", end))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.run_polling()

if __name__ == '__main__':
    main()