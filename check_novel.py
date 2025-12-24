from google import genai # <--- เรียกใช้แบบใหม่
import feedparser
import requests
from bs4 import BeautifulSoup
import time
import os

# ==========================================
# ⚙️ ส่วนตั้งค่า
# ==========================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") 
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
RSS_URL = "https://kakuyomu.jp/works/822139839754922306/rss"
DB_FILE = "last_episode_discord.txt"

# ตั้งค่า Client ใหม่
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY) # <--- สร้าง Client
else:
    print("❌ ไม่พบ GEMINI_API_KEY")
    exit(1)

# ==========================================
# 🛠️ ฟังก์ชันทำงาน
# ==========================================

def get_latest_episode():
    feed = feedparser.parse(RSS_URL)
    if feed.entries:
        return feed.entries[0]
    return None

def get_novel_content(url):
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        body_elem = soup.select_one('.widget-episodeBody')
        if body_elem:
            return body_elem.get_text(separator="\n", strip=True)
        return ""
    except Exception as e:
        print(f"❌ Error fetching content: {e}")
        return None

def translate_with_gemini(text):
    prompt = f"""
    คุณคือนักแปลนิยายไลท์โนเวลมืออาชีพ แปลเนื้อหาต่อไปนี้จากภาษาญี่ปุ่นเป็นภาษาไทย
    - ขอสำนวนวัยรุ่น อ่านง่าย สนุก เป็นธรรมชาติ
    - ไม่ต้องแปลคำทับศัพท์ที่เกมเมอร์เข้าใจ
    - จัดย่อหน้าให้อ่านง่าย
    
    เนื้อหาต้นฉบับ:
    {text}
    """
    try:
        # คำสั่งแบบใหม่ (v1.0)
        response = client.models.generate_content(
            model='gemini-1.5-flash', 
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"❌ Translation Error: {e}")
        return None

def send_to_discord(title, link, content):
    if not DISCORD_WEBHOOK_URL:
        return

    header = {
        "content": f"🚨 **ตอนใหม่มาแล้ว!** 🚨\n\n📖 **{title}**\n🔗 [อ่านต้นฉบับ]({link})\n\n🤖 กำลังแปล... รอสักครู่ครับ",
        "username": "น้องบอทนักแปล"
    }
    requests.post(DISCORD_WEBHOOK_URL, json=header)
    
    chunk_size = 1900
    chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
    
    for i, chunk in enumerate(chunks):
        msg = chunk
        if len(chunks) > 1:
            msg = f"**[Part {i+1}/{len(chunks)}]**\n{chunk}"
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg, "username": "น้องบอทนักแปล"})
        time.sleep(1)

    requests.post(DISCORD_WEBHOOK_URL, json={"content": "✅ **แปลจบตอนครับ!**", "username": "น้องบอทนักแปล"})

# ==========================================
# 🚀 Main Loop
# ==========================================

def main():
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w") as f: f.write("")

    with open(DB_FILE, "r") as f:
        last_link = f.read().strip()

    latest = get_latest_episode()
    
    if latest:
        print(f"🔍 เช็คเจอ: {latest.title}")
        if latest.link != last_link:
            print("✨ พบตอนใหม่! เริ่มดำเนินการ...")
            raw_content = get_novel_content(latest.link)
            if raw_content:
                translated_text = translate_with_gemini(raw_content)
                if translated_text:
                    send_to_discord(latest.title, latest.link, translated_text)
                    with open(DB_FILE, "w") as f:
                        f.write(latest.link)
                    print("💾 บันทึกสถานะเรียบร้อย")
        else:
            print("😴 ยังไม่มีตอนใหม่")

if __name__ == "__main__":
    main()
