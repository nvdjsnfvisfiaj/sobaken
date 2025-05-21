import logging
import re
import random
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, InputFile, CallbackQuery
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import io

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

giveaway_state = {}
farm_state = {}
user_message_count = {}      # {(chat_id, user_id): int}
user_daily_messages = {}     # {(chat_id, user_id): [timestamps]}
refresh_cooldowns = {}      # {(chat_id, user_id, type): last_refresh_timestamp}
ADMIN_ID = 1267171169

def get_gift_number_note(gift_number: str) -> str:
    if gift_number.isdigit():
        num = int(gift_number)
        if 1 <= num <= 10:
            return "\n\n💎 Номер этого подарка считается редким (#1-10)"
    if len(set(gift_number)) == 1 and len(gift_number) > 1:
        return "\n\n💎 У данного подарка ценный номер (повторяющиеся цифры)!"
    return ""

async def is_admin(context, chat_id, user_id):
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception:
        return False

def is_command_message(text: str) -> bool:
    if not text:
        return False
    cmd = text.strip().lower()
    return (
        cmd == "фарм" or
        cmd == "профиль" or
        cmd == "импорт" or
        cmd == "топ дня" or
        cmd == "топ"
    )

def make_user_link(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{name}</a>'

async def build_top_day_message(chat_id, context, now=None):
    if now is None:
        now = int(time.time())
    daily_counts = {}
    for (c_id, u_id), timestamps in user_daily_messages.items():
        if c_id != chat_id:
            continue
        recent = [t for t in timestamps if t >= now - 24*60*60]
        if recent:
            daily_counts[u_id] = len(recent)
            user_daily_messages[(c_id, u_id)] = recent
    top = sorted(daily_counts.items(), key=lambda x: -x[1])[:10]
    message_lines = ["☀️ <b>Топ дня:</b>\n"]
    place = 1
    for user_id, count in top:
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            name = member.user.full_name
        except Exception:
            name = str(user_id)
        user_link = make_user_link(user_id, name)
        message_lines.append(f"{place}. {user_link} - {count}")
        place += 1
    if len(message_lines) == 1:
        message_lines.append("Нет данных за последние 24 часа.")
    return "\n".join(message_lines)

async def build_top_all_message(chat_id, context):
    total_counts = {}
    for (c_id, u_id), count in user_message_count.items():
        if c_id != chat_id:
            continue
        total_counts[u_id] = count
    top = sorted(total_counts.items(), key=lambda x: -x[1])[:10]
    message_lines = ["💬 <b>Топ чата:</b>\n"]
    place = 1
    for user_id, count in top:
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            name = member.user.full_name
        except Exception:
            name = str(user_id)
        user_link = make_user_link(user_id, name)
        message_lines.append(f"{place}. {user_link} - {count}")
        place += 1
    if len(message_lines) == 1:
        message_lines.append("Нет данных для топа.")
    return "\n".join(message_lines)

def get_refresh_keyboard(top_type):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄️ Обновить", callback_data=f"refresh_{top_type}")]
    ])

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

def farm_chance():
    ranges = [
        (1, 10, 0.40),
        (11, 20, 0.25),
        (21, 30, 0.15),
        (31, 40, 0.10),
        (41, 45, 0.07),
        (46, 50, 0.03),
    ]
    r = random.random()
    acc = 0
    for start, end, prob in ranges:
        acc += prob
        if r <= acc:
            return random.randint(start, end)
    return random.randint(1, 10)

