import asyncio
import logging
import os
import html
from datetime import datetime
from html import escape
from typing import Final, Any, Optional, List

# aiogram kutubxonalari
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, or_f
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton,
    Message, CallbackQuery, BotCommand, InlineKeyboardMarkup
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# Asinxron ma'lumotlar bazasi kutubxonasi
import aiosqlite
from dotenv import load_dotenv

# .env faylini yuklash
load_dotenv()

try:
    from groq import Groq
except ImportError:
    Groq = None

# ==========================================================================================
# 💎 PREMIUM KONFIGURATSIYA VA DIZAYN
# ==========================================================================================
class Assets:
    TOKEN: Final[str] = os.getenv("BOT_TOKEN", "")
    GROQ_KEY: Final[str] = os.getenv("GROQ_API_KEY", "")
    
    # KO'P ADMINLI TIZIM: .env faylda ADMIN_IDS=123,456 kabi yoziladi
    _admin_ids_str = os.getenv("ADMIN_IDS", "0")
    ADMIN_IDS: Final[List[int]] = [int(x.strip()) for x in _admin_ids_str.split(",") if x.strip().isdigit()]
    
    DB_NAME: Final[str] = os.getenv("DB_NAME", "database.db")

    # Dizayn chiziqlari
    D_LINE = "<b>━━━━━━━━━━━━━━━━━━━━━━━━━</b>"
    S_LINE = "<i>─────────────────────────</i>"
    HEADER = "🎓 <b>LOGOS PLATINUM ACADEMY</b>"

    # Menyular
    ICO_TEST = "📚 Testlar Bazasi"
    ICO_CHECK = "✍️ Test Topshirish"
    ICO_DAILY = "🔥 Kunlik Test"
    ICO_TOP = "🏆 Top 10 Reyting"
    ICO_AI = "🧠 AI Mentor (PRO)"
    ICO_HIS = "📊 Natijalar Tarixi"
    ICO_PROF = "👤 Mening Profilim"
    ICO_HELP = "🎧 Admin Bilan Aloqa"
    ICO_ADM = "⚙️ Admin Boshqaruvi"
    ICO_BACK = "🔙 Orqaga"
    ICO_HOME = "🏠 Bosh Menyu"

    # Admin Menyular
    ADM_ADD_TEST = "📝 Test Qo'shish"
    ADM_ADD_DAILY = "🌟 Kunlik Test Qo'shish"
    ADM_STATS = "📈 Umumiy Statistika"
    ADM_DAILY_STATS = "📊 Kunlik Statistika"
    ADM_DEL_TEST = "🗑 Test O'chirish"
    ADM_BROADCAST = "📢 Xabar Tarqatish"

    @staticmethod
    def progress_bar(perc: float) -> str:
        full = max(0, min(10, int(perc // 10)))
        empty = 10 - full
        return "🟩" * full + "⬜" * empty


logging.basicConfig(level=logging.INFO)
bot = Bot(token=Assets.TOKEN)
dp = Dispatcher(storage=MemoryStorage())

groq_client = Groq(api_key=Assets.GROQ_KEY) if Groq and Assets.GROQ_KEY else None

# ==========================================================================================
# 🗄 MUKAMMAL ASINXRON MA'LUMOTLAR BAZASI
# ==========================================================================================
class DB:
    @classmethod
    async def init_db(cls):
        async with aiosqlite.connect(Assets.DB_NAME) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA foreign_keys=ON;")

            await db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    uid INTEGER PRIMARY KEY,
                    fullname TEXT NOT NULL,
                    username TEXT,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS tests (
                    kod TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    javoblar TEXT NOT NULL,
                    file_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS results (
                    rid INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid INTEGER,
                    kod TEXT,
                    ball INTEGER,
                    total INTEGER,
                    perc REAL,
                    mistakes TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(uid) REFERENCES users(uid) ON DELETE CASCADE,
                    FOREIGN KEY(kod) REFERENCES tests(kod) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_results_uid ON results(uid);
                CREATE INDEX IF NOT EXISTS idx_results_kod ON results(kod);

                CREATE TABLE IF NOT EXISTS daily_tests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kod TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    javoblar TEXT NOT NULL,
                    file_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS daily_results (
                    uid INTEGER,
                    kod TEXT,
                    ball INTEGER,
                    total INTEGER,
                    perc REAL,
                    mistakes TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (uid, kod),
                    FOREIGN KEY(uid) REFERENCES users(uid) ON DELETE CASCADE
                );
            """)
            await db.commit()

    @classmethod
    async def fetch_one(cls, query: str, params: tuple = ()) -> Optional[dict]:
        async with aiosqlite.connect(Assets.DB_NAME) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    @classmethod
    async def fetch_all(cls, query: str, params: tuple = ()) -> List[dict]:
        async with aiosqlite.connect(Assets.DB_NAME) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    @classmethod
    async def execute(cls, query: str, params: tuple = ()) -> int:
        async with aiosqlite.connect(Assets.DB_NAME) as db:
            async with db.execute(query, params) as cursor:
                last_id = cursor.lastrowid
                await db.commit()
                return last_id

    @classmethod
    async def clear_daily_stats(cls):
        await cls.execute("DELETE FROM daily_results")
        await cls.execute("DELETE FROM daily_tests")


# ==========================================================================================
# 🧠 HOLATLAR (STATES)
# ==========================================================================================
class Form(StatesGroup):
    reg = State()
    check_code = State()
    solve_ans = State()
    daily_solve_ans = State()
    ai_chat = State()
    support = State()
    adm_reply = State()

    adm_add_kod = State()
    adm_add_title = State()
    adm_add_ans = State()
    adm_add_file = State()

    adm_add_daily_kod = State()
    adm_add_daily_title = State()
    adm_add_daily_ans = State()
    adm_add_daily_file = State()
    adm_broadcast = State()

# ==========================================================================================
# 🎨 FOYDALANUVCHI INTERFEYSI (UI)
# ==========================================================================================
class UI:
    @staticmethod
    def main_menu(user_id: int):
        b = ReplyKeyboardBuilder()
        b.row(KeyboardButton(text=Assets.ICO_TEST), KeyboardButton(text=Assets.ICO_CHECK))
        b.row(KeyboardButton(text=Assets.ICO_DAILY), KeyboardButton(text=Assets.ICO_TOP))
        b.row(KeyboardButton(text=Assets.ICO_HIS), KeyboardButton(text=Assets.ICO_PROF))
        b.row(KeyboardButton(text=Assets.ICO_AI), KeyboardButton(text=Assets.ICO_HELP))
        
        # Agar adminlardan biri bo'lsa
        if user_id in Assets.ADMIN_IDS:
            b.row(KeyboardButton(text=Assets.ICO_ADM))
            
        return b.as_markup(resize_keyboard=True)

    @staticmethod
    def admin_menu():
        b = ReplyKeyboardBuilder()
        b.row(KeyboardButton(text=Assets.ADM_ADD_TEST), KeyboardButton(text=Assets.ADM_ADD_DAILY))
        b.row(KeyboardButton(text=Assets.ADM_STATS), KeyboardButton(text=Assets.ADM_DAILY_STATS))
        b.row(KeyboardButton(text=Assets.ADM_DEL_TEST), KeyboardButton(text=Assets.ADM_BROADCAST))
        b.row(KeyboardButton(text=Assets.ICO_HOME))
        return b.as_markup(resize_keyboard=True)

    @staticmethod
    def back_btn():
        return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=Assets.ICO_BACK)]], resize_keyboard=True)

# ==========================================================================================
# YORDAMCHI FUNKSIYALAR
# ==========================================================================================
def fmt_dt(value: Optional[str]) -> str:
    return str(value)[:16].replace("T", " ") if value else "-"

def normalize_answers(text: str) -> str:
    return "".join((text or "").lower().split())

def score_answers(user_ans: str, correct_ans: str):
    u = normalize_answers(user_ans)
    t = normalize_answers(correct_ans)
    mistakes = []
    correct = 0

    for i in range(min(len(u), len(t))):
        if u[i] == t[i]:
            correct += 1
        else:
            mistakes.append(f"{i+1}{u[i].upper()}")

    return u, t, correct, mistakes

async def get_active_daily_test():
    return await DB.fetch_one("SELECT * FROM daily_tests ORDER BY id DESC LIMIT 1")

# ==========================================================================================
# MAJBURIY OBUNA
# ==========================================================================================
REQUIRED_CHANNELS = [
    {"name": "📢 Asosiy Kanal", "id": "@alo_math"},
]

async def is_subscribed(bot: Bot, user_id: int) -> bool:
    if user_id in Assets.ADMIN_IDS:
        return True
    
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel["id"], user_id=user_id)
            if member.status in ['left', 'kicked', 'banned']:
                return False
        except Exception:
            return False 
    return True

def get_subscription_keyboard():
    b = InlineKeyboardBuilder()
    for channel in REQUIRED_CHANNELS:
        url = f"https://t.me/{channel['id'].replace('@', '')}"
        b.row(InlineKeyboardButton(text=channel["name"], url=url))
    b.row(InlineKeyboardButton(text="✅ Obunani tasdiqlash", callback_data="check_subscription"))
    return b.as_markup()

# ==========================================================================================
# AVTOMATIK YO'NALTIRISH VA START
# ==========================================================================================
async def process_user_entry(message: Message, state: FSMContext, user_id: int, user_firstname: str):
    user = await DB.fetch_one("SELECT * FROM users WHERE uid=?", (user_id,))

    if not user:
        await state.set_state(Form.reg)
        text = (
            f"{Assets.HEADER}\n"
            f"{Assets.D_LINE}\n\n"
            f"👋 Assalomu alaykum, <b>{html.escape(user_firstname)}</b>!\n"
            f"Matematikadan maxsus test botiga xush kelibsiz.\n\n"
            f"✍️ <i>Iltimos, ism va familiyangizni to'liq kiriting:</i>\n\n"
            f"💡 <b>Namuna:</b> <i>Abdullayev Alisher</i>"
        )
        await message.answer(text, parse_mode="HTML")
    else:
        status_text = "Administrator 👑" if user_id in Assets.ADMIN_IDS else "Premium O'quvchi 💎"
        dashboard = (
            f"{Assets.HEADER}\n"
            f"{Assets.D_LINE}\n\n"
            f"👤 Foydalanuvchi: <b>{html.escape(user['fullname'])}</b>\n"
            f"🎖 Status: <b>{status_text}</b>\n\n"
            f"👇 <i>Quyidagi menyudan kerakli bo'limni tanlang:</i>"
        )
        await message.answer(dashboard, reply_markup=UI.main_menu(user_id), parse_mode="HTML")

@dp.message(or_f(Command("start"), F.text == Assets.ICO_HOME, F.text == Assets.ICO_BACK))
async def global_reset(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    if not await is_subscribed(bot, message.from_user.id):
        text = (
            f"🛑 <b>Majburiy Obuna</b>\n"
            f"{Assets.S_LINE}\n"
            f"Botdan foydalanish uchun rasmiy kanalga a'zo bo'lishingiz kerak."
        )
        return await message.answer(text, reply_markup=get_subscription_keyboard(), parse_mode="HTML")
    await process_user_entry(message, state, message.from_user.id, message.from_user.first_name)

@dp.callback_query(F.data == "check_subscription")
async def check_sub_handler(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not await is_subscribed(bot, call.from_user.id):
        return await call.answer("❌ Kanalga obuna bo'lmadingiz!", show_alert=True)
    await call.message.delete()
    await process_user_entry(call.message, state, call.from_user.id, call.from_user.first_name)

@dp.message(Form.reg)
async def registration_finish(message: Message, state: FSMContext):
    await DB.execute(
        "INSERT INTO users (uid, fullname, username) VALUES (?, ?, ?) ON CONFLICT(uid) DO UPDATE SET fullname=excluded.fullname",
        (message.from_user.id, message.text, message.from_user.username)
    )
    success_text = (
        f"✅ <b>Muvaffaqiyatli ro'yxatdan o'tdingiz!</b>\n\n"
        f"Hurmatli <b>{html.escape(message.text)}</b>, tizimdan foydalanishingiz mumkin."
    )
    await message.answer(success_text, parse_mode="HTML", reply_markup=UI.main_menu(message.from_user.id))
    await state.clear()

# ==========================================================================================
# 1. TESTLAR VA TOP 10 REYTING BO'LIMI
# ==========================================================================================
@dp.message(F.text == Assets.ICO_TOP)
async def top_10_users(message: Message):
    # Top 10 foydalanuvchilar to'plagan umumiy ballari bo'yicha
    query = """
        SELECT u.fullname, COUNT(r.rid) as tests_count, SUM(r.ball) as total_score
        FROM results r
        JOIN users u ON r.uid = u.uid
        GROUP BY u.uid
        ORDER BY total_score DESC
        LIMIT 10
    """
    top_users = await DB.fetch_all(query)
    
    if not top_users:
        return await message.answer("📭 Reyting hozircha bo'sh. Hech kim test ishlamagan.")
    
    msg = f"🏆 <b>TOP 10 FOYDALANUVCHILAR</b>\n{Assets.D_LINE}\n\n"
    for idx, user in enumerate(top_users, start=1):
        medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else "🎖"
        msg += f"{medal} <b>{escape(user['fullname'])}</b>\n"
        msg += f"└ 📈 Umumiy ball: <b>{user['total_score']}</b> | 📝 Testlar: {user['tests_count']} ta\n\n"
        
    await message.answer(msg, parse_mode="HTML")

@dp.message(F.text == Assets.ICO_TEST)
async def test_list(message: Message):
    tests = await DB.fetch_all("SELECT * FROM tests ORDER BY created_at DESC")
    if not tests: return await message.answer("📭 Hozircha testlar bazasi bo'sh.", parse_mode="HTML")

    res_text = f"📂 <b>MAVJUD TESTLAR BAZASI</b>\n{Assets.D_LINE}\n\n"
    for t in tests:
        res_text += (
            f"📘 <b>{escape(t['title'])}</b>\n"
            f"🔑 Kod: <code>{escape(t['kod'])}</code> | 🕒 {fmt_dt(t['created_at'])}\n"
            f"{Assets.S_LINE}\n"
        )
    await message.answer(res_text, parse_mode="HTML")

@dp.message(F.text == Assets.ICO_CHECK)
async def check_init(message: Message, state: FSMContext):
    await state.set_state(Form.check_code)
    await message.answer(
        "🆔 <b>TEST KODINI KIRITING</b>\n\nIltimos, yechmoqchi bo'lgan testingiz maxsus kodini yuboring:",
        reply_markup=UI.back_btn(), parse_mode="HTML"
    )

@dp.message(Form.check_code)
async def check_process(message: Message, state: FSMContext):
    test = await DB.fetch_one("SELECT * FROM tests WHERE kod=?", (message.text.strip(),))
    if not test:
        return await message.answer("🚫 Bunday kodli test mavjud emas! Qaytadan tekshirib kiriting.")

    await state.update_data(active_test=test)
    await state.set_state(Form.solve_ans)

    info = (
        f"📋 <b>TEST MA'LUMOTLARI</b>\n"
        f"{Assets.D_LINE}\n"
        f"📖 Fan: <b>{escape(test['title'])}</b>\n"
        f"🔢 Savollar: <b>{len(normalize_answers(test['javoblar']))} ta</b>\n"
        f"🔑 Kod: <code>{escape(test['kod'])}</code>\n"
        f"{Assets.S_LINE}\n"
        f"📥 <b>Javoblaringizni bitta xabarda yuboring:</b>\n(Masalan: <code>abcdabcd...</code>)"
    )

    if test["file_id"]:
        await message.answer_document(test["file_id"], caption=info, parse_mode="HTML")
    else:
        await message.answer(info, parse_mode="HTML")

@dp.message(Form.solve_ans)
async def test_logic(message: Message, state: FSMContext):
    data = await state.get_data()
    test = data.get("active_test")
    if not test:
        await state.clear()
        return await message.answer("⚠️ Xatolik yuz berdi. Boshqatan urinib ko'ring.")

    u_ans, t_ans, correct, mistakes = score_answers(message.text, test["javoblar"])

    if len(u_ans) != len(t_ans):
        return await message.answer(
            f"❌ <b>Soni mos kelmadi!</b>\nSiz <b>{len(u_ans)}</b> ta, testda esa <b>{len(t_ans)}</b> ta savol bor."
        )

    total = len(t_ans)
    perc = (correct / total) * 100 if total else 0

    rid = await DB.execute(
        "INSERT INTO results (uid, kod, ball, total, perc, mistakes) VALUES (?,?,?,?,?,?)",
        (message.from_user.id, test["kod"], correct, total, perc, ", ".join(mistakes))
    )

    # DYNAMIC STRING RESOLUTION (SYNTAX ERROR TARTIBGA SOLINDI)
    mistakes_text = ", ".join(mistakes) if mistakes else "Ajoyib, barcha javoblar to'g'ri!"
    
    res_msg = (
        f"🏁 <b>NATIJA: {escape(test['title'])}</b>\n"
        f"{Assets.D_LINE}\n"
        f"👤 O'quvchi: <b>{escape(message.from_user.full_name)}</b>\n"
        f"🎯 To'g'ri javoblar: <b>{correct} / {total}</b>\n"
        f"📈 O'zlashtirish: <b>{perc:.1f} %</b>\n\n"
        f"{Assets.progress_bar(perc)}\n\n"
        f"⚠️ Xatolar: <code>{escape(mistakes_text)}</code>\n"
        f"{Assets.S_LINE}\n"
        f"🆔 Natija ID: <code>#{rid}</code>"
    )
    await message.answer(res_msg, reply_markup=UI.main_menu(message.from_user.id), parse_mode="HTML")
    await state.clear()

# ==========================================================================================
# 2. KUNLIK TEST BO'LIMI
# ==========================================================================================
@dp.message(F.text == Assets.ICO_DAILY)
async def daily_test_start(message: Message, state: FSMContext):
    test = await get_active_daily_test()
    if not test:
        return await message.answer("📭 Hozircha bugun uchun kunlik test berilmagan.")

    await state.update_data(active_daily_test=test)
    await state.set_state(Form.daily_solve_ans)

    info = (
        f"🔥 <b>BUGUNGI KUNLIK TEST</b>\n"
        f"{Assets.D_LINE}\n"
        f"📖 Mavzu: <b>{escape(test['title'])}</b>\n"
        f"🔢 Savollar: <b>{len(normalize_answers(test['javoblar']))} ta</b>\n"
        f"{Assets.S_LINE}\n"
        f"📥 <b>Javoblarni yuboring:</b> (Masalan: <code>abcd...</code>)"
    )

    if test["file_id"]:
        await message.answer_document(test["file_id"], caption=info, parse_mode="HTML")
    else:
        await message.answer(info, parse_mode="HTML")

@dp.message(Form.daily_solve_ans)
async def daily_test_logic(message: Message, state: FSMContext):
    data = await state.get_data()
    test = data.get("active_daily_test")
    if not test:
        await state.clear()
        return await message.answer("⚠️ Kunlik test topilmadi.")

    u_ans, t_ans, correct, mistakes = score_answers(message.text, test["javoblar"])

    if len(u_ans) != len(t_ans):
        return await message.answer(f"❌ <b>Soni mos kelmadi!</b>\nSavollar soni: {len(t_ans)} ta.")

    total = len(t_ans)
    perc = (correct / total) * 100 if total else 0

    await DB.execute(
        "INSERT INTO daily_results (uid, kod, ball, total, perc, mistakes) VALUES (?,?,?,?,?,?) ON CONFLICT(uid, kod) DO UPDATE SET ball=excluded.ball, perc=excluded.perc, mistakes=excluded.mistakes, timestamp=CURRENT_TIMESTAMP",
        (message.from_user.id, test["kod"], correct, total, perc, ", ".join(mistakes))
    )

    mistakes_text = ", ".join(mistakes) if mistakes else "Ajoyib, barcha javoblar to'g'ri!"

    res_msg = (
        f"🏆 <b>KUNLIK TEST NATIJANGIZ</b>\n"
        f"{Assets.D_LINE}\n"
        f"🎯 Natija: <b>{correct} / {total}</b> ({perc:.1f}%)\n"
        f"{Assets.progress_bar(perc)}\n\n"
        f"⚠️ Xatolar: <code>{escape(mistakes_text)}</code>\n"
        f"{Assets.S_LINE}\n"
        f"<i>Sizning natijangiz bugungi umumiy reytingga qo'shildi!</i>"
    )
    await message.answer(res_msg, reply_markup=UI.main_menu(message.from_user.id), parse_mode="HTML")
    await state.clear()

# ==========================================================================================
# 3. YORDAM (SUPPORT - KO'P ADMINLI TIZIM)
# ==========================================================================================
@dp.message(F.text == Assets.ICO_HELP)
async def support_start(message: Message, state: FSMContext):
    await state.set_state(Form.support)
    await message.answer(
        f"📝 <b>ADMINISTRATSIYAGA MUROJAAT</b>\n{Assets.S_LINE}\n"
        f"Savol yoki taklifingizni to'liq yozib qoldiring:",
        reply_markup=UI.back_btn(), parse_mode="HTML"
    )

@dp.message(Form.support)
async def support_sent(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    msg_text = message.text or ""

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✍️ Javob yozish", callback_data=f"reply_{user_id}"))

    admin_msg = (
        f"📩 <b>YANGI MUROJAAT</b>\n"
        f"{Assets.D_LINE}\n"
        f"👤 Kimdan: <b>{escape(user_name)}</b>\n"
        f"💬 Matn: <i>{escape(msg_text)}</i>"
    )

    # Barcha adminlarga murojaatni yetkazish
    for adm in Assets.ADMIN_IDS:
        try:
            await bot.send_message(adm, admin_msg, reply_markup=kb.as_markup(), parse_mode="HTML")
        except Exception:
            pass

    await message.answer(f"✅ Murojaatingiz adminga yetkazildi.", reply_markup=UI.main_menu(user_id))
    await state.clear()

@dp.callback_query(F.data.startswith("reply_"))
async def admin_reply_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in Assets.ADMIN_IDS:
        return await call.answer("Sizga ruxsat yo'q!", show_alert=True)

    target_id = call.data.split("_", 1)[1]
    await state.update_data(reply_target_id=target_id)
    await state.set_state(Form.adm_reply)
    await call.message.answer(f"📝 ID {target_id} uchun javob matnini yozing:", reply_markup=UI.back_btn())
    await call.answer()

@dp.message(Form.adm_reply)
async def admin_reply_sent(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return

    data = await state.get_data()
    target_id = data.get("reply_target_id")
    reply_text = message.text or ""
    
    try:
        await bot.send_message(
            int(target_id),
            f"👨‍💻 <b>ADMINISTRATSIYA JAVOBI:</b>\n{Assets.S_LINE}\n{escape(reply_text)}",
            parse_mode="HTML"
        )
        await message.answer(f"✅ Javob foydalanuvchiga yuborildi.", reply_markup=UI.admin_menu())
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: Bu foydalanuvchi botni bloklagan bo'lishi mumkin.")

    await state.clear()

# ==========================================================================================
# 4. SUN'IY INTELLEKT (AI)
# ==========================================================================================
@dp.message(F.text == Assets.ICO_AI)
async def ai_init(message: Message, state: FSMContext):
    await state.set_state(Form.ai_chat)
    await message.answer(
        f"🤖 <b>AI USTOZ (GROQ)</b>\n{Assets.S_LINE}\nIstagan savolingizni bering:",
        reply_markup=UI.back_btn(), parse_mode="HTML"
    )

@dp.message(Form.ai_chat)
async def ai_logic(message: Message):
    if message.text == Assets.ICO_BACK: return

    loading = await message.answer("⏳ <i>Fikrlanmoqda...</i>", parse_mode="HTML")
    try:
        if not groq_client:
            return await loading.edit_text("⚠️ AI API kaliti ulanmagan.")

        resp = groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Sen aqlli ustozsan. Savollarga o'zbek tilida aniq javob ber."},
                {"role": "user", "content": message.text}
            ],
            model="llama-3.3-70b-versatile"
        )
        await loading.edit_text(
            f"🧠 <b>AI JAVOBI:</b>\n{Assets.D_LINE}\n{escape(resp.choices[0].message.content)}", 
            parse_mode="HTML"
        )
    except Exception:
        await loading.edit_text("❌ Tizimda xatolik yuz berdi. Iltimos keyinroq urinib ko'ring.")

# ==========================================================================================
# 5. PROFIL VA TARIX
# ==========================================================================================
@dp.message(F.text == Assets.ICO_PROF)
async def profile(message: Message):
    u = await DB.fetch_one("SELECT * FROM users WHERE uid=?", (message.from_user.id,))
    if not u: return await message.answer("Profil topilmadi. /start tugmasini bosing.")

    text = (
        f"👤 <b>MENING PROFILIM</b>\n{Assets.D_LINE}\n"
        f"Ism: <b>{escape(u['fullname'])}</b>\n"
        f"ID: <code>{u['uid']}</code>\n"
        f"Ro'yxatdan o'tgan sana: <b>{fmt_dt(u['joined_at'])}</b>\n"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == Assets.ICO_HIS)
async def history(message: Message):
    res = await DB.fetch_all("SELECT * FROM results WHERE uid=? ORDER BY timestamp DESC LIMIT 10", (message.from_user.id,))
    if not res: return await message.answer("Hozircha test natijalaringiz yo'q.")

    msg = f"📊 <b>OXIRGI NATIJALAR (TOP 10)</b>\n{Assets.D_LINE}\n"
    for r in res:
        msg += f"🔖 Kod: {escape(r['kod'])} | 🎯 {r['ball']}/{r['total']} ({r['perc']:.1f}%)\n"
    await message.answer(msg, parse_mode="HTML")

# ==========================================================================================
# 6. ADMIN PANEL
# ==========================================================================================
@dp.message(F.text == Assets.ICO_ADM)
async def admin_portal(message: Message):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    await message.answer("⚙️ <b>ADMIN BOSHQARUV PANELI</b>", reply_markup=UI.admin_menu(), parse_mode="HTML")

@dp.message(F.text == Assets.ADM_ADD_TEST)
async def adm_add_start(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    await state.set_state(Form.adm_add_kod)
    await message.answer("1️⃣ Test kodini kiriting (Masalan: 1234):", reply_markup=UI.back_btn())

@dp.message(Form.adm_add_kod)
async def adm_add_k(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    
    check = await DB.fetch_one("SELECT kod FROM tests WHERE kod=?", (message.text.strip(),))
    if check:
        return await message.answer("❌ Bu kod band. Boshqa kod kiriting.")
        
    await state.update_data(kod=message.text.strip())
    await state.set_state(Form.adm_add_title)
    await message.answer("2️⃣ Test nomini yozing:")

@dp.message(Form.adm_add_title)
async def adm_add_t(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    await state.update_data(title=message.text.strip())
    await state.set_state(Form.adm_add_ans)
    await message.answer("3️⃣ To'g'ri javoblarni yuboring (abcd...):")

@dp.message(Form.adm_add_ans)
async def adm_add_a(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    ans = normalize_answers(message.text)
    if not ans:
        return await message.answer("⚠️ Javoblar bo'sh bo'lmasin.")
        
    await state.update_data(ans=ans)
    await state.set_state(Form.adm_add_file)
    await message.answer("4️⃣ Fayl yuboring (yoki /skip):")

@dp.message(Form.adm_add_file)
async def adm_add_f(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    data = await state.get_data()
    fid = message.document.file_id if message.document else None

    if not fid and message.text != "/skip":
        return await message.answer("Fayl yoki /skip yuboring.")

    await DB.execute(
        "INSERT INTO tests (kod, title, javoblar, file_id) VALUES (?,?,?,?)",
        (data["kod"], data["title"], data["ans"], fid)
    )
    await message.answer("✅ Yangi test muvaffaqiyatli saqlandi!", reply_markup=UI.admin_menu())
    await state.clear()

# Kunlik test qo'shish
@dp.message(F.text == Assets.ADM_ADD_DAILY)
async def adm_daily_start(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    await state.set_state(Form.adm_add_daily_kod)
    await message.answer("1️⃣ Kunlik test kodi:", reply_markup=UI.back_btn())

@dp.message(Form.adm_add_daily_kod)
async def adm_daily_k(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    await state.update_data(kod=message.text.strip())
    await state.set_state(Form.adm_add_daily_title)
    await message.answer("2️⃣ Sarlavha:")

@dp.message(Form.adm_add_daily_title)
async def adm_daily_t(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    await state.update_data(title=message.text.strip())
    await state.set_state(Form.adm_add_daily_ans)
    await message.answer("3️⃣ Javoblar (abcd...):")

@dp.message(Form.adm_add_daily_ans)
async def adm_daily_a(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    ans = normalize_answers(message.text)
    if not ans:
        return await message.answer("⚠️ Javoblar bo'sh bo'lmasin.")
        
    await state.update_data(ans=ans)
    await state.set_state(Form.adm_add_daily_file)
    await message.answer("4️⃣ Fayl (yoki /skip):")

@dp.message(Form.adm_add_daily_file)
async def adm_daily_f(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    data = await state.get_data()
    fid = message.document.file_id if message.document else None

    await DB.clear_daily_stats()
    await DB.execute(
        "INSERT INTO daily_tests (kod, title, javoblar, file_id) VALUES (?,?,?,?)",
        (data["kod"], data["title"], data["ans"], fid)
    )
    await message.answer("✅ Kunlik test qo'shildi! Eski natijalar tozalandi.", reply_markup=UI.admin_menu())
    await state.clear()

# O'chirish paneli
@dp.message(F.text == Assets.ADM_DEL_TEST)
async def adm_del(message: Message):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    tests = await DB.fetch_all("SELECT kod, title FROM tests")
    if not tests: return await message.answer("Hozircha testlar yo'q.")
    
    kb = InlineKeyboardBuilder()
    for t in tests:
        kb.row(InlineKeyboardButton(text=f"🗑 {t['kod']} | {t['title']}", callback_data=f"del_{t['kod']}"))
    await message.answer("O'chiriladigan testni tanlang:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("del_"))
async def adm_del_cb(call: CallbackQuery):
    if call.from_user.id not in Assets.ADMIN_IDS: return
    kod = call.data.split("_")[1]
    
    await DB.execute("DELETE FROM tests WHERE kod=?", (kod,))
    await DB.execute("DELETE FROM results WHERE kod=?", (kod,))
    await call.message.edit_text(f"✅ Kod {kod} bo'lgan barcha test va uning natijalari o'chirildi.")

# Statistikalar
@dp.message(F.text == Assets.ADM_STATS)
async def adm_stats(message: Message):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    u_row = await DB.fetch_one("SELECT COUNT(*) as c FROM users")
    r_row = await DB.fetch_one("SELECT COUNT(*) as c FROM results")
    
    u = u_row["c"] if u_row else 0
    r = r_row["c"] if r_row else 0
    await message.answer(f"📈 <b>Umumiy statistika:</b>\n👥 Ro'yxatdan o'tganlar: {u}\n📝 Topshirilgan jami testlar: {r}", parse_mode="HTML")

@dp.message(F.text == Assets.ADM_DAILY_STATS)
async def adm_dstats(message: Message):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    res = await DB.fetch_all(
        "SELECT u.fullname, r.ball, r.perc FROM daily_results r JOIN users u ON r.uid = u.uid ORDER BY r.perc DESC"
    )
    if not res: return await message.answer("Natijalar yo'q.")
    text = "🔥 <b>Kunlik Reyting (Top 20):</b>\n\n"
    for i, r in enumerate(res[:20], 1):
        text += f"{i}. {r['fullname']} - {r['ball']} ({r['perc']:.1f}%)\n"
    await message.answer(text, parse_mode="HTML")

# Broadcast
@dp.message(F.text == Assets.ADM_BROADCAST)
async def adm_broad(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    await state.set_state(Form.adm_broadcast)
    await message.answer("📢 Barchaga yuboriladigan xabarni yozing:", reply_markup=UI.back_btn())

@dp.message(Form.adm_broadcast)
async def adm_broad_send(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    users = await DB.fetch_all("SELECT uid FROM users")
    msg = message.text or ""
    await message.answer("⏳ Xabar tarqatilmoqda, kuting...")
    c = 0
    for u in users:
        try:
            await bot.send_message(u['uid'], f"📢 <b>Diqqat!</b>\n\n{msg}", parse_mode="HTML")
            c += 1
            await asyncio.sleep(0.05)
        except Exception: 
            pass
    await message.answer(f"✅ {c} kishiga yuborildi.", reply_markup=UI.admin_menu())
    await state.clear()

# ==========================================================================================
# MAIN LOOP
# ==========================================================================================
async def main():
    # Ma'lumotlar bazasini asinxron ishga tushirish
    await DB.init_db()
    
    await bot.set_my_commands([BotCommand(command="start", description="🏠 Bosh menyu")])
    print(f"✅ ASINXRON BOT ISHGA TUSHDI! (Adminlar soni: {len(Assets.ADMIN_IDS)})")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
