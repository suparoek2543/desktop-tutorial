from google import genai
from google.genai import types
import cloudscraper
import requests
from bs4 import BeautifulSoup
import time
import os
import re
import random
import json
from urllib.parse import urljoin

# ==========================================
# ⚙️ ส่วนตั้งค่า
# ==========================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") 
JSON_DB_FILE = "novels.json"

# 🟢 รายชื่อนิยาย
NOVEL_LIST = [
    {
        "name": "เป็นความลับที่สาวสวยที่สุดในโรงเรียนและเพื่อนสมัยเด็กสุดเท่อยากจะนิสัยเสียและนอนไม่หลับเว้นแต่เธอจะอยู่ข้างๆ", 
        "url": "https://kakuyomu.jp/works/822139839754922306",
        "webhook_url": os.getenv("WEBHOOK_NOVEL_1"), 
        "db_file": "last_ep_novel_1.txt"
    },
    {
        "name": "เขาได้ทําลายทั้งครอบครัวของสาวสวยระดับ S ที่แข็งแกร่งและเติมคูน้ําด้านนอกของเธอ",
        "url": "https://kakuyomu.jp/works/822139836904500727",
        "webhook_url": os.getenv("WEBHOOK_NOVEL_2"), 
        "db_file": "last_ep_novel_2.txt"
    },
        {
        "name": "เพื่อนสมัยเด็กที่ต้องการได้รับการปรนเปรอเข้ามาหาฉันพร้อมและต้องการจูบฉัน",
        "url": "https://kakuyomu.jp/works/1177354054897649731",
        "webhook_url": os.getenv("WEBHOOK_NOVEL_3"), 
        "db_file": "last_ep_novel_3.txt"
    }
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
# 🛠️ ฟังก์ชันแปลภาษา (Smart System V.3)
# ==========================================

def translate_title(text):
    if not client or not text: return text
    prompt = f"""
    Translate this Japanese novel title to Thai.
    Style: Catchy, Short, Natural (Teenager/Light Novel style).
    Strict Rules: Output ONLY the translated text. No explanations.
    Original: {text}
    """
    try:
        res = client.models.generate_content(
            model='gemini-1.5-flash', contents=prompt,
            config=types.GenerateContentConfig(safety_settings=[
                types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE')
            ])
        )
        return res.text.strip().replace('"', '') if res.text else text
    except: return text

def translate_smart(text, retry_count=0):
    if not client or not text: return None, "Error"
    
    # --- 🛡️ กลยุทธ์ 1-3: พยายามแปลทั้งก้อน ---
    prompts = [
        # รอบ 0: ปกติ
        f"แปลนิยายญี่ปุ่นนี้เป็นไทย สำนวนวัยรุ่น (เก็บอารมณ์ครบ):\n{text[:15000]}",
        # รอบ 1: Soften
        f"แปลโดยเลี่ยงคำล่อแหลมและรุนแรง (Soft Version):\n{text[:15000]}",
        # รอบ 2: Summary
        f"สรุปเนื้อเรื่องตอนนี้เป็นภาษาไทย (ตัดฉากเรททิ้ง เล่าแค่เหตุการณ์):\n{text[:15000]}"
    ]

    if retry_count < 3:
        try:
            prompt = prompts[retry_count]
            if retry_count > 0: print(f"   🔧 แก้เกมรอบที่ {retry_count}...")
            
            res = client.models.generate_content(
                model='gemini-1.5-flash', 
                contents=prompt,
                config=types.GenerateContentConfig(safety_settings=[
                    types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE')
                ])
            )
            if res.text and res.text.strip(): return res.text, None
        except Exception as e:
            if "429" in str(e): time.sleep(10); return translate_smart(text, retry_count)
            pass 
        
        time.sleep(2)
        return translate_smart(text, retry_count + 1)

    # --- ⚔️ กลยุทธ์ 4 (ไม้ตาย): หั่นครึ่งแล้วแปล (Split Mode) ---
    if retry_count == 3:
        print("   ⚔️ ไม้ตายสุดท้าย: หั่นครึ่งแล้วแปล (Split Mode)...")
        try:
            mid = len(text) // 2
            part1 = text[:mid]
            part2 = text[mid:]
            
            # เรียกตัวเองซ้ำด้วยโหมด Soften (1)
            res1, _ = translate_smart(part1, retry_count=1)
            res2, _ = translate_smart(part2, retry_count=1)
            
            # ถ้ารอดทั้งคู่ หรือรอดบ้าง ก็เอามารวมกัน
            full_text = ""
            full_text += (res1 if res1 else "⚠️ [ส่วนแรกแปลไม่ผ่าน]") + "\n\n--- (ต่อ) ---\n\n"
            full_text += (res2 if res2 else "⚠️ [ส่วนหลังแปลไม่ผ่าน]")
            
            return full_text, None
        except Exception as e:
            print(f"   ❌ Split Mode Failed: {e}")

    # ถ้าหลุดมาถึงตรงนี้คือไม่ไหวแล้ว
    fallback = "⚠️ เนื้อหาตอนนี้แรงเกินไป ระบบไม่สามารถแปลได้ (กรุณาอ่านต้นฉบับ)"
    return fallback, None

# ==========================================
# 🛠️ ฟังก์ชันจัดการ JSON & Notification
# ==========================================

def save_to_json(novel_url, novel_name_thai, ep_data):
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

def send_discord_notification(webhook_url, novel_name, ep_title, link):
    if not webhook_url: return
    msg = {
        "content": f"🚨 **ตอนใหม่มาแล้ว!**\n📚 เรื่อง: **{novel_name}**\n📄 ตอน: **{ep_title}**\n\n🔗 ต้นฉบับ: {link}\n✨ *เนื้อหาแปลไทยอัปเดตลงเว็บแล้วครับ!*"
    }
    requests.post(webhook_url, json=msg)

# ==========================================
# 🛠️ Crawler Logic
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
                print("⏳ กำลังแปลเนื้อหา...")
                # 🟢 ใช้ translate_smart (มี Split Mode)
                translated_content, error_msg = translate_smart(content)
                
                if translated_content:
                    print("⏳ กำลังแปลชื่อตอน...")
                    thai_ep_title = translate_title(latest.title)
                    
                    # ตรวจสอบว่าเป็นข้อความแจ้งเตือนความล้มเหลวหรือไม่
                    is_safety_error = "⚠️" in translated_content and "ไม่สามารถแปลได้" in translated_content
                    
                    # ✅ บันทึกลงเว็บ (JSON) เสมอ (คนอ่านจะได้เห็นว่ามีตอนใหม่ แม้จะแปลไม่ได้)
                    ep_data = {
                        "ep_id": str(latest.ep_id),
                        "title": thai_ep_title,
                        "content": translated_content,
                        "link": latest.link
                    }
                    save_to_json(novel['url'], novel['name'], ep_data)
                    
                    # ✅ แจ้งเตือน Discord
                    print("🚀 แจ้งเตือน Discord...")
                    send_discord_notification(webhook, novel['name'], thai_ep_title, latest.link)
                    
                    # ✅ ตัดสินใจเรื่องการจำค่า (DB)
                    if is_safety_error:
                        print("   ⚠️ ติด Safety -> ไม่บันทึกสถานะล่าสุด (เพื่อให้รอบหน้าลองใหม่)")
                    else:
                        print("   ✅ แปลสำเร็จ -> บันทึกสถานะล่าสุด")
                        with open(db_file, "w") as f: f.write(latest.link)
                        
                else:
                    print(f"❌ แปลล้มเหลว: {error_msg}")
            else:
                print("❌ ดึงเนื้อหาไม่ได้")
        else:
            print("😴 ยังไม่มีตอนใหม่")
    else:
        print("❌ เช็คหน้าเว็บไม่สำเร็จ")

def main():
    print("🤖 Daily Bot Checking (Smart V.3 + Split Mode)...")
    for novel in NOVEL_LIST:
        process_novel(novel)
        print("-" * 30)

if __name__ == "__main__":
    main()
