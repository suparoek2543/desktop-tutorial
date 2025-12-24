from google import genai
from google.genai import types # <--- เพิ่มตัวนี้เพื่อตั้งค่า Safety
import cloudscraper
import requests
from bs4 import BeautifulSoup
import time
import os
import re

# ==========================================
# ⚙️ ส่วนตั้งค่า
# ==========================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") 
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
NOVEL_MAIN_URL = "https://kakuyomu.jp/works/822139839754922306"
DB_FILE = "last_episode_discord.txt" 

# ตั้งค่า Client
if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"❌ Error initializing Client: {e}")
        client = None
else:
    print("⚠️ ไม่พบ GEMINI_API_KEY")
    client = None

scraper = cloudscraper.create_scraper()

# ==========================================
# 🛠️ ฟังก์ชันทำงาน
# ==========================================

class Episode:
    def __init__(self, title, link):
        self.title = title
        self.link = link

def get_all_episodes():
    print(f"📖 กำลังโหลดหน้าสารบัญ: {NOVEL_MAIN_URL}")
    try:
        response = scraper.get(NOVEL_MAIN_URL)
        if response.status_code != 200: 
            print(f"❌ เข้าเว็บไม่ได้ Status: {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        target_pattern = re.compile(r'/works/\d+/episodes/\d+')
        raw_links = soup.find_all('a', href=target_pattern)
        
        episodes = []
        seen_urls = set()

        for tag in raw_links:
            href = tag['href']
            full_link = "https://kakuyomu.jp" + href if href.startswith('/') else href
            
            if full_link in seen_urls: continue
            seen_urls.add(full_link)

            title = tag.text.strip()
            if not title:
                span = tag.find('span')
                title = span.text.strip() if span else "ตอนที่ (ไม่ทราบชื่อ)"

            episodes.append(Episode(title, full_link))

        print(f"✅ พบทั้งหมด {len(episodes)} ตอน")
        return episodes

    except Exception as e:
        print(f"❌ Error checking main page: {e}")
        return []

def get_content(url):
    try:
        response = scraper.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        body = soup.select_one('.widget-episodeBody')
        return body.get_text(separator="\n", strip=True) if body else None
    except Exception as e:
        print(f"   ❌ Error content: {e}")
        return None

def translate(text):
    if not text or not client: return None
    
    prompt = f"แปลนิยายญี่ปุ่นนี้เป็นไทย สำนวนวัยรุ่น อ่านง่าย:\n{text}"
    
    try:
        # ✅ ตั้งค่า Safety Settings เป็น BLOCK_NONE (ปิดตัวกรอง)
        # เพื่อให้นิยายผ่านได้สะดวกขึ้น
        response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=prompt,
            config=types.GenerateContentConfig(
                safety_settings=[
                    types.SafetySetting(
                        category='HARM_CATEGORY_HARASSMENT',
                        threshold='BLOCK_NONE'
                    ),
                    types.SafetySetting(
                        category='HARM_CATEGORY_HATE_SPEECH',
                        threshold='BLOCK_NONE'
                    ),
                    types.SafetySetting(
                        category='HARM_CATEGORY_SEXUALLY_EXPLICIT',
                        threshold='BLOCK_NONE'
                    ),
                    types.SafetySetting(
                        category='HARM_CATEGORY_DANGEROUS_CONTENT',
                        threshold='BLOCK_NONE'
                    )
                ]
            )
        )
        return response.text
    except Exception as e:
        # ✅ ปริ้นท์ Error ตัวจริงออกมาดูว่าเกิดอะไรขึ้น
        print(f"   ❌ Gemini Error: {e}")
        return None

def send_discord(title, link, content):
    if not DISCORD_WEBHOOK_URL: return
    
    requests.post(DISCORD_WEBHOOK_URL, json={
        "content": f"📚 **[แปลย้อนหลัง]**\n**{title}**\n🔗 {link}\n*(กำลังแปล...)*"
    })
    
    chunk_size = 1900
    chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
    for i, chunk in enumerate(chunks):
        msg = f"**[{i+1}/{len(chunks)}]**\n{chunk}" if len(chunks) > 1 else chunk
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
        time.sleep(1)
    
    requests.post(DISCORD_WEBHOOK_URL, json={"content": "✅ **จบตอน**"})

# ==========================================
# 🚀 Main Loop (Batch)
# ==========================================

def main():
    print("🚀 เริ่มระบบแปลย้อนหลัง (Batch Translation)...")
    
    all_episodes = get_all_episodes()
    
    if not all_episodes:
        print("❌ ไม่พบตอน หรือเว็บเข้าไม่ได้")
        return

    for i, ep in enumerate(all_episodes):
        print(f"\n[{i+1}/{len(all_episodes)}] กำลังทำ: {ep.title}")
        
        content = get_content(ep.link)
        if not content:
            print(f"   ❌ ข้าม (ดึงเนื้อหาไม่ได้): {ep.link}")
            continue

        print("   ⏳ แปลภาษา...")
        translated = translate(content)
        if not translated:
            print("   ❌ ข้าม (แปลไม่ผ่าน - ดู Error ด้านบน)")
            continue

        print("   🚀 ส่ง Discord...")
        send_discord(ep.title, ep.link, translated)

        with open(DB_FILE, "w") as f:
            f.write(ep.link)

        print("   💤 พัก 30 วินาที...")
        time.sleep(30) 

    print("\n🎉 แปลครบทุกตอนแล้วครับ!")

if __name__ == "__main__":
    main()
