from google import genai
from google.genai import types
import cloudscraper
import requests
from bs4 import BeautifulSoup
import time
import os
import re
import random
import json # ✅ เพิ่ม json

# ==========================================
# ⚙️ ส่วนตั้งค่า
# ==========================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") 
JSON_DB_FILE = "novels.json" # ✅ ไฟล์สำหรับหน้าเว็บ

# 🟢 รายชื่อนิยาย
NOVEL_LIST = [
    {
        "name": "เป็นความลับที่สาวสวยที่สุดในโรงเรียนและเพื่อนสมัยเด็กสุดเท่อยากจะนิสัยเสียและนอนไม่หลับเว้นแต่เธอจะอยู่ข้างๆ", 
        "url": "https://kakuyomu.jp/works/822139839754922306",
        # ใส่ Webhook URL ของเรื่องนี้ (แนะนำให้ดึงจาก Secret หรือใส่ตรงนี้ถ้า Repo เป็น Private)
        "webhook_url": os.getenv("WEBHOOK_NOVEL_1"), 
        "db_file": "last_ep_novel_1.txt" # ไฟล์จำตอนล่าสุด (ห้ามซ้ำกับเรื่องอื่น)
    },
    {
        "name": "เขาได้ทําลายทั้งครอบครัวของสาวสวยระดับ S ที่แข็งแกร่งและเติมคูน้ําด้านนอกของเธอ",
        "url": "https://kakuyomu.jp/works/822139836904500727",
        "webhook_url": os.getenv("WEBHOOK_NOVEL_2"), 
        "db_file": "last_ep_novel_2.txt"
    },
]

if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"❌ Client Error: {e}"); client = None
else:
    client = None

scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

# ==========================================
# 🛠️ ฟังก์ชันจัดการ JSON (ลงเว็บ)
# ==========================================

def translate_short(text):
    """แปลชื่อตอน/ชื่อเรื่อง"""
    if not client or not text: return text
    try:
        res = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=f"แปลชื่อนี้เป็นภาษาไทย (สั้นๆ กระชับ): {text}",
            config=types.GenerateContentConfig(safety_settings=[
                types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE')
            ])
        )
        return res.text.strip() if res.text else text
    except: return text

def save_to_json(novel_url, novel_name_thai, ep_data):
    """บันทึกตอนใหม่ลง novels.json"""
    data = {}
    if os.path.exists(JSON_DB_FILE):
        with open(JSON_DB_FILE, "r", encoding="utf-8") as f:
            try:
                content = f.read()
                if content: data = json.loads(content)
                if isinstance(data, list): data = {} 
            except: data = {}

    if novel_url not in data:
        data[novel_url] = { "title": novel_name_thai, "chapters": [] }
    
    # อัปเดตชื่อเรื่องให้เป็นปัจจุบัน
    data[novel_url]["title"] = novel_name_thai
    
    chapters = data[novel_url]["chapters"]
    existing_idx = next((index for (index, d) in enumerate(chapters) if d["link"] == ep_data["link"]), None)
    
    if existing_idx is not None:
        chapters[existing_idx] = ep_data
    else:
        chapters.append(ep_data)
        
    data[novel_url]["chapters"] = chapters

    with open(JSON_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"💾 อัปเดตเว็บแล้ว: {ep_data['title']}")

# ==========================================
# 🛠️ ฟังก์ชันหลัก
# ==========================================

class Episode:
    def __init__(self, title, link, ep_id):
        self.title = title
        self.link = link
        self.ep_id = int(ep_id)

def get_latest_episode_from_web(novel_url):
    try:
        r = scraper.get(novel_url)
        if r.status_code != 200: return None
        soup = BeautifulSoup(r.text, 'html.parser')
        
        target = re.compile(r'/works/\d+/episodes/(\d+)')
        links = soup.find_all('a', href=target)
        
        if links:
            last_ep = links[-1]
            match = target.search(last_ep['href'])
            ep_id = match.group(1) if match else 0
            title = last_ep.text.strip() or f"Episode {ep_id}"
            link = "https://kakuyomu.jp" + last_ep['href'] if last_ep['href'].startswith('/') else last_ep['href']
            return Episode(title, link, ep_id)
        return None
    except: return None

