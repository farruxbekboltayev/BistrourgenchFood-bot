import os
import json
import random
import sqlite3
from datetime import datetime

from telegram import (
    Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

TOKEN = os.getenv("TOKEN", "BOT_TOKEN_BU_YERGA")

ADMIN_IDS = [5702824058]

ADMIN_CHANNEL_ID = -1003925609420
KITCHEN_CHANNEL_ID = -1003992130229
DELIVERY_CHANNEL_ID = -1003937711655

ADMIN_USERNAME = "@farrukh01uz"
CARD_NUMBER = "9860060138529692"

DB_NAME = "food_bot.db"


def db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def format_price(price):
    return f"{price:,}".replace(",", " ")


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        name TEXT,
        phone TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS foods (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        price INTEGER,
        available INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        user_name TEXT,
        phone TEXT,
        items TEXT,
        total INTEGER,
        code TEXT,
        code_active INTEGER DEFAULT 1,
        status TEXT,
        lat REAL,
        lon REAL,
        created_at TEXT
    )
    """)

    cur.execute("SELECT COUNT(*) AS c FROM foods")
    if cur.fetchone()["c"] == 0:
        foods = [
            ("Lavash", 35000, 1),
            ("Burger", 28000, 1),
            ("Pizza", 70000, 1),
            ("Cola", 12000, 1),
        ]
        cur.executemany(
            "INSERT INTO foods (name, price, available) VALUES (?, ?, ?)",
            foods
        )

    conn.commit()
    conn.close()


def get_foods():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM foods ORDER BY id ASC")
    foods = cur.fetchall()
    conn.close()
    return foods


def get_food(food_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM foods WHERE id=?", (food_id,))
    food = cur.fetchone()
    conn.close()
    return food


def get_order(order_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM orders WHERE id=?", (order_id,))
    order = cur.fetchone()
    conn.close()
    return order


def update_order(order_id, status=None, code_active=None):
    conn = db()
    cur = conn.cursor()

    if status is not None:
        cur.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))

    if code_active is not None:
        cur.execute("UPDATE orders SET code_active=? WHERE id=?", (code_active, order_id))

    conn.commit()
    conn.close()


def generate_code():
    conn = db()
    cur = conn.cursor()

    while True:
        code = str(random.randint(1000, 9999))
        cur.execute(
            "SELECT id FROM orders WHERE code=? AND code_active=1",
            (code,)
        )
        if not cur.fetchone():
            conn.close()
            return code


def order_text(order, title):
    items = json.loads(order["items"])

    text = f"{title}\n\n"
    text += f"📦 Buyurtma: #{order['id']}\n"
    text += f"👤 Ism: {order['user_name']}\n"
    text += f"📞 Telefon: {order['phone']}\n"
    text += f"🔢 Kod: {order['code']}\n\n"
    text += "🍔 Buyurtmalar:\n"

    for item in items:
        text += f"- {item['name']} x{item['qty']} — {format_price(item['subtotal'])} so‘m\n"

    text += f"\n💰 Jami: {format_price(order['total'])} so‘m"
    return text


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.setdefault("cart", {})

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = cur.fetchone()
    conn.close()

    if user:
        await show_menu(update, context)
        return

    btn = KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True)
    keyboard = ReplyKeyboardMarkup([[btn]], resize_keyboard=True)

    await update.message.reply_text(
        "Assalomu alaykum! Buyurtma berish uchun telefon raqamingizni yuboring.",
        reply_markup=keyboard
    )


async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    context.user_data["phone"] = contact.phone_number
    context.user_data["step"] = "waiting_name"

    await update.message.reply_text(
        "Ismingizni yozing:",
        reply_markup=ReplyKeyboardRemove()
    )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    step = context.user_data.get("step")

    if step == "waiting_name":
        phone = context.user_data.get("phone")

        conn = db()
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO users (user_id, name, phone) VALUES (?, ?, ?)",
            (user_id, text, phone)
        )
        conn.commit()
        conn.close()

        context.user_data["step"] = None
        context.user_data["cart"] = {}

        await update.message.reply_text(f"Rahmat, {text}!")
        await show_menu(update, context)
        return

    if step == "admin_add_name":
        if user_id not in ADMIN_IDS:
            return

        context.user_data["new_food_name"] = text
        context.user_data["step"] = "admin_add_price"
        await update.message.reply_text("Narxini yozing. Masalan: 35000")
        return

    if step == "admin_add_price":
        if user_id not in ADMIN_IDS:
            return

        if not text.isdigit():
            await update.message.reply_text("Narx faqat raqam bo‘lishi kerak.")
            return

        name = context.user_data["new_food_name"]
        price = int(text)

        conn = db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO foods (name, price, available) VALUES (?, ?, 1)",
            (name, price)
        )
        conn.commit()
        conn.close()

        context.user_data["step"] = None
        await update.message.reply_text("✅ Ovqat menyuga qo‘shildi.")
        await admin_panel(update, context)
        return

    await update.message.reply_text("Menyu uchun /start bosing.")


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    foods = get_foods()
    keyboard = []

    for food in foods:
        status = "✅" if food["available"] else "❌ Tugagan"
        keyboard.append([
            InlineKeyboardButton(
                f"{food['name']} — {format_price(food['price'])} so‘m {status}",
                callback_data=f"food:{food['id']}"
            )
        ])

    keyboard.append([InlineKeyboardButton("🛒 Savatcha", callback_data="cart")])

    text = "🍽 Menyu:\n\nKerakli ovqatni tanlang."

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def show_food_quantity(query, context, food_id):
    food = get_food(food_id)
    qty = context.user_data["cart"].get(str(food_id), 0)

    text = f"""
🍔 {food['name']}
Narxi: {format_price(food['price'])} so‘m

Soni: {qty} ta
"""

    keyboard = [
        [
            InlineKeyboardButton("➖", callback_data=f"minus:{food_id}"),
            InlineKeyboardButton("➕", callback_data=f"plus:{food_id}")
        ],
        [InlineKeyboardButton("🛒 Savatcha", callback_data="cart")],
        [InlineKeyboardButton("⬅️ Menyu", callback_data="menu")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def show_cart(query, context):
    cart = context.user_data.get("cart", {})

    if not cart:
        await query.edit_message_text(
            "🛒 Savatcha bo‘sh.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Menyu", callback_data="menu")]
            ])
        )
        return

    text = "🛒 Savatcha:\n\n"
    total = 0

    for food_id, qty in cart.items():
        food = get_food(int(food_id))
        if not food:
            continue

        subtotal = food["price"] * qty
        total += subtotal
        text += f"{food['name']} x{qty} — {format_price(subtotal)} so‘m\n"

    text += f"\n💰 Jami: {format_price(total)} so‘m"

    keyboard = [
        [InlineKeyboardButton("✅ Buyurtma berish", callback_data="checkout")],
        [InlineKeyboardButton("⬅️ Menyu", callback_data="menu")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("step") != "waiting_location":
        return

    user_id = update.effective_user.id
    cart = context.user_data.get("cart", {})
    loc = update.message.location

    if not cart:
        await update.message.reply_text("Savatchangiz bo‘sh.")
        return

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = cur.fetchone()

    items = []
    total = 0

    for food_id, qty in cart.items():
        food = get_food(int(food_id))
        if not food:
            continue

        subtotal = food["price"] * qty
        total += subtotal

        items.append({
            "id": food["id"],
            "name": food["name"],
            "qty": qty,
            "price": food["price"],
            "subtotal": subtotal
        })

    code = generate_code()

    cur.execute("""
    INSERT INTO orders 
    (user_id, user_name, phone, items, total, code, code_active, status, lat, lon, created_at)
    VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
    """, (
        user_id,
        user["name"],
        user["phone"],
        json.dumps(items, ensure_ascii=False),
        total,
        code,
        "pending_review",
        loc.latitude,
        loc.longitude,
        datetime.now().isoformat()
    ))

    order_id = cur.lastrowid
    conn.commit()
    conn.close()

    context.user_data["step"] = None

    await send_review_to_user(update, context, order_id)


async def send_review_to_user(update, context, order_id):
    order = get_order(order_id)

    text = order_text(
        order,
        "📋 Buyurtmani tekshiring\n\n📍 Manzil: Siz yuborgan lokatsiya qabul qilindi"
    )

    text += "\n\nAgar hammasi to‘g‘ri bo‘lsa, tasdiqlang."

    keyboard = [
        [InlineKeyboardButton("✅ Tasdiqlash va to‘lovga o‘tish", callback_data=f"confirm_order:{order_id}")],
        [InlineKeyboardButton("✏️ Buyurtmani tahrirlash", callback_data=f"edit_order:{order_id}")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data=f"cancel:{order_id}")]
    ]

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    context.user_data.setdefault("cart", {})
    cart = context.user_data["cart"]

    if data.startswith("food:"):
        food_id = int(data.split(":")[1])
        food = get_food(food_id)

        if not food:
            await query.answer("Bu ovqat topilmadi.", show_alert=True)
            return

        if food["available"] == 0:
            await query.answer("Kechirasiz, bu ovqat hozircha mavjud emas.", show_alert=True)
            return

        cart[str(food_id)] = cart.get(str(food_id), 0) + 1
        await show_food_quantity(query, context, food_id)

    elif data.startswith("plus:"):
        food_id = int(data.split(":")[1])
        food = get_food(food_id)

        if food and food["available"]:
            cart[str(food_id)] = cart.get(str(food_id), 0) + 1

        await show_food_quantity(query, context, food_id)

    elif data.startswith("minus:"):
        food_id = int(data.split(":")[1])

        if cart.get(str(food_id), 0) > 1:
            cart[str(food_id)] -= 1
        else:
            cart.pop(str(food_id), None)

        await show_food_quantity(query, context, food_id)

    elif data == "menu":
        await show_menu(update, context)

    elif data == "cart":
        await show_cart(query, context)

    elif data == "checkout":
        if not cart:
            await query.edit_message_text("Savatcha bo‘sh.")
            return

        btn = KeyboardButton("📍 Lokatsiya yuborish", request_location=True)
        keyboard = ReplyKeyboardMarkup([[btn]], resize_keyboard=True)

        context.user_data["step"] = "waiting_location"

        await query.message.reply_text(
            "Buyurtmani yakunlash uchun lokatsiyangizni yuboring.",
            reply_markup=keyboard
        )

    elif data.startswith("confirm_order:"):
        order_id = int(data.split(":")[1])
        await confirm_order(query, context, order_id)

    elif data.startswith("edit_order:"):
        order_id = int(data.split(":")[1])
        await edit_order(query, context, order_id, update)

    elif data.startswith("cancel:"):
        order_id = int(data.split(":")[1])
        await cancel_question(query, order_id)

    elif data.startswith("confirm_cancel:"):
        order_id = int(data.split(":")[1])
        await confirm_cancel(query, context, order_id)

    elif data == "admin_menu":
        await show_admin_menu(query)

    elif data == "admin_add_food":
        if query.from_user.id not in ADMIN_IDS:
            return
        context.user_data["step"] = "admin_add_name"
        await query.message.reply_text("Yangi ovqat nomini yozing:")

    elif data.startswith("admin_toggle:"):
        food_id = int(data.split(":")[1])
        await admin_toggle_food(query, food_id)

    elif data.startswith("admin_paid:"):
        await admin_paid(query, context, int(data.split(":")[1]))

    elif data.startswith("admin_not_paid:"):
        await admin_not_paid(query, context, int(data.split(":")[1]))

    elif data.startswith("kitchen_ready:"):
        await kitchen_ready(query, context, int(data.split(":")[1]))

    elif data.startswith("delivery_start:"):
        await delivery_start(query, context, int(data.split(":")[1]))

    elif data.startswith("delivery_done:"):
        await delivery_done(query, context, int(data.split(":")[1]))

    elif data.startswith("rate:"):
        _, order_id, rating = data.split(":")
        await query.edit_message_text(
            f"Rahmat! Buyurtma #{order_id} uchun {rating} ⭐️ baho berdingiz."
        )


async def confirm_order(query, context, order_id):
    order = get_order(order_id)

    if order["status"] != "pending_review":
        await query.answer("Bu buyurtma allaqachon qayta ishlangan.", show_alert=True)
        return

    update_order(order_id, status="payment_waiting")

    text = f"""
💳 To‘lov ma’lumotlari

📦 Buyurtma: #{order_id}
🔢 Tasdiqlash kodi: {order['code']}

💰 Jami summa: {format_price(order['total'])} so‘m
💳 Karta: {CARD_NUMBER}

Pul o‘tkazayotganda izoh qismiga shu kodni yozing:
{order['code']}
"""

    keyboard = [
        [InlineKeyboardButton("✏️ Buyurtmani tahrirlash", callback_data=f"edit_order:{order_id}")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data=f"cancel:{order_id}")]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    await send_to_admin(context, order_id)


async def edit_order(query, context, order_id, update):
    order = get_order(order_id)

    if order["status"] not in ["pending_review", "payment_waiting"]:
        await query.answer("Bu buyurtmani endi tahrirlab bo‘lmaydi.", show_alert=True)
        return

    update_order(order_id, status="edited_cancelled", code_active=0)

    old_items = json.loads(order["items"])
    new_cart = {}

    for item in old_items:
        new_cart[str(item["id"])] = item["qty"]

    context.user_data["cart"] = new_cart

    await query.edit_message_text(
        "✏️ Buyurtmani tahrirlashingiz mumkin. Menyudan kerakli o‘zgarishlarni qiling."
    )

    await show_menu(update, context)


async def cancel_question(query, order_id):
    keyboard = [
        [InlineKeyboardButton("✅ Ha, bekor qilaman", callback_data=f"confirm_cancel:{order_id}")],
        [InlineKeyboardButton("❌ Yo‘q", callback_data="menu")]
    ]

    await query.edit_message_text(
        "❗ Rostdan ham buyurtmani bekor qilmoqchimisiz?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def confirm_cancel(query, context, order_id):
    order = get_order(order_id)

    if order["status"] not in ["pending_review", "payment_waiting"]:
        await query.answer("Bu buyurtmani endi bekor qilib bo‘lmaydi.", show_alert=True)
        return

    update_order(order_id, status="cancelled", code_active=0)

    await query.edit_message_text("❌ Buyurtmangiz bekor qilindi.")

    await context.bot.send_message(
        chat_id=ADMIN_CHANNEL_ID,
        text=f"❌ Buyurtma #{order_id} mijoz tomonidan bekor qilindi.\n🔢 Kod: {order['code']}"
    )


async def send_to_admin(context, order_id):
    order = get_order(order_id)

    keyboard = [
        [InlineKeyboardButton("✅ To‘lov tasdiqlandi", callback_data=f"admin_paid:{order_id}")],
        [InlineKeyboardButton("❌ To‘lov tasdiqlanmadi", callback_data=f"admin_not_paid:{order_id}")]
    ]

    await context.bot.send_message(
        chat_id=ADMIN_CHANNEL_ID,
        text=order_text(order, "🆕 Yangi buyurtma\n\nHolat: ⏳ To‘lov kutilmoqda"),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    await context.bot.send_location(
        chat_id=ADMIN_CHANNEL_ID,
        latitude=order["lat"],
        longitude=order["lon"]
    )


async def admin_paid(query, context, order_id):
    order = get_order(order_id)

    if order["status"] != "payment_waiting":
        await query.answer("Bu buyurtma to‘lov kutish holatida emas.", show_alert=True)
        return

    update_order(order_id, status="paid")

    await context.bot.send_message(
        chat_id=order["user_id"],
        text="✅ To‘lovingiz tasdiqlandi. Buyurtmangiz tayyorlanmoqda."
    )

    keyboard = [
        [InlineKeyboardButton("✅ Buyurtma tayyorlandi", callback_data=f"kitchen_ready:{order_id}")]
    ]

    await context.bot.send_message(
        chat_id=KITCHEN_CHANNEL_ID,
        text=order_text(order, "👨‍🍳 Oshpazlar uchun buyurtma\n\nHolat: 🍳 Tayyorlanmoqda"),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    await query.edit_message_text(order_text(order, "✅ To‘lov tasdiqlandi"))


async def admin_not_paid(query, context, order_id):
    order = get_order(order_id)
    update_order(order_id, status="payment_rejected")

    admin_link = f"https://t.me/{ADMIN_USERNAME.replace('@', '')}"

    await context.bot.send_message(
        chat_id=order["user_id"],
        text="❌ To‘lovingiz tasdiqlanmadi.\n\nIltimos, admin bilan bog‘laning.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👨‍💼 Admin bilan bog‘lanish", url=admin_link)]
        ])
    )

    await query.edit_message_text(order_text(order, "❌ To‘lov tasdiqlanmadi"))


async def kitchen_ready(query, context, order_id):
    order = get_order(order_id)

    if order["status"] != "paid":
        await query.answer("Avval to‘lov tasdiqlanishi kerak.", show_alert=True)
        return

    update_order(order_id, status="ready")

    await context.bot.send_message(
        chat_id=order["user_id"],
        text="🍔 Buyurtmangiz tayyor bo‘ldi. Tez orada kuryer yo‘lga chiqadi."
    )

    keyboard = [
        [InlineKeyboardButton("🚚 Yo‘lga chiqdi", callback_data=f"delivery_start:{order_id}")],
        [InlineKeyboardButton("✅ Yetkazildi", callback_data=f"delivery_done:{order_id}")]
    ]

    await context.bot.send_message(
        chat_id=DELIVERY_CHANNEL_ID,
        text=order_text(
            order,
            "🚚 Kuryerlar uchun buyurtma\n\nHolat: ✅ Tayyor\n📍 Lokatsiya pastda yuborilgan"
        ),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    await context.bot.send_location(
        chat_id=DELIVERY_CHANNEL_ID,
        latitude=order["lat"],
        longitude=order["lon"]
    )

    await query.edit_message_text(order_text(order, "✅ Buyurtma tayyorlandi"))


async def delivery_start(query, context, order_id):
    order = get_order(order_id)

    if order["status"] != "ready":
        await query.answer("Buyurtma hali tayyor holatda emas.", show_alert=True)
        return

    update_order(order_id, status="on_the_way")

    await context.bot.send_message(
        chat_id=order["user_id"],
        text="🚚 Buyurtmangiz yo‘lga chiqdi. Kuryer tez orada yetib boradi."
    )

    await query.edit_message_text(order_text(order, "🚚 Buyurtma yo‘lga chiqdi"))


async def delivery_done(query, context, order_id):
    order = get_order(order_id)

    if order["status"] not in ["ready", "on_the_way"]:
        await query.answer("Bu buyurtmani yetkazildi qilib bo‘lmaydi.", show_alert=True)
        return

    update_order(order_id, status="completed", code_active=0)

    keyboard = [
        [
            InlineKeyboardButton("1 ⭐️", callback_data=f"rate:{order_id}:1"),
            InlineKeyboardButton("2 ⭐️", callback_data=f"rate:{order_id}:2"),
            InlineKeyboardButton("3 ⭐️", callback_data=f"rate:{order_id}:3"),
        ],
        [
            InlineKeyboardButton("4 ⭐️", callback_data=f"rate:{order_id}:4"),
            InlineKeyboardButton("5 ⭐️", callback_data=f"rate:{order_id}:5"),
        ]
    ]

    await context.bot.send_message(
        chat_id=order["user_id"],
        text="✅ Buyurtmangiz yetkazildi.\n\nIltimos, xizmatimizga baho bering:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    await query.edit_message_text(order_text(order, "✅ Buyurtma yakunlandi\n\nKod yopildi"))


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Siz admin emassiz.")
        return

    keyboard = [
        [InlineKeyboardButton("🍽 Menyuni boshqarish", callback_data="admin_menu")],
        [InlineKeyboardButton("➕ Ovqat qo‘shish", callback_data="admin_add_food")]
    ]

    await update.message.reply_text(
        "👨‍💼 Admin panel:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_admin_menu(query):
    foods = get_foods()

    text = "🍽 Menyu boshqaruvi:\n\n"
    keyboard = []

    for food in foods:
        status = "✅ Mavjud" if food["available"] else "❌ Tugagan"
        text += f"{food['id']}. {food['name']} — {format_price(food['price'])} so‘m — {status}\n"

        keyboard.append([
            InlineKeyboardButton(
                f"{food['name']} holatini o‘zgartirish",
                callback_data=f"admin_toggle:{food['id']}"
            )
        ])

    keyboard.append([InlineKeyboardButton("➕ Ovqat qo‘shish", callback_data="admin_add_food")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_toggle_food(query, food_id):
    if query.from_user.id not in ADMIN_IDS:
        return

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT available FROM foods WHERE id=?", (food_id,))
    food = cur.fetchone()

    if food:
        new_status = 0 if food["available"] else 1
        cur.execute("UPDATE foods SET available=? WHERE id=?", (new_status, food_id))

    conn.commit()
    conn.close()

    await show_admin_menu(query)


def main():
    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))

    app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    app.add_handler(MessageHandler(filters.LOCATION, location_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
