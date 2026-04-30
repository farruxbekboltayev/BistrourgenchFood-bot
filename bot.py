import os
import json
import math
import random
import calendar
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from telegram import (
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

ADMIN_IDS = [5702824058]

ADMIN_CHANNEL_ID = int(os.getenv("ADMIN_CHANNEL_ID"))
KITCHEN_CHANNEL_ID = int(os.getenv("KITCHEN_CHANNEL_ID"))
DELIVERY_CHANNEL_ID = int(os.getenv("DELIVERY_CHANNEL_ID"))

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@farrukh01uz")
CARD_NUMBER = os.getenv("CARD_NUMBER", "9860060138529692")

RESTAURANT_LAT = float(os.getenv("RESTAURANT_LAT", "41.5550893"))
RESTAURANT_LON = float(os.getenv("RESTAURANT_LON", "60.6290251"))

TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent"))


def db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS food_users (
        user_id BIGINT PRIMARY KEY,
        name TEXT,
        phone TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS food_foods (
        id SERIAL PRIMARY KEY,
        name TEXT,
        price INTEGER,
        available INTEGER DEFAULT 1,
        photo_id TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS food_orders (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        user_name TEXT,
        phone TEXT,
        items TEXT,
        food_total INTEGER DEFAULT 0,
        delivery_fee INTEGER DEFAULT 0,
        distance_km REAL DEFAULT 0,
        total INTEGER DEFAULT 0,
        code TEXT,
        code_active INTEGER DEFAULT 0,
        status TEXT,
        lat REAL,
        lon REAL,
        created_at TEXT,
        courier_id BIGINT,
        courier_name TEXT,
        courier_username TEXT,
        rating INTEGER,
        rating_comment TEXT,
        admin_msg_id BIGINT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS food_settings (
        id INTEGER PRIMARY KEY,
        work_start TEXT,
        work_end TEXT
    )
    """)

    cur.execute("SELECT COUNT(*) FROM food_settings")
    if cur.fetchone()["count"] == 0:
        cur.execute(
            "INSERT INTO food_settings (id, work_start, work_end) VALUES (1, '10:00', '22:00')"
        )

    cur.execute("SELECT COUNT(*) FROM food_foods")
    if cur.fetchone()["count"] == 0:
        foods = [
            ("Lavash", 35000, 1, None),
            ("Burger", 28000, 1, None),
            ("Pizza", 70000, 1, None),
            ("Cola", 12000, 1, None),
        ]
        cur.executemany(
            "INSERT INTO food_foods (name, price, available, photo_id) VALUES (%s, %s, %s, %s)",
            foods,
        )

    conn.commit()
    conn.close()


def now_iso():
    return datetime.now(TIMEZONE).isoformat()


def format_price(price):
    return f"{int(price):,}".replace(",", " ")


def calculate_distance_km(lat1, lon1, lat2, lon2):
    radius = 6371

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(radius * c, 2)


def get_delivery_fee(distance_km):
    if distance_km <= 3:
        return 10000
    if distance_km <= 6:
        return 15000
    if distance_km <= 10:
        return 20000
    return 30000


def generate_code():
    conn = db()
    cur = conn.cursor()

    while True:
        code = str(random.randint(1000, 9999))
        cur.execute(
            "SELECT id FROM food_orders WHERE code=%s AND code_active=1",
            (code,),
        )
        if not cur.fetchone():
            conn.close()
            return code


def get_settings():
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM food_settings WHERE id=%s", (1,))
    row = cur.fetchone()
    conn.close()
    return row


def work_time_text():
    row = get_settings()
    return f"{row['work_start']} – {row['work_end']}"


def is_work_time():
    row = get_settings()

    start_h, start_m = map(int, row["work_start"].split(":"))
    end_h, end_m = map(int, row["work_end"].split(":"))

    now = datetime.now(TIMEZONE).time()
    start = time(start_h, start_m)
    end = time(end_h, end_m)

    if start < end:
        return start <= now < end

    return now >= start or now < end


def get_foods(include_all=False):
    conn = db()
    cur = conn.cursor()

    if include_all:
        cur.execute("SELECT * FROM food_foods ORDER BY id ASC")
    else:
        cur.execute("SELECT * FROM food_foods WHERE available=1 ORDER BY id ASC")

    rows = cur.fetchall()
    conn.close()
    return rows


def get_food(food_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM food_foods WHERE id=%s", (food_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_order(order_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM food_orders WHERE id=%s", (order_id,))
    row = cur.fetchone()
    conn.close()
    return row


def update_order(order_id, status=None, code_active=None):
    conn = db()
    cur = conn.cursor()

    if status is not None:
        cur.execute(
            "UPDATE food_orders SET status=%s WHERE id=%s",
            (status, order_id),
        )

    if code_active is not None:
        cur.execute(
            "UPDATE food_orders SET code_active=%s WHERE id=%s",
            (code_active, order_id),
        )

    conn.commit()
    conn.close()


def order_text(order, title):
    items = json.loads(order["items"])

    text = f"{title}\n\n"
    text += f"📦 Buyurtma: #{order['id']}\n"
    text += f"👤 Ism: {order['user_name']}\n"
    text += f"📞 Telefon: {order['phone']}\n"

    if order["code"]:
        text += f"🔢 Kod: {order['code']}\n"

    if order["courier_name"]:
        courier = order["courier_name"]
        if order["courier_username"]:
            courier += f" (@{order['courier_username']})"
        text += f"🚚 Kuryer: {courier}\n"

    text += "\n🍔 Buyurtmalar:\n"

    for item in items:
        text += f"- {item['name']} x{item['qty']} — {format_price(item['subtotal'])} so‘m\n"

    text += f"\n🍽 Ovqatlar jami: {format_price(order['food_total'])} so‘m"
    text += f"\n📍 Masofa: {order['distance_km']} km"
    text += f"\n🚚 Yetkazib berish: {format_price(order['delivery_fee'])} so‘m"
    text += f"\n💰 Jami: {format_price(order['total'])} so‘m"

    if order["rating"]:
        text += f"\n\n⭐️ Baho: {order['rating']}"

    if order["rating_comment"]:
        text += f"\n💬 Izoh: {order['rating_comment']}"

    return text

# ================= USER START / REGISTER =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 🔥 har safar /start bosilganda eski step va vaqtinchalik ma’lumotlar tozalanadi
    context.user_data.clear()

    user_id = update.effective_user.id
    context.user_data.setdefault("cart", {})

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM food_users WHERE user_id=%s", (user_id,))
    user = cur.fetchone()
    conn.close()

    if user:
        await show_menu(update, context)
        return

    btn = KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True)
    keyboard = ReplyKeyboardMarkup([[btn]], resize_keyboard=True)

    await update.message.reply_text(
        "Assalomu alaykum! Buyurtma berish uchun telefon raqamingizni yuboring.",
        reply_markup=keyboard,
    )


async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    context.user_data["phone"] = contact.phone_number
    context.user_data["step"] = "waiting_name"

    await update.message.reply_text(
        "Ismingizni yozing:",
        reply_markup=ReplyKeyboardRemove(),
    )


# ================= MENU =================

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    foods = get_foods()
    keyboard = []

    if not foods:
        text = "🍽 Hozircha menyuda ovqat yo‘q."
    else:
        text = "🍽 Menyu:\n\nKerakli ovqatni tanlang."

        for food in foods:
            keyboard.append([
                InlineKeyboardButton(
                    f"{food['name']} — {format_price(food['price'])} so‘m",
                    callback_data=f"food:{food['id']}",
                )
            ])

        keyboard.append([InlineKeyboardButton("🛒 Savatcha", callback_data="cart")])

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        )


async def show_food_quantity(query, context, food_id):
    food = get_food(food_id)

    if not food:
        await query.answer("Ovqat topilmadi.", show_alert=True)
        return

    qty = context.user_data["cart"].get(str(food_id), 0)

    keyboard = [
        [
            InlineKeyboardButton("➖", callback_data=f"minus:{food_id}"),
            InlineKeyboardButton("➕", callback_data=f"plus:{food_id}"),
        ],
        [InlineKeyboardButton("🛒 Savatcha", callback_data="cart")],
        [InlineKeyboardButton("⬅️ Menyu", callback_data="menu")],
    ]

    caption = (
        f"🍔 {food['name']}\n"
        f"Narxi: {format_price(food['price'])} so‘m\n\n"
        f"Soni: {qty} ta"
    )

    if food["photo_id"]:
        await query.message.reply_photo(
            photo=food["photo_id"],
            caption=caption,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        try:
            await query.delete_message()
        except Exception:
            pass
    else:
        await query.edit_message_text(
            caption,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def show_cart(query, context):
    cart = context.user_data.get("cart", {})

    if not cart:
        await query.edit_message_text(
            "🛒 Savatcha bo‘sh.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Menyu", callback_data="menu")]
            ]),
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

    text += f"\n🍽 Ovqatlar jami: {format_price(total)} so‘m"

    keyboard = [
        [InlineKeyboardButton("✅ Buyurtma berish", callback_data="checkout")],
        [InlineKeyboardButton("⬅️ Menyu", callback_data="menu")],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ================= TEXT HANDLER =================

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    step = context.user_data.get("step")

    if text == "🍽 Yana buyurtma berish":
        context.user_data["cart"] = {}
        await show_menu(update, context)
        return

    # 🔹 Ism kiritish
    if step == "waiting_name":
        phone = context.user_data.get("phone")

        conn = db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO food_users (user_id, name, phone)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id)
            DO UPDATE SET name=EXCLUDED.name, phone=EXCLUDED.phone
            """,
            (user_id, text, phone),
        )
        conn.commit()
        conn.close()

        context.user_data["step"] = None
        context.user_data["cart"] = {}

        await update.message.reply_text(f"Rahmat, {text}!")
        await show_menu(update, context)
        return

    # 🔹 Izoh yozish (ratingdan keyin)
    if step == "waiting_comment":
        order_id = context.user_data.get("rating_order_id")

        conn = db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE food_orders SET rating_comment=%s WHERE id=%s",
            (text, order_id),
        )
        conn.commit()
        conn.close()

        context.user_data["step"] = None

        reply_keyboard = ReplyKeyboardMarkup(
            [["🍽 Yana buyurtma berish"]],
            resize_keyboard=True,
        )

        await update.message.reply_text(
            "🙏 Rahmat! Izohingiz qabul qilindi.",
            reply_markup=reply_keyboard,
        )
        return

    await update.message.reply_text("Menyu uchun /start bosing.")

# ================= PHOTO HANDLER FOR ADMIN ADD FOOD =================

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step")
    user_id = update.effective_user.id

    if step != "admin_add_photo":
        return

    if user_id not in ADMIN_IDS:
        return

    photo_id = update.message.photo[-1].file_id
    name = context.user_data["new_food_name"]
    price = context.user_data["new_food_price"]

    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO food_foods (name, price, available, photo_id) VALUES (%s, %s, 1, %s)",
        (name, price, photo_id),
    )
    conn.commit()
    conn.close()

    context.user_data["step"] = None

    await update.message.reply_text("✅ Ovqat rasm bilan menyuga qo‘shildi.")
    await admin_panel(update, context)


# ================= LOCATION / REVIEW =================

async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("step") != "waiting_location":
        return

    user_id = update.effective_user.id
    cart = context.user_data.get("cart", {})
    loc = update.message.location

    if not cart:
        await update.message.reply_text(
            "Savatchangiz bo‘sh.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM food_users WHERE user_id=%s", (user_id,))
    user = cur.fetchone()

    if not user:
        conn.close()
        await update.message.reply_text("Iltimos, /start bosib qayta ro‘yxatdan o‘ting.")
        return

    items = []
    food_total = 0

    for food_id, qty in cart.items():
        food = get_food(int(food_id))
        if not food:
            continue

        subtotal = food["price"] * qty
        food_total += subtotal

        items.append({
            "id": food["id"],
            "name": food["name"],
            "qty": qty,
            "price": food["price"],
            "subtotal": subtotal,
        })

    distance_km = calculate_distance_km(
        RESTAURANT_LAT,
        RESTAURANT_LON,
        loc.latitude,
        loc.longitude,
    )

    delivery_fee = get_delivery_fee(distance_km)
    total = food_total + delivery_fee

    cur.execute("""
        INSERT INTO food_orders
        (user_id, user_name, phone, items, food_total, delivery_fee, distance_km, total,
         code, code_active, status, lat, lon, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, 0, %s, %s, %s, %s)
        RETURNING id
    """, (
        user_id,
        user["name"],
        user["phone"],
        json.dumps(items, ensure_ascii=False),
        food_total,
        delivery_fee,
        distance_km,
        total,
        "pending_review",
        loc.latitude,
        loc.longitude,
        now_iso(),
    ))

    order_id = cur.fetchone()["id"]
    conn.commit()
    conn.close()

    context.user_data["step"] = None

    await update.message.reply_text(
        "📍 Lokatsiya qabul qilindi.",
        reply_markup=ReplyKeyboardRemove()
    )

    await send_review_message_from_message(update, order_id)


async def send_review_message_from_message(update, order_id):
    order = get_order(order_id)

    text = order_text(
        order,
        "📋 Buyurtmani tekshiring\n\n📍 Manzil: Siz yuborgan lokatsiya qabul qilindi",
    )

    text += "\n\nAgar hammasi to‘g‘ri bo‘lsa, tasdiqlang."

    keyboard = [
        [InlineKeyboardButton("✅ Tasdiqlash va to‘lovga o‘tish", callback_data=f"confirm_order:{order_id}")],
        [InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"edit_menu:{order_id}")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data=f"cancel:{order_id}")],
    ]

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def send_review_message(query, order_id):
    order = get_order(order_id)

    text = order_text(
        order,
        "📋 Buyurtmani tekshiring\n\n📍 Manzil: Siz yuborgan lokatsiya qabul qilindi",
    )

    text += "\n\nAgar hammasi to‘g‘ri bo‘lsa, tasdiqlang."

    keyboard = [
        [InlineKeyboardButton("✅ Tasdiqlash va to‘lovga o‘tish", callback_data=f"confirm_order:{order_id}")],
        [InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"edit_menu:{order_id}")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data=f"cancel:{order_id}")],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ================= CALLBACK HANDLER =================

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
        if not is_work_time():
           await query.message.reply_text(
            f"⏰ Hozir buyurtma qabul qilinmaydi.\n\n"
            f"Ish vaqti: {work_time_text()}"
        )
        return

        if not cart:
            await query.edit_message_text("Savatcha bo‘sh.")
            return

        btn = KeyboardButton("📍 Lokatsiya yuborish", request_location=True)
        keyboard = ReplyKeyboardMarkup([[btn]], resize_keyboard=True)

        context.user_data["step"] = "waiting_location"

        await query.message.reply_text(
            "Buyurtmani yakunlash uchun lokatsiyangizni yuboring.",
            reply_markup=keyboard,
        )

    elif data.startswith("confirm_order:"):
        await confirm_order(query, context, int(data.split(":")[1]))

    elif data.startswith("paid_by_user:"):
        await paid_by_user(query, context, int(data.split(":")[1]))

    elif data.startswith("edit_menu:"):
        order_id = int(data.split(":")[1])

        keyboard = [
            [InlineKeyboardButton("👤 Ismni tahrirlash", callback_data=f"edit_name:{order_id}")],
            [InlineKeyboardButton("📞 Telefonni tahrirlash", callback_data=f"edit_phone:{order_id}")],
            [InlineKeyboardButton("🍔 Buyurtmalarni tahrirlash", callback_data=f"edit_order:{order_id}")],
            [InlineKeyboardButton("⬅️ Orqaga", callback_data=f"back_review:{order_id}")],
        ]

        await query.edit_message_text(
            "✏️ Nimani tahrirlaysiz?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("edit_name:"):
        order_id = int(data.split(":")[1])
        order = get_order(order_id)

        if order["status"] not in ["pending_review", "payment_waiting"]:
            await query.answer("Bu buyurtmani endi tahrirlab bo‘lmaydi.", show_alert=True)
            return

        context.user_data["step"] = "edit_name"
        context.user_data["edit_order_id"] = order_id
        await query.message.reply_text("Yangi ismni yozing:")

    elif data.startswith("edit_phone:"):
        order_id = int(data.split(":")[1])
        order = get_order(order_id)

        if order["status"] not in ["pending_review", "payment_waiting"]:
            await query.answer("Bu buyurtmani endi tahrirlab bo‘lmaydi.", show_alert=True)
            return

        context.user_data["step"] = "edit_phone"
        context.user_data["edit_order_id"] = order_id
        await query.message.reply_text("Yangi telefon raqamni yozing:")

    elif data.startswith("edit_order:"):
        await edit_order(query, context, int(data.split(":")[1]), update)

    elif data.startswith("back_review:"):
        await send_review_message(query, int(data.split(":")[1]))

    elif data.startswith("cancel:"):
        await cancel_question(query, int(data.split(":")[1]))

    elif data.startswith("confirm_cancel:"):
        await confirm_cancel(query, context, int(data.split(":")[1]))

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
        await save_rating(query, context, int(data.split(":")[1]), int(data.split(":")[2]))

    elif data.startswith("skip_comment:"):
        await skip_comment(query, context, int(data.split(":")[1]))

    elif data == "admin_menu":
        await show_admin_menu(query)

    elif data.startswith("admin_food:"):
        await show_admin_food_settings(query, int(data.split(":")[1]))

    elif data == "admin_add_food":
        if query.from_user.id not in ADMIN_IDS:
            return

        context.user_data["step"] = "admin_add_name"

        await query.message.reply_text(
            "Yangi ovqat nomini yozing:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_back_main")]
            ])
        )

    elif data == "admin_skip_photo":
        if query.from_user.id not in ADMIN_IDS:
            return

        name = context.user_data["new_food_name"]
        price = context.user_data["new_food_price"]

        conn = db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO food_foods (name, price, available, photo_id) VALUES (%s, %s, 1, NULL)",
            (name, price),
        )
        conn.commit()
        conn.close()

        context.user_data["step"] = None
        await query.edit_message_text("✅ Ovqat rasmsiz menyuga qo‘shildi.")

    elif data.startswith("admin_toggle:"):
        await admin_toggle_food(query, int(data.split(":")[1]))

    elif data.startswith("admin_edit_price:"):
        food_id = int(data.split(":")[1])
        context.user_data["step"] = "admin_edit_price"
        context.user_data["edit_food_id"] = food_id

        await query.message.reply_text(
            "Yangi narxni yozing. Masalan: 45000",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Orqaga", callback_data=f"admin_food:{food_id}")]
            ])
        )

    elif data.startswith("admin_delete_food:"):
        food_id = int(data.split(":")[1])

        await query.edit_message_text(
            "❗ Rostdan ham bu ovqatni o‘chirmoqchimisiz?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Ha, o‘chirish", callback_data=f"admin_confirm_delete:{food_id}")],
                [InlineKeyboardButton("❌ Yo‘q", callback_data=f"admin_food:{food_id}")]
            ])
        )

    elif data.startswith("admin_confirm_delete:"):
        food_id = int(data.split(":")[1])

        conn = db()
        cur = conn.cursor()
        cur.execute("DELETE FROM food_foods WHERE id=%s", (food_id,))
        conn.commit()
        conn.close()

        await query.edit_message_text("🗑 Ovqat menyudan o‘chirildi.")

    elif data == "admin_work_time":
        if query.from_user.id not in ADMIN_IDS:
            return

        context.user_data["step"] = "admin_work_time"

        await query.message.reply_text(
            f"Hozirgi ish vaqti: {work_time_text()}\n\n"
            "Yangi vaqtni yozing. Masalan: 09:00-23:00",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_back_main")]
            ])
        )

    elif data == "admin_back_main":
        context.user_data["step"] = None
        await query.edit_message_text("👨‍💼 Admin panel")
        await query.message.reply_text(
            "Kerakli bo‘limni tanlang:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🍽 Menyuni boshqarish", callback_data="admin_menu")],
                [InlineKeyboardButton("➕ Ovqat qo‘shish", callback_data="admin_add_food")],
                [InlineKeyboardButton("⏰ Ish vaqtini sozlash", callback_data="admin_work_time")],
                [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats")],
            ])
        )

    elif data == "admin_stats":
        await show_stats_menu(query)

    elif data.startswith("stats:"):
        _, period, offset = data.split(":")
        await show_stats(query, period, int(offset))

