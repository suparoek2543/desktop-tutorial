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
NOVEL_MAIN_URL = "https://kakuyomu.jp/works/16816700429097793676"

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
# 🛠️ ฟังก์ชันจัดการ JSON แบบใหม่ (รองรับหลายเรื่อง)
# ==========================================

def get_novel_title():
    """ดึงชื่อนิยายจากหน้าหลัก"""
    print(f"📖 กำลังดึงชื่อเรื่องจาก: {NOVEL_MAIN_URL}")
    try:
        response = scraper.get(NOVEL_MAIN_URL)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # หาชื่อเรื่อง (Kakuyomu ใช้ id="workTitle")
        title_elem = soup.select_one('#workTitle')
        if not title_elem:
             # เผื่อหาไม่เจอ ลองหา h1
             title_elem = soup.select_one('h1')
             
        title = title_elem.text.strip() if title_elem else "นิยายไม่ทราบชื่อ"
        print(f"✅ ชื่อเรื่อง: {title}")
        return title
    except Exception as e:
        print(f"❌ ดึงชื่อเรื่องไม่ได้: {e}")
        return "นิยายไม่ทราบชื่อ"

def save_to_json(novel_title, ep_data):
    """บันทึกข้อมูลลง JSON แบบจัดหมวดหมู่"""
    data = {}
    
    # 1. โหลดข้อมูลเก่า
    if os.path.exists(JSON_DB_FILE):
        with open(JSON_DB_FILE, "r", encoding="utf-8") as f:
            try:
                content = f.read()
                if content: data = json.loads(content)
                
                # ⚠️ เช็คว่าโครงสร้างเก่าเป็น Array [] หรือเปล่า? (ถ้าใช่ต้องแปลงเป็น Dict {})
                if isinstance(data, list):
                    print("⚠️ ตรวจพบโครงสร้างเก่า (Array) กำลังแปลงเป็นแบบใหม่...")
                    data = {} # ล้างของเก่าทิ้ง เพราะโครงสร้างเปลี่ยน
            except:
                data = {}

    # 2. เตรียม Key สำหรับเรื่องนี้ (ใช้ URL เป็น ID จะได้ไม่ซ้ำ)
    novel_id = NOVEL_MAIN_URL
    
    # ถ้ายังไม่มีเรื่องนี้ใน Database ให้สร้างใหม่
    if novel_id not in data:
        data[novel_id] = {
            "title": novel_title,
            "chapters": []
        }
    
    # 3. เพิ่ม/อัปเดตตอน
    chapters = data[novel_id]["chapters"]
    
    # เช็คว่ามีตอนนี้อยู่แล้วไหม
    existing_idx = next((index for (index, d) in enumerate(chapters) if d["link"] == ep_data["link"]), None)
    
    if existing_idx is not None:
        chapters[existing_idx] = ep_data # ทับของเดิม
    else:
        chapters.append(ep_data) # เพิ่มใหม่
        
    data[novel_id]["chapters"] = chapters

    # 4. บันทึก
    with open(JSON_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        print(f"💾 บันทึกตอนที่ {ep_data['ep_id']} ลงหมวด '{novel_title}' เรียบร้อย")

# ==========================================
# 🛠️ ฟังก์ชันเดิม
# ==========================================
# (ส่วนนี้เหมือนเดิม แต่ตัดตอนแปะโค้ดยาวๆ ออกเพื่อให้ดูง่าย)
# ... Load History, Get Url, Translate Smart ...
# (ให้ใช้ฟังก์ชันเดิมจาก V.9 ที่ผมส่งให้ก่อนหน้าได้เลย แต่เปลี่ยน Main Loop ตามด้านล่าง)

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
        # Fallback
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

def translate_smart(text, r=0):
    if not client or not text: return None, "Error"
    ps = [
        f"แปลนิยายญี่ปุ่นนี้เป็นไทย สำนวนวัยรุ่น:\nเนื้อหา:\n{text[:15000]}",
        f"**แปลเลี่ยงเนื้อหาล่อแหลม**:\nเนื้อหา:\n{text[:15000]}",
        f"สรุปเนื้อเรื่อง:\nเนื้อหา:\n{text[:15000]}"
    ]
    try:
        res = client.models.generate_content(
            model='gemini-2.5-pro', contents=ps[min(r,2)],
            config=types.GenerateContentConfig(safety_settings=[
                types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE')
            ])
        )
        if not res.text: raise ValueError("Empty")
        return res.text, None
    except Exception as e:
        if r<2: time.sleep(2); return translate_smart(text, r+1)
        return None, str(e)

# ==========================================
# 🚀 Main Loop (อัปเดตใหม่)
# ==========================================

def main():
    print("🚀 เริ่มระบบ Web Novel (Tree View Supported)...")
    
    # 1. ดึงชื่อเรื่องก่อนเลย (เพื่อใช้เป็นชื่อโฟลเดอร์)
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
            data = get_content_and_next_link(current_url) # โหลดเพื่อหา Next Link เฉยๆ
            if data and data['next_link']:
                current_url = data['next_link']
                ep_count += 1
                continue
            else:
                break

        data = get_content_and_next_link(current_url)
        if not data: break

        title = data['title']
        translated, err = translate_smart(data['content'])
        
        if translated:
            print(f"   ✅ แปลเสร็จ -> บันทึกเข้าเรื่อง '{novel_title}'")
            
            ep_data = {
                "ep_id": data['ep_id'],
                "title": title,
                "content": translated,
                "link": current_url
            }
            
            # 🟢 เรียกใช้ save_to_json แบบใหม่ (ส่งชื่อเรื่องไปด้วย)
            save_to_json(novel_title, ep_data)
            
            save_to_history(current_url)
            completed_urls.add(current_url)
        else:
            print(f"   ❌ ไม่ผ่าน: {err}")

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
