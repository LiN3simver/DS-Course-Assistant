from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json
import time
import re

def scrape_professors():
    all_professors = []

    with sync_playwright() as p:
        # headless=False 讓你看著它跑，確認沒問題後可改成 True 在背景執行
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        print("🚀 連線至巨量資料管理學院師資頁面...")
        page.goto("https://bigdata.scu.edu.tw/team/#full-time-professor")
        
        # 等待網頁完全載入
        page.wait_for_load_state('networkidle')
        time.sleep(2) 

        html = page.content()
        soup = BeautifulSoup(html, 'html.parser')

        # 1. 鎖定「專任教師」的區塊
        # 根據你的第一張截圖，這個區塊的 id 是 "full-time-professor"
        full_time_panel = soup.find('div', id='full-time-professor')

        if not full_time_panel:
            print("❌ 找不到專任教師區塊，請確認網址或網頁結構。")
            browser.close()
            return

        # 2. 找出所有大頭照的超連結
        # 根據截圖，連結標籤是 <a class="link-img">
        link_tags = full_time_panel.find_all('a', class_='link-img')
        
        # 萃取出 href 網址，並使用 set() 去除重複的網址
        profile_urls = list(set([tag.get('href') for tag in link_tags if tag.get('href')]))

        print(f"📊 找到 {len(profile_urls)} 位專任教師，開始逐一爬取資料...")

        # 3. 進入每位老師的個人頁面爬取「簡介」
        for url in profile_urls:
            print(f"🔍 正在進入: {url}")
            try:
                page.goto(url)
                page.wait_for_load_state('networkidle')
                time.sleep(1) # 給網頁一點時間渲染排版

                detail_soup = BeautifulSoup(page.content(), 'html.parser')

                # (A) 抓取教師姓名
                # 網頁的標題 (<title>) 通常會寫 "金凱儀 - 東吳大學..."，我們切出名字
                page_title = detail_soup.title.text if detail_soup.title else "未知教師"
                name = page_title.split('-')[0].strip()

                # (B) 抓取「簡介」與所有專業資訊
                # WordPress 網站的主要內容通常包在 <div class="entry-content"> 裡面
                # 為了確保 RAG 能拿到所有資訊，我們將這個區塊內的純文字全部抽出來
                content_div = detail_soup.find('div', class_='entry-content')
                
                intro_text = ""
                if content_div:
                    # 抽出所有文字，並用換行符號隔開
                    raw_text = content_div.get_text(separator='\n', strip=True)
                    # 清理多餘的空白行，讓資料更乾淨
                    intro_text = re.sub(r'\n{2,}', '\n', raw_text)
                else:
                    intro_text = "無法精準定位簡介區塊。"

                # 準備存入 JSON 的資料格式
                prof_data = {
                    "name": name,
                    "profile_url": url,
                    "expertise_and_intro": intro_text
                }

                all_professors.append(prof_data)
                
                print(f"   ✅ 已成功抓取：{name} 的專業資訊")

            except Exception as e:
                print(f"⚠️ 爬取 {url} 時發生錯誤: {e}")

        browser.close()

        # 4. 存檔為 JSON
        file_name = 'scu_professors_data.json'
        with open(file_name, 'w', encoding='utf-8') as f:
            json.dump(all_professors, f, ensure_ascii=False, indent=4)
            
        print(f"\n🏁 任務完成！所有教師專業資料已儲存至 {file_name}")

if __name__ == "__main__":
    scrape_professors()