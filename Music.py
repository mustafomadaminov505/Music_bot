#!/usr/bin/env python3
"""
Telegram musiqa bot (synchronous, pyTelegramBotAPI).
Xususiyatlar:
- YouTube qidiruv (yt-dlp)
- Tanlangan video/trackni yuklab olish
- Agar ffmpeg mavjud bo'lsa MP3ga konvert qilish
- Agar ffmpeg bo'lmasa original audio faylni yuborish yoki document sifatida yuborish
- 50 MB bot yuklash limitini tekshirish
- Vaqtinchalik fayllarni tozalash
"""

import os
import logging
import shutil
import glob
from pathlib import Path
import yt_dlp
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

# =========== Sozlamalar ===========
DOWNLOAD_DIR = Path("downloads")
BOT_TOKEN = "8999686153:AAHW4NX-ULWT-3Q_BsxE8d0KrL1pXQr0FQs"
TELEGRAM_BOT_UPLOAD_LIMIT_MB = 50.0  # taxminiy limit (botlar uchun odatda 50MB)
# ===================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN)

# Foydalanuvchi qidiruv natijalarini saqlash (oddiy in-memory)
user_search_results = {}

def find_ffmpeg():
    """ffmpeg va ffprobe ni qidiradi. Yo'li topilsa dict qaytaradi, aks holda None."""
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    if ffmpeg_path and ffprobe_path:
        return {"ffmpeg": ffmpeg_path, "ffprobe": ffprobe_path}
    return None

@bot.message_handler(commands=["start"])
def start(message):
    user_name = message.from_user.first_name or "Foydalanuvchi"
    welcome_text = (
        f"✨ Assalomu alaykum, {user_name}!\n\n"
        "🎵 Musiqa qidirish va yuklab olish botiga xush kelibsiz!\n\n"
        "🔍 Menga qo'shiq nomi yoki ijrochini yozing."
    )
    bot.send_message(message.chat.id, welcome_text)

