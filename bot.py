import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import openai
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# Load tokens from .env
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

openai.api_key = OPENAI_API_KEY

# Connect to MongoDB
client = MongoClient(MONGO_URI)
db = client['ELVISJS-BOT']
summaries_collection = db['summaries']
quizzes_collection = db['quizzes']

# In-memory user state
user_state = {}  # {user_id: {"topic": str, "answer": str}}

# Summarize topic
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
                    "content": "You are a helpful and concise JavaScript instructor. Provide a clear explanation with 2-3 examples from the given topic."
                },
                {
                    "role": "user",
                    "content": f"Explain the JavaScript topic '{topic}' to a beginner. Include a short description, examples, and common use cases."
                }
            ],
            max_tokens=300,
        )

        summary = response.choices[0].message.content.strip()
        summaries_collection.insert_one({"topic": topic, "summary": summary})
        return summary
    except Exception as e:
        return f"❌ Error during summarization: {e}"


# Generate quiz with correct letter answer
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
                        "Format like:\n"
                        "Question: ...\n"
                        "A. ...\n"
                        "B. ...\n"
                        "C. ...\n"
                        "D. ...\n"
                        "Answer: A"
                    )
                },
                {
                    "role": "user",
                    "content": f"Generate a multiple choice question for the topic: {topic}"
                }
            ],
            max_tokens=300,
        )
        full_quiz = response.choices[0].message.content.strip()

        parts = full_quiz.split("Answer:")
        question = parts[0].strip()
        answer = parts[1].strip().upper() if len(parts) > 1 else "A"

        quizzes_collection.insert_one({"topic": topic, "quiz": question, "answer": answer})
        return question, answer
    except Exception as e:
        return "❌ Error generating quiz.", "A"


# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hi! I'm your Fullstack JS bot. Send me a topic like 'loops', 'functions', etc., and I'll teach you and give a quiz.")


# Handle messages (topic or answer)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # If user is answering a quiz
    if user_id in user_state and 'answer' in user_state[user_id]:
        correct = user_state[user_id]['answer'].strip().upper()
        user_answer = text.strip().upper()

        if user_answer == correct:
            await update.message.reply_text("✅ Correct! 🎉")
        else:
            await update.message.reply_text(f"❌ Incorrect. The correct answer was: *{correct}*", parse_mode="Markdown")

        del user_state[user_id]  # Reset
        return

    # Otherwise, treat it as a new topic
    topic = text.lower()
    await update.message.reply_text(f"📘 Learning about *{topic}*...", parse_mode="Markdown")

    summary = await summarize_text(topic)
    await update.message.reply_text(summary, parse_mode="Markdown")

    await update.message.reply_text("🧠 Here's a quiz for practice:")

    quiz, answer = await generate_quiz(topic)
    await update.message.reply_text(quiz, parse_mode="Markdown")

    user_state[user_id] = {"topic": topic, "answer": answer}


# Log errors
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.warning(f"Update {update} caused error: {context.error}")


# Run bot
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    print("🤖 Bot is running...")
    app.run_polling()