# ================= TEXT HANDLER CONTINUATION FOR ADMIN =================
# DIQQAT: agar 2-qismdagi text_handler ichida admin step'lar bo‘lmasa,
# quyidagi text_handler'ni 2-qismdagi eski text_handler o‘rniga to‘liq almashtiring.

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    step = context.user_data.get("step")

    if text == "🍽 Yana buyurtma berish":
        context.user_data["cart"] = {}
        await show_menu(update, context)
        return

    if step == "waiting_name":
        phone = context.user_data.get("phone")

        conn = db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO food_users (user_id, name, phone)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id)
            DO UPDATE SET name=EXCLUDED.name, phone=EXCLUDED.phone
            """,
            (user_id, text, phone),
        )
        conn.commit()
        conn.close()

        context.user_data["step"] = None
        context.user_data["cart"] = {}

        await update.message.reply_text(f"Rahmat, {text}!")
        await show_menu(update, context)
        return

    if step == "edit_name":
        order_id = context.user_data["edit_order_id"]

        conn = db()
        cur = conn.cursor()
        cur.execute("UPDATE food_orders SET user_name=%s WHERE id=%s", (text, order_id))
        conn.commit()
        conn.close()

        context.user_data["step"] = None
        await update.message.reply_text("✅ Ism yangilandi.")
        await send_review_message_from_message(update, order_id)
        return

    if step == "edit_phone":
        order_id = context.user_data["edit_order_id"]

        conn = db()
        cur = conn.cursor()
        cur.execute("UPDATE food_orders SET phone=%s WHERE id=%s", (text, order_id))
        conn.commit()
        conn.close()

        context.user_data["step"] = None
        await update.message.reply_text("✅ Telefon raqam yangilandi.")
        await send_review_message_from_message(update, order_id)
        return

    if step == "waiting_comment":
        order_id = context.user_data.get("rating_order_id")

        conn = db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE food_orders SET rating_comment=%s WHERE id=%s",
            (text, order_id),
        )
        conn.commit()
        conn.close()

        order = get_order(order_id)

        if order["admin_msg_id"]:
            try:
                await context.bot.edit_message_text(
                    chat_id=ADMIN_CHANNEL_ID,
                    message_id=order["admin_msg_id"],
                    text=order_text(order, "✅ Buyurtma yetkazildi\n\nKod yopildi"),
                )
            except Exception:
                pass

        context.user_data["step"] = None

        reply_keyboard = ReplyKeyboardMarkup(
            [["🍽 Yana buyurtma berish"]],
            resize_keyboard=True,
        )

        await update.message.reply_text(
            "🙏 Rahmat! Izohingiz qabul qilindi.",
            reply_markup=reply_keyboard,
        )
        return

    if step == "admin_add_name":
        if user_id not in ADMIN_IDS:
            return

        context.user_data["new_food_name"] = text
        context.user_data["step"] = "admin_add_price"

        await update.message.reply_text(
            "Narxini yozing. Masalan: 35000",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_back_main")]
            ])
        )
        return

    if step == "admin_add_price":
        if user_id not in ADMIN_IDS:
            return

        if not text.isdigit():
            await update.message.reply_text("Narx faqat raqam bo‘lishi kerak.")
            return

        context.user_data["new_food_price"] = int(text)
        context.user_data["step"] = "admin_add_photo"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭ Rasmsiz qo‘shish", callback_data="admin_skip_photo")],
            [InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_back_main")]
        ])

        await update.message.reply_text(
            "Endi ovqat rasmini yuboring yoki rasmsiz qo‘shing.",
            reply_markup=keyboard,
        )
        return

    if step == "admin_edit_price":
        if user_id not in ADMIN_IDS:
            return

        if not text.isdigit():
            await update.message.reply_text("Narx faqat raqam bo‘lishi kerak.")
            return

        food_id = context.user_data["edit_food_id"]
        new_price = int(text)

        conn = db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE food_foods SET price=%s WHERE id=%s",
            (new_price, food_id)
        )
        conn.commit()
        conn.close()

        context.user_data["step"] = None

        await update.message.reply_text(
            f"✅ Narx yangilandi: {format_price(new_price)} so‘m"
        )
        return

    if step == "admin_work_time":
        if user_id not in ADMIN_IDS:
            return

        try:
            start_time_text, end_time_text = text.replace(" ", "").split("-")
            datetime.strptime(start_time_text, "%H:%M")
            datetime.strptime(end_time_text, "%H:%M")

            conn = db()
            cur = conn.cursor()
            cur.execute(
                "UPDATE food_settings SET work_start=%s, work_end=%s WHERE id=%s",
                (start_time_text, end_time_text, 1),
            )
            conn.commit()
            conn.close()

            context.user_data["step"] = None
            await update.message.reply_text(
                f"✅ Ish vaqti yangilandi: {start_time_text} – {end_time_text}"
            )
            await admin_panel(update, context)
        except Exception:
            await update.message.reply_text("Noto‘g‘ri format. Masalan: 09:00-23:00")
        return

    await update.message.reply_text("Menyu uchun /start bosing.")


# ================= ORDER FLOW =================

async def confirm_order(query, context, order_id):
    order = get_order(order_id)

    if order["status"] != "pending_review":
        await query.answer("Bu buyurtma allaqachon qayta ishlangan.", show_alert=True)
        return

    code = generate_code()

    conn = db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE food_orders SET status=%s, code=%s, code_active=1 WHERE id=%s",
        ("payment_waiting", code, order_id),
    )
    conn.commit()
    conn.close()

    order = get_order(order_id)

    text = f"""
