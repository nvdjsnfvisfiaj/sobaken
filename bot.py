import logging
import re
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

giveaway_state = {}  # {chat_id: {"active": bool, "participants": set(user_id), "message_id": int, "participant_data": {user_id: (username, name)}}}

REACTION_EMOJIS = ['😂', '💩', '👍', '❤️']

def get_gift_number_note(gift_number: str) -> str:
    """Return a note about the rarity or value of the gift number, if applicable."""
    # Check for rare number (1-10)
    if gift_number.isdigit():
        num = int(gift_number)
        if 1 <= num <= 10:
            return "\n\n💎 Номер этого подарка считается редким (#1-10)"
    # Check for all repeated digits (like 222, 11, 5555, 8888, etc)
    if len(set(gift_number)) == 1 and len(gift_number) > 1:
        return "\n\n💎 У данного подарка ценный номер (повторяющиеся цифры)!"
    return ""

# Check admin
async def is_admin(context, chat_id, user_id):
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception:
        return False

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

    if state.get("active", False):
        await message.reply_text(
            '<b>Невозможно запустить раздачу</b> пока запущена другая!',
            parse_mode="HTML"
        )
        return

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
        if not user.is_bot and not (text and text.startswith('/')):
            is_user_admin = await is_admin(context, chat_id, user.id)
            if is_user_admin:
                pass  # Do not add admin to giveaway
            elif user.id not in state["participants"]:
                state["participants"].add(user.id)
                state["participant_data"][user.id] = (user.username, user.full_name)
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

    # --- NFT ссылка ---
    nft_pattern = r"(https://t\.me/nft/|t\.me/nft/)(\w+)-(\d+)"
    match = re.search(nft_pattern, text or "")
    if match:
        nft_url = match.group(0)
        gift_name = match.group(2)
        gift_number = match.group(3)
        note = get_gift_number_note(gift_number)
        response_text = f'<a href="{nft_url}">🎁</a> {gift_name} #{gift_number}{note}'
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Посмотреть 🎁", url=nft_url)],
            [InlineKeyboardButton("Продать подарки", url="https://t.me/tonnel_network_bot/gifts?startapp=ref_1267171169")]
        ])
        await context.bot.send_message(chat_id=chat_id, text=response_text, reply_markup=keyboard, parse_mode="HTML")
        await message.delete()
        return

def main() -> None:
    application = ApplicationBuilder().token("7998421928:AAHXo33u_YD-aLJp7MxGCTWpGqOgK0BzR8U").build()
    application.add_handler(CommandHandler("give", give))
    application.add_handler(CommandHandler("end", end))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.run_polling()

if __name__ == '__main__':
    main()