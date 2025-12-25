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
NOVEL_MAIN_URL = "https://kakuyomu.jp/works/822139839754922306"

JSON_DB_FILE = "novels.json"
HISTORY_FILE = "history_novel_2.txt"

if GEMINI_API_KEY:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
    except:
        client = None
else:
    client = None

scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

# ==========================================
# 🛠️ ฟังก์ชันช่วยแปล
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
            model='gemini-2.5-pro', contents=prompt,
            config=types.GenerateContentConfig(safety_settings=[
                types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE')
            ])
        )
        return res.text.strip().replace('"', '') if res.text else text
    except: return text

# ==========================================
# 🛠️ ฟังก์ชันจัดการ JSON
# ==========================================

def get_novel_title():
    print(f"📖 กำลังดึงชื่อเรื่องจาก: {NOVEL_MAIN_URL}")
    try:
        response = scraper.get(NOVEL_MAIN_URL)
        soup = BeautifulSoup(response.text, 'html.parser')
        title_elem = soup.select_one('#workTitle') or soup.select_one('h1')
        raw_title = title_elem.text.strip() if title_elem else "นิยายไม่ทราบชื่อ"
        thai_title = translate_title(raw_title)
        print(f"✅ ชื่อไทย: {thai_title}")
        return thai_title
    except Exception as e:
        print(f"❌ ดึงชื่อเรื่องไม่ได้: {e}")
        return "นิยายไม่ทราบชื่อ"

def save_to_json(novel_title, ep_data):
    data = {}
    if os.path.exists(JSON_DB_FILE):
        with open(JSON_DB_FILE, "r", encoding="utf-8") as f:
            try:
                content = f.read()
                if content: data = json.loads(content)
                if isinstance(data, list): data = {}
            except: data = {}

    novel_id = NOVEL_MAIN_URL
    if novel_id not in data: data[novel_id] = { "title": novel_title, "chapters": [] }
    
    data[novel_id]["title"] = novel_title
    chapters = data[novel_id]["chapters"]
    existing_idx = next((index for (index, d) in enumerate(chapters) if d["link"] == ep_data["link"]), None)
    
    if existing_idx is not None: chapters[existing_idx] = ep_data
    else: chapters.append(ep_data)
        
    data[novel_id]["chapters"] = chapters

    with open(JSON_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"💾 บันทึกตอนที่ {ep_data['ep_id']} ลง JSON แล้ว")

# ==========================================
# 🛠️ ฟังก์ชัน Crawler & Smart Translate
# ==========================================

def load_history():
    if not os.path.exists(HISTORY_FILE): return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f: return set(l.strip() for l in f)

def save_to_history(url):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f: f.write(url + "\n")

def get_first_episode_url():
    try:
        r = scraper.get(NOVEL_MAIN_URL)
        s = BeautifulSoup(r.text, 'html.parser')
        l = s.select_one('a#readFromFirstEpisode')
        if l: return urljoin(NOVEL_MAIN_URL, l['href'])
        ts = re.compile(r'/works/\d+/episodes/\d+')
        ls = s.find_all('a', href=ts)
        if ls: 
            sl = sorted(ls, key=lambda x: int(re.search(r'episodes/(\d+)', x['href']).group(1)))
            return urljoin(NOVEL_MAIN_URL, sl[0]['href'])
    except: pass
    return None

def find_next_link(soup, url):
    n = soup.select_one('a.widget-episode-navigation-next') or soup.select_one('a#contentMain-readNextEpisode') or soup.find('a', string=re.compile('次のエピソード'))
    return urljoin(url, n['href']) if n else None

def get_content_and_next_link(url, max=3):
    h={'Referer': NOVEL_MAIN_URL}
    for _ in range(max):
        try:
            time.sleep(1)
            r = scraper.get(url, headers=h, timeout=15)
            if r.status_code==200:
                s = BeautifulSoup(r.text, 'html.parser')
                t = s.select_one('.widget-episodeTitle').text.strip()
                b = s.select_one('.widget-episodeBody').get_text(separator="\n", strip=True)
                eid = re.search(r'episodes/(\d+)', url).group(1)
                return {"title":t, "content":b, "next_link":find_next_link(s, url), "ep_id":eid}
        except: time.sleep(2)
    return None

