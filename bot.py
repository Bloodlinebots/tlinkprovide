import os
import time
import re
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from filelock import FileLock

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_IDS = [int(i) for i in os.getenv("ADMIN_IDS", "").split()]

# MongoDB setup
mongo = MongoClient(MONGO_URI)
db = mongo["linkbot"]
users = db["users"]

# File path for .txt links
LINK_FILE = "links_pool.txt"
LOCK_FILE = "links_pool.txt.lock"

app = Client("hybrid-bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Utils
def load_links():
    with open(LINK_FILE, "r") as f:
        return [line.strip() for line in f if line.strip()]

def save_links(new_links):
    existing = set(load_links())
    combined = list(existing.union(set(new_links)))
    with FileLock(LOCK_FILE):
        with open(LINK_FILE, "w") as f:
            f.write("\n".join(combined))

def get_unique_link(user_id):
    all_links = load_links()
    data = users.find_one({"user_id": user_id})
    assigned = data.get("links_assigned", []) if data else []

    for link in all_links:
        if link not in assigned:
            users.update_one(
                {"user_id": user_id},
                {"$addToSet": {"links_assigned": link}, "$set": {"last_assigned": time.time()}},
                upsert=True,
            )
            return link
    return None

# Commands
@app.on_message(filters.command("start"))
async def start(client, message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Get Link", callback_data="get_link")]
    ])
    await message.reply("Welcome! Tap to get your link:", reply_markup=keyboard)

@app.on_callback_query(filters.regex("get_link"))
async def send_link(client, callback):
    user_id = callback.from_user.id
    with FileLock(LOCK_FILE):
        link = get_unique_link(user_id)
    if link:
        await callback.message.edit_text(f"Here's your unique link:\n{link}")
    else:
        await callback.message.edit_text("You've received all available links. Please wait for admin to upload more.")

@app.on_message(filters.command("upload") & filters.user(ADMIN_IDS))
async def upload_links(client, message):
    if not message.reply_to_message or not message.reply_to_message.document:
        return await message.reply("Reply to a .txt file to upload links.")

    path = await message.reply_to_message.download()
    with open(path, "r") as src:
        links = [line.strip() for line in src if line.strip().startswith("https://terabox.com/s/")]
    save_links(links)
    await message.reply(f"✅ Uploaded {len(links)} new links.")

@app.on_message(filters.command("stats") & filters.user(ADMIN_IDS))
async def stats(client, message):
    user_count = users.count_documents({})
    total_links = len(load_links())
    assigned_count = users.aggregate([{"$unwind": "$links_assigned"}, {"$count": "total"}])
    assigned_count = list(assigned_count)
    assigned_count = assigned_count[0]["total"] if assigned_count else 0
    await message.reply(f"📊 Users: {user_count}\n📁 Links in pool: {total_links}\n🔄 Total assigned: {assigned_count}")

@app.on_message(filters.command("mylinks"))
async def my_links(client, message):
    user_id = message.from_user.id
    data = users.find_one({"user_id": user_id})
    links = data.get("links_assigned", []) if data else []
    if links:
        reply = "🧾 Your assigned links:\n" + "\n".join(links[-5:])
    else:
        reply = "😶 You haven't received any links yet. Tap the button to get one."
    await message.reply(reply)

@app.on_message(filters.text & filters.user(ADMIN_IDS))
async def handle_text_links(client, message):
    links = re.findall(r"https://terabox\.com/s/\S+", message.text)
    if links:
        save_links(links)
        await message.reply(f"✅ Added {len(links)} new link(s) from your message.")

@app.on_message(filters.document & filters.user(ADMIN_IDS))
async def handle_txt_upload(client, message):
    if message.document.file_name.endswith(".txt"):
        path = await message.download()
        with open(path, "r") as f:
            links = [line.strip() for line in f if line.strip().startswith("https://terabox.com/s/")]
        save_links(links)
        await message.reply(f"✅ Uploaded {len(links)} new link(s) from file.")

@app.on_message(filters.command("export") & filters.user(ADMIN_IDS))
async def export_assigned(client, message):
    from datetime import datetime
    export_file = f"assigned_links_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(export_file, "w") as f:
        for doc in users.find():
            user_id = doc["user_id"]
            links = doc.get("links_assigned", [])
            for l in links:
                f.write(f"{user_id}: {l}\n")
    await message.reply_document(export_file, caption="📤 Exported assigned links.")

app.run()