@bot.message_handler(content_types=["text"])
def search_music(message):
    query = message.text.strip()
    if not query or query.startswith("/"):
        return
    status = bot.send_message(message.chat.id, f"🔎 \"{query}\" bo'yicha qidirilmoqda...")
    try:
        ydl_opts = {
            "extract_flat": True,
            "skip_download": True,
            "default_search": "ytsearch8",
            "quiet": True,
            "no_warnings": True,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch8:{query}", download=False)
            entries = info.get("entries", []) if isinstance(info, dict) else []

        if not entries:
            bot.edit_message_text("❌ Hech narsa topilmadi. Boshqa so'z bilan urinib ko'ring.", message.chat.id, status.message_id)
            return

        keyboard = InlineKeyboardMarkup(row_width=1)
        user_search_results[message.chat.id] = {}

        for idx, entry in enumerate(entries):
            title = entry.get("title", "Musiqa")
            video_id = entry.get("id")
            btn_text = f"🎶 {title[:60]}"
            cb_data = f"music_{idx}"
            user_search_results[message.chat.id][str(idx)] = {
                "id": video_id,
                "title": title,
            }
            keyboard.add(InlineKeyboardButton(text=btn_text, callback_data=cb_data))

        bot.edit_message_text(
            f"🎶 Qidiruv natijalari:\nSo'rov: {query}\n\nKerakli musiqani tanlang:",
            message.chat.id,
            status.message_id,
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.exception("Qidiruv xatosi")
        try:
            bot.edit_message_text("❌ Qidiruvda xatolik yuz berdi. Iltimos, qayta urinib ko'ring.", message.chat.id, status.message_id)
        except Exception:
            pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("music_"))
def handle_download(call):
    idx = call.data.split("_", 1)[1]
    chat_id = call.message.chat.id

    if chat_id not in user_search_results or idx not in user_search_results[chat_id]:
        bot.answer_callback_query(call.id, "⚠️ Qidiruv natijasi eskirgan. Qayta qidiring.", show_alert=True)
        return

    music = user_search_results[chat_id][idx]
    video_id = music["id"]
    title = music["title"]

    bot.answer_callback_query(call.id, "⏳ Yuklanmoqda, iltimos kuting...")
    status_msg = bot.send_message(chat_id, f"📥 {title}\nYuklanmoqda...")

    DOWNLOAD_DIR.mkdir(exist_ok=True)

    # ffmpeg mavjudligini tekshirish
    ff = find_ffmpeg()
    if ff:
        logger.info(f"FFmpeg topildi: {ff['ffmpeg']}")
    else:
        logger.info("FFmpeg topilmadi — konvertatsiya qilinmaydi, original audio yuboriladi.")

    # YTDLP sozlamalari
    # outtmpl video id asosida saqlashni kafolatlaydi (oson topish uchun)
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(DOWNLOAD_DIR / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }

    # Agar ffmpeg bo'lsa, postprocessor qo'shamiz (MP3)
    if ff:
        # ffmpeg_location kutubxonaning to'liq katalogi bo'lishi mumkin
        ffmpeg_dir = os.path.dirname(ff["ffmpeg"])
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
        # yt-dlp parametr sifatida "ffmpeg_location" qabul qiladi:
        ydl_opts["ffmpeg_location"] = ffmpeg_dir

    url = f"https://www.youtube.com/watch?v={video_id}"
    downloaded_file = None

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # prepare_filename bazaviy nomni beradi (asl ext bilan)
            base = ydl.prepare_filename(info)
            # Agar mp3 konvert qilingan bo'lsa .mp3 ni kutamiz
            if ff:
                candidate = os.path.splitext(base)[0] + ".mp3"
                if os.path.exists(candidate):
                    downloaded_file = candidate
                else:
                    # Ba'zan postprocessor nomini boshqa joyga yoki boshqacha qiladi — glob qidiramiz
                    pattern = str(DOWNLOAD_DIR / f"{video_id}.*")
                    matches = glob.glob(pattern)
                    if matches:
                        downloaded_file = matches[0]
            else:
                # ffmpeg yo'q: original fayl (m4a, webm, mp4) bo'ladi
                pattern = str(DOWNLOAD_DIR / f"{video_id}.*")
                matches = glob.glob(pattern)
                if matches:
                    downloaded_file = matches[0]

        if not downloaded_file or not os.path.exists(downloaded_file):
            raise FileNotFoundError("Yuklangan fayl topilmadi.")

        # Hajm tekshiruvi
        size_mb = os.path.getsize(downloaded_file) / (1024 * 1024)
        logger.info(f"Yuklangan fayl: {downloaded_file} ({size_mb:.2f} MB)")

        if size_mb > TELEGRAM_BOT_UPLOAD_LIMIT_MB:
            # Juda katta — link yuborish yoki document sifatida yuborish (document ham katta bo'lsa bo'lmaydi)
            bot.edit_message_text(
                f"⚠️ Fayl juda katta ({size_mb:.1f} MB). Bot orqali yuborib bo'lmaydi. Mana YouTube havolasi:\n{url}",
                chat_id,
                status_msg.message_id,
            )
            return

        # Faylni yuborish: avvalo send_audio qilib ko'ramiz; muammo bo'lsa send_document
        sent = False
        try:
            with open(downloaded_file, "rb") as f:
                # send_audio qabul qiladigan formatlarga MP3, M4A, OGG kiradi — agar xato bo'lsa exceptga tushadi
                bot.send_audio(
                    chat_id,
                    f,
                    title=title,
                    caption=f"🎧 {title}"
                )
                sent = True
        except Exception as send_exc:
            logger.warning("send_audio bilan yuborishda xatolik, document sifatida yuboriladi: %s", send_exc)
            try:
                with open(downloaded_file, "rb") as f:
                    bot.send_document(chat_id, f, caption=f"🎧 {title}")
                    sent = True
            except Exception as doc_exc:
                logger.exception("send_document ham xato berdi")
                raise doc_exc

        if sent:
            try:
                bot.delete_message(chat_id, status_msg.message_id)
            except Exception:
                pass

    except Exception as e:
        logger.exception("Yuklash yoki yuborishda xato")
        try:
            bot.edit_message_text("❌ Yuklashda xatolik yuz berdi. Iltimos, boshqa qo'shiqni tanlang.", chat_id, status_msg.message_id)
        except Exception:
            pass
    finally:
        # Tozalash: video_id bilan boshlanuvchi barcha fayllarni o'chiramiz
        try:
            for p in DOWNLOAD_DIR.glob(f"{video_id}.*"):
                try:
                    p.unlink()
                except Exception as ex:
                    logger.warning("Faylni o'chirishda xato: %s", ex)
        except Exception as ex:
            logger.warning("Tozalash jarayonida xato: %s", ex)

if __name__ == "__main__":
    logger.info("Bot ishga tushmoqda...")
    try:
        bot.infinity_polling(skip_pending=True)
    except KeyboardInterrupt:
        logger.info("To'xtatildi (KeyboardInterrupt).")
    except Exception:
        logger.exception("Bot pollingda xato yuz berdi.")