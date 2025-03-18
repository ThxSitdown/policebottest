import discord
import os
import gspread
import json
import re
import logging
import threading
import requests
import time
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask
from discord.ext import commands
import datetime

# ตั้งค่า Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ตั้งค่า Discord Bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ตั้งค่า Flask App
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is running."

@app.route('/health')
def health_check():
    return {"status": "ok", "bot_status": bot.is_ready()}

def run_flask():
    try:
        logging.info("🌍 Starting Flask on port 5000...")
        app.run(host="0.0.0.0", port=5000, threaded=True)
    except Exception as e:
        logging.error(f"❌ Flask app error: {e}")

@bot.event
async def on_ready():
    logging.info(f"🤖 {bot.user} is online and ready!")
    await bot.change_presence(activity=discord.Game(name="Roblox"))

# ✅ ตั้งค่า Google Sheets
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")
sheet, log_red_case, log_black_case = None, None, None

if GOOGLE_CREDENTIALS:
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(GOOGLE_CREDENTIALS), SCOPE)
        client = gspread.authorize(creds)
        
        # เชื่อมต่อชีตหลัก "PoliceDutytest"
        sheet = client.open("PoliceDutytest").worksheet("Sheet1")
        logging.info("✅ Google Sheets (PoliceDutytest) เชื่อมต่อสำเร็จ")
        
        # เชื่อมต่อชีต "PoliceCase"
        police_case_sheet = client.open("PoliceCase")
        log_red_case = police_case_sheet.worksheet("logREDcase")
        log_black_case = police_case_sheet.worksheet("logBlackcase")
        logging.info("✅ Google Sheets (PoliceCase) เชื่อมต่อสำเร็จ")

    except Exception as e:
        logging.error(f"❌ ไม่สามารถเชื่อมต่อ Google Sheets: {e}")
else:
    logging.warning("⚠️ GOOGLE_CREDENTIALS not found.")

# ✅ ตั้งค่าห้องที่ใช้รับข้อมูล
DUTY_CHANNEL_ID = 1330215305066188864  
CASE_CHANNEL_ID = 1350960006073159802 

# ✅ ฟังก์ชันแปลงเวลาเป็นรูปแบบ DD/MM/YYYY HH:MM:SS
def format_datetime(raw_time):
    pattern = r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})"
    match = re.search(pattern, raw_time)
    
    if match:
        day, month, year, hour, minute, second = match.groups()
        formatted_time = f"{int(day):02d}/{int(month):02d}/{year} {int(hour):02d}:{int(minute):02d}:{int(second):02d}"
        logging.info(f"🕒 แปลงเวลา {raw_time} ➝ {formatted_time}")
        return formatted_time
    else:
        logging.warning(f"⚠️ รูปแบบเวลาไม่ถูกต้อง: {raw_time}")
        return raw_time

# ✅ ฟังก์ชันบันทึกข้อมูลลง Google Sheets
def save_to_sheet(sheet, values):
    try:
        last_row = len(sheet.col_values(1)) + 1
        sheet.update(f"A{last_row}:D{last_row}", [values])
        logging.info(f"✅ บันทึกลง Google Sheets: {values}")
    except Exception as e:
        logging.error(f"❌ ไม่สามารถบันทึกลง Google Sheets: {e}")

@bot.event
async def on_message(message):
    if message.author.bot:
        content = message.content.strip()

        # ✅ ตรวจสอบการบันทึกเวลางาน (PoliceDutytest)
        if message.channel.id == DUTY_CHANNEL_ID and message.author.name == "Captain Hook":
            name, steam_id, check_in_time, check_out_time = None, None, None, None

            if message.embeds:
                for embed in message.embeds:
                    for field in embed.fields:
                        if "ชื่อ" in field.name:
                            name = field.value.strip("`").strip()
                        elif "ไอดี" in field.name:
                            steam_id = field.value.strip().replace("steam:", "")
                        elif "เข้างาน" in field.name:
                            check_in_time = format_datetime(field.value.strip())
                        elif "ออกงาน" in field.name:
                            check_out_time = format_datetime(field.value.strip())

            # ใช้ Regex เป็นตัวสำรอง
            if not all([name, steam_id, check_in_time, check_out_time]):
                pattern = r"ชื่อ\s*(.+?)\s*ไอดี\s*steam:(\S+)\s*เวลาเข้างาน\s*(?:\S+\s-\s)?([\d/]+\s[\d:]+)\s*เวลาออกงาน\s*(?:\S+\s-\s)?([\d/]+\s[\d:]+)"
                match = re.search(pattern, content, re.DOTALL | re.MULTILINE | re.IGNORECASE)

                if match:
                    name = match.group(1).strip("`").strip()
                    steam_id = match.group(2).strip()
                    check_in_time = format_datetime(match.group(3).strip())
                    check_out_time = format_datetime(match.group(4).strip())

            # ✅ บันทึกลง Google Sheets ถ้าข้อมูลครบ
            if all([name, steam_id, check_in_time, check_out_time]) and sheet:
                save_to_sheet(sheet, [name, steam_id, check_in_time, check_out_time])
            else:
                logging.warning("⚠️ ข้อมูลไม่ครบถ้วน ไม่สามารถบันทึกได้!")

        # ✅ ตรวจสอบการบันทึกคดี (PoliceCase)
        elif message.channel.id == CASE_CHANNEL_ID:
            logging.info(f"📌 Raw case message: {repr(content)}")

            case_match = re.search(r"Name:\s*([^\n]+).*?ได้ทำคดี\s*([^\n]+)", content, re.DOTALL | re.IGNORECASE)
            
            if case_match:
                officer_name = case_match.group(1).strip()
                case_details = case_match.group(2).strip()
                logging.info(f"✅ Extracted case - Officer: {officer_name}, Case: {case_details}")

                if "RED" in case_details and log_red_case:
                    logging.info("🚨 RED case detected, saving to logREDcase")
                    save_to_sheet(log_red_case, [officer_name, case_details])
                elif log_black_case:
                    logging.info("📁 Black case detected, saving to logBlackcase")
                    save_to_sheet(log_black_case, [officer_name, case_details])
            else:
                logging.warning("⚠️ Case format not recognized")

    await bot.process_commands(message)

# ✅ ฟังก์ชัน Keep-Alive
KEEP_ALIVE_URL = "https://policebottest.onrender.com/health"

def keep_alive():
    while True:
        try:
            response = requests.get(KEEP_ALIVE_URL)
            if response.status_code == 200:
                logging.info("✅ Keep-alive successful.")
            else:
                logging.warning(f"⚠️ Keep-alive failed (Status: {response.status_code})")
        except Exception as e:
            logging.error(f"❌ Keep-alive error: {e}")
        time.sleep(40)

# ✅ ฟังก์ชันรันบอท
def run_discord_bot():
    DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not DISCORD_BOT_TOKEN:
        logging.error("❌ DISCORD_BOT_TOKEN not found. Bot will not start.")
        return
    
    try:
        logging.info("🚀 Starting Discord Bot...")
        bot.run(DISCORD_BOT_TOKEN)
    except discord.errors.LoginFailure:
        logging.error("❌ Invalid Discord Bot Token!")
    except Exception as e:
        logging.error(f"❌ Discord bot error: {e}")

# ✅ Main
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    run_discord_bot()
