from google import genai
from google.genai import types
import cloudscraper
import requests
from bs4 import BeautifulSoup
import time
import os
import re
import random
from urllib.parse import urljoin

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

# ตั้งค่า Scraper ให้เหมือนคนใช้คอมพิวเตอร์
scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

# ==========================================
# 🛠️ ฟังก์ชันทำงาน
# ==========================================

def get_first_episode_url():
    """หาลิงก์ตอนที่ 1 จากหน้าหลัก"""
    print(f"📖 กำลังหาตอนแรกจาก: {NOVEL_MAIN_URL}")
    try:
        response = scraper.get(NOVEL_MAIN_URL)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # หาปุ่ม "อ่านตั้งแต่ตอนแรก"
        first_ep_link = soup.select_one('a#readFromFirstEpisode')
        
        if first_ep_link:
            href = first_ep_link['href']
            full_link = urljoin(NOVEL_MAIN_URL, href)
            print(f"✅ เจอตอนแรก: {full_link}")
            return full_link
        else:
            # สำรอง: ถ้าหาปุ่มไม่เจอ ให้ลองหาลิงก์ตอนแรกสุดในสารบัญ
            target_pattern = re.compile(r'/works/\d+/episodes/\d+')
            links = soup.find_all('a', href=target_pattern)
            if links:
                href = links[0]['href'] # เอาตัวบนสุด
                full_link = urljoin(NOVEL_MAIN_URL, href)
                print(f"⚠️ ไม่เจอปุ่มหลัก แต่เจอลิงก์ในสารบัญ: {full_link}")
                return full_link
                
        print("❌ หาลิงก์ตอนแรกไม่เจอเลย")
        return None
    except Exception as e:
        print(f"❌ Error getting first episode: {e}")
        return None

def get_content_and_next_link(url, max_retries=3):
    """ดึงเนื้อหา + ชื่อตอน + ลิงก์ตอนถัดไป"""
    headers = {'Referer': NOVEL_MAIN_URL}
    
    for attempt in range(max_retries):
        try:
            time.sleep(random.uniform(2, 4)) # Delay กันโดนแบน
            response = scraper.get(url, headers=headers, timeout=20)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 1. ดึงชื่อตอน
                title_elem = soup.select_one('.widget-episodeTitle')
                title = title_elem.text.strip() if title_elem else "Unknown Title"
                
                # 2. ดึงเนื้อหา
                body = soup.select_one('.widget-episodeBody')
                content = body.get_text(separator="\n", strip=True) if body else None
                
                # 3. หาปุ่ม "ตอนถัดไป" (Next Episode)
                next_link = None
                next_btn = soup.select_one('a.widget-episode-navigation-next')
                if next_btn:
                    next_link = urljoin(url, next_btn['href'])
                
                if content:
                    return {
                        "title": title,
                        "content": content,
                        "next_link": next_link,
                        "current_url": url
                    }
            
            print(f"   ⚠️ ครั้งที่ {attempt+1} ไม่สำเร็จ (Status: {response.status_code})")
        except Exception as e:
            print(f"   ⚠️ Error: {e}")
            
    return None

def translate(text):
    if not text or not client: return None
    
    # ใช้ Prompt แบบ Soften
    prompt = f"""
    แปลนิยายญี่ปุ่นนี้เป็นไทย สำนวนวัยรุ่น อ่านสนุก (แนวไลท์โนเวล):
    
    **กฎสำคัญ:** - หากเจอฉากล่อแหลม/วูบวาบ ให้ปรับสำนวนให้ซอฟต์ลง (ใช้คำเลี่ยง/เปรียบเปรย)
    - ห้ามหยุดแปล ให้แปลจนจบตอน
    
    เนื้อหา:
    {text[:15000]} 
    """ 
    # ตัด text เผื่อยาวเกิน Token limit (Gemini รับได้เยอะแต่กันเหนียว)

    try:
        # ✅ แก้ชื่อ Model เป็นตัวที่มีอยู่จริง (1.5-flash หรือ 1.5-pro)
        response = client.models.generate_content(
            model='gemini-1.5-flash', 
            contents=prompt,
            config=types.GenerateContentConfig(
                safety_settings=[
                    types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE')
                ]
            )
        )
        return response.text
    except Exception as e:
        print(f"   ❌ Gemini Error: {e}")
        return None

def send_discord(ep_num, title, link, content):
    if not DISCORD_WEBHOOK_URL: return
    
    # Header
    requests.post(DISCORD_WEBHOOK_URL, json={
        "content": f"📚 **[ตอนที่ {ep_num}] {title}**\n🔗 {link}\n*(กำลังแปล...)*"
    })
    
    # Body
    chunk_size = 1900
    chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
    for i, chunk in enumerate(chunks):
        msg = f"**[{i+1}/{len(chunks)}]**\n{chunk}" if len(chunks) > 1 else chunk
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
        time.sleep(1)
    
    # Footer
    requests.post(DISCORD_WEBHOOK_URL, json={"content": f"✅ **จบตอนที่ {ep_num}**"})

def send_discord_error(ep_num, url, msg):
    if not DISCORD_WEBHOOK_URL: return
    requests.post(DISCORD_WEBHOOK_URL, json={
        "content": f"⚠️ **[ข้ามตอนที่ {ep_num}]** {msg}\n🔗 {url}"
    })

# ==========================================
# 🚀 Main Loop (Chain Method)
# ==========================================

def main():
    print("🚀 เริ่มระบบแปลแบบลูกโซ่ (Chain Crawling)...")
    
    # 1. เริ่มที่ตอนแรก
    current_url = get_first_episode_url()
    if not current_url:
        return

    ep_count = 1
    
    # 2. วนลูปไปเรื่อยๆ จนกว่าจะไม่มีตอนถัดไป
    while current_url:
        print(f"\n[{ep_count}] กำลังประมวลผลลิงก์: {current_url}")
        
        # ดึงข้อมูล
        data = get_content_and_next_link(current_url)
        
        if not data:
            print("   ❌ ดึงข้อมูลล้มเหลว -> ข้าม")
            send_discord_error(ep_count, current_url, "ดึงเนื้อหาไม่ได้")
            break # หยุดถ้าดึงไม่ได้ (เดี๋ยวจะวนลูปไม่รู้จบ)

        title = data['title']
        content = data['content']
        next_link = data['next_link']
        
        print(f"   📖 เรื่อง: {title}")

        # แปล
        print("   ⏳ แปลภาษา...")
        translated = translate(content)
        
        if translated:
            print("   🚀 ส่ง Discord...")
            send_discord(ep_count, title, current_url, translated)
            
            # บันทึกล่าสุด
            with open(DB_FILE, "w") as f:
                f.write(current_url)
        else:
            print("   ❌ แปลไม่ผ่าน -> ข้าม")
            send_discord_error(ep_count, current_url, "Gemini แปลไม่ผ่าน")

        # เตรียมไปตอนต่อไป
        if next_link:
            print(f"   ➡️ พบตอนถัดไป... (รอ 30 วิ)")
            current_url = next_link
            ep_count += 1
            time.sleep(30) # พักเครื่อง
        else:
            print("\n🏁 ไม่พบตอนถัดไป (จบเรื่องแล้ว หรือเป็นตอนล่าสุด)")
            current_url = None # จบลูป

    print("\n🎉 ทำงานเสร็จสิ้น!")

if __name__ == "__main__":
    main()