def translate_smart(text, retry_count=0):
    if not client or not text: return None, "Error"
    
    # 4 Strategies: Normal -> Soften -> Summary -> Split
    prompts = [
        f"แปลนิยายญี่ปุ่นนี้เป็นไทย สำนวนวัยรุ่น (เก็บอารมณ์ครบ):\n{text[:15000]}",
        f"แปลโดยเลี่ยงคำล่อแหลมและรุนแรง (Soft Version):\n{text[:15000]}",
        f"สรุปเนื้อเรื่องตอนนี้เป็นภาษาไทย (ตัดฉากเรททิ้ง เล่าแค่เหตุการณ์):\n{text[:15000]}"
    ]

    # Strategy 1-3
    if retry_count < 3:
        try:
            prompt = prompts[retry_count]
            if retry_count > 0: print(f"   🔧 แก้เกมรอบที่ {retry_count}...")
            
            res = client.models.generate_content(
                model='gemini-2.5-pro', 
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

    # Strategy 4: Split Mode
    if retry_count == 3:
        print("   ⚔️ ไม้ตายสุดท้าย: หั่นครึ่งแล้วแปล...")
        try:
            mid = len(text) // 2
            r1, _ = translate_smart(text[:mid], 1)
            r2, _ = translate_smart(text[mid:], 1)
            full = (r1 or "") + "\n\n--- (ต่อ) ---\n\n" + (r2 or "")
            if len(full) > 50: return full, None
        except: pass

    # Failed
    return "⚠️ เนื้อหาตอนนี้แรงเกินไป ระบบไม่สามารถแปลได้ (กรุณาอ่านต้นฉบับ)", None

# ==========================================
# 🚀 Main Loop (แก้ไข logic การบันทึก)
# ==========================================

def main():
    print("🚀 เริ่มระบบ Web Novel...")
    
    novel_title = get_novel_title()
    completed_urls = load_history()
    current_url = get_first_episode_url()
    
    if not current_url: print("❌ หาตอนแรกไม่เจอ"); return

    ep_count = 1
    
    while current_url:
        print(f"\n[{ep_count}] ตรวจสอบ: {current_url}")
        
        if current_url in completed_urls:
            print("   ⏩ มีในประวัติแล้ว -> ข้าม")
            data = get_content_and_next_link(current_url) 
            if data and data['next_link']:
                current_url = data['next_link']; ep_count += 1; continue
            else: break

        data = get_content_and_next_link(current_url)
        if not data: break

        print(f"   ⏳ กำลังแปลชื่อตอน: {data['title']}")
        thai_chapter_title = translate_title(data['title'])
        
        print("   ⏳ กำลังแปลเนื้อหา...")
        translated_content, err = translate_smart(data['content'])
        
        if translated_content:
            # ✅ ตรวจสอบว่าใช่ข้อความ Error หรือไม่
            is_error_message = "⚠️" in translated_content and "ไม่สามารถแปลได้" in translated_content
            
            ep_data = {
                "ep_id": data['ep_id'],
                "title": thai_chapter_title,
                "content": translated_content,
                "link": current_url
            }
            save_to_json(novel_title, ep_data)
            
            if is_error_message:
                print("   ⚠️ ติด Safety -> บันทึกแจ้งเตือนลงเว็บ แต่ [ไม่บันทึกประวัติ] (รอรันใหม่)")
            else:
                print("   ✅ แปลเสร็จสมบูรณ์ -> บันทึกประวัติ")
                save_to_history(current_url)
                completed_urls.add(current_url)
        else:
            print(f"   ❌ เนื้อหาไม่ผ่านเลย: {err}")

        if data['next_link']:
            print("   ➡️ ไปตอนถัดไป...")
            current_url = data['next_link']
            ep_count += 1
            time.sleep(5)
        else:
            print("🏁 จบเรื่อง")
            break

if __name__ == "__main__":
    main()
