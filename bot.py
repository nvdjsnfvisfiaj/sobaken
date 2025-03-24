import logging
import re
from telegram import Update, ChatMember
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Define the command handler for /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('🐒')

# Define the message handler to delete HTTP or HTTPS links or respond to specific ones
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    text = message.text
    user = message.from_user
    user_name = user.first_name
    user_username = user.username
    user_link = f"{user_name} (@{user_username})" if user_username else user_name

    # Check if the user is an admin
    chat_member = await context.bot.get_chat_member(update.message.chat_id, user.id)
    is_admin = chat_member.status in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]

    # Updated regex pattern to match both https://t.me/nft/ and t.me/nft/
    nft_pattern = r"(https://t.me/nft/|t.me/nft/)(\w+)-(\d+)"
    match = re.search(nft_pattern, text)

    if match:
        gift_name = match.group(2)
        gift_number = match.group(3)
        response_text = (
            f"🐵 *Пользователь {user_link} отправляет ссылку на коллекционный подарок!*\n\n"
            f"🔗 *Отправленная ссылка:* {text}\n\n"
            f"🎁 *Название подарка:* `{gift_name}`\n"
            f"🔢 *Номер подарка:* `{gift_number}`"
        )
        await message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN)
        if not is_admin:
            await message.delete()
    elif (re.search(r'http://|https://', text)) and not is_admin:
        await message.delete()

def main() -> None:
    # Create the Application and pass it your bot's token.
    application = ApplicationBuilder().token("7998421928:AAGs7WUfu-2lRzAOY7H8aU-iesEK7RB63B0").build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()