import asyncio
import logging
import os
import sqlite3
import random
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
from aiohttp import web
from dotenv import load_dotenv

# .env faylini yuklash
load_dotenv()

try:
    from groq import Groq
except Exception:
    Groq = None

# ==========================================================================================
# 💎 PREMIUM KONFIGURATSIYA VA AKTIVLAR
# ==========================================================================================
class Assets:
    TOKEN: Final[str] = os.getenv("BOT_TOKEN")
    GROQ_KEY: Final[str] = os.getenv("GROQ_API_KEY")
    
    # Ikki kishilik admin tizimi (ADMIN_ID_1 va ADMIN_ID_2)
    ADMIN_ID_1: Final[int] = int(os.getenv("ADMIN_ID_1", 0))
    ADMIN_ID_2: Final[int] = int(os.getenv("ADMIN_ID_2", 0))
    ADMIN_IDS: Final[List[int]] = [ADMIN_ID_1, ADMIN_ID_2]

    DB_NAME: Final[str] = os.getenv("DB_NAME", "database.db")
    
    # Chiroyli vizual dizayn chiziqlari
    D_LINE = "<b>▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬</b>"
    S_LINE = "<b>────────────────────</b>"

    # Menyular uchun Premium Emojilar va Matnlar
    ICO_TEST = "🧩 Testlar Markazi"
    ICO_CHECK = "📝 Test Topshirish"
    ICO_DAILY = "📅 Kunlik Testlar"
    ICO_AI = "🤖 AI Mentor (Premium)"
    ICO_HIS = "📈 Natijalarim"
    ICO_TOP = "🏆 Top 10 Foydalanuvchi"
    ICO_PROF = "👤 Shaxsiy Kabinet"
    ICO_HELP = "🆘 Yordam / Aloqa"
    ICO_ADM = "🛠 Admin Boshqaruvi"
    ICO_BACK = "⬅️ Orqaga"
    ICO_HOME = "🏠 Asosiy Menyu"

    # Admin boshqaruv buyruqlari
    ADM_ADD_TEST = "➕ Yangi Test"
    ADM_ADD_DAILY = "➕ Kunlik Test"
    ADM_STATS = "📊 Umumiy Statistika"
    ADM_DAILY_STATS = "📊 Kunlik Statistika"
    ADM_DEL_TEST = "🗑 Testni O'chirish"
    ADM_BROADCAST = "📢 Barchaga Xabar"

    @staticmethod
    def progress_bar(perc: float) -> str:
        full = max(0, min(10, int(perc // 10)))
        empty = 10 - full
        return "🟢" * full + "⚪" * empty

    @classmethod
    def is_admin(cls, user_id: int) -> bool:
        return user_id in cls.ADMIN_IDS


logging.basicConfig(level=logging.INFO)
bot = Bot(token=Assets.TOKEN)
dp = Dispatcher(storage=MemoryStorage())
groq_client = Groq(api_key=Assets.GROQ_KEY) if Groq and Assets.GROQ_KEY else None


# ==========================================================================================
# 🗄 MUKAMMAL VA XAVFSIZ DATABASE TIZIMI
# ==========================================================================================
class DB:
    @staticmethod
    def connect():
        conn = sqlite3.connect(Assets.DB_NAME)
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def setup(cls):
        """Ma'lumotlar bazasini xavfsiz ishga tushirish"""
        with cls.connect() as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    uid INTEGER PRIMARY KEY,
                    fullname TEXT NOT NULL,
                    username TEXT,
                    joined_at TIMESTAMP NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS tests (
                    kod TEXT PRIMARY KEY,
                    javoblar TEXT NOT NULL,
                    file_id TEXT,
                    title TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS results (
                    rid INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid INTEGER NOT NULL,
                    kod TEXT NOT NULL,
                    ball INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    perc REAL NOT NULL,
                    mistakes TEXT,
                    timestamp TIMESTAMP NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS daily_tests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kod TEXT NOT NULL,
                    javoblar TEXT NOT NULL,
                    file_id TEXT,
                    title TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS daily_results (
                    uid INTEGER PRIMARY KEY,
                    kod TEXT NOT NULL,
                    ball INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    perc REAL NOT NULL,
                    mistakes TEXT,
                    timestamp TIMESTAMP NOT NULL
                )
            """)
            conn.commit()

    @classmethod
    def run(cls, sql: str, params: tuple = (), fetch: str = "none") -> Any:
        """SQL Injection'dan himoyalangan xavfsiz SQL so'rovlar bajaruvchisi"""
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
        with cls.connect() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM daily_results")
            c.execute("DELETE FROM daily_tests")
            conn.commit()


# ==========================================================================================
# 🧠 BOSQIChLI STATE-LAR
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
# 🎨 CHIROYLI FOYDALANUVChI INTERFEYSI (UI)
# ==========================================================================================
class UI:
    @staticmethod
    def main_menu(user_id: int):
        b = ReplyKeyboardBuilder()
        b.row(KeyboardButton(text=Assets.ICO_TEST), KeyboardButton(text=Assets.ICO_CHECK))
        b.row(KeyboardButton(text=Assets.ICO_DAILY), KeyboardButton(text=Assets.ICO_AI))
        b.row(KeyboardButton(text=Assets.ICO_HIS), KeyboardButton(text=Assets.ICO_TOP))
        b.row(KeyboardButton(text=Assets.ICO_PROF), KeyboardButton(text=Assets.ICO_HELP))
        
        # Agar foydalanuvchi Admin bo'lsa, Admin boshqaruv tugmasi ko'rinadi
        if Assets.is_admin(user_id):
            b.row(KeyboardButton(text=Assets.ICO_ADM))
            
        b.adjust(2, 2, 2, 2, 1 if Assets.is_admin(user_id) else 0)
        return b.as_markup(resize_keyboard=True)

    @staticmethod
    def admin_menu():
        b = ReplyKeyboardBuilder()
        b.row(KeyboardButton(text=Assets.ADM_ADD_TEST), KeyboardButton(text=Assets.ADM_ADD_DAILY))
        b.row(KeyboardButton(text=Assets.ADM_STATS), KeyboardButton(text=Assets.ADM_DAILY_STATS))
        b.row(KeyboardButton(text=Assets.ADM_DEL_TEST), KeyboardButton(text=Assets.ADM_BROADCAST))
        b.row(KeyboardButton(text=Assets.ICO_HOME))
        b.adjust(2, 2, 2, 1)
        return b.as_markup(resize_keyboard=True)

    @staticmethod
    def back_btn():
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=Assets.ICO_BACK)]],
            resize_keyboard=True
        )


# ==========================================================================================
# ⚙️ FOYDALI FUNKSIYALAR VA MATEMATIK HISOB-KITOB
# ==========================================================================================
def now_text() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M")


def fmt_dt(value: Optional[str]) -> str:
    if not value:
        return "-"
    return str(value)[:16].replace("T", " ")


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
            mistakes.append(f"{i+1}-{u[i].upper()}")

    return u, t, correct, mistakes


def get_active_daily_test():
    return DB.run("SELECT * FROM daily_tests ORDER BY id DESC LIMIT 1", fetch="one")


# ==========================================================================================
# 📢 MAJBURIY OBUNA TIZIMI (MAJBURIY KANALLAR)
# ==========================================================================================
REQUIRED_CHANNELS = [
    {"name": "📢 Asosiy Kanal", "id": "@satpro7"},
]

async def is_subscribed(bot: Bot, user_id: int) -> bool:
    """Foydalanuvchining majburiy kanallarga obunasini tekshirish"""
    # Adminlar majburiy obunadan ozod qilinadi
    if Assets.is_admin(user_id):
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
    """Obuna bo'lish tugmalarini shakllantirish"""
    builder = InlineKeyboardBuilder()
    for channel in REQUIRED_CHANNELS:
        url = f"https://t.me/{channel['id'].replace('@', '')}"
        builder.row(InlineKeyboardButton(text=channel["name"], url=url))
    
    builder.row(InlineKeyboardButton(text="✅ Obunani tasdiqlash", callback_data="check_subscription"))
    return builder.as_markup()


# ==========================================================================================
# 🚪 TIZIMGA KIRISh VA AVTOMATIK PROSESLAR
# ==========================================================================================
async def process_user_entry(message: Message, state: FSMContext, user_id: int, user_firstname: str):
    DB.setup()
    user = DB.run("SELECT * FROM users WHERE uid=?", (user_id,), fetch="one")

    if not user:
        await state.set_state(Form.reg)
        text = (
            f"🌟 <b>LOGOS PLATINUM ACADEMY</b>\n"
            f"{Assets.D_LINE}\n\n"
            f"👋 Assalomu alaykum, <b>{html.escape(user_firstname)}</b>!\n"
            f"Matematika sertifikat botiga xush kelibsiz.\n\n"
            f"✍️ <i>Bot imkoniyatlaridan to'liq foydalanish uchun ism va familiyangizni kiriting:</i>\n\n"
            f"💡 <b>Namuna:</b> <i>Aliyev Vali</i>"
        )
        await message.answer(text, parse_mode="HTML")
    else:
        role_label = "💎 Premium Hamkor (Admin)" if Assets.is_admin(user_id) else "👤 Premium A'zo"
        dashboard = (
            f"👑 <b>ASOSIY BOSHQARUV PANELI</b>\n"
            f"{Assets.D_LINE}\n\n"
            f"👤 Foydalanuvchi: <b>{html.escape(user['fullname'])}</b>\n"
            f"🎖 Status: <b>{role_label}</b>\n\n"
            f"📅 Sana: <b>{datetime.now().strftime('%d.%m.%Y')}</b>\n"
            f"🕒 Vaqt: <b>{datetime.now().strftime('%H:%M')}</b>\n\n"
            f"👇 <i>Davom etish uchun pastdagi menyudan foydalaning:</i>"
        )
        await message.answer(dashboard, reply_markup=UI.main_menu(user_id), parse_mode="HTML")


# ==========================================================================================
# 🚀 START / HOME / BACK BOSHQARUVI
# ==========================================================================================
@dp.message(or_f(Command("start"), F.text == Assets.ICO_HOME, F.text == Assets.ICO_BACK))
async def global_reset(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    
    # 1. Obunani tekshirish
    subscribed = await is_subscribed(bot, message.from_user.id)
    if not subscribed:
        text = (
            f"🛑 <b>DIQQAT! Botdan foydalanish cheklangan!</b>\n"
            f"{Assets.D_LINE}\n\n"
            f"Tizim xizmatlaridan foydalanish uchun quyidagi rasmiy kanallarimizga obuna bo'lishingiz majburiy.\n\n"
            f"<i>Obuna bo'lib, pastdagi <b>«✅ Obunani tasdiqlash»</b> tugmasini bosing:</i>"
        )
        await message.answer(text, reply_markup=get_subscription_keyboard(), parse_mode="HTML")
        return

    # 2. Kirish jarayoni
    await process_user_entry(message, state, message.from_user.id, message.from_user.first_name)


@dp.callback_query(F.data == "check_subscription")
async def check_sub_handler(call: CallbackQuery, state: FSMContext, bot: Bot):
    subscribed = await is_subscribed(bot, call.from_user.id)
    if not subscribed:
        await call.answer("❌ Siz hali barcha kanallarga obuna bo'lmadingiz! Iltimos, tekshirib qaytadan urinib ko'ring.", show_alert=True)
        return

    await call.message.delete()
    await process_user_entry(call.message, state, call.from_user.id, call.from_user.first_name)


# ==========================================================================================
# 📝 RO'YXATDAN O'TISH
# ==========================================================================================
@dp.message(Form.reg)
async def registration_finish(message: Message, state: FSMContext):
    fullname = message.text.strip()
    if len(fullname) < 4 or " " not in fullname:
        return await message.answer("⚠️ Iltimos, ism va familiyangizni to'liq kiriting (masalan: <i>Aliyev Vali</i>):", parse_mode="HTML")

    DB.run(
        "INSERT OR REPLACE INTO users (uid, fullname, username, joined_at) VALUES (?,?,?,?)",
        (message.from_user.id, fullname, message.from_user.username, datetime.now().isoformat())
    )
    
    success_text = (
        f"🎉 <b>Muvaffaqiyatli ro'yxatdan o'tdingiz!</b>\n"
        f"{Assets.D_LINE}\n\n"
        f"Hurmatli <b>{html.escape(fullname)}</b>, tizimga muvaffaqiyatli qo'shildingiz! 🚀\n"
        f"Endi testlar, reytinglar va AI yordamchisidan to'liq foydalana olasiz.\n\n"
        f"👇 <i>Kerakli menyuni tanlang:</i>"
    )
    
    await message.answer(
        success_text,
        parse_mode="HTML",
        reply_markup=UI.main_menu(message.from_user.id)
    )
    await state.clear()


# ==========================================================================================
# 📂 TESTLAR ARXIVI VA TOPSHIRISH
# ==========================================================================================
@dp.message(F.text == Assets.ICO_TEST)
async def test_list(message: Message):
    tests = DB.run("SELECT * FROM tests ORDER BY created_at DESC", fetch="all")
    if not tests:
        return await message.answer("📭 <b>Hozircha tizimda faol testlar mavjud emas.</b>", parse_mode="HTML")

    res_text = f"📂 <b>TIZIMDAGI FAOL TESTLAR ARXIVI</b>\n{Assets.D_LINE}\n"
    for t in tests:
        res_text += (
            f"📙 <b>{escape(t['title'])}</b>\n"
            f"└ 🔑 Test kodi: <code>{escape(t['kod'])}</code> | 🕒 {fmt_dt(t['created_at'])}\n"
            f"{Assets.S_LINE}\n"
        )
    res_text += "<i>💡 Testni topshirish va natijani tekshirish uchun quyidagi menyuda '📝 Test Topshirish' bo'limiga o'ting.</i>"
    await message.answer(res_text, parse_mode="HTML")


@dp.message(F.text == Assets.ICO_CHECK)
async def check_init(message: Message, state: FSMContext):
    await state.set_state(Form.check_code)
    await message.answer(
        "🆔 <b>TEST KODINI KIRITING</b>\n"
        f"{Assets.S_LINE}\n"
        "Iltimos, topshirmoqchi bo'lgan testingizning maxsus kodini yuboring:",
        reply_markup=UI.back_btn(),
        parse_mode="HTML"
    )


@dp.message(Form.check_code)
async def check_process(message: Message, state: FSMContext):
    test_code = message.text.strip()
    test = DB.run("SELECT * FROM tests WHERE kod=?", (test_code,), fetch="one")
    if not test:
        return await message.answer("🚫 <b>Xato kod:</b> Tizimda bunday kodli test topilmadi! Qayta urinib ko'ring.", parse_mode="HTML")

    await state.update_data(active_test=test)
    await state.set_state(Form.solve_ans)

    info = (
        f"📝 <b>TESTNING FAOL MA'LUMOTLARI</b>\n"
        f"{Assets.D_LINE}\n"
        f"📖 Fan / Mavzu: <b>{escape(test['title'])}</b>\n"
        f"🔢 Savollar soni: <b>{len(normalize_answers(test['javoblar']))} ta</b>\n"
        f"🔑 Test kodi: <code>{escape(test['kod'])}</code>\n"
        f"{Assets.S_LINE}\n"
        f"📥 <b>Javoblaringizni quyidagi formatda yuboring:</b>\n"
        f"Format: <code>abcd...</code> (masalan: <i>abcdabcd</i>)"
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
        return await message.answer("⚠️ Muammo yuz berdi. Iltimos jarayonni boshidan boshlang.")

    u_ans, t_ans, correct, mistakes = score_answers(message.text, test["javoblar"])

    if len(u_ans) != len(t_ans):
        return await message.answer(
            f"❌ <b>Soni mos kelmadi!</b>\n\n"
            f"Siz {len(u_ans)} ta javob yubordingiz, ammo testda {len(t_ans)} ta savol mavjud.\n"
            f"Iltimos, qaytadan diqqat bilan tekshirib javobingizni qayta yuboring.",
            parse_mode="HTML"
        )

    total = len(t_ans)
    perc = (correct / total) * 100 if total else 0

    rid = DB.run(
        "INSERT INTO results (uid, kod, ball, total, perc, mistakes, timestamp) VALUES (?,?,?,?,?,?,?)",
        (
            message.from_user.id,
            test["kod"],
            correct,
            total,
            perc,
            ", ".join(mistakes),
            datetime.now().isoformat()
        )
    )

    res_msg = (
        f"🏁 <b>SINOV NATIJASI</b>\n"
        f"{Assets.D_LINE}\n"
        f"👤 Nom: <b>{escape(message.from_user.full_name)}</b>\n"
        f"📊 Natija: <b>{correct} / {total} ball</b>\n"
        f"📈 Foiz ko'rsatkichi: <b>{perc:.1f} %</b>\n\n"
        f"{Assets.progress_bar(perc)}\n\n"
        f"❌ Yo'l qo'yilgan xatolar:\n"
        f"<code>{escape(', '.join(mistakes) if mistakes else 'MUKAMMAL NATIJA! BARAKALLA! 🎉')}</code>\n"
        f"{Assets.S_LINE}\n"
        f"🔖 Natija kodi: <code>#{rid}</code>"
    )
    await message.answer(res_msg, reply_markup=UI.main_menu(message.from_user.id), parse_mode="HTML")
    await state.clear()


# ==========================================================================================
# 📅 KUNLIK SINOV TESTLARI BO'LIMI
# ==========================================================================================
@dp.message(F.text == Assets.ICO_DAILY)
async def daily_test_start(message: Message, state: FSMContext):
    test = get_active_daily_test()
    if not test:
        return await message.answer(
            "📭 <b>Hozirda faol kunlik test e'lon qilinmagan.</b>\n"
            "Adminlar yangi kunlik test yuklashganda shu bo'limda faollashadi.",
            parse_mode="HTML"
        )

    await state.update_data(active_daily_test=test)
    await state.set_state(Form.daily_solve_ans)

    info = (
        f"🌟 <b>KUNLIK PREMIUM TEST</b>\n"
        f"{Assets.D_LINE}\n"
        f"📖 Mavzu: <b>{escape(test['title'])}</b>\n"
        f"🔢 Savollar soni: <b>{len(normalize_answers(test['javoblar']))} ta</b>\n"
        f"🕒 Yuklangan vaqt: <b>{fmt_dt(test['created_at'])}</b>\n"
        f"{Assets.S_LINE}\n"
        f"📥 <b>Javoblaringizni shu yerda yuboring:</b>\n"
        f"Format: <code>abcd...</code>"
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
        return await message.answer("⚠️ Kunlik test ma'lumotlari yangilangan. Iltimos qayta boshlang.")

    u_ans, t_ans, correct, mistakes = score_answers(message.text, test["javoblar"])

    if len(u_ans) != len(t_ans):
        return await message.answer(
            f"❌ <b>Soni mos kelmadi!</b>\n\n"
            f"Siz {len(u_ans)} ta javob berdingiz, ammo testda {len(t_ans)} ta savol bor."
        )

    total = len(t_ans)
    perc = (correct / total) * 100 if total else 0

    DB.run(
        """
        INSERT OR REPLACE INTO daily_results 
        (uid, kod, ball, total, perc, mistakes, timestamp) 
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            message.from_user.id,
            test["kod"],
            correct,
            total,
            perc,
            ", ".join(mistakes),
            datetime.now().isoformat()
        )
    )

    res_msg = (
        f"🏆 <b>KUNLIK TEST NATIJASI</b>\n"
        f"{Assets.D_LINE}\n"
        f"👤 Nom: <b>{escape(message.from_user.full_name)}</b>\n"
        f"📊 Ball: <b>{correct} / {total}</b>\n"
        f"📈 Foiz ko'rsatkichi: <b>{perc:.1f} %</b>\n\n"
        f"{Assets.progress_bar(perc)}\n\n"
        f"❌ Xatolar: <code>{escape(', '.join(mistakes) if mistakes else 'TABRIKLAYMIZ! XATOSIZ SINOV! 🎉')}</code>\n"
        f"{Assets.S_LINE}\n"
        f"📅 Ushbu natija kunlik reyting jadvaliga muvaffaqiyatli yozildi!"
    )
    await message.answer(res_msg, reply_markup=UI.main_menu(message.from_user.id), parse_mode="HTML")
    await state.clear()


# ==========================================================================================
# 🏆 TOP 10 FOYDALANUVCHI (MUKAMMAL REYTING TIZIMI)
# ==========================================================================================
@dp.message(F.text == Assets.ICO_TOP)
async def show_top_users(message: Message):
    # Eng yuqori o'rtacha foiz ko'rsatkichlariga ega bo'lgan foydalanuvchilar (SQL injection'ga qarshi to'liq himoyalangan)
    query = """
        SELECT u.fullname, COUNT(r.rid) as total_tests, AVG(r.perc) as avg_score
        FROM results r
        JOIN users u ON r.uid = u.uid
        GROUP BY r.uid
        ORDER BY avg_score DESC, total_tests DESC
        LIMIT 10
    """
    top_users = DB.run(query, fetch="all")
    
    if not top_users:
        return await message.answer("🏆 <b>Hali tizimda foydalanuvchilar test ishlashmagan.</b> Birinchi bo'lib natija ko'rsating!", parse_mode="HTML")

    text = (
        f"🏆 <b>TIZIMDAGI KUCHLI 10 FOYDALANUVChI</b>\n"
        f"<i>(Umumiy o'rtacha ko'rsatkichlar asosida)</i>\n"
        f"{Assets.D_LINE}\n\n"
    )
    
    for i, user in enumerate(top_users, 1):
        # Kuchli uchlik uchun maxsus kuboklar
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        icon = medals.get(i, f"<b>{i}.</b>")
        
        text += (
            f"{icon} <b>{escape(user['fullname'])}</b>\n"
            f"└  O'rtacha: <code>{user['avg_score']:.1f}%</code> | Jami: <code>{user['total_tests']} marta</code> topshirgan\n"
            f"{Assets.S_LINE}\n"
        )
        
    await message.answer(text, parse_mode="HTML")


# ==========================================================================================
# 👤 SHAXSIY KABINET VA PROFIL
# ==========================================================================================
@dp.message(F.text == Assets.ICO_PROF)
async def profile(message: Message):
    u = DB.run("SELECT * FROM users WHERE uid=?", (message.from_user.id,), fetch="one")
    if not u:
        return await message.answer("⚠️ Profilingiz aniqlanmadi. Qaytadan /start buyrug'ini yuboring.", parse_mode="HTML")

    # Jami topshirilgan testlar soni va o'rtacha ball
    stats = DB.run("SELECT COUNT(*) as cnt, AVG(perc) as av FROM results WHERE uid=?", (message.from_user.id,), fetch="one")
    cnt = stats["cnt"] if stats and stats["cnt"] else 0
    avg = stats["av"] if stats and stats["av"] else 0.0

    role_label = "Tizim Administratori 👑" if Assets.is_admin(message.from_user.id) else "Premium A'zo 💎"

    p_text = (
        f"👤 <b>SHAXSIY PROFIL MA'LUMOTLARI</b>\n"
        f"{Assets.D_LINE}\n\n"
        f"🆔 ID raqamingiz: <code>{u['uid']}</code>\n"
        f"👤 To'liq ismingiz: <b>{escape(u['fullname'])}</b>\n"
        f"🎖 Joriy status: <b>{role_label}</b>\n"
        f"📅 Ro'yxatdan o'tilgan sana: <b>{fmt_dt(u['joined_at'])}</b>\n"
        f"{Assets.S_LINE}\n"
        f"📊 <b>Sizning umumiy natijalaringiz:</b>\n"
        f"└ Topshirilgan testlar: <b>{cnt} ta</b>\n"
        f"└ O'rtacha natijangiz: <b>{avg:.1f} %</b>\n\n"
        f"<i>Barcha natijalaringiz ma'lumotlar bazasida xavfsiz holatda saqlanadi.</i>"
    )
    await message.answer(p_text, parse_mode="HTML")


@dp.message(F.text == Assets.ICO_HIS)
async def history(message: Message):
    res = DB.run(
        "SELECT * FROM results WHERE uid=? ORDER BY timestamp DESC LIMIT 10",
        (message.from_user.id,),
        fetch="all"
    )
    if not res:
        return await message.answer("<b>Siz hali biror marta ham test topshirmadingiz.</b> Natijalar shu yerda jamlanadi.", parse_mode="HTML")

    msg = f"📊 <b>OXIRGI 10 TA NATIJALARINGIZ RO'YXATI</b>\n{Assets.D_LINE}\n"
    for r in res:
        msg += (
            f"📎 <b>Kod: {escape(r['kod'])}</b> | "
            f"To'g'ri: <b>{r['ball']}/{r['total']}</b> | "
            f"<b>{r['perc']:.1f}%</b> | 🕒 {fmt_dt(r['timestamp'])}\n"
            f"{Assets.S_LINE}\n"
        )
    await message.answer(msg, parse_mode="HTML")


# ==========================================================================================
# 🆘 ADMIN ALOQA TIZIMI (MUROJAAT VA SAVOLLAR)
# ==========================================================================================
@dp.message(F.text == Assets.ICO_HELP)
async def support_start(message: Message, state: FSMContext):
    await state.set_state(Form.support)
    await message.answer(
        f"📬 <b>ADMINISTRATSIYA BILAN ALOQA</b>\n"
        f"{Assets.S_LINE}\n\n"
        f"Savol, taklif va shikoyatlaringizni batafsil yozib qoldiring.\n"
        f"Tez orada mas'ul adminlarimiz sizga bevosita bot orqali javob berishadi.\n\n"
        f"✍️ <i>Xabar matnini kiriting:</i>",
        reply_markup=UI.back_btn(),
        parse_mode="HTML"
    )


@dp.message(Form.support)
async def support_sent(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    text = message.text or ""

    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✍️ Javob yozish", callback_data=f"reply_{user_id}"))

    # Barcha adminlarga bildirishnoma yuborish
    for admin_id in Assets.ADMIN_IDS:
        if admin_id != 0:
            try:
                await bot.send_message(
                    admin_id,
                    f"🆕 <b>YANGI MUROJAAT</b>\n"
                    f"{Assets.D_LINE}\n"
                    f"👤 Kimdan: <b>{escape(user_name)}</b>\n"
                    f"🆔 ID: <code>{user_id}</code>\n"
                    f"💬 Xabar: <i>{escape(text)}</i>\n"
                    f"{Assets.D_LINE}",
                    reply_markup=kb.as_markup(),
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await message.answer(
        "✅ <b>Sizning xabaringiz adminga yetkazildi!</b>\nTez orada mas'ul admin siz bilan bog'lanadi.",
        reply_markup=UI.main_menu(message.from_user.id),
        parse_mode="HTML"
    )
    await state.clear()


@dp.callback_query(F.data.startswith("reply_"))
async def admin_reply_start(call: CallbackQuery, state: FSMContext):
    if not Assets.is_admin(call.from_user.id):
        return await call.answer("Bu funksiyadan foydalanish uchun sizda yetarli ruxsat yo'q!", show_alert=True)

    target_id = call.data.split("_", 1)[1]
    await state.update_data(reply_to=target_id)
    await state.set_state(Form.adm_reply)

    await call.message.answer(
        f"📝 <b>Foydalanuvchiga yuboriladigan javob matnini kiriting:</b>\n"
        f"User ID: <code>{target_id}</code>",
        reply_markup=UI.back_btn(),
        parse_mode="HTML"
    )
    await call.answer()


@dp.message(Form.adm_reply)
async def admin_reply_sent(message: Message, state: FSMContext):
    if not Assets.is_admin(message.from_user.id):
        return

    data = await state.get_data()
    target_id = data.get("reply_to")
    reply_text = message.text or ""

    try:
        await bot.send_message(
            int(target_id),
            f"📩 <b>ADMINISTRATSIYA JAVOBI</b>\n"
            f"{Assets.D_LINE}\n\n"
            f"{escape(reply_text)}\n\n"
            f"{Assets.D_LINE}\n"
            f"<i>Yana biror tushunarsiz holat yoki muammolar bo'lsa, qaytadan yozishingiz mumkin.</i>",
            parse_mode="HTML"
        )
        await message.answer("✅ Javobingiz foydalanuvchiga muvaffaqiyatli yetkazildi.", reply_markup=UI.admin_menu(), parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Xatolik: Xabarni yetkazishning imkoni bo'lmadi.\n<code>{escape(str(e))}</code>", parse_mode="HTML")

    await state.clear()


# ==========================================================================================
# 🧠 AI MENTOR INTEGRATSIYASI (GROQ)
# ==========================================================================================
@dp.message(F.text == Assets.ICO_AI)
async def ai_init(message: Message, state: FSMContext):
    await state.set_state(Form.ai_chat)
    await message.answer(
        f"🧠 <b>LOGOS PREMIUM AI MENTOR</b>\n"
        f"{Assets.S_LINE}\n"
        "Men sizga istalgan mavzuda yoki matematik misollarni yechishda yordam bera olaman.\n"
        "O'zingizni qiziqtirgan savolni batafsil bayon eting:",
        reply_markup=UI.back_btn(),
        parse_mode="HTML"
    )


@dp.message(Form.ai_chat)
async def ai_logic(message: Message):
    if message.text == Assets.ICO_BACK:
        return

    loading = await message.answer("🔄 <i>Sun'iy intellekt tahlil qilmoqda, biroz kuting...</i>")
    try:
        if not groq_client:
            await loading.edit_text("⚠️ <b>AI tizimi hozirda faol emas.</b> GROQ_API_KEY topilmadi.", parse_mode="HTML")
            return

        resp = groq_client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "Siz matematika va tabiiy fanlar bo'yicha aqlli va do'stona ta'lim mentorisiz. Savollarga faqat O'zbek tilida, nihoyatda aniq, tushunarli va batafsil javob bering."
                },
                {"role": "user", "content": message.text}
            ],
            model="llama-3.3-70b-versatile"
        )
        ai_reply = (
            f"🎓 <b>USTOZNING AI JAVOBI:</b>\n"
            f"{Assets.D_LINE}\n\n"
            f"{escape(resp.choices[0].message.content)}\n\n"
            f"{Assets.S_LINE}\n"
            f"<i>Yana qanday savollarga javob berishimni istaysiz?</i>"
        )
        await loading.edit_text(ai_reply, parse_mode="HTML")
    except Exception:
        await loading.edit_text("⚠️ <b>Texnik nosozlik!</b> Sun'iy intellekt bilan ulanishda xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring.", parse_mode="HTML")


# ==========================================================================================
# 🛠 MULTI-ADMIN BOSHQARUV PANELI (HAMMA ADMINLAR KIRISHI MUMKIN)
# ==========================================================================================
@dp.message(F.text == Assets.ICO_ADM)
async def admin_portal(message: Message):
    if not Assets.is_admin(message.from_user.id):
        return

    daily = get_active_daily_test()
    daily_info = (
        f"📅 <b>Kunlik faol test:</b> {escape(daily['title'])} [<code>{escape(daily['kod'])}</code>]\n"
        if daily else
        "📅 <b>Kunlik faol test:</b> e'lon qilinmagan\n"
    )

    status_bar = "🟢 TIZIM FAOL | Logos Platinum v4.9 PRO"
    await message.answer(
        f"<b>{Assets.D_LINE}</b>\n"
        f"⚡️ <b>ADMINISTRATOR BOSHQARUV PANELI</b>\n"
        f"<b>{Assets.D_LINE}</b>\n\n"
        f"👤 Profilingiz: <b>{escape(message.from_user.full_name)}</b>\n"
        f"📊 Tizim holati: <code>{escape(status_bar)}</code>\n"
        f"🕒 Joriy vaqt: <code>{datetime.now().strftime('%H:%M:%S')}</code>\n"
        f"{daily_info}\n"
        f"<i>Boshqarish uchun quyidagi menyu buyruqlaridan foydalaning:</i>",
        reply_markup=UI.admin_menu(),
        parse_mode="HTML"
    )


# --- ADMINGA YANGI TEST YARATISH BOSQICHMI-BOSQICH ---
@dp.message(F.text == Assets.ADM_ADD_TEST)
async def adm_add_start(message: Message, state: FSMContext):
    if not Assets.is_admin(message.from_user.id):
        return
    await state.set_state(Form.adm_add_kod)
    await message.answer(
        f"🧩 <b>YANGI TEST YARATISH TIZIMI</b>\n"
        f"{Assets.S_LINE}\n\n"
        f"<b>1-QADAM:</b> Yangi test uchun <b>ID KOD</b> (unique) kiriting.\n"
        f"<i>Masalan: <code>math_01</code></i>",
        reply_markup=UI.back_btn(),
        parse_mode="HTML"
    )


@dp.message(Form.adm_add_kod)
async def adm_add_k(message: Message, state: FSMContext):
    if not Assets.is_admin(message.from_user.id):
        return
    test_kod = message.text.strip()
    check = DB.run("SELECT kod FROM tests WHERE kod=?", (test_kod,), fetch="one")
    if check:
        return await message.answer("❌ <b>Bu kod band!</b> Boshqa xavfsiz va noyob kod kiriting.", parse_mode="HTML")

    await state.update_data(kod=test_kod)
    await state.set_state(Form.adm_add_title)
    await message.answer("<b>2-QADAM:</b> Sinov testi uchun sarlavha yoki mavzuni yuboring:", parse_mode="HTML")


@dp.message(Form.adm_add_title)
async def adm_add_t(message: Message, state: FSMContext):
    if not Assets.is_admin(message.from_user.id):
        return
    await state.update_data(title=message.text.strip())
    await state.set_state(Form.adm_add_ans)
    await message.answer(
        "<b>3-QADAM:</b> Ushbu testning to'g'ri javoblarini yuboring:\n"
        "📥 <i>Namuna: <code>abcdabcd...</code></i>",
        parse_mode="HTML"
    )


@dp.message(Form.adm_add_ans)
async def adm_add_a(message: Message, state: FSMContext):
    if not Assets.is_admin(message.from_user.id):
        return
    ans = normalize_answers(message.text)
    if not ans:
        return await message.answer("⚠️ To'g'ri javoblar bo'sh bo'lishi mumkin emas.", parse_mode="HTML")

    await state.update_data(ans=ans)
    await state.set_state(Form.adm_add_file)
    await message.answer(
        "<b>4-QADAM:</b> Test faylini biriktiring (PDF yoki rasm ixtiyoriy):\n"
        "➡️ <i>Faylsiz davom etish uchun: /skip buyrug'ini bering</i>",
        parse_mode="HTML"
    )


@dp.message(Form.adm_add_file)
async def adm_add_f(message: Message, state: FSMContext):
    if not Assets.is_admin(message.from_user.id):
        return

    data = await state.get_data()
    fid = message.document.file_id if message.document else None

    if not message.document and (message.text or "").strip() != "/skip":
        return await message.answer("⚠️ Iltimos, fayl yuboring yoki fayl qo'shmaslik uchun /skip yuboring.", parse_mode="HTML")

    DB.run(
        "INSERT INTO tests (kod, javoblar, file_id, title, created_at) VALUES (?,?,?,?,?)",
        (data["kod"], data["ans"], fid, data["title"], datetime.now().isoformat())
    )

    await message.answer(
        f"✨ <b>YANGI TEST TIZIMGA QO'SHILDI!</b>\n"
        f"{Assets.D_LINE}\n"
        f"📂 Mavzu: <b>{escape(data['title'])}</b>\n"
        f"🔑 Kod: <code>{escape(data['kod'])}</code>\n"
        f"✅ Jami savollar: <b>{len(data['ans'])} ta</b>\n"
        f"{Assets.D_LINE}",
        reply_markup=UI.admin_menu(),
        parse_mode="HTML"
    )
    await state.clear()


# --- ADMINGA KUNLIK TEST QO'SHISH BOSQICHMI-BOSQICH ---
@dp.message(F.text == Assets.ADM_ADD_DAILY)
async def adm_add_daily_start(message: Message, state: FSMContext):
    if not Assets.is_admin(message.from_user.id):
        return
    await state.set_state(Form.adm_add_daily_kod)
    await message.answer(
        f"🌟 <b>YANGI KUNLIK TEST QO'SHISH</b>\n"
        f"{Assets.S_LINE}\n\n"
        f"<b>1-QADAM:</b> Kunlik test uchun <b>ID KOD</b> kiriting.\n"
        f"<i>Masalan: <code>daily_01</code></i>",
        reply_markup=UI.back_btn(),
        parse_mode="HTML"
    )


@dp.message(Form.adm_add_daily_kod)
async def adm_add_daily_k(message: Message, state: FSMContext):
    if not Assets.is_admin(message.from_user.id):
        return
    await state.update_data(daily_kod=message.text.strip())
    await state.set_state(Form.adm_add_daily_title)
    await message.answer("<b>2-QADAM:</b> Kunlik test mavzusini kiriting:", parse_mode="HTML")


@dp.message(Form.adm_add_daily_title)
async def adm_add_daily_t(message: Message, state: FSMContext):
    if not Assets.is_admin(message.from_user.id):
        return
    await state.update_data(daily_title=message.text.strip())
    await state.set_state(Form.adm_add_daily_ans)
    await message.answer(
        "<b>3-QADAM:</b> To'g'ri javoblarni ketma-ket yuboring:\n"
        "📥 <i>Namuna: <code>abcdabcd</code></i>",
        parse_mode="HTML"
    )


@dp.message(Form.adm_add_daily_ans)
async def adm_add_daily_a(message: Message, state: FSMContext):
    if not Assets.is_admin(message.from_user.id):
        return
    ans = normalize_answers(message.text)
    if not ans:
        return await message.answer("⚠️ Javoblar bo'sh qolmasligi zarur.", parse_mode="HTML")

    await state.update_data(daily_ans=ans)
    await state.set_state(Form.adm_add_daily_file)
    await message.answer(
        "<b>4-QADAM:</b> Kunlik test faylini yuklang (PDF yoki rasm ixtiyoriy):\n"
        "➡️ <i>Faylsiz o'tish uchun: /skip buyrug'ini bering</i>",
        parse_mode="HTML"
    )


@dp.message(Form.adm_add_daily_file)
async def adm_add_daily_f(message: Message, state: FSMContext):
    if not Assets.is_admin(message.from_user.id):
        return

    data = await state.get_data()
    fid = message.document.file_id if message.document else None

    if not message.document and (message.text or "").strip() != "/skip":
        return await message.answer("⚠️ Iltimos, fayl yuboring yoki /skip yozing.", parse_mode="HTML")

    # Avvalgi kunlik testlar va ularning statistikasi tozalanadi
    DB.clear_daily_stats()

    DB.run(
        "INSERT INTO daily_tests (kod, javoblar, file_id, title, created_at) VALUES (?,?,?,?,?)",
        (data["daily_kod"], data["daily_ans"], fid, data["daily_title"], datetime.now().isoformat())
    )

    await message.answer(
        f"🌟 <b>YANGI KUNLIK TEST FAOLLASHTIRILDI!</b>\n"
        f"{Assets.D_LINE}\n"
        f"📂 Sarlavha: <b>{escape(data['daily_title'])}</b>\n"
        f"🔑 Kod: <code>{escape(data['daily_kod'])}</code>\n"
        f"✅ Savollar: <b>{len(data['daily_ans'])} ta</b>\n"
        f"🧹 Diqqat: Eski kunlik test natijalari butunlay tozalandi.\n"
        f"{Assets.D_LINE}",
        reply_markup=UI.admin_menu(),
        parse_mode="HTML"
    )
    await state.clear()


# --- TEST O'CHIRISH PANELI ---
@dp.message(F.text == Assets.ADM_DEL_TEST)
async def adm_del_list(message: Message):
    if not Assets.is_admin(message.from_user.id):
        return

    tests = DB.run("SELECT kod, title FROM tests ORDER BY created_at DESC", fetch="all")
    if not tests:
        return await message.answer("📂 <b>Tizimda o'chirish uchun testlar topilmadi.</b>", parse_mode="HTML")

    kb = InlineKeyboardBuilder()
    for t in tests:
        kb.row(InlineKeyboardButton(
            text=f"🗑 {t['kod']} | {t['title']}",
            callback_data=f"pre_del_{t['kod']}"
        ))

    await message.answer(
        f"⚠️ <b>TESTLARNI O'CHIRISh TIZIMI</b>\n"
        f"{Assets.S_LINE}\n"
        f"O'chirmoqchi bo'lgan testingiz ustiga bosing 👇",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("pre_del_"))
async def pre_del(call: CallbackQuery):
    if not Assets.is_admin(call.from_user.id):
        return await call.answer("Taqqiqlangan!", show_alert=True)

    kod = call.data.split("_", 2)[2]
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ TASDIQLASH", callback_data=f"confirm_del_{kod}"),
        InlineKeyboardButton(text="❌ BEKOR QILISH", callback_data="cancel_adm")
    )
    await call.message.edit_text(
        f"🛑 <b>DIQQAT! OGOH BO'LING!</b>\n\n"
        f"Siz <b>{kod}</b> kodli testni bazadan butunlay o'chirib yuborish arafasidasiz.\n"
        f"Bunga bog'liq bo'lgan barcha foydalanuvchilar natijalari o'chib ketadi!",
        reply_markup=kb.as_markup(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("confirm_del_"))
async def confirm_del(call: CallbackQuery):
    if not Assets.is_admin(call.from_user.id):
        return
    kod = call.data.split("_", 2)[2]
    DB.run("DELETE FROM tests WHERE kod=?", (kod,))
    DB.run("DELETE FROM results WHERE kod=?", (kod,))
    await call.answer("Muvaffaqiyatli o'chirildi!", show_alert=True)
    await call.message.edit_text(f"🏁 <b>{kod}</b> kodli test tizimdan muvaffaqiyatli o'chirildi.")


# --- ADMIN STATISTIKA TIZIMI ---
async def show_general_stats(message_or_call):
    tests = DB.run("SELECT kod, title FROM tests ORDER BY created_at DESC", fetch="all")
    u_count = DB.run("SELECT COUNT(*) as c FROM users", fetch="one")["c"]
    r_count = DB.run("SELECT COUNT(*) as c FROM results", fetch="one")["c"]

    res_text = (
        f"📊 <b>UMUMIY TIZIM STATISTIKASI</b>\n"
        f"{Assets.D_LINE}\n\n"
        f"👥 Ro'yxatdan o'tganlar: <b>{u_count} ta</b>\n"
        f"📝 Umumiy yechilgan testlar: <b>{r_count} marta</b>\n"
        f"{Assets.S_LINE}\n"
        f"<i>Alohid batafsil statistika olish uchun kerakli testni tanlang:</i>"
    )
    
    kb = InlineKeyboardBuilder()
    for t in tests:
        kb.row(InlineKeyboardButton(text=f"📂 {t['title']} ({t['kod']})", callback_data=f"stat_{t['kod']}"))

    if isinstance(message_or_call, Message):
        await message_or_call.answer(res_text, reply_markup=kb.as_markup(), parse_mode="HTML")
    else:
        await message_or_call.message.edit_text(res_text, reply_markup=kb.as_markup(), parse_mode="HTML")


@dp.message(F.text == Assets.ADM_STATS)
async def adm_general_stats(message: Message):
    if not Assets.is_admin(message.from_user.id):
        return
    await show_general_stats(message)


@dp.callback_query(F.data.startswith("stat_"))
async def detailed_test_stats(call: CallbackQuery):
    if not Assets.is_admin(call.from_user.id):
        return
    kod = call.data.split("_", 1)[1]
    
    results = DB.run("""
        SELECT u.fullname, COUNT(r.rid) as tries, MAX(r.ball) as m_ball, MAX(r.total) as total, MAX(r.perc) as m_perc 
        FROM results r JOIN users u ON r.uid = u.uid 
        WHERE r.kod = ? 
        GROUP BY u.uid 
        ORDER BY m_perc DESC
    """, (kod,), fetch="all")

    test = DB.run("SELECT title FROM tests WHERE kod=?", (kod,), fetch="one")
    t_name = test['title'] if test else "Noma'lum"

    if not results:
        await call.answer("Ushbu test hali hech kim tomonidan ishlanmadi!", show_alert=True)
        return

    text = (
        f"📈 <b>SINOV STATISTIKASI (BATAFSIL)</b>\n"
        f"{Assets.D_LINE}\n"
        f"🏷 Fan/Mavzu: <b>{t_name}</b>\n"
        f"🔑 Kod: <code>{kod}</code>\n"
        f"👥 Sinovdan o'tganlar: <b>{len(results)} kishi</b>\n"
        f"{Assets.S_LINE}\n\n"
    )

    for i, r in enumerate(results, 1):
        text += f"<b>{i}. {escape(r['fullname'])}</b>\n└ 🏆 Natija: {r['m_ball']}/{r['total']} ({r['m_perc']:.1f}%) | Urinishlar: {r['tries']} marta\n\n"

    if len(text) > 4000: 
        text = text[:4000] + "...\n(Ro'yxat juda uzunligi sababli qisqartirildi)"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Orqaga", callback_data="back_to_stats")]])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "back_to_stats")
async def back_to_stats_list(call: CallbackQuery):
    if not Assets.is_admin(call.from_user.id):
        return
    await show_general_stats(call)


@dp.message(F.text == Assets.ADM_DAILY_STATS)
async def adm_daily_stats(message: Message):
    if not Assets.is_admin(message.from_user.id):
        return
    results = DB.run(
        "SELECT u.fullname, r.ball, r.total, r.perc FROM daily_results r "
        "JOIN users u ON r.uid = u.uid ORDER BY r.perc DESC, r.timestamp ASC",
        fetch="all"
    )

    if not results:
        return await message.answer("📅 <b>Kunlik sinov testlari bo'yicha ma'lumotlar mavjud emas.</b>", parse_mode="HTML")

    text = f"🏆 <b>KUNLIK SINOV REYTING JADVALI</b>\n{Assets.D_LINE}\n\n"
    for i, r in enumerate(results, 1):
        icon = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🔹"
        text += f"{icon} <b>{escape(r['fullname'])}</b> - {r['ball']}/{r['total']} (<b>{r['perc']:.1f}%</b>)\n"

    await message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data == "cancel_adm")
async def cancel_adm(call: CallbackQuery):
    await call.message.edit_text("🚫 <b>Bajarilayotgan amal admin tomonidan bekor qilindi.</b>", parse_mode="HTML")


# --- BROADCAST (BARCHAGA XABAR YUBORISH) ---
@dp.message(F.text == Assets.ADM_BROADCAST)
async def broadcast_start(message: Message, state: FSMContext):
    if not Assets.is_admin(message.from_user.id):
        return
    await state.set_state(Form.adm_broadcast)
    await message.answer(
        f"📢 <b>FOYDALANUVCHILARGA XABAR YUBORISH</b>\n"
        f"{Assets.S_LINE}\n\n"
        f"Bot a'zolarining barchasiga yuborilishi kerak bo'lgan xabarni shu yerga kiritib yuboring.\n"
        f"<i>Xabar matni rasm, video yoki havolalar bilan bo'lishi mumkin.</i>",
        reply_markup=UI.back_btn(),
        parse_mode="HTML"
    )


@dp.message(Form.adm_broadcast)
async def broadcast_send(message: Message, state: FSMContext):
    if not Assets.is_admin(message.from_user.id):
        return
    
    users = DB.run("SELECT uid FROM users", fetch="all")
    msg_text = message.text or ""
    
    await message.answer("🔄 <i>Xabarlar barcha a'zolarga tarqatilmoqda, kuting...</i>", parse_mode="HTML")
    success, fail = 0, 0
    
    for u in users:
        try:
            design_msg = (
                f"✨ <b>LOGOS PLATINUM ACADEMY</b> ✨\n"
                f"{Assets.D_LINE}\n\n"
                f"{msg_text}\n\n"
                f"{Assets.D_LINE}\n"
                f"<i>Hurmat bilan, Akademiya Ma'muriyati 👑</i>"
            )
            await bot.send_message(u['uid'], design_msg, parse_mode="HTML")
            success += 1
            await asyncio.sleep(0.05)  # Telegram limitlariga qarshi xavfsizlik cheklovi
        except Exception:
            fail += 1

    await message.answer(
        f"✅ <b>Xabar barchaga muvaffaqiyatli tarqatildi!</b>\n\n"
        f"🟢 Yetkazildi: <b>{success} ta</b> foydalanuvchiga\n"
        f"🔴 Bloklaganlar / Nosoz: <b>{fail} ta</b>",
        reply_markup=UI.admin_menu(), parse_mode="HTML"
    )
    await state.clear()


# ==========================================================================================
# 🚀 ASOSIY PYHON ISHGA TUShIRISh TIZIMI
# ==========================================================================================
async def handle(request):
    return web.Response(text="Bot runs successfully on background!")

async def main():
    DB.setup()
    
    # Render va Cloud muhiti uchun kichik Web-Server (Health Check)
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 8080)))
    await site.start()

    # Bot menyu buyruqlarini telegram serveriga o'rnatish
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Botni boshlash / Yangilash")
    ])
    
    print("💎 LOGOS PLATINUM V4.9 PRO IS RUNNING ALIVE...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
