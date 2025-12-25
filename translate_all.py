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

# ตั้งค่า Scraper
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
            print(f"✅ เจอตอนแรก (ปุ่มเหลือง): {full_link}")
            return full_link
        else:
            # สำรอง: ลองหาลิงก์ในสารบัญตัวแรกสุด
            target_pattern = re.compile(r'/works/\d+/episodes/\d+')
            links = soup.find_all('a', href=target_pattern)
            if links:
                # เรียงลำดับแล้วเอาตัวแรก (เผื่อเว็บเรียงกลับด้าน)
                # ปกติ Kakuyomu ลิงก์ตอน ID น้อย = ตอนแรก
                sorted_links = sorted(links, key=lambda x: int(re.search(r'episodes/(\d+)', x['href']).group(1)))
                href = sorted_links[0]['href']
                full_link = urljoin(NOVEL_MAIN_URL, href)
                print(f"⚠️ ไม่เจอปุ่มหลัก แต่เจอในสารบัญ: {full_link}")
                return full_link
                
        print("❌ หาลิงก์ตอนแรกไม่เจอเลย")
        return None
    except Exception as e:
        print(f"❌ Error getting first episode: {e}")
        return None

def find_next_link(soup, current_url):
    """ฟังก์ชันหาปุ่ม Next แบบอัจฉริยะ (หาทุกซอกทุกมุม)"""
    next_link = None
    
    # วิธีที่ 1: หาปุ่มลูกศรขวา (ปกติ)
    next_btn = soup.select_one('a.widget-episode-navigation-next')
    
    # วิธีที่ 2: หาปุ่มใหญ่ "อ่านตอนต่อไป" (id="contentMain-readNextEpisode")
    if not next_btn:
        next_btn = soup.select_one('a#contentMain-readNextEpisode')
        
    # วิธีที่ 3: หาจาก Text คำว่า "次のエピソード" (เผื่อ Class เปลี่ยน)
    if not next_btn:
        next_btn = soup.find('a', string=re.compile('次のエピソード'))
        
    if next_btn:
        try:
            return urljoin(current_url, next_btn['href'])
        except:
            return None
            
    return None

def get_content_and_next_link(url, max_retries=3):
    headers = {'Referer': NOVEL_MAIN_URL}
    
    for attempt in range(max_retries):
        try:
            time.sleep(random.uniform(2, 4))
            response = scraper.get(url, headers=headers, timeout=20)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                title_elem = soup.select_one('.widget-episodeTitle')
                title = title_elem.text.strip() if title_elem else "Unknown Title"
                
                body = soup.select_one('.widget-episodeBody')
                content = body.get_text(separator="\n", strip=True) if body else None
                
                # ✅ ใช้ฟังก์ชันใหม่หาปุ่ม Next
                next_link = find_next_link(soup, url)
                
                if content:
                    return {
                        "title": title,
                        "content": content,
                        "next_link": next_link
                    }
                else:
                    # ถ้าหาเนื้อหาไม่เจอ ให้ลองเซฟ HTML มาดู (Debug)
                    if attempt == max_retries - 1:
                        with open("debug_error.html", "w", encoding="utf-8") as f:
                            f.write(response.text)
                        print("⚠️ หาเนื้อหาไม่เจอ (บันทึก debug_error.html แล้ว)")

            print(f"   ⚠️ ครั้งที่ {attempt+1} ไม่สำเร็จ (Status: {response.status_code})")
        except Exception as e:
            print(f"   ⚠️ Error: {e}")
            
    return None

def translate(text):
    if not text or not client: return None
    
    prompt = f"""
    แปลนิยายญี่ปุ่นนี้เป็นไทย สำนวนวัยรุ่น อ่านสนุก:
    - เจอฉากวูบวาบให้ปรับสำนวนให้ซอฟต์ลง (ใช้คำเลี่ยง)
    - ห้ามหยุดแปล ให้แปลจนจบ
    
    เนื้อหา:
    {text[:15000]} 
    """ 
    try:
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
    
    requests.post(DISCORD_WEBHOOK_URL, json={
        "content": f"📚 **[ตอนที่ {ep_num}] {title}**\n🔗 {link}\n*(กำลังแปล...)*"
    })
    
    chunk_size = 1900
    chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
    for i, chunk in enumerate(chunks):
        msg = f"**[{i+1}/{len(chunks)}]**\n{chunk}" if len(chunks) > 1 else chunk
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
        time.sleep(1)
    
    requests.post(DISCORD_WEBHOOK_URL, json={"content": f"✅ **จบตอนที่ {ep_num}**"})

def send_discord_error(ep_num, url, msg):
    if not DISCORD_WEBHOOK_URL: return
    requests.post(DISCORD_WEBHOOK_URL, json={
        "content": f"⚠️ **[ข้ามตอนที่ {ep_num}]** {msg}\n🔗 {url}"
    })

# ==========================================
# 🚀 Main Loop
# ==========================================

def main():
    print("🚀 เริ่มระบบแปลแบบลูกโซ่ (V.5 - Super Finder)...")
    
    current_url = get_first_episode_url()
    if not current_url:
        return

    ep_count = 1
    
    while current_url:
        print(f"\n[{ep_count}] กำลังประมวลผลลิงก์: {current_url}")
        
        data = get_content_and_next_link(current_url)
        
        if not data:
            print("   ❌ ดึงข้อมูลล้มเหลว -> หยุดทำงาน")
            send_discord_error(ep_count, current_url, "ดึงเนื้อหาไม่ได้")
            break

        title = data['title']
        content = data['content']
        next_link = data['next_link']
        
        print(f"   📖 เรื่อง: {title}")
        
        # Log ว่าเจอตอนต่อไปไหม
        if next_link:
            print(f"   🔗 เจอลิงก์ตอนถัดไป: {next_link}")
        else:
            print(f"   ⚠️ ไม่เจอปุ่ม Next (อาจเป็นตอนจบ)")

        print("   ⏳ แปลภาษา...")
        translated = translate(content)
        
        if translated:
            print("   🚀 ส่ง Discord...")
            send_discord(ep_count, title, current_url, translated)
            with open(DB_FILE, "w") as f:
                f.write(current_url)
        else:
            print("   ❌ แปลไม่ผ่าน -> ข้าม")
            send_discord_error(ep_count, current_url, "Gemini แปลไม่ผ่าน")

        if next_link:
            print(f"   ➡️ ไปตอนถัดไป... (รอ 30 วิ)")
            current_url = next_link
            ep_count += 1
            time.sleep(30)
        else:
            print("\n🏁 ไม่พบตอนถัดไป (จบการทำงาน)")
            current_url = None

    print("\n🎉 ทำงานเสร็จสิ้น!")

if __name__ == "__main__":
    main()
