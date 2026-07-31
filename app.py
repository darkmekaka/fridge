import streamlit as st
import requests
import pandas as pd
import json
from datetime import datetime, date, timedelta, timezone
from groq import Groq

# 앱 화면 설정 (모바일 최적화 넓이 설정)
st.set_page_config(page_title="쑥잠이 냉장고", page_icon="🍳", layout="centered")

# 한국 시간(KST, UTC+9) 기준 오늘 날짜 산출 함수
def get_kst_today():
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).date()

# 구글 시트 날짜 데이터 오차 보정 함수
def parse_sheet_date(date_val):
    if not date_val:
        return ""
    date_str = str(date_val)
    try:
        if 'T' in date_str:
            dt_utc = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            kst = timezone(timedelta(hours=9))
            dt_kst = dt_utc.astimezone(kst)
            return dt_kst.strftime("%Y-%m-%d")
        else:
            return date_str[:10]
    except Exception:
        return date_str[:10]

# 순수 HTML/CSS 기반 모바일 완벽 방어 스타일 정의
st.markdown("""
    <style>
    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 3rem !important;
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
        max-width: 100% !important;
        overflow-x: hidden !important;
    }
    
    /* 냉장고 목록 커스텀 카드 컨테이너 */
    .fridge-table-header {
        display: flex;
        align-items: center;
        padding: 4px 12px;
        margin-bottom: 6px;
        font-size: 0.85rem;
        color: #888;
        font-weight: bold;
    }
    
    .fridge-row {
        display: flex;
        flex-direction: row;
        flex-wrap: nowrap;
        align-items: center;
        background-color: #ffffff;
        border: 1px solid #eaeaea;
        border-radius: 10px;
        padding: 10px 12px;
        margin-bottom: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.02);
        width: 100%;
        box-sizing: border-box;
    }
    
    /* 각 컬럼의 비율 및 고정 폭 설정 (절대 줄바꿈 방지) */
    .col-name {
        flex: 1;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    
    .col-name a {
        color: #222222;
        text-decoration: none;
        font-weight: bold;
        font-size: 0.95rem;
        display: block;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .col-name a:hover {
        color: #e67e22;
    }
    
    .col-date {
        flex: 0 0 75px;
        width: 75px;
        text-align: center;
        font-size: 0.9rem;
        color: #555;
        white-space: nowrap;
    }
    
    .col-days {
        flex: 0 0 55px;
        width: 55px;
        text-align: right;
        font-size: 0.9rem;
        color: #e67e22;
        font-weight: bold;
        white-space: nowrap;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🍳 쑥잠이 냉장고")
st.write("식자재 이름을 누르면 수정 및 삭제 팝업이 열립니다.")

# st.secrets에서 기본값 불러오기
default_gas_url = ""
default_groq_key = ""

try:
    if "GAS_WEB_APP_URL" in st.secrets:
        default_gas_url = st.secrets["GAS_WEB_APP_URL"]
    if "GROQ_API_KEY" in st.secrets:
        default_groq_key = st.secrets["GROQ_API_KEY"]
except Exception:
    pass

# 세션 상태 초기화
if "web_app_url" not in st.session_state:
    st.session_state.web_app_url = default_gas_url
if "saved_groq_key" not in st.session_state:
    st.session_state.saved_groq_key = default_groq_key

# 사이드바: 설정 변경 메뉴
with st.sidebar.expander("🔧 설정 변경 (필요한 경우만)", expanded=False):
    with st.form("config_form"):
        temp_url = st.text_input("GAS 웹 앱 URL", value=st.session_state.web_app_url)
        temp_groq_key = st.text_input("Groq API Key 입력", type="password", value=st.session_state.saved_groq_key)
        
        save_btn = st.form_submit_button("💾 설정 업데이트", use_container_width=True)
        
        if save_btn:
            st.session_state.web_app_url = temp_url
            st.session_state.saved_groq_key = temp_groq_key
            st.success("설정이 업데이트되었습니다!")

web_app_url = st.session_state.web_app_url
groq_api_key = st.session_state.saved_groq_key

# 데이터 조회 함수 (GET)
def fetch_sheet_data(url):
    if not url:
        return None
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        st.error(f"데이터를 불러오는 중 오류 발생: {e}")
        return None

# 데이터 변경 함수 (POST)
def send_post_request(url, payload):
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        st.error(f"서버 통신 중 오류 발생: {e}")
        return None

# 중앙 팝업 모달 함수 (분류: 식자재, 밑반찬, 양념)
@st.dialog("⚙️ 품목 관리")
def open_edit_dialog(sheet_row_idx, current_ing, clean_date_str, current_cat, web_url):
    st.write(f"**[{current_ing}]** 정보를 수정하거나 삭제할 수 있습니다.")
    
    with st.form(key=f"modal_form_{sheet_row_idx}"):
        edit_ing_name = st.text_input("이름 수정", value=current_ing)
        try:
            p_dt = datetime.strptime(clean_date_str, "%Y-%m-%d").date()
        except ValueError:
            p_dt = get_kst_today()
        edit_date_val = st.date_input("입고일 수정", value=p_dt)
        
        categories_list = ["식자재", "밑반찬", "양념"]
        cat_index = categories_list.index(current_cat) if current_cat in categories_list else 0
        edit_cat_val = st.selectbox("분류 변경", categories_list, index=cat_index)
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            save_clicked = st.form_submit_button("💾 수정 저장", use_container_width=True)
        with col_btn2:
            del_clicked = st.form_submit_button("🗑️ 삭제하기", use_container_width=True)
            
        if save_clicked:
            payload = {
                "action": "update",
                "rowIndex": sheet_row_idx,
                "ingredient": edit_ing_name,
                "date": edit_date_val.strftime("%Y-%m-%d"),
                "category": edit_cat_val
            }
            res = send_post_request(web_url, payload)
            if res and res.get("status") == "success":
                st.success("수정 완료!")
                st.query_params.clear()
                st.rerun()
                
        if del_clicked:
            payload = {
                "action": "delete",
                "rowIndex": sheet_row_idx
            }
            res = send_post_request(web_url, payload)
            if res and res.get("status") == "success":
                st.success("삭제 완료!")
                st.query_params.clear()
                st.rerun()

# 메인 로직 실행
if not web_app_url:
    st.warning("⚠️ GAS 웹 앱 URL이 설정되지 않았습니다. 사이드바의 [설정 변경] 메뉴에서 입력해 주세요.")
else:
    rows = fetch_sheet_data(web_app_url)
    
    if rows is None:
        st.error("데이터를 불러올 수 없습니다. URL을 확인해 주세요.")
    else:
        tab1, tab2 = st.tabs(["🛒 냉장고 재료 관리", "🤖 AI 한상차림 식단"])
        
        with tab1:
            st.subheader("🛒 식자재 및 반찬 추가하기")
            with st.form("add_ingredient_form", clear_on_submit=True):
                new_ingredient = st.text_input("품목 이름 (예: 대파, 참기름)")
                input_date = st.date_input("입력 날짜", value=get_kst_today())
                item_category = st.selectbox("분류 선택", ["식자재", "밑반찬", "양념"])
                
                submitted = st.form_submit_button("냉장고에 담기", use_container_width=True)
                
                if submitted and new_ingredient:
                    payload = {
                        "action": "append",
                        "ingredient": new_ingredient,
                        "date": input_date.strftime("%Y-%m-%d"),
                        "category": item_category
                    }
                    res = send_post_request(web_app_url, payload)
                    if res and res.get("status") == "success":
                        st.success(f"[{item_category}] '{new_ingredient}' 추가 완료!")
                        st.rerun()

            st.divider()
            st.subheader("📦 현재 냉장고 보관함")
            
            if len(rows) > 1:
                data_rows = rows[1:]
                kst_today = get_kst_today()
                
                sub_tab1, sub_tab2, sub_tab3 = st.tabs(["🥩 식자재", "🥗 밑반찬", "🧂 양념류"])
                
                categories_mapping = {
                    "식자재": sub_tab1,
                    "밑반찬": sub_tab2,
                    "양념": sub_tab3
                }
                
                # 쿼리 파라미터로 전달된 편집 요청 확인
                edit_target_idx = st.query_params.get("edit", None)
                
                for cat_name, sub_tab_obj in categories_mapping.items():
                    with sub_tab_obj:
                        cat_items = []
                        for i, row_data in enumerate(data_rows):
                            sheet_row_idx = i + 2
                            current_ing = row_data[0] if len(row_data) > 0 else ""
                            current_date = row_data[1] if len(row_data) > 1 else ""
                            current_cat = row_data[2] if len(row_data) > 2 else "식자재"
                            
                            if not current_cat:
                                current_cat = "식자재"
                                
                            if current_cat == cat_name:
                                clean_date_str = parse_sheet_date(current_date)
                                short_date = clean_date_str[5:] if len(clean_date_str) >= 10 else clean_date_str
                                try:
                                    parsed_date = datetime.strptime(clean_date_str, "%Y-%m-%d").date()
                                    days_passed = (kst_today - parsed_date).days + 1
                                    days_label = f"{days_passed}일"
                                except ValueError:
                                    days_label = "-"
                                    
                                cat_items.append((sheet_row_idx, current_ing, clean_date_str, short_date, days_label, current_cat))
                        
                        if cat_items:
                            # 상단 헤더
                            header_html = f"""
                            <div class="fridge-table-header">
                                <div class="col-name">식자재명</div>
                                <div class="col-date">입고일</div>
                                <div class="col-days">경과일</div>
                            </div>
                            """
                            st.markdown(header_html, unsafe_allow_html=True)
                            
                            # 순수 HTML 행 출력 (아이콘 제거 및 냉장고 느낌의 🧊 아이콘 적용)
                            for sheet_row_idx, current_ing, clean_date_str, short_date, days_label, current_cat in cat_items:
                                row_html = f"""
                                <div class="fridge-row">
                                    <div class="col-name">
                                        <a href="?edit={sheet_row_idx}" target="_self">🧊 {current_ing}</a>
                                    </div>
                                    <div class="col-date">{short_date}</div>
                                    <div class="col-days">{days_label}</div>
                                </div>
                                """
                                st.markdown(row_html, unsafe_allow_html=True)
                                
                                # 만약 해당 행이 클릭되어 쿼리 파라미터에 전달되었다면 다이얼로그 오픈
                                if edit_target_idx and str(edit_target_idx) == str(sheet_row_idx):
                                    open_edit_dialog(sheet_row_idx, current_ing, clean_date_str, current_cat, web_app_url)
                        else:
                            st.info(f"등록된 [{cat_name}] 항목이 없습니다.")
            else:
                st.info("냉장고가 비어있습니다.")

        with tab2:
            st.subheader("🤖 AI 맞춤 레시피 추천")
            
            selected_category = st.selectbox(
                "요리 종류 선택",
                ["전체 (상관없음)", "볶음류", "찌개/국물류", "구이/부침류", "무침/샐러드류"]
            )
            plan_period = st.selectbox(
                "추천 유형 선택",
                ["단기 추천 (메인 요리 3가지)", "📅 1주일 한상차림 캘린더 식단"]
            )
            
            if not groq_api_key:
                st.warning("⚠️ Groq API Key가 설정되지 않았습니다. 사이드바의 [설정 변경] 메뉴에서 입력해 주세요.")
            else:
                button_label = "✨ Groq 레시피 추천 받기" if "단기" in plan_period else "📅 1주일 한상차림 생성하기"
                if st.button(button_label, use_container_width=True):
                    try:
                        if len(rows) <= 1:
                            st.warning("냉장고가 비어있습니다!")
                        else:
                            data_rows = rows[1:]
                            ingredients_all = []
                            side_dishes = []
                            condiments = []
                            
                            for row in data_rows:
                                if len(row) > 0 and row[0]:
                                    ing_name = row[0]
                                    cat = row[2] if len(row) > 2 else "식자재"
                                    if cat == "밑반찬":
                                        side_dishes.append(ing_name)
                                    elif cat == "양념":
                                        condiments.append(ing_name)
                                    else:
                                        ingredients_all.append(ing_name)
                            
                            main_str = ", ".join(ingredients_all) if ingredients_all else "없음"
                            side_str = ", ".join(side_dishes) if side_dishes else "없음"
                            cond_str = ", ".join(condiments) if condiments else "기본 양념"
                            
                            with st.spinner("AI가 한상차림을 구성하고 있습니다..."):
                                client = Groq(api_key=groq_api_key)
                                
                                prompt = f"""
다음은 냉장고 보유 품목이야:
- 식자재: [{main_str}]
- 보유 밑반찬: [{side_str}]
- 양념: [{cond_str}]
선호 요리: [{selected_category}].

규칙:
- 100% 순수 한국어로만 작성.
- 중국어, 일본어, 한자 사용 금지.
- 조리 순서는 줄바꿈(\\n) 사용.
- JSON 객체 형태로만 답변: {{"recipes": [{{"recipe_name": "이름", "matched_ingredients": ["재료"], "missing_ingredients": ["필요재료"], "instructions": "1. 단계\\n2. 단계"}}]}}
"""
                                chat_completion = client.chat.completions.create(
                                    messages=[
                                        {"role": "system", "content": "You are a helpful culinary assistant that outputs only valid JSON in Korean."},
                                        {"role": "user", "content": prompt}
                                    ],
                                    model="llama-3.3-70b-versatile",
                                    response_format={"type": "json_object"},
                                )
                                
                                result_text = chat_completion.choices[0].message.content
                                response_data = json.loads(result_text)
                                recipes = response_data.get("recipes", [])
                                
                                for i, r in enumerate(recipes, 1):
                                    st.markdown(f"### 🏆 {i}. {r['recipe_name']}")
                                    st.write(f"✅ **사용 재료:** {', '.join(r['matched_ingredients'])}")
                                    st.write(f"🛒 **추가 필요:** {', '.join(r['missing_ingredients']) if r['missing_ingredients'] else '없음'}")
                                    st.markdown(f"🍳 **조리법:**\n\n{r['instructions']}")
                                    st.divider()
                                        
                    except Exception as e:
                        st.error(f"오류 발생: {e}")