def get_time_left(seconds):
    mins = seconds // 60
    hours = mins // 60
    mins = mins % 60
    if hours > 0:
        if mins > 0:
            return f"{hours} час{'а' if 2 <= hours <= 4 else '' if hours == 1 else 'ов'} {mins} минут{'ы' if mins in [2,3,4] else 'а' if mins == 1 else '' if mins == 0 else ''}"
        else:
            return f"{hours} час{'а' if 2 <= hours <= 4 else '' if hours == 1 else 'ов'}"
    else:
        return f"{mins} минут{'ы' if mins in [2,3,4] else 'а' if mins == 1 else '' if mins == 0 else ''}"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    text = message.text
    user = message.from_user
    chat_id = message.chat_id

    # Реакция на слова "продать", "купить", "продажа", "продам"
    if text:
        lowered = text.lower()
        if any(word in lowered for word in ("продать", "купить", "продажа", "продам")):
            await message.reply_text(
                'Купить и продать подарки можно в <a href="https://t.me/tonnel_network_bot/gifts?startapp=ref_1267171169">Tonnel Relayer Bot</a>',
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_to_message_id=message.message_id
            )
            return

    # Считаем сообщения пользователя в чате (всего и за 24 часа), если это не команда
    if not user.is_bot and not is_command_message(text):
        key = (chat_id, user.id)
        user_message_count[key] = user_message_count.get(key, 0) + 1
        key_daily = (chat_id, user.id)
        now = int(time.time())
        if key_daily not in user_daily_messages:
            user_daily_messages[key_daily] = []
        user_daily_messages[key_daily].append(now)
        user_daily_messages[key_daily] = [
            t for t in user_daily_messages[key_daily] if t >= now - 24*60*60
        ]

    # == Giveaway logic ==
    state = giveaway_state.get(chat_id)
    if state and state.get("active", False):
        if not user.is_bot and not (text and text.startswith('/')):
            is_user_admin = await is_admin(context, chat_id, user.id)
            if is_user_admin:
                pass
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

    # --- Фарм команда ---
    if text and text.strip().lower() == "фарм":
        user_id = user.id
        now = int(time.time())
        farm = farm_state.get(user_id, {"last_farm": 0, "coins": 0})
        cooldown = 3 * 60 * 60
        left = farm["last_farm"] + cooldown - now
        if left > 0:
            time_left = get_time_left(left)
            reply_text = f"☹️ <b>Не зафармлено!</b> Зафармить можно только через <b>{time_left}</b>"
            await message.reply_text(reply_text, parse_mode="HTML", reply_to_message_id=message.message_id)
            return
        coins = farm_chance()
        farm_state[user_id] = {"last_farm": now, "coins": farm["coins"] + coins}
        reply_text = f"🌸 <b>Зафармлено!</b> Получено <b>+{coins}</b>🪙\nСледующий фарм через 3 часа"
        await message.reply_text(reply_text, parse_mode="HTML", reply_to_message_id=message.message_id)
        return

    # --- Профиль команда ---
    if text and text.strip().lower() == "профиль":
        user_id = user.id
        coins = farm_state.get(user_id, {}).get("coins", 0)
        key_daily = (chat_id, user_id)
        now = int(time.time())
        daily_count = 0
        if key_daily in user_daily_messages:
            daily_count = len([t for t in user_daily_messages[key_daily] if t >= now - 24*60*60])
        reply_text = (
            f"💎<b> Профиль {user.full_name}</b>\n\n"
            f"Монет: <b>{coins}</b>🪙\n"
            f"Сообщений за последние 24 часа: <b>{daily_count}</b>"
        )
        await message.reply_text(reply_text, parse_mode="HTML", reply_to_message_id=message.message_id)
        return

    # --- Импорт команда ---
    if text and text.strip().lower() == "импорт":
        if user.id != ADMIN_ID:
            await message.reply_text(
                "❌ Данная команда вам недоступна",
                parse_mode="HTML",
                reply_to_message_id=message.message_id
            )
            return
        export_lines = []
        for user_id, data in farm_state.items():
            coins = data.get("coins", 0)
            name = None
            for (chatid, uid), count in user_message_count.items():
                if uid == user_id:
                    try:
                        member = await context.bot.get_chat_member(chatid, uid)
                        name = member.user.full_name
                        break
                    except Exception:
                        pass
            if not name:
                name = str(user_id)
            export_lines.append(f"{name} - {coins}")
        export_text = "\n\n".join(export_lines)
        file_bytes = io.BytesIO(export_text.encode('utf-8'))
        file_bytes.name = "coins.txt"
        await message.reply_document(document=InputFile(file_bytes, filename="coins.txt"))
        return

    # --- Топ дня команда ---
    if text and text.strip().lower() == "топ дня":
        message_text = await build_top_day_message(chat_id, context)
        keyboard = get_refresh_keyboard("day")
        await message.reply_text(
            message_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=keyboard
        )
        return

    # --- Топ за всё время ---
    if text and text.strip().lower() == "топ":
        message_text = await build_top_all_message(chat_id, context)
        keyboard = get_refresh_keyboard("all")
        await message.reply_text(
            message_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=keyboard
        )
        return

async def refresh_top_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query: CallbackQuery = update.callback_query
    user = query.from_user
    chat_id = query.message.chat_id
    data = query.data
    top_type = None
    if data == "refresh_day":
        top_type = "day"
    elif data == "refresh_all":
        top_type = "all"
    else:
        await query.answer("Неизвестный тип топа.", show_alert=True)
        return

    now = int(time.time())
    cooldown_key = (chat_id, user.id, top_type)
    last_refresh = refresh_cooldowns.get(cooldown_key, 0)
    if now - last_refresh < 15:
        await query.answer("❌ Не так часто! Попробуйте через несколько секунд...", show_alert=True)
        return
    refresh_cooldowns[cooldown_key] = now

    if top_type == "day":
        message_text = await build_top_day_message(chat_id, context, now)
    elif top_type == "all":
        message_text = await build_top_all_message(chat_id, context)
    else:
        message_text = "Ошибка топа."

    keyboard = get_refresh_keyboard(top_type)
    try:
        await query.edit_message_text(
            message_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=keyboard
        )
        await query.answer("🔄️ Статистика обновлена!", show_alert=True)
    except Exception as e:
        await query.answer("Ошибка обновления.", show_alert=True)

def main() -> None:
    application = ApplicationBuilder().token("7998421928:AAHXo33u_YD-aLJp7MxGCTWpGqOgK0BzR8U").build()
    application.add_handler(CommandHandler("give", give))
    application.add_handler(CommandHandler("end", end))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(refresh_top_callback, pattern=r"^refresh_"))
    application.run_polling()

if __name__ == '__main__':
    main()