def get_content(url, main_url):
    h = {'Referer': main_url, 'Accept-Language': 'ja'}
    for _ in range(3):
        try:
            time.sleep(2)
            r = scraper.get(url, headers=h, timeout=20)
            if r.status_code == 200:
                s = BeautifulSoup(r.text, 'html.parser')
                b = s.select_one('.widget-episodeBody') or s.select_one('#contentMain-inner')
                if b: return b.get_text(separator="\n", strip=True)
        except: pass
    return None

def translate(text):
    if not text or not client: return None
    prompt = f"แปลนิยายญี่ปุ่นนี้เป็นไทย สำนวนวัยรุ่น (เจอฉากล่อแหลมให้เลี่ยงคำ):\n{text[:15000]}"
    try:
        res = client.models.generate_content(
            model='gemini-2.5-pro', contents=prompt,
            config=types.GenerateContentConfig(safety_settings=[
                types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE')
            ])
        )
        return res.text
    except: return None

def send_discord_notification(webhook_url, novel_name, ep_title, link):
    """✅ แจ้งเตือนสั้นๆ ว่ามีตอนใหม่"""
    if not webhook_url: return
    
    # URL ของหน้าเว็บเรา (ถ้ามี GitHub Pages)
    # web_url = "https://ชื่อคุณ.github.io/ชื่อrepo/"
    
    msg = {
        "content": f"🚨 **ตอนใหม่มาแล้ว!**\n📚 เรื่อง: **{novel_name}**\n📄 ตอน: **{ep_title}**\n\n🔗 ต้นฉบับ: {link}\n✨ *เนื้อหาแปลไทยอัปเดตลงเว็บแล้วครับ!*"
    }
    requests.post(webhook_url, json=msg)

# ==========================================
# 🚀 Main Process
# ==========================================

def process_novel(novel):
    print(f"\n--- 🔄 ตรวจสอบ: {novel['name']} ---")
    webhook = novel.get('webhook_url')
    db_file = novel['db_file']
    
    if not os.path.exists(db_file): open(db_file, "w").write("")
    with open(db_file, "r") as f: last_link = f.read().strip()

    latest = get_latest_episode_from_web(novel['url'])
    
    if latest:
        if latest.link != last_link:
            print(f"✨ พบตอนใหม่: {latest.title}")
            
            content = get_content(latest.link, novel['url'])
            if content:
                # 1. แปลเนื้อหา (เพื่อลงเว็บ)
                print("⏳ กำลังแปลเนื้อหา...")
                translated_content = translate(content)
                
                # 2. แปลชื่อตอน (เพื่อลงเว็บ)
                thai_ep_title = translate_short(latest.title)
                
                if translated_content:
                    # ✅ บันทึกลง JSON (Web)
                    ep_data = {
                        "ep_id": str(latest.ep_id),
                        "title": thai_ep_title,
                        "content": translated_content,
                        "link": latest.link
                    }
                    save_to_json(novel['url'], novel['name'], ep_data)
                    
                    # ✅ แจ้งเตือน Discord (Short)
                    print("🚀 แจ้งเตือน Discord...")
                    send_discord_notification(webhook, novel['name'], thai_ep_title, latest.link)
                    
                    # ✅ อัปเดต DB
                    with open(db_file, "w") as f: f.write(latest.link)
                else:
                    print("❌ แปลล้มเหลว")
            else:
                print("❌ ดึงเนื้อหาไม่ได้")
        else:
            print("😴 ยังไม่มีตอนใหม่")
    else:
        print("❌ เช็คหน้าเว็บไม่สำเร็จ")

def main():
    print("🤖 Daily Bot Checking...")
    for novel in NOVEL_LIST:
        process_novel(novel)
        print("-" * 30)

if __name__ == "__main__":
    main()