💳 To‘lov ma’lumotlari

📦 Buyurtma: #{order_id}
🔢 Tasdiqlash kodi: {code}

🍽 Ovqatlar jami: {format_price(order['food_total'])} so‘m
🚚 Yetkazib berish: {format_price(order['delivery_fee'])} so‘m
💰 Jami summa: {format_price(order['total'])} so‘m

💳 Karta: {CARD_NUMBER}

Pul o‘tkazayotganda izoh qismiga shu kodni yozing:
{code}
"""

    keyboard = [
        [InlineKeyboardButton("✅ To‘lov qildim", callback_data=f"paid_by_user:{order_id}")]
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    await send_to_admin(context, order_id)


async def paid_by_user(query, context, order_id):
    order = get_order(order_id)

    await query.answer("✅ Admin tekshiradi.", show_alert=True)

    await query.edit_message_text(
        order_text(
            order,
            "✅ To‘lov qildim deb belgilandi\n\nAdmin to‘lovni tekshiradi"
        )
    )

    if order["admin_msg_id"]:
        keyboard = [
            [InlineKeyboardButton("✅ To‘lov tasdiqlandi", callback_data=f"admin_paid:{order_id}")],
            [InlineKeyboardButton("❌ To‘lov tasdiqlanmadi", callback_data=f"admin_not_paid:{order_id}")],
        ]

        try:
            await context.bot.edit_message_text(
                chat_id=ADMIN_CHANNEL_ID,
                message_id=order["admin_msg_id"],
                text=order_text(
                    order,
                    "🆕 Yangi buyurtma\n\nHolat: ⏳ To‘lov kutilmoqda\n\n💳 Mijoz: To‘lov qildim deb belgiladi",
                ),
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception:
            pass


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
        "✏️ Buyurtmalarni tahrirlashingiz mumkin. Menyudan kerakli o‘zgarishlarni qiling."
    )

    await show_menu(update, context)


async def cancel_question(query, order_id):
    keyboard = [
        [InlineKeyboardButton("✅ Ha, bekor qilaman", callback_data=f"confirm_cancel:{order_id}")],
        [InlineKeyboardButton("❌ Yo‘q", callback_data=f"back_review:{order_id}")],
    ]

    await query.edit_message_text(
        "❗ Rostdan ham buyurtmani bekor qilmoqchimisiz?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def confirm_cancel(query, context, order_id):
    order = get_order(order_id)

    if order["status"] not in ["pending_review", "payment_waiting"]:
        await query.answer("Bu buyurtmani endi bekor qilib bo‘lmaydi.", show_alert=True)
        return

    update_order(order_id, status="cancelled", code_active=0)

    await query.edit_message_text("❌ Buyurtmangiz bekor qilindi.")

    if order["admin_msg_id"]:
        try:
            await context.bot.edit_message_text(
                chat_id=ADMIN_CHANNEL_ID,
                message_id=order["admin_msg_id"],
                text=order_text(order, "❌ Buyurtma mijoz tomonidan bekor qilindi"),
            )
        except Exception:
            pass


async def send_to_admin(context, order_id):
    order = get_order(order_id)

    keyboard = [
        [InlineKeyboardButton("✅ To‘lov tasdiqlandi", callback_data=f"admin_paid:{order_id}")],
        [InlineKeyboardButton("❌ To‘lov tasdiqlanmadi", callback_data=f"admin_not_paid:{order_id}")],
    ]

    msg = await context.bot.send_message(
        chat_id=ADMIN_CHANNEL_ID,
        text=order_text(order, "🆕 Yangi buyurtma\n\nHolat: ⏳ To‘lov kutilmoqda"),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    conn = db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE food_orders SET admin_msg_id=%s WHERE id=%s",
        (msg.message_id, order_id),
    )
    conn.commit()
    conn.close()

# ================= ADMIN PAYMENT / KITCHEN / DELIVERY / RATING =================

async def admin_paid(query, context, order_id):
    order = get_order(order_id)

    if order["status"] != "payment_waiting":
        await query.answer("Bu buyurtma to‘lov kutish holatida emas.", show_alert=True)
        return

    update_order(order_id, status="paid")
    order = get_order(order_id)

    await context.bot.send_message(
        chat_id=order["user_id"],
        text="✅ To‘lovingiz tasdiqlandi. Buyurtmangiz tayyorlanmoqda.",
    )

    keyboard = [
        [InlineKeyboardButton("✅ Buyurtma tayyorlandi", callback_data=f"kitchen_ready:{order_id}")]
    ]

    await context.bot.send_message(
        chat_id=KITCHEN_CHANNEL_ID,
        text=order_text(order, "👨‍🍳 Oshpazlar uchun buyurtma\n\nHolat: 🍳 Tayyorlanmoqda"),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    await query.edit_message_text(order_text(order, "✅ To‘lov tasdiqlandi"))


async def admin_not_paid(query, context, order_id):
    order = get_order(order_id)

    update_order(order_id, status="payment_rejected")
    order = get_order(order_id)

    admin_link = f"https://t.me/{ADMIN_USERNAME.replace('@', '')}"

    await context.bot.send_message(
        chat_id=order["user_id"],
        text="❌ To‘lovingiz tasdiqlanmadi.\n\nIltimos, admin bilan bog‘laning.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👨‍💼 Admin bilan bog‘lanish", url=admin_link)]
        ]),
    )

    await query.edit_message_text(order_text(order, "❌ To‘lov tasdiqlanmadi"))


async def kitchen_ready(query, context, order_id):
    order = get_order(order_id)

    if order["status"] != "paid":
        await query.answer("Avval to‘lov tasdiqlanishi kerak.", show_alert=True)
        return

    update_order(order_id, status="ready")
    order = get_order(order_id)

    await context.bot.send_message(
        chat_id=order["user_id"],
        text="🍔 Buyurtmangiz tayyor bo‘ldi. Tez orada kuryer yo‘lga chiqadi.",
    )

    keyboard = [
        [InlineKeyboardButton("🚚 Yo‘lga chiqdi", callback_data=f"delivery_start:{order_id}")]
    ]

    await context.bot.send_message(
        chat_id=DELIVERY_CHANNEL_ID,
        text=order_text(
            order,
            "🚚 Kuryerlar uchun buyurtma\n\nHolat: ✅ Tayyor\n📍 Lokatsiya pastda yuborilgan",
        ),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

    await context.bot.send_location(
        chat_id=DELIVERY_CHANNEL_ID,
        latitude=order["lat"],
        longitude=order["lon"],
    )

    await query.edit_message_text(order_text(order, "✅ Buyurtma tayyorlandi"))


async def delivery_start(query, context, order_id):
    order = get_order(order_id)

    if order["status"] != "ready":
        await query.answer(
            "Bu buyurtmani boshqa kuryer olgan yoki hali tayyor emas.",
            show_alert=True,
        )
        return

    courier_id = query.from_user.id
    courier_name = query.from_user.full_name
    courier_username = query.from_user.username or ""

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        UPDATE food_orders
        SET status=%s, courier_id=%s, courier_name=%s, courier_username=%s
        WHERE id=%s
    """, ("on_the_way", courier_id, courier_name, courier_username, order_id))
    conn.commit()
    conn.close()

    order = get_order(order_id)

    await context.bot.send_message(
        chat_id=order["user_id"],
        text="🚚 Buyurtmangiz yo‘lga chiqdi. Kuryer tez orada yetib boradi.",
    )

    keyboard = [
        [InlineKeyboardButton("✅ Yetkazildi", callback_data=f"delivery_done:{order_id}")]
    ]

    await query.edit_message_text(
        order_text(order, "🚚 Buyurtma yo‘lga chiqdi"),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def delivery_done(query, context, order_id):
    order = get_order(order_id)

    if order["courier_id"] and order["courier_id"] != query.from_user.id:
        await query.answer(
            "Bu buyurtmani faqat olgan kuryer yakunlay oladi.",
            show_alert=True,
        )
        return

    if order["status"] != "on_the_way":
        await query.answer("Avval 'Yo‘lga chiqdi' bosilishi kerak.", show_alert=True)
        return

    update_order(order_id, status="completed", code_active=0)
    order = get_order(order_id)

    rating_keyboard = [
        [
            InlineKeyboardButton("1 ⭐️", callback_data=f"rate:{order_id}:1"),
            InlineKeyboardButton("2 ⭐️", callback_data=f"rate:{order_id}:2"),
            InlineKeyboardButton("3 ⭐️", callback_data=f"rate:{order_id}:3"),
        ],
        [
            InlineKeyboardButton("4 ⭐️", callback_data=f"rate:{order_id}:4"),
            InlineKeyboardButton("5 ⭐️", callback_data=f"rate:{order_id}:5"),
        ],
    ]

    reply_keyboard = ReplyKeyboardMarkup(
        [["🍽 Yana buyurtma berish"]],
        resize_keyboard=True,
    )

    await context.bot.send_message(
        chat_id=order["user_id"],
        text="✅ Buyurtmangiz yetkazildi.",
        reply_markup=reply_keyboard,
    )

    await context.bot.send_message(
        chat_id=order["user_id"],
        text="Iltimos, xizmatimizga baho bering:",
        reply_markup=InlineKeyboardMarkup(rating_keyboard),
    )

    await query.edit_message_text(
        order_text(order, "✅ Buyurtma yetkazildi\n\nKod yopildi")
    )

    if order["admin_msg_id"]:
        try:
            await context.bot.edit_message_text(
                chat_id=ADMIN_CHANNEL_ID,
                message_id=order["admin_msg_id"],
                text=order_text(order, "✅ Buyurtma yetkazildi\n\nKod yopildi"),
            )
        except Exception:
            pass


async def save_rating(query, context, order_id, rating):
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE food_orders SET rating=%s WHERE id=%s",
        (rating, order_id),
    )
    conn.commit()
    conn.close()

    context.user_data["step"] = "waiting_comment"
    context.user_data["rating_order_id"] = order_id

    keyboard = [
        [InlineKeyboardButton("⏭ O‘tkazib yuborish", callback_data=f"skip_comment:{order_id}")]
    ]

    await query.edit_message_text(
        f"Rahmat! Siz {rating} ⭐️ baho berdingiz.\n\n💬 Izoh yozing yoki o‘tkazib yuboring:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def skip_comment(query, context, order_id):
    context.user_data["step"] = None

    order = get_order(order_id)

    if order["admin_msg_id"]:
        try:
            await context.bot.edit_message_text(
                chat_id=ADMIN_CHANNEL_ID,
                message_id=order["admin_msg_id"],
                text=order_text(
                    order,
                    "✅ Buyurtma yetkazildi\n\nKod yopildi\n💬 Izoh: qoldirilmadi"
                ),
            )
        except Exception:
            pass

    await query.edit_message_text("🙏 Rahmat! Baho uchun minnatdormiz.")

# ================= ADMIN PANEL =================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Siz admin emassiz.")
        return

    keyboard = [
        [InlineKeyboardButton("🍽 Menyuni boshqarish", callback_data="admin_menu")],
        [InlineKeyboardButton("➕ Ovqat qo‘shish", callback_data="admin_add_food")],
        [InlineKeyboardButton("⏰ Ish vaqtini sozlash", callback_data="admin_work_time")],
        [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats")],
    ]

    await update.message.reply_text(
        "👨‍💼 Admin panel\n\nKerakli bo‘limni tanlang:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_admin_menu(query):
    foods = get_foods(include_all=True)

    text = "🍽 Menyu boshqaruvi:\n\n"
    keyboard = []

    for food in foods:
        status = "✅ Mavjud" if food["available"] else "❌ Tugagan"
        text += f"{food['id']}. {food['name']} — {format_price(food['price'])} so‘m — {status}\n"

        keyboard.append([
            InlineKeyboardButton(
                f"⚙️ {food['name']}",
                callback_data=f"admin_food:{food['id']}",
            )
        ])

    keyboard.append([InlineKeyboardButton("➕ Ovqat qo‘shish", callback_data="admin_add_food")])
    keyboard.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_back_main")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_admin_food_settings(query, food_id):
    food = get_food(food_id)

    if not food:
        await query.answer("Ovqat topilmadi.", show_alert=True)
        return

    status = "✅ Mavjud" if food["available"] else "❌ Tugagan"

    text = f"""
🍽 Ovqat sozlamalari

Nomi: {food['name']}
Narxi: {format_price(food['price'])} so‘m
Holati: {status}
"""

    keyboard = [
        [InlineKeyboardButton("✅ / ❌ Holatini o‘zgartirish", callback_data=f"admin_toggle:{food_id}")],
        [InlineKeyboardButton("✏️ Narxni o‘zgartirish", callback_data=f"admin_edit_price:{food_id}")],
        [InlineKeyboardButton("🗑 O‘chirish", callback_data=f"admin_delete_food:{food_id}")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_menu")],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def admin_toggle_food(query, food_id):
    if query.from_user.id not in ADMIN_IDS:
        return

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT available FROM food_foods WHERE id=%s", (food_id,))
    food = cur.fetchone()

    if food:
        new_status = 0 if food["available"] else 1
        cur.execute(
            "UPDATE food_foods SET available=%s WHERE id=%s",
            (new_status, food_id),
        )

    conn.commit()
    conn.close()

    await show_admin_food_settings(query, food_id)


# ================= STATISTICS =================

async def show_stats_menu(query):
    if query.from_user.id not in ADMIN_IDS:
        return

    keyboard = [
        [InlineKeyboardButton("📅 Kunlik", callback_data="stats:day:0")],
        [InlineKeyboardButton("🗓 Haftalik", callback_data="stats:week:0")],
        [InlineKeyboardButton("📆 Oylik", callback_data="stats:month:0")],
        [InlineKeyboardButton("📈 Yillik", callback_data="stats:year:0")],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_back_main")],
    ]

    await query.edit_message_text(
        "📊 Statistika turini tanlang:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def get_period_range(period, offset):
    today = datetime.now(TIMEZONE).date()

    if period == "day":
        target = today + timedelta(days=offset)
        start = datetime.combine(target, time.min, tzinfo=TIMEZONE)
        end = datetime.combine(target, time.max, tzinfo=TIMEZONE)
        title = "📅 Kunlik statistika"
        nav = ("⬅️ Oldingi kun", "Keyingi kun ➡️")

    elif period == "week":
        monday = today - timedelta(days=today.weekday())
        target_monday = monday + timedelta(weeks=offset)
        target_sunday = target_monday + timedelta(days=6)

        start = datetime.combine(target_monday, time.min, tzinfo=TIMEZONE)
        end = datetime.combine(target_sunday, time.max, tzinfo=TIMEZONE)
        title = "🗓 Haftalik statistika"
        nav = ("⬅️ Oldingi hafta", "Keyingi hafta ➡️")

    elif period == "month":
        year = today.year
        month = today.month + offset

        while month < 1:
            month += 12
            year -= 1

        while month > 12:
            month -= 12
            year += 1

        last_day = calendar.monthrange(year, month)[1]

        start = datetime(year, month, 1, 0, 0, 0, tzinfo=TIMEZONE)
        end = datetime(year, month, last_day, 23, 59, 59, tzinfo=TIMEZONE)
        title = "📆 Oylik statistika"
        nav = ("⬅️ Oldingi oy", "Keyingi oy ➡️")

    else:
        year = today.year + offset
        start = datetime(year, 1, 1, 0, 0, 0, tzinfo=TIMEZONE)
        end = datetime(year, 12, 31, 23, 59, 59, tzinfo=TIMEZONE)
        title = "📈 Yillik statistika"
        nav = ("⬅️ Oldingi yil", "Keyingi yil ➡️")

    return start, end, title, nav


async def show_stats(query, period, offset):
    if query.from_user.id not in ADMIN_IDS:
        return

    start, end, title, nav = get_period_range(period, offset)

    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM food_orders WHERE created_at BETWEEN %s AND %s",
        (start.isoformat(), end.isoformat()),
    )
    rows = cur.fetchall()
    conn.close()

    total_orders = len(rows)
    completed = [r for r in rows if r["status"] == "completed"]
    cancelled = [r for r in rows if r["status"] == "cancelled"]
    rejected = [r for r in rows if r["status"] == "payment_rejected"]

    revenue = sum((r["total"] or 0) for r in completed)

    ratings = [r["rating"] for r in completed if r["rating"]]
    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else "Hali baho yo‘q"

    food_count = {}
    courier_count = {}

    for row in completed:
        try:
            items = json.loads(row["items"])
        except Exception:
            items = []

        for item in items:
            food_count[item["name"]] = food_count.get(item["name"], 0) + item["qty"]

        if row["courier_name"]:
            courier_count[row["courier_name"]] = courier_count.get(row["courier_name"], 0) + 1

    if food_count:
        foods_text = "\n".join(
            [f"- {name}: {qty} ta" for name, qty in sorted(food_count.items())]
        )
    else:
        foods_text = "Hali yo‘q"

    if courier_count:
        courier_text = "\n".join(
            [f"- {name}: {qty} ta" for name, qty in sorted(courier_count.items())]
        )
    else:
        courier_text = "Hali yo‘q"

    text = f"""
{title}
Davr: {start.date()} – {end.date()}

📦 Jami buyurtmalar: {total_orders}
✅ Yetkazilgan: {len(completed)}
❌ Bekor qilingan: {len(cancelled)}
💳 To‘lov tasdiqlanmagan: {len(rejected)}

💰 Jami tushum: {format_price(revenue)} so‘m
⭐️ O‘rtacha baho: {avg_rating}

🍔 Ovqatlar:
{foods_text}

🚚 Kuryerlar:
{courier_text}
"""

    keyboard = [
        [
            InlineKeyboardButton(nav[0], callback_data=f"stats:{period}:{offset - 1}"),
            InlineKeyboardButton(nav[1], callback_data=f"stats:{period}:{offset + 1}"),
        ],
        [InlineKeyboardButton("⬅️ Statistika menyusi", callback_data="admin_stats")],
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ================= RUN BOT =================

def main():
    if not TOKEN:
        raise ValueError("TOKEN Railway Variables ichida yo‘q")

    if not DATABASE_URL:
        raise ValueError("DATABASE_URL Railway Variables ichida yo‘q")

    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))

    app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    app.add_handler(MessageHandler(filters.LOCATION, location_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
