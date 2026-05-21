import asyncio
import logging
import os
import sqlite3
import html
from datetime import datetime
from html import escape
from typing import Final, Any, Optional, List

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
    
    # Ko'p adminli tizim: .env faylda ADMIN_IDS=123,456 kabi yoziladi
    _admin_ids_str = os.getenv("ADMIN_IDS", "0")
    ADMIN_IDS: Final[List[int]] = [int(x.strip()) for x in _admin_ids_str.split(",") if x.strip().isdigit()]
    
    DB_NAME: Final[str] = os.getenv("DB_NAME", "database.db")

    # Dizayn elementlari
    D_LINE = "<b>━━━━━━━━━━━━━━━━━━━━━━━━━</b>"
    S_LINE = "<i>─────────────────────────</i>"
    HEADER = "🎓 <b>LOGOS PLATINUM ACADEMY</b>"

    # Menyular (Yangi dizayn)
    ICO_TEST = "📚 Testlar Bazasi"
    ICO_CHECK = "✍️ Test Topshirish"
    ICO_DAILY = "🔥 Kunlik Test"
    ICO_AI = "🧠 AI Mentor (PRO)"
    ICO_HIS = "📊 Natijalar Tarixi"
    ICO_PROF = "👤 Mening Profilim"
    ICO_HELP = "🎧 Admin Bilan Aloqa"
    ICO_ADM = "⚙️ Admin Boshqaruvi"
    ICO_BACK = "🔙 Orqaga Qaytish"
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
# 🗄 MA'LUMOTLAR BAZASI (DATABASE)
# ==========================================================================================
class DB:
    @staticmethod
    def connect():
        conn = sqlite3.connect(Assets.DB_NAME)
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def setup(cls):
        with cls.connect() as conn:
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS users (
                uid INTEGER PRIMARY KEY, fullname TEXT, username TEXT, joined_at TIMESTAMP
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS tests (
                kod TEXT PRIMARY KEY, javoblar TEXT, file_id TEXT, title TEXT, created_at TIMESTAMP
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS results (
                rid INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, kod TEXT, ball INTEGER, 
                total INTEGER, perc REAL, mistakes TEXT, timestamp TIMESTAMP
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS daily_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, kod TEXT, javoblar TEXT, file_id TEXT, 
                title TEXT, created_at TIMESTAMP
            )""")
            c.execute("""CREATE TABLE IF NOT EXISTS daily_results (
                uid INTEGER PRIMARY KEY, kod TEXT, ball INTEGER, total INTEGER, 
                perc REAL, mistakes TEXT, timestamp TIMESTAMP
            )""")
            conn.commit()

    @classmethod
    def run(cls, sql: str, params: tuple = (), fetch: str = "none") -> Any:
        with cls.connect() as conn:
            c = conn.cursor()
            c.execute(sql, params)
            if fetch == "all":
                return [dict(r) for r in c.fetchall()]
            if fetch == "one":
                row = c.fetchone()
                return dict(row) if row else None
            conn.commit()
            return c.lastrowid

    @classmethod
    def clear_daily_stats(cls):
        cls.run("DELETE FROM daily_results")
        cls.run("DELETE FROM daily_tests")

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
        b.row(KeyboardButton(text=Assets.ICO_DAILY), KeyboardButton(text=Assets.ICO_AI))
        b.row(KeyboardButton(text=Assets.ICO_HIS), KeyboardButton(text=Assets.ICO_PROF))
        b.row(KeyboardButton(text=Assets.ICO_HELP))
        
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
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=Assets.ICO_BACK)]],
            resize_keyboard=True
        )

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
            mistakes.append(f"{i+1}{u[i].upper()}") # 1A, 2B formatida (ixchamroq)

    return u, t, correct, mistakes

def get_active_daily_test():
    return DB.run("SELECT * FROM daily_tests ORDER BY id DESC LIMIT 1", fetch="one")

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
    DB.setup()
    user = DB.run("SELECT * FROM users WHERE uid=?", (user_id,), fetch="one")

    if not user:
        await state.set_state(Form.reg)
        text = (
            f"{Assets.HEADER}\n"
            f"{Assets.D_LINE}\n\n"
            f"👋 Assalomu alaykum, <b>{html.escape(user_firstname)}</b>!\n"
            f"SAT dan maxsus test botiga xush kelibsiz.\n\n"
            f"✍️ <i>Iltimos, ism va familiyangizni to'liq kiriting:</i>\n\n"
            f"💡 <b>Namuna:</b> <i>Abdullayev Alisher</i>"
        )
        await message.answer(text, parse_mode="HTML")
    else:
        status_text = "Tizim Administratori 👑" if user_id in Assets.ADMIN_IDS else "Premium O'quvchi 💎"
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
            f"Botdan foydalanish uchun quyidagi rasmiy kanallarimizga a'zo bo'lishingiz kerak."
        )
        return await message.answer(text, reply_markup=get_subscription_keyboard(), parse_mode="HTML")

    await process_user_entry(message, state, message.from_user.id, message.from_user.first_name)

@dp.callback_query(F.data == "check_subscription")
async def check_sub_handler(call: CallbackQuery, state: FSMContext, bot: Bot):
    if not await is_subscribed(bot, call.from_user.id):
        return await call.answer("❌ Barcha kanallarga obuna bo'lmadingiz!", show_alert=True)

    await call.message.delete()
    await process_user_entry(call.message, state, call.from_user.id, call.from_user.first_name)

@dp.message(Form.reg)
async def registration_finish(message: Message, state: FSMContext):
    DB.run(
        "INSERT OR REPLACE INTO users (uid, fullname, username, joined_at) VALUES (?,?,?,?)",
        (message.from_user.id, message.text, message.from_user.username, datetime.now().isoformat())
    )
    success_text = (
        f"✅ <b>Muvaffaqiyatli ro'yxatdan o'tdingiz!</b>\n\n"
        f"Hurmatli <b>{html.escape(message.text)}</b>, testlardan va AI xizmatidan foydalanishingiz mumkin."
    )
    await message.answer(success_text, parse_mode="HTML", reply_markup=UI.main_menu(message.from_user.id))
    await state.clear()

# ==========================================================================================
# 1. TESTLAR BO'LIMI
# ==========================================================================================
@dp.message(F.text == Assets.ICO_TEST)
async def test_list(message: Message):
    tests = DB.run("SELECT * FROM tests ORDER BY created_at DESC", fetch="all")
    if not tests:
        return await message.answer("📭 Hozircha testlar bazasi bo'sh.", parse_mode="HTML")

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
    test = DB.run("SELECT * FROM tests WHERE kod=?", (message.text.strip(),), fetch="one")
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
        f"📥 <b>Javoblaringizni bitta xabarda yuboring:</b> (Masalan: <code>abcdabcd...</code>)"
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

    rid = DB.run(
        "INSERT INTO results (uid, kod, ball, total, perc, mistakes, timestamp) VALUES (?,?,?,?,?,?,?)",
        (message.from_user.id, test["kod"], correct, total, perc, ", ".join(mistakes), datetime.now().isoformat())
    )

    res_msg = (
        f"🏁 <b>NATIJA: {escape(test['title'])}</b>\n"
        f"{Assets.D_LINE}\n"
        f"👤 O'quvchi: <b>{escape(message.from_user.full_name)}</b>\n"
        f"🎯 To'g'ri javoblar: <b>{correct} / {total}</b>\n"
        f"📈 O'zlashtirish: <b>{perc:.1f} %</b>\n\n"
        f"{Assets.progress_bar(perc)}\n\n"
        f"⚠️ Xatolar: <code>{escape(', '.join(mistakes) if mistakes else 'Barcha javoblar to\\'g\\'ri!')}</code>\n"
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
    test = get_active_daily_test()
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

    DB.run(
        "INSERT OR REPLACE INTO daily_results (uid, kod, ball, total, perc, mistakes, timestamp) VALUES (?,?,?,?,?,?,?)",
        (message.from_user.id, test["kod"], correct, total, perc, ", ".join(mistakes), datetime.now().isoformat())
    )

    res_msg = (
        f"🏆 <b>KUNLIK TEST NATIJANGIZ</b>\n"
        f"{Assets.D_LINE}\n"
        f"🎯 Natija: <b>{correct} / {total}</b> ({perc:.1f}%)\n"
        f"{Assets.progress_bar(perc)}\n\n"
        f"⚠️ Xatolar: <code>{escape(', '.join(mistakes) if mistakes else 'Ajoyib!')}</code>\n"
        f"{Assets.S_LINE}\n"
        f"<i>Sizning natijangiz bugungi umumiy reytingga qo'shildi!</i>"
    )
    await message.answer(res_msg, reply_markup=UI.main_menu(message.from_user.id), parse_mode="HTML")
    await state.clear()

# ==========================================================================================
# 3. YORDAM (SUPPORT KO'P ADMINLI TIZIM)
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
    
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✍️ Javob yozish", callback_data=f"reply_{user_id}"))

    admin_msg = (
        f"📩 <b>YANGI MUROJAAT</b>\n"
        f"{Assets.D_LINE}\n"
        f"👤 Kimdan: <b>{escape(user_name)}</b>\n"
        f"💬 Matn: <i>{escape(message.text or '')}</i>"
    )

    # Barcha adminlarga yuborish
    for adm in Assets.ADMIN_IDS:
        try:
            await bot.send_message(adm, admin_msg, reply_markup=kb.as_markup(), parse_mode="HTML")
        except Exception:
            pass

    await message.answer("✅ Murojaatingiz adminga yetkazildi.", reply_markup=UI.main_menu(user_id))
    await state.clear()

@dp.callback_query(F.data.startswith("reply_"))
async def admin_reply_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id not in Assets.ADMIN_IDS:
        return await call.answer("Sizga ruxsat yo'q!", show_alert=True)

    target_id = call.data.split("_", 1)[1]
    await state.update_data(reply_to=target_id)
    await state.set_state(Form.adm_reply)
    await call.message.answer(f"📝 Foydalanuvchi (ID: {target_id}) uchun javob matnini yozing:", reply_markup=UI.back_btn())
    await call.answer()

@dp.message(Form.adm_reply)
async def admin_reply_sent(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return

    data = await state.get_data()
    target_id = data.get("reply_to")
    
    try:
        await bot.send_message(
            int(target_id),
            f"👨‍💻 <b>ADMINISTRATSIYA JAVOBI:</b>\n{Assets.S_LINE}\n{escape(message.text or '')}",
            parse_mode="HTML"
        )
        await message.answer("✅ Javobingiz foydalanuvchiga yuborildi.", reply_markup=UI.admin_menu())
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {e}")

    await state.clear()

# ==========================================================================================
# 4. SUN'IY INTELLEKT (AI)
# ==========================================================================================
@dp.message(F.text == Assets.ICO_AI)
async def ai_init(message: Message, state: FSMContext):
    await state.set_state(Form.ai_chat)
    await message.answer(
        f"🤖 <b>AI USTOZ (GROQ Llama)</b>\n{Assets.S_LINE}\nIstagan savolingizni bering:",
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
        await loading.edit_text("❌ Tizimda xatolik yuz berdi.")

# ==========================================================================================
# 5. PROFIL VA TARIX
# ==========================================================================================
@dp.message(F.text == Assets.ICO_PROF)
async def profile(message: Message):
    u = DB.run("SELECT * FROM users WHERE uid=?", (message.from_user.id,), fetch="one")
    if not u: return await message.answer("Profil topilmadi. /start tugmasini bosing.")

    text = (
        f"👤 <b>MENING PROFILIM</b>\n{Assets.D_LINE}\n"
        f"Ism: <b>{escape(u['fullname'])}</b>\n"
        f"ID: <code>{u['uid']}</code>\n"
        f"Sana: <b>{fmt_dt(u['joined_at'])}</b>\n"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == Assets.ICO_HIS)
async def history(message: Message):
    res = DB.run("SELECT * FROM results WHERE uid=? ORDER BY timestamp DESC LIMIT 10", (message.from_user.id,), fetch="all")
    if not res: return await message.answer("Hozircha test natijalaringiz yo'q.")

    msg = f"📊 <b>OXIRGI NATIJALAR</b>\n{Assets.D_LINE}\n"
    for r in res:
        msg += f"🔖 Kod: {escape(r['kod'])} | 🎯 {r['ball']}/{r['total']} ({r['perc']:.1f}%)\n"
    await message.answer(msg, parse_mode="HTML")

# ==========================================================================================
# 6. ADMIN PANEL
# ==========================================================================================
@dp.message(F.text == Assets.ICO_ADM)
async def admin_portal(message: Message):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    await message.answer("⚙️ <b>ADMIN BOSH QARUV PANELI</b>", reply_markup=UI.admin_menu(), parse_mode="HTML")

@dp.message(F.text == Assets.ADM_ADD_TEST)
async def adm_add_start(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    await state.set_state(Form.adm_add_kod)
    await message.answer("1️⃣ Test kodini kiriting (Masalan: 1234):", reply_markup=UI.back_btn())

@dp.message(Form.adm_add_kod)
async def adm_add_k(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    if DB.run("SELECT kod FROM tests WHERE kod=?", (message.text.strip(),), fetch="one"):
        return await message.answer("❌ Bu kod band.")
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
    await state.update_data(ans=normalize_answers(message.text))
    await state.set_state(Form.adm_add_file)
    await message.answer("4️⃣ Fayl yuboring (yoki /skip):")

@dp.message(Form.adm_add_file)
async def adm_add_f(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    data = await state.get_data()
    fid = message.document.file_id if message.document else None

    if not fid and message.text != "/skip":
        return await message.answer("Fayl yoki /skip yuboring.")

    DB.run(
        "INSERT INTO tests (kod, javoblar, file_id, title, created_at) VALUES (?,?,?,?,?)",
        (data["kod"], data["ans"], fid, data["title"], datetime.now().isoformat())
    )
    await message.answer("✅ Test saqlandi!", reply_markup=UI.admin_menu())
    await state.clear()

# Kunlik test
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
    await state.update_data(ans=normalize_answers(message.text))
    await state.set_state(Form.adm_add_daily_file)
    await message.answer("4️⃣ Fayl (yoki /skip):")

@dp.message(Form.adm_add_daily_file)
async def adm_daily_f(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    data = await state.get_data()
    fid = message.document.file_id if message.document else None

    DB.clear_daily_stats()
    DB.run(
        "INSERT INTO daily_tests (kod, javoblar, file_id, title, created_at) VALUES (?,?,?,?,?)",
        (data["kod"], data["ans"], fid, data["title"], datetime.now().isoformat())
    )
    await message.answer("✅ Kunlik test qo'shildi! Eski natijalar o'chirildi.", reply_markup=UI.admin_menu())
    await state.clear()

# Statistika va O'chirish (Qisqartirilgan)
@dp.message(F.text == Assets.ADM_DEL_TEST)
async def adm_del(message: Message):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    tests = DB.run("SELECT kod, title FROM tests", fetch="all")
    if not tests: return await message.answer("Testlar yo'q.")
    
    kb = InlineKeyboardBuilder()
    for t in tests:
        kb.row(InlineKeyboardButton(text=f"🗑 {t['kod']} | {t['title']}", callback_data=f"del_{t['kod']}"))
    await message.answer("O'chiriladigan testni tanlang:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("del_"))
async def adm_del_cb(call: CallbackQuery):
    if call.from_user.id not in Assets.ADMIN_IDS: return
    kod = call.data.split("_")[1]
    DB.run("DELETE FROM tests WHERE kod=?", (kod,))
    DB.run("DELETE FROM results WHERE kod=?", (kod,))
    await call.message.edit_text(f"✅ {kod} o'chirildi.")

@dp.message(F.text == Assets.ADM_STATS)
async def adm_stats(message: Message):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    u = DB.run("SELECT COUNT(*) as c FROM users", fetch="one")["c"]
    r = DB.run("SELECT COUNT(*) as c FROM results", fetch="one")["c"]
    await message.answer(f"📈 <b>Umumiy statistika:</b>\n👥 O'quvchilar: {u}\n📝 Topshirilgan testlar: {r}", parse_mode="HTML")

@dp.message(F.text == Assets.ADM_DAILY_STATS)
async def adm_dstats(message: Message):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    res = DB.run("SELECT u.fullname, r.ball, r.perc FROM daily_results r JOIN users u ON r.uid = u.uid ORDER BY r.perc DESC", fetch="all")
    if not res: return await message.answer("Natijalar yo'q.")
    text = "🔥 <b>Kunlik Reyting:</b>\n\n"
    for i, r in enumerate(res[:20], 1):
        text += f"{i}. {r['fullname']} - {r['ball']} ({r['perc']:.1f}%)\n"
    await message.answer(text, parse_mode="HTML")

@dp.message(F.text == Assets.ADM_BROADCAST)
async def adm_broad(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    await state.set_state(Form.adm_broadcast)
    await message.answer("📢 Barchaga yuboriladigan xabarni yozing:", reply_markup=UI.back_btn())

@dp.message(Form.adm_broadcast)
async def adm_broad_send(message: Message, state: FSMContext):
    if message.from_user.id not in Assets.ADMIN_IDS: return
    users = DB.run("SELECT uid FROM users", fetch="all")
    msg = message.text or ""
    await message.answer("⏳ Tarqatilmoqda...")
    c = 0
    for u in users:
        try:
            await bot.send_message(u['uid'], f"📢 <b>Diqqat!</b>\n\n{msg}", parse_mode="HTML")
            c += 1
            await asyncio.sleep(0.05)
        except Exception: pass
    await message.answer(f"✅ {c} kishiga yuborildi.", reply_markup=UI.admin_menu())
    await state.clear()

# ==========================================================================================
# MAIN LOOP
# ==========================================================================================
async def main():
    DB.setup()
    await bot.set_my_commands([BotCommand(command="start", description="🏠 Bosh menyu")])
    print(f"✅ BOT ISHGA TUSHDI! (Adminlar soni: {len(Assets.ADMIN_IDS)})")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
