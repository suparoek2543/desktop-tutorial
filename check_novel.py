import google.generativeai as genai
import feedparser
import requests
from bs4 import BeautifulSoup
import time
import os

# ==========================================
# ⚙️ ส่วนตั้งค่า (รับค่าจาก GitHub Secrets)
# ==========================================
# ระบบจะดึง Key จากตู้เซฟของ GitHub มาใช้เอง อัตโนมัติ
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") 
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
RSS_URL = "https://kakuyomu.jp/works/822139839754922306/rss"
DB_FILE = "last_episode_discord.txt"

# ตั้งค่า Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    print("❌ ไม่พบ GEMINI_API_KEY กรุณาตั้งค่าใน GitHub Secrets")
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
    - ไม่ต้องแปลคำทับศัพท์ที่เกมเมอร์เข้าใจ (เช่น สเตตัส, สกิล)
    - จัดย่อหน้าให้อ่านง่าย
    
    เนื้อหาต้นฉบับ:
    {text}
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"❌ Translation Error: {e}")
        return None

def send_to_discord(title, link, content):
    if not DISCORD_WEBHOOK_URL:
        print("❌ ไม่พบ DISCORD_WEBHOOK_URL")
        return

    # 1. แจ้งเตือนหัวข้อ
    header = {
        "content": f"🚨 **ตอนใหม่มาแล้ว!** 🚨\n\n📖 **{title}**\n🔗 [อ่านต้นฉบับ]({link})\n\n🤖 กำลังแปล... รอสักครู่ครับ",
        "username": "น้องบอทนักแปล"
    }
    requests.post(DISCORD_WEBHOOK_URL, json=header)
    
    # 2. แบ่งส่งเนื้อหา (Discord รับได้ 2000 ตัวอักษร เราตัดที่ 1900)
    chunk_size = 1900
    chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
    
    for i, chunk in enumerate(chunks):
        msg = chunk
        if len(chunks) > 1:
            msg = f"**[Part {i+1}/{len(chunks)}]**\n{chunk}"
            
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg, "username": "น้องบอทนักแปล"})
        time.sleep(1) # พักกันโดนบล็อก

    # 3. จบ
    requests.post(DISCORD_WEBHOOK_URL, json={"content": "✅ **แปลจบตอนครับ!**", "username": "น้องบอทนักแปล"})

# ==========================================
# 🚀 Main Loop
# ==========================================

def main():
    # สร้างไฟล์ DB เปล่าๆ ถ้ายังไม่มี (ป้องกัน error ครั้งแรก)
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
                    
                    # อัปเดตลิงก์ล่าสุด
                    with open(DB_FILE, "w") as f:
                        f.write(latest.link)
                    print("💾 บันทึกสถานะเรียบร้อย")
        else:
            print("😴 ยังไม่มีตอนใหม่")

if __name__ == "__main__":
    main()
