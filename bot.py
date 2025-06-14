import os
import logging
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
)
import openai
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# === Environment Variables ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
PORT = int(os.environ.get("PORT", 10000))

# === Webhook Path ===
WEBHOOK_PATH = f"{TELEGRAM_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# === OpenAI Key ===
openai.api_key = OPENAI_API_KEY

# === MongoDB Setup ===
client = MongoClient(MONGO_URI)
db = client['ELVISJS-BOT']
summaries_collection = db['summaries']
quizzes_collection = db['quizzes']

# === User State (in-memory) ===
user_state = {}

# === Summary Generator ===
async def summarize_text(topic: str) -> str:
    cached = summaries_collection.find_one({"topic": topic})
    if cached:
        return cached['summary']

    try:
        response = openai.chat.completions.create(
            model='gpt-3.5-turbo',
            messages=[
                {
                    "role": "system",
                    "content": "You're a helpful and concise JavaScript instructor. Provide a clear explanation with 2-3 examples."
                },
                {
                    "role": "user",
                    "content": f"Explain the JavaScript topic '{topic}' to a beginner. Include a short description, examples, and use cases."
                }
            ],
            max_tokens=300
        )
        summary = response.choices[0].message.content.strip()
        summaries_collection.insert_one({"topic": topic, "summary": summary})
        return summary
    except Exception as e:
        return f"❌ Error during summarization: {e}"

# === Quiz Generator ===
async def generate_quiz(topic: str) -> tuple[str, str]:
    cached = quizzes_collection.find_one({"topic": topic})
    if cached:
        return cached['quiz'], cached['answer']

    try:
        response = openai.chat.completions.create(
            model='gpt-3.5-turbo',
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You're a quiz generator for JavaScript learners. "
                        "Create a multiple-choice question (A to D) with one correct answer. "
                        "Format:\nQuestion: ...\nA. ...\nB. ...\nC. ...\nD. ...\nAnswer: A"
                    )
                },
                {
                    "role": "user",
                    "content": f"Generate a multiple choice question for the topic: {topic}"
                }
            ],
            max_tokens=300
        )
        full_quiz = response.choices[0].message.content.strip()
        parts = full_quiz.split("Answer:")
        question = parts[0].strip()
        answer = parts[1].strip().upper() if len(parts) > 1 else "A"
        quizzes_collection.insert_one({"topic": topic, "quiz": question, "answer": answer})
        return question, answer
    except Exception as e:
        return "❌ Error generating quiz.", "A"

# === Telegram Command: /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! I'm your Fullstack JS bot. Send me a topic like 'loops', 'functions', etc., and I'll teach you and give you a quiz!"
    )

# === Telegram Message Handler ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id in user_state and 'answer' in user_state[user_id]:
        correct = user_state[user_id]['answer'].strip().upper()
        user_answer = text.strip().upper()

        if user_answer == correct:
            await update.message.reply_text("✅ Correct! 🎉")
        else:
            await update.message.reply_text(
                f"❌ Incorrect. The correct answer was: *{correct}*",
                parse_mode="Markdown"
            )

        del user_state[user_id]
        return

    # New topic
    topic = text.lower()
    await update.message.reply_text(f"📘 Learning about *{topic}*...", parse_mode="Markdown")

    summary = await summarize_text(topic)
    await update.message.reply_text(summary, parse_mode="Markdown")

    await update.message.reply_text("🧠 Here's a quiz for practice:")
    quiz, answer = await generate_quiz(topic)
    await update.message.reply_text(quiz, parse_mode="Markdown")

    user_state[user_id] = {"topic": topic, "answer": answer}

# === Error Logger ===
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.warning(f"Update {update} caused error: {context.error}")

# === Main Bot Runner with Webhook ===
async def main():
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    await app.bot.delete_webhook()
    await app.bot.set_webhook(url=WEBHOOK_URL)

    print(f"🚀 Webhook set at {WEBHOOK_URL}, listening on port {PORT}...")

    await app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=WEBHOOK_URL
    )

    # Clean shutdown (optional, but good practice)
    await app.shutdown()
    await app.wait_closed()

# === Event Loop Handling ===
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" in str(e):
            loop = asyncio.get_event_loop()
            loop.run_until_complete(main())
        else:
            raise
