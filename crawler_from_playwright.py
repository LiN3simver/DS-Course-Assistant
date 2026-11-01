from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import time
import json
import re
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / '.env')


def credentials():
    student_id, password = os.getenv('SCU_STUDENT_ID'), os.getenv('SCU_PASSWORD')
    if student_id and password:
        return student_id, password
    try:
        import config
        return config.STUDENT_ID, config.PASSWORD
    except (ImportError, AttributeError) as exc:
        raise RuntimeError('請在 .env 設定 SCU_STUDENT_ID 與 SCU_PASSWORD。') from exc

def run_crawler():
    student_id, password = credentials()
    # 🎯 定義想要連續爬取的學期清單
    targets = [
        {"year": "113", "semester": "2"},
        {"year": "114", "semester": "1"}
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print("🚀 正在連線至東吳校務行政系統...")
        page.goto("https://web.sys.scu.edu.tw/default.asp")
        page.wait_for_load_state('networkidle')

        # 1. 登入
        login_frame = page.frame(name="frame3")
        if login_frame:
            login_frame.fill("input[name='id']", student_id)
            login_frame.fill("input[name='passwd']", password)
            login_frame.click("#btnLogin")
            time.sleep(3)
            print("✅ 登入成功！")

            # 2. 導航左側選單 (只需要展開一次目錄)
            menu_frame = page.frame(name="frame1")
            if menu_frame:
                try:
                    menu_frame.click("a:has-text('學生服務')")
                    time.sleep(0.5)
                    menu_frame.click("a:has-text('教務')")
                    time.sleep(0.5)
                    menu_frame.click("a:has-text('全校課務資料查詢')")
                    time.sleep(1)
                except Exception as e:
                    print(f"❌ 展開選單時發生錯誤: {e}")
                    browser.close()
                    return

                # 🔁 3. 開始學期迴圈
                for target in targets:
                    target_year = target["year"]
                    target_sem = target["semester"]
                    print(f"\n{'='*40}")
                    print(f"▶️ 開始處理：{target_year}學年 第{target_sem}學期")
                    print(f"{'='*40}")

                    # 點擊左側重新整理表單
                    menu_frame.click("a[href*='course203.asp']")
                    # 💡 給系統絕對足夠的時間去刷新這個 frame (非常重要)
                    time.sleep(3) 

                    main_frame = page.frame(name="frame2")
                    if not main_frame:
                        print("❌ 找不到查詢表單，跳過此學期。")
                        continue

                    print("⚙️ 設定查詢條件 (啟動升級防禦機制)...")
                    
                    # (1) 先填學年與學期，並強迫網頁把潛在的重置事件跑完
                    year_input = main_frame.locator("input[name='syear']")
                    year_input.clear()
                    year_input.fill(target_year)
                    # 💡 模擬人類按 Tab 鍵，強制觸發輸入框的 onblur/onchange 事件
                    year_input.press("Tab") 
                    time.sleep(1) # 等待系統可能的重新載入
                    
                    main_frame.select_option("select[name='smester']", value=target_sem)
                    time.sleep(1)

                    # (2) 開始操作連動下拉選單
                    main_frame.select_option("select[name='clsid1']", label="學士班")
                    
                    # 程式會盯著畫面，直到系統跑完 JavaScript、跑出「資料科學系」為止
                    print("⏳ 等待系統載入學系選單...")
                    main_frame.locator("select[name='clsid02'] option:has-text('資料科學系')").wait_for(state="attached", timeout=5000)
                    
                    # 確認選項存在後，精準點擊
                    main_frame.select_option("select[name='clsid02']", label="資料科學系")
                    time.sleep(1) # 選完再停一秒，讓系統鎖定這個選項
                    
                    print("🔍 選項已鎖定，準備送出查詢...")
                    main_frame.click("input[value='查詢']")
                    
                    page.wait_for_load_state('networkidle')
                    time.sleep(3) 

                    # 4. 開始解析該學期的清單
                    all_courses_data = []
                    page_html = main_frame.content()
                    soup = BeautifulSoup(page_html, 'html.parser')

                    result_table = None
                    for table in soup.find_all('table'):
                        if table.find('a', href=True):
                            result_table = table
                            break

                    if not result_table:
                        print(f"❌ 找不到 {target_year}-{target_sem} 的結果表格。")
                        continue

                    rows = result_table.find_all('tr')
                    if len(rows) <= 1:
                        print(f"❌ {target_year}-{target_sem} 沒有任何課程資料。")
                        continue

                    for row in rows[1:]:
                        cols = row.find_all('td')
                        if len(cols) < 3:
                            continue

                        a_tag_code = cols[1].find('a')
                        a_tag_name = cols[2].find('a')
                        if not a_tag_code:
                            continue

                        course_code = a_tag_code.text.strip()
                        course_name_text = cols[2].text.strip()

                        print(f"  - 爬取：{course_code} {course_name_text}")

                        course_info = {
                            "course_code": course_code,
                            "course_name": course_name_text,
                            "teacher": "未知",
                            "average_score": None,
                            "score_distribution": {},
                            "syllabus": {
                                "content": "無資料",
                                "grading": "無資料"
                            }
                        }

                        detail_page = context.new_page()
                        try:
                            score_href = a_tag_code.get('href', '').strip()
                            if not score_href:
                                print(f"⚠️ {course_code} 沒有成績連結，略過。")
                                detail_page.close()
                                continue

                            score_url = score_href if score_href.startswith('http') else f"https://web.sys.scu.edu.tw/{score_href.lstrip('/')}"
                            detail_page.goto(score_url)
                            detail_page.wait_for_load_state('networkidle')
                            detail_soup = BeautifulSoup(detail_page.content(), 'html.parser')

                            detail_tables = detail_soup.find_all('table')
                            if detail_tables:
                                info_rows = detail_tables[0].find_all('tr')
                                if len(info_rows) > 1:
                                    info_cols = info_rows[1].find_all('td')
                                    if len(info_cols) >= 5:
                                        course_info["teacher"] = info_cols[4].text.strip()

                            for tbl in detail_tables:
                                if "0~49" in tbl.get_text():
                                    for tr in tbl.find_all('tr'):
                                        tds = tr.find_all(['td', 'th'])
                                        if len(tds) >= 2 and "~" in tds[0].text:
                                            course_info["score_distribution"][tds[0].text.strip()] = tds[1].text.strip()
                                        if len(tds) >= 4 and "~" in tds[2].text:
                                            course_info["score_distribution"][tds[2].text.strip()] = tds[3].text.strip()
                                    break

                            avg_text_node = detail_soup.find(string=re.compile("全班成績平均值"))
                            if avg_text_node:
                                match = re.search(r"[\d\.]+", avg_text_node)
                                if match:
                                    course_info["average_score"] = float(match.group())

                            time.sleep(1)

                            if a_tag_name:
                                syllabus_href = a_tag_name.get('href', '').strip()
                                if syllabus_href:
                                    syllabus_url = syllabus_href if syllabus_href.startswith('http') else f"https://web.sys.scu.edu.tw{syllabus_href}"
                                    detail_page.goto(syllabus_url)
                                    detail_page.wait_for_load_state('networkidle')

                                    syllabus_soup = BeautifulSoup(detail_page.content(), 'html.parser')
                                    raw_text = syllabus_soup.get_text(separator='\n', strip=True)
                                    content_start = raw_text.find("四、課程內容 Course Description")
                                    grading_start = raw_text.find("五、考評及成績核算方式 Grading")
                                    office_start = raw_text.find("六、授課教師課業輔導時間")

                                    if content_start != -1 and grading_start != -1:
                                        content_text = raw_text[content_start + len("四、課程內容 Course Description"):grading_start].strip()
                                        course_info["syllabus"]["content"] = re.sub(r"\n{2,}", "\n", content_text)

                                    if grading_start != -1 and office_start != -1:
                                        grading_text = raw_text[grading_start + len("五、考評及成績核算方式 Grading"):office_start].strip()
                                        course_info["syllabus"]["grading"] = re.sub(r"\n{2,}", "\n", grading_text)

                            all_courses_data.append(course_info)

                        except Exception as e:
                            print(f"⚠️ 爬取 {course_code} 時發生錯誤: {e}")
                        finally:
                            detail_page.close()

                        time.sleep(1)

                    file_name = f'scu_courses_data_{target_year}_{target_sem}.json'
                    with open(file_name, 'w', encoding='utf-8') as f:
                        json.dump(all_courses_data, f, ensure_ascii=False, indent=4)
                    print(f"✅ {target_year}-{target_sem} 資料已儲存至 {file_name}\n")

            else:
                print("❌ 找不到左側選單框架。")
        browser.close()
        print("🏁 全部任務執行完畢！")

if __name__ == "__main__":
    run_crawler()
