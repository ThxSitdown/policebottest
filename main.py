import discord
import os
import gspread
import json
import re
import logging
import threading
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

# ตั้งค่า Google Sheets
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

# ตั้งค่าห้องที่ใช้รับข้อมูล
DUTY_CHANNEL_ID = 1330215305066188864
CASE_CHANNEL_ID = 1341326589157445652 
TAKE_CHANNEL_ID = 1351619485899030651

# ฟังก์ชันแปลงเวลาเป็นรูปแบบ DD/MM/YYYY HH:MM:SS
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

def calculate_bonus_time(start_time_str, end_time_str):
    try:
        start_dt = datetime.datetime.strptime(start_time_str, "%d/%m/%Y %H:%M:%S")
        end_dt = datetime.datetime.strptime(end_time_str, "%d/%m/%Y %H:%M:%S")

        total_bonus = datetime.timedelta()
        current = start_dt

        while current < end_dt:
            day = current.weekday()
            bonus_start = current.replace(hour=18, minute=0, second=0)

            # วันศุกร์-เสาร์-อาทิตย์ ➝ 18:00–04:00 วันถัดไป
            if day >= 4:
                bonus_end = bonus_start + datetime.timedelta(hours=10)
            else:
                bonus_end = bonus_start + datetime.timedelta(hours=6)

            if day == 6:
                logging.info(f"📅 Sunday adjustment: {bonus_start} -> {bonus_end}")

            # ช่วงเวลาที่จริงที่ทำงานและอยู่ในช่วงโบนัส
            real_start = max(current, bonus_start, start_dt)
            real_end = min(end_dt, bonus_end)

            if real_end > real_start:
                total_bonus += (real_end - real_start)

            current = current.replace(hour=0, minute=0, second=0) + datetime.timedelta(days=1)

        hours, remainder = divmod(total_bonus.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        formatted_bonus_time = f"{hours:02}:{minutes:02}:{seconds:02}"

        return formatted_bonus_time if total_bonus != datetime.timedelta() else "00:00:00"
    except Exception as e:
        logging.error(f"❌ Error calculating bonus time: {e}")
        return "00:00:00"

def save_to_sheet(sheet, values):
    try:
        last_row = len(sheet.col_values(1)) + 1  # หาค่า row ล่าสุด
        sheet.update(values=[values[:5]], range_name=f"A{last_row}:E{last_row}")
        sheet.update(values=[values[6:]], range_name=f"G{last_row}:H{last_row}")
        logging.info(f"✅ บันทึกลง Google Sheets: {values}")
    except Exception as e:
        logging.error(f"❌ ไม่สามารถบันทึกลง Google Sheets: {e}")

@bot.event
async def on_message(message):
    if message.author.bot:
        content = message.content.strip()

        # ตรวจสอบการบันทึกเวลางาน (PoliceDutytest)
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

            # บันทึกลง Google Sheets ถ้าข้อมูลครบ
            if all([name, steam_id, check_in_time, check_out_time]) and sheet:
                bonus_time = calculate_bonus_time(check_in_time, check_out_time)  # คำนวณโบนัสเวลา
                values = [name, steam_id, check_in_time, check_out_time, "", "", "", bonus_time]  # บันทึกข้อมูลพร้อม bonus_time
                save_to_sheet(sheet, values)  # บันทึกลง Google Sheets
            else:
                logging.warning("⚠️ ข้อมูลไม่ครบถ้วน ไม่สามารถบันทึกได้!")


        # ตรวจสอบการบันทึกคดี (PoliceCase)
        elif message.channel.id == CASE_CHANNEL_ID:
            logging.info(f"📌 Raw case message: {repr(content)}")

            case_match = None  # เก็บผลลัพธ์ของการตรวจสอบคดี

            # ลองดึงข้อมูลจาก Embed (ทุกฟิลด์)
            if message.embeds:
                embed = message.embeds[0]  # ดึงเฉพาะ Embed แรก
                embed_data = f"📌 Embed Data - Title: {embed.title}, Desc: {embed.description}, Fields: {[{'name': f.name, 'value': f.value} for f in embed.fields]}"
                logging.info(embed_data)

                # รวมข้อมูลจากทุกฟิลด์เป็นข้อความเดียว
                embed_text = f"{embed.title}\n{embed.description}\n" + "\n".join([f"{f.name}: {f.value}" for f in embed.fields])

                # ลองค้นหา "ได้ทำคดี" จาก Embed
                case_match = re.search(r"Name:\s*([^\n]+).*?ได้ทำคดี\s*([^\n]+)", embed_text, re.DOTALL | re.IGNORECASE)

            # บันทึกข้อมูลหากตรงรูปแบบ
            if case_match:
                officer_name = case_match.group(1).strip()
                case_details = case_match.group(2).strip()

                officer_name = re.sub(r"\*\*", "", officer_name).strip()

                case_details = re.split(r"\s*ใส่\s*", case_details)[0]
                logging.info(f"✅ Extracted case - Officer: {officer_name}, Case: {case_details}")

                if re.search(r"\bred\b", case_details, re.IGNORECASE) and log_red_case:
                    logging.info("🚨 RED case detected, saving to logREDcase")
                    save_to_sheet(log_red_case, [officer_name, case_details])
                elif log_black_case:
                    logging.info("📁 Black case detected, saving to logBlackcase")
                    save_to_sheet(log_black_case, [officer_name, case_details])
            else:
                logging.warning("⚠️ Case format not recognized")

        
        # Take2 Channel
    elif message.channel.id == TAKE_CHANNEL_ID:
        logging.info(f"📌 รับข้อความจาก Take2 Channel: {repr(message.content)}")

        take_sheet = police_case_sheet.worksheet("Take2")  # ดึงชีต Take2

        # บันทึกข้อมูลลง Google Sheets
        if take_sheet:
            save_to_sheet(take_sheet, [message.author.display_name, message.content])
            logging.info(f"✅ บันทึกลง Take2: {message.author.display_name} - {message.content}")
        else:
            logging.error("❌ ไม่สามารถเข้าถึงชีต Take2")

    await bot.process_commands(message)

# ฟังก์ชันรันบอท
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

# Main
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    run_discord_bot()
