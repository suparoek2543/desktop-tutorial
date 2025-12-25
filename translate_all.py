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
# 🛠️ ฟังก์ชันช่วยแปล (เพิ่มใหม่)
# ==========================================

def translate_title(text):
    """ฟังก์ชันสำหรับแปลชื่อเรื่อง/ชื่อตอน ให้สั้น กระชับ น่าสนใจ"""
    if not client or not text: return text # ถ้าไม่มี Key ให้คืนค่าเดิม
    
    prompt = f"""
    Translate this Japanese novel title to Thai.
    Target audience: Teenagers / Light Novel readers.
    Style: Catchy, Short, Natural.
    
    Strict Rules:
    1. Output ONLY the translated text.
    2. No explanations, no notes, no options.
    
    Original Text:
    {text}
    """
    try:
        # ใช้ Flash Model เพื่อความไว
        response = client.models.generate_content(
            model='gemini-2.5-pro', 
            contents=prompt,
            config=types.GenerateContentConfig(safety_settings=[
                types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE')
            ])
        )
        if response.text:
            return response.text.strip().replace("ชื่อเรื่อง:", "").replace("แปล:", "").strip()
        return text
    except:
        return text # ถ้า Error ให้ใช้ชื่อญี่ปุ่นไปก่อน

# ==========================================
# 🛠️ ฟังก์ชันจัดการ JSON
# ==========================================

def get_novel_title():
    """ดึงชื่อนิยาย + แปลเป็นไทย"""
    print(f"📖 กำลังดึงและแปลชื่อเรื่องจาก: {NOVEL_MAIN_URL}")
    try:
        response = scraper.get(NOVEL_MAIN_URL)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title_elem = soup.select_one('#workTitle') or soup.select_one('h1')
        raw_title = title_elem.text.strip() if title_elem else "นิยายไม่ทราบชื่อ"
        
        # 🟢 สั่งแปลชื่อเรื่องตรงนี้
        thai_title = translate_title(raw_title)
        
        print(f"✅ ชื่อไทย: {thai_title} (Original: {raw_title})")
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
    
    if novel_id not in data:
        data[novel_id] = { "title": novel_title, "chapters": [] }
    
    # อัปเดตชื่อเรื่องให้เป็นไทยเสมอ (เผื่อแก้คำแปล)
    data[novel_id]["title"] = novel_title
    
    chapters = data[novel_id]["chapters"]
    existing_idx = next((index for (index, d) in enumerate(chapters) if d["link"] == ep_data["link"]), None)
    
    if existing_idx is not None:
        chapters[existing_idx] = ep_data
    else:
        chapters.append(ep_data)
        
    data[novel_id]["chapters"] = chapters

    with open(JSON_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"💾 บันทึกตอนที่ {ep_data['ep_id']} ลง JSON แล้ว")

# ==========================================
# 🛠️ ฟังก์ชัน Crawler (เหมือนเดิม)
# ==========================================

def load_history():
    if not os.path.exists(HISTORY_FILE): return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f: return set(l.strip() for l in f)

def save_to_history(url):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f: f.write(url + "\n")

def get_first_episode_url():
    try:
        response = scraper.get(NOVEL_MAIN_URL)
        soup = BeautifulSoup(response.text, 'html.parser')
        l = soup.select_one('a#readFromFirstEpisode')
        if l: return urljoin(NOVEL_MAIN_URL, l['href'])
        ts = re.compile(r'/works/\d+/episodes/\d+')
        ls = soup.find_all('a', href=ts)
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
            
            response = client.models.generate_content(
                model='gemini-2.5-pro', 
                contents=prompt,
                config=types.GenerateContentConfig(safety_settings=[
                    types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE')
                ])
            )
            if response.text and response.text.strip(): return response.text, None
        except Exception as e:
            if "429" in str(e): time.sleep(10); return translate_smart(text, retry_count)
            pass # ถ้า Error อื่นๆ ให้หลุดไปทำรอบถัดไป
        
        # ถ้าไม่ผ่าน ให้ลองรอบถัดไป
        time.sleep(2)
        return translate_smart(text, retry_count + 1)

    # --- ✂️ กลยุทธ์ 4 (ไม้ตาย): หั่นครึ่งแล้วแปลทีละส่วน ---
    if retry_count == 3:
        print("   ⚔️ ไม้ตายสุดท้าย: หั่นครึ่งแล้วแปล (Split Mode)...")
        try:
            mid = len(text) // 2
            part1 = text[:mid]
            part2 = text[mid:]
            
            # แปลส่วนแรก
            res1, err1 = translate_smart(part1, retry_count=1) # ใช้โหมด Soften แปล
            # แปลส่วนหลัง
            res2, err2 = translate_smart(part2, retry_count=1) # ใช้โหมด Soften แปล
            
            # รวมร่าง
            full_text = ""
            full_text += res1 if res1 else "⚠️ [ส่วนแรกแปลไม่ผ่าน]\n"
            full_text += "\n\n--- (ต่อ) ---\n\n"
            full_text += res2 if res2 else "⚠️ [ส่วนหลังแปลไม่ผ่าน]\n"
            
            return full_text, None
        except Exception as e:
            return None, f"ยอมแพ้แล้วจริงๆ ({e})"
            
    # ถ้าหลุดมาถึงตรงนี้คือไม่ไหวแล้ว
    fallback = "⚠️ เนื้อหาตอนนี้แรงเกินไป ระบบไม่สามารถแปลได้ (กรุณาอ่านต้นฉบับ)"
    return fallback, None
# ==========================================
# 🚀 Main Loop
# ==========================================

def main():
    print("🚀 เริ่มระบบ Web Novel (แปลไทยสมบูรณ์แบบ)...")
    
    # 1. แปลชื่อเรื่องก่อน
    novel_title = get_novel_title()
    
    completed_urls = load_history()
    current_url = get_first_episode_url()
    
    if not current_url: 
        print("❌ หาตอนแรกไม่เจอ"); return

    ep_count = 1
    
    while current_url:
        print(f"\n[{ep_count}] ตรวจสอบ: {current_url}")
        
        if current_url in completed_urls:
            print("   ⏩ มีในประวัติแล้ว -> ข้าม")
            data = get_content_and_next_link(current_url) 
            if data and data['next_link']:
                current_url = data['next_link']
                ep_count += 1
                continue
            else:
                break

        data = get_content_and_next_link(current_url)
        if not data: break

        # 🟢 สั่งแปลชื่อตอนตรงนี้
        print(f"   ⏳ กำลังแปลชื่อตอน: {data['title']}")
        thai_chapter_title = translate_title(data['title'])
        
        print("   ⏳ กำลังแปลเนื้อหา...")
        translated_content, err = translate_smart(data['content'])
        
        if translated_content:
            print(f"   ✅ แปลเสร็จ -> บันทึก")
            
            ep_data = {
                "ep_id": data['ep_id'],
                "title": thai_chapter_title, # ใช้ชื่อไทยที่แปลแล้ว
                "content": translated_content,
                "link": current_url
            }
            
            save_to_json(novel_title, ep_data)
            save_to_history(current_url)
            completed_urls.add(current_url)
        else:
            print(f"   ❌ เนื้อหาไม่ผ่าน: {err}")

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
