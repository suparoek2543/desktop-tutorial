from google import genai
from google.genai import types
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
DISCORD_WEBHOOK_URL = os.getenv("WEBHOOK_NOVEL_2")
NOVEL_MAIN_URL = "https://kakuyomu.jp/works/16816700429097793676"
DB_FILE = "last_ep_novel_2.txt" 

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
    def __init__(self, title, link, ep_id):
        self.title = title
        self.link = link
        self.ep_id = int(ep_id)

def get_all_episodes():
    print(f"📖 กำลังโหลดหน้าสารบัญ: {NOVEL_MAIN_URL}")
    try:
        response = scraper.get(NOVEL_MAIN_URL)
        if response.status_code != 200: 
            print(f"❌ เข้าเว็บไม่ได้ Status: {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        target_pattern = re.compile(r'/works/\d+/episodes/(\d+)')
        
        episodes = []
        seen_ids = set()
        
        raw_links = soup.find_all('a', href=target_pattern)

        for tag in raw_links:
            href = tag['href']
            match = target_pattern.search(href)
            if not match: continue
            
            ep_id = match.group(1)
            if ep_id in seen_ids: continue
            seen_ids.add(ep_id)

            full_link = "https://kakuyomu.jp" + href if href.startswith('/') else href
            
            # พยายามหาชื่อตอนให้ได้
            title = tag.text.strip()
            if not title:
                span = tag.find('span')
                title = span.text.strip() if span else f"Episode {ep_id}"

            episodes.append(Episode(title, full_link, ep_id))

        # เรียงลำดับตาม ID
        episodes.sort(key=lambda x: x.ep_id)
        
        print(f"✅ พบทั้งหมด {len(episodes)} ตอน")
        return episodes

    except Exception as e:
        print(f"❌ Error checking main page: {e}")
        return []

def get_content_with_retry(url, max_retries=3):
    """ฟังก์ชันดึงเนื้อหาแบบมี Retry (ลองใหม่ถ้าพลาด)"""
    for attempt in range(max_retries):
        try:
            response = scraper.get(url, timeout=15) # เพิ่ม timeout
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                body = soup.select_one('.widget-episodeBody')
                if body:
                    return body.get_text(separator="\n", strip=True)
            
            print(f"   ⚠️พยายามครั้งที่ {attempt+1} ล้มเหลว (Status: {response.status_code})...")
            time.sleep(2) # พักก่อนลองใหม่
            
        except Exception as e:
            print(f"   ⚠️พยายามครั้งที่ {attempt+1} Error: {e}")
            time.sleep(2)
            
    return None # ถ้าครบ 3 รอบแล้วยังไม่ได้ ให้คืนค่า None

def translate(text):
    if not text or not client: return None
    
    prompt = f"""
    คุณคือนักแปลนิยายมืออาชีพ หน้าที่ของคุณคือแปลนิยายญี่ปุ่นเรื่องนี้เป็นภาษาไทย
    
    กติกาการแปล:
    1. ขอสำนวนวัยรุ่น อ่านสนุก เป็นธรรมชาติ (เหมือนไลท์โนเวลแปลไทยลิขสิทธิ์)
    2. **สำคัญมาก:** หากพบเนื้อหาที่ล่อแหลมทางเพศ, วาบหวิว หรือรุนแรงเกินไป ให้ **"ปรับสำนวนให้ซอฟต์ลง" (Soften)** ทันที
       - ให้ใช้ "คำเลี่ยง" "คำเปรียบเปรย" หรือ "บรรยายความรู้สึก" แทนการใช้คำลามกโดยตรง
       - ห้ามหยุดแปล ให้แปลจนจบตอนโดยรักษาเนื้อเรื่องหลักไว้
    
    เนื้อหาต้นฉบับ:
    {text}
    """
    try:
        response = client.models.generate_content(
            model='gemini-2.5-pro', 
            contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"❌ Translation Error: {e}")
        return None

def send_discord(ep_num, title, link, content):
    if not DISCORD_WEBHOOK_URL: return
    
    # ส่งหัวข้อ
    requests.post(DISCORD_WEBHOOK_URL, json={
        "content": f"📚 **[ตอนที่ {ep_num}] {title}**\n🔗 {link}\n*(กำลังแปล...)*"
    })
    
    # ส่งเนื้อหา
    chunk_size = 1900
    chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
    for i, chunk in enumerate(chunks):
        msg = f"**[{i+1}/{len(chunks)}]**\n{chunk}" if len(chunks) > 1 else chunk
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
        time.sleep(1)
    
    # ส่งจบ
    requests.post(DISCORD_WEBHOOK_URL, json={"content": f"✅ **จบตอนที่ {ep_num}**"})

def send_discord_error(ep_num, title, link):
    """แจ้งเตือน Error เข้า Discord"""
    if not DISCORD_WEBHOOK_URL: return
    requests.post(DISCORD_WEBHOOK_URL, json={
        "content": f"⚠️ **[ข้ามตอนที่ {ep_num}]** เกิดข้อผิดพลาดในการดึงข้อมูล\n📖 {title}\n🔗 {link}"
    })

# ==========================================
# 🚀 Main Loop (Batch)
# ==========================================

def main():
    print("🚀 เริ่มระบบแปลย้อนหลัง (V.2 - Retry)...")
    
    all_episodes = get_all_episodes()
    
    if not all_episodes:
        print("❌ ไม่พบตอน")
        return

    # เริ่มจาก i=1 (ตอนที่ 1)
    for i, ep in enumerate(all_episodes, start=1):
        print(f"\n[{i}/{len(all_episodes)}] กำลังทำ: ตอนที่ {i} - {ep.title}")
        
        # 1. ดึงเนื้อหา (แบบ Retry)
        content = get_content_with_retry(ep.link)
        
        if not content:
            print(f"   ❌ ข้าม (ดึงเนื้อหาไม่ได้หลังจากลอง 3 รอบ)")
            send_discord_error(i, ep.title, ep.link) # แจ้ง Discord ว่าข้าม
            continue

        # 2. แปล
        print("   ⏳ แปลภาษา...")
        translated = translate(content)
        if not translated:
            print("   ❌ ข้าม (แปลไม่ผ่าน)")
            send_discord_error(i, ep.title, ep.link)
            continue

        # 3. ส่ง Discord
        print("   🚀 ส่ง Discord...")
        send_discord(i, ep.title, ep.link, translated)

        with open(DB_FILE, "w") as f:
            f.write(ep.link)

        print("   💤 พัก 30 วินาที...")
        time.sleep(30) 

    print("\n🎉 แปลครบทุกตอนแล้วครับ!")

if __name__ == "__main__":
    main()
