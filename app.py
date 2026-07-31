import streamlit as st
import requests
import pandas as pd
import json
from datetime import datetime, date, timedelta, timezone
from groq import Groq

# 앱 화면 설정
st.set_page_config(page_title="우리집 스마트 냉장고", page_icon="🍳", layout="wide")

# 한국 시간(KST, UTC+9) 기준 오늘 날짜 산출 함수
def get_kst_today():
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).date()

# 구글 시트 날짜 데이터의 UTC/KST 시차 오차를 보정하여 정확한 YYYY-MM-DD로 변환하는 함수
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

# 순수 톱니바퀴 버튼 스타일 초기화 CSS (전역 수직 정렬은 제거함)
st.markdown("""
    <style>
    div[data-testid="stHorizontalBlock"] button {
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
        padding: 0px !important;
        min-height: auto !important;
        font-size: 1.1rem !important;
        margin: 0px !important;
    }
    div[data-testid="stHorizontalBlock"] button:hover {
        background-color: rgba(0, 0, 0, 0.05) !important;
        border: none !important;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🍳 우리가족 스마트 냉장고 & 한상차림 AI")
st.write("구글 앱스 스크립트(GAS)와 초고속 Groq AI로 식자재, 밑반찬, 양념류를 완벽하게 관리하세요!")

# 세션 상태(Session State) 초기화
if "web_app_url" not in st.session_state:
    st.session_state.web_app_url = ""
if "saved_groq_key" not in st.session_state:
    st.session_state.saved_groq_key = ""

# 사이드바: 설정 관리 폼
st.sidebar.header("🔧 설정 관리")
with st.sidebar.form("config_form"):
    temp_url = st.text_input("GAS 웹 앱 URL", value=st.session_state.web_app_url, help="구글 앱스 스크립트 배포 후 발급받은 웹 앱 URL을 입력하세요.")
    temp_groq_key = st.text_input("Groq API Key 입력", type="password", value=st.session_state.saved_groq_key, help="console.groq.com에서 무료로 발급받은 API 키를 입력하세요.")
    
    save_btn = st.form_submit_button("💾 설정 저장하기")
    
    if save_btn:
        st.session_state.web_app_url = temp_url
        st.session_state.saved_groq_key = temp_groq_key
        st.success("설정이 성공적으로 저장되었습니다!")

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

# 품목 수정 및 삭제를 위한 중앙 팝업 모달 함수
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
        edit_cat_val = st.selectbox("분류 변경", ["식자재", "밑반찬", "양념 및 부침가루"], index=["식자재", "밑반찬", "양념 및 부침가루"].index(current_cat) if current_cat in ["식자재", "밑반찬", "양념 및 부침가루"] else 0)
        
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
                st.rerun()
                
        if del_clicked:
            payload = {
                "action": "delete",
                "rowIndex": sheet_row_idx
            }
            res = send_post_request(web_url, payload)
            if res and res.get("status") == "success":
                st.success("삭제 완료!")
                st.rerun()

# 메인 로직 실행
if not web_app_url:
    st.warning("⚠️ 사이드바에 구글 앱스 스크립트(GAS) 웹 앱 URL을 입력하고 **[설정 저장하기]**를 눌러주세요.")
else:
    # 데이터 로드
    rows = fetch_sheet_data(web_app_url)
    
    if rows is None:
        st.error("웹 앱 URL이 올바르지 않거나 데이터를 불러올 수 없습니다. URL을 다시 확인해 주세요.")
    else:
        # 탭 메뉴 구성
        tab1, tab2 = st.tabs(["🛒 냉장고 재료 관리", "🤖 한상차림 AI 식단"])
        
        with tab1:
            st.subheader("🛒 식자재 및 반찬 추가하기")
            with st.form("add_ingredient_form", clear_on_submit=True):
                col_f1, col_f2, col_f3 = st.columns([2, 1.5, 1.5])
                with col_f1:
                    new_ingredient = st.text_input("품목 이름 (예: 대파, 멸치볶음, 진간장)")
                with col_f2:
                    input_date = st.date_input("입력 날짜", value=get_kst_today())
                with col_f3:
                    item_category = st.selectbox("분류 선택", ["식자재", "밑반찬", "양념 및 부침가루"])
                
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
                        st.success(f"[{item_category}] '{new_ingredient}'이(가) 추가되었습니다!")
                        st.rerun()

            st.divider()
            st.subheader("📦 현재 우리집 냉장고 보관함")
            
            if len(rows) > 1:
                data_rows = rows[1:] # 헤더 제외
                kst_today = get_kst_today()
                
                # 카테고리별 탭 메뉴 생성 (모바일 가독성 향상)
                sub_tab1, sub_tab2, sub_tab3 = st.tabs(["🥩 식자재", "🥗 밑반찬", "🧂 양념 및 부침가루"])
                
                categories_mapping = {
                    "식자재": sub_tab1,
                    "밑반찬": sub_tab2,
                    "양념 및 부침가루": sub_tab3
                }
                
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
                                try:
                                    parsed_date = datetime.strptime(clean_date_str, "%Y-%m-%d").date()
                                    days_passed = (kst_today - parsed_date).days + 1
                                    days_label = f"{days_passed}일째"
                                except ValueError:
                                    days_label = "-"
                                    
                                cat_items.append((sheet_row_idx, current_ing, clean_date_str, days_label, current_cat))
                        
                        if cat_items:
                            st.write("") # 여백
                            for sheet_row_idx, current_ing, clean_date_str, days_label, current_cat in cat_items:
                                r_c1, r_c2, r_c3, r_c4 = st.columns([2.2, 1.5, 1.2, 0.7])
                                
                                with r_c1:
                                    st.markdown(f"<span style='font-size: 1.05rem; font-weight: bold;'>{current_ing}</span>", unsafe_allow_html=True)
                                with r_c2:
                                    st.markdown(f"<span style='font-size: 0.9rem; color: #666;'>📅 {clean_date_str}</span>", unsafe_allow_html=True)
                                with r_c3:
                                    st.markdown(f"<span style='font-size: 0.85rem; color: #333;'>⏱️ {days_label}</span>", unsafe_allow_html=True)
                                with r_c4:
                                    # 클릭 시 화면 정중앙에 팝업창 모달 호출
                                    if st.button("⚙️", key=f"gear_{sheet_row_idx}", help="품목 관리"):
                                        open_edit_dialog(sheet_row_idx, current_ing, clean_date_str, current_cat, web_app_url)
                                        
                                st.markdown("<hr style='margin: 5px 0px; border: none; border-top: 1px solid #eee;'>", unsafe_allow_html=True)
                        else:
                            st.info(f"등록된 [{cat_name}] 항목이 없습니다.")
            else:
                st.info("냉장고가 텅 비어있습니다. 품목을 추가해 보세요!")

        with tab2:
            st.subheader("🤖 AI 맞춤 레시피 및 한상차림 식단")
            
            col_opt1, col_opt2 = st.columns(2)
            with col_opt1:
                selected_category = st.selectbox(
                    "요리 종류 선택",
                    ["전체 (상관없음)", "볶음류", "찌개/국물류", "구이/부침류", "무침/샐러드류", "면/분식류"]
                )
            with col_opt2:
                plan_period = st.selectbox(
                    "추천 유형 선택",
                    ["단기 추천 (메인 요리 3가지)", "📅 1주일 한상차림 캘린더 식단 (메인+밑반찬+양념 조합)"]
                )
            
            if not groq_api_key:
                st.warning("⚠️ AI 기능을 사용하려면 사이드바에 Groq API Key를 입력하고 **[설정 저장하기]** 버튼을 눌러주세요.")
            else:
                button_label = "✨ Groq 레시피 추천 받기" if "단기" in plan_period else "📅 1주일 한상차림 캘린더 생성하기"
                if st.button(button_label, use_container_width=True):
                    try:
                        if len(rows) <= 1:
                            st.warning("냉장고가 비어있어 추천할 재료가 없습니다!")
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
                                    elif cat == "양념 및 부침가루":
                                        condiments.append(ing_name)
                                    else:
                                        ingredients_all.append(ing_name)
                            
                            main_str = ", ".join(ingredients_all) if ingredients_all else "없음"
                            side_str = ", ".join(side_dishes) if side_dishes else "없음"
                            cond_str = ", ".join(condiments) if condiments else "기본 양념"
                            
                            with st.spinner("Groq AI가 식자재, 밑반찬, 양념류를 분석하여 최적의 한상차림을 구성하고 있습니다..."):
                                client = Groq(api_key=groq_api_key)
                                
                                if "단기" in plan_period:
                                    prompt = f"""
다음은 우리집 냉장고 보유 품목들이야:
- 식자재: [{main_str}]
- 보유 밑반찬: [{side_str}]
- 양념 및 부침가루: [{cond_str}]

사용자가 선호하는 요리 종류(카테고리)는 다음과 같아: [{selected_category}].
이 재료들과 보유 중인 밑반찬, 양념류를 조화롭게 활용하여 만들 수 있는 최고의 메인 요리 3가지를 추천해줘.

[매우 중요한 규칙]
- 답변은 반드시 **100% 순수한 한국어(국문)**로만 작성해 주세요. 
- 중국어, 일본어, 한자(漢字)는 절대 사용하지 마세요.
- 조리 순서(instructions)는 반드시 줄바꿈 문자(\\n)를 사용하여 세로로 떨어지도록 작성해 주세요.

반드시 아래 구조를 가진 JSON 객체 형태로만 답변해줘. 루트 키는 "recipes"로 하고 값은 배열 형태로 만들어줘.

{{
  "recipes": [
    {{
      "recipe_name": "요리 이름",
      "matched_ingredients": ["사용한 보유 재료들"],
      "missing_ingredients": ["추가로 필요한 재료들"],
      "instructions": "1. 첫 번째 단계\\n2. 두 번째 단계\\n3. 세 번째 단계"
    }}
  ]
}}
"""
                                else:
                                    prompt = f"""
다음은 우리집 냉장고 보유 품목들이야:
- 식자재: [{main_str}]
- 보유 밑반찬: [{side_str}]
- 양념 및 부침가루: [{cond_str}]

이 재료들과 밑반찬, 양념류를 활용하여, 7일 동안(1주일) 메인 요리와 보유 중인 밑반찬을 조화롭게 곁들여 먹을 수 있는 영양 균형 잡힌 **'1주일 한상차림 식단'**을 짜줘.

[매우 중요한 규칙]
- 답변은 반드시 **100% 순수한 한국어(국문)**로만 작성해 주세요. 
- 중국어, 일본어, 한자(漢字)는 절대 사용하지 마세요.
- 1주일치 식단을 요약하는 형태로 구성하되, 각 날짜별로 메인 요리와 함께 곁들일 밑반찬 구성을 recipe_name에 적어줘 (예: "1일차: 김치찌개 + 멸치볶음").
- 조리 순서(instructions)는 줄바꿈 문자(\\n)를 사용하여 세로로 작성해줘.

반드시 아래 구조를 가진 JSON 객체 형태로만 답변해줘. 루트 키는 "recipes"로 하고 값은 배열 형태로 만들어줘. (총 7일치)

{{
  "recipes": [
    {{
      "recipe_name": "1일차: 메인요리명 + 곁들일 밑반찬",
      "matched_ingredients": ["사용한 보유 재료들"],
      "missing_ingredients": ["추가로 필요한 재료들"],
      "instructions": "1. 첫 번째 단계\\n2. 두 번째 단계\\n3. 세 번째 단계"
    }}
  ]
}}
"""
                                
                                chat_completion = client.chat.completions.create(
                                    messages=[
                                        {
                                            "role": "system",
                                            "content": "You are a helpful culinary assistant that outputs only valid JSON with proper newline characters."
                                        },
                                        {
                                            "role": "user",
                                            "content": prompt,
                                        }
                                    ],
                                    model="llama-3.3-70b-versatile",
                                    response_format={"type": "json_object"},
                                )
                                
                                result_text = chat_completion.choices[0].message.content
                                response_data = json.loads(result_text)
                                recipes = response_data.get("recipes", [])
                                
                                if "1주일" in plan_period:
                                    st.subheader("📅 1주일 한상차림 캘린더 식단표")
                                    st.write("메인 요리와 냉장고 속 밑반찬이 조화를 이루는 7일간의 식단 요약입니다.")
                                    
                                    calendar_data = []
                                    for r in recipes:
                                        calendar_data.append({
                                            "일정": r['recipe_name'].split(":")[0] if ":" in r['recipe_name'] else "일정",
                                            "추천 한상 메뉴": r['recipe_name'],
                                            "사용 재료": ", ".join(r['matched_ingredients']),
                                            "추가 장보기": ", ".join(r['missing_ingredients']) if r['missing_ingredients'] else "없음"
                                        })
                                    
                                    df_cal = pd.DataFrame(calendar_data)
                                    st.dataframe(df_cal, use_container_width=True, hide_index=True)
                                    
                                    st.divider()
                                    st.subheader("🍳 상세 조리법 및 한상 차림 가이드")
                                    for i, r in enumerate(recipes, 1):
                                        with st.expander(f"📌 {r['recipe_name']}"):
                                            st.write(f"✅ **사용 재료:** {', '.join(r['matched_ingredients'])}")
                                            st.write(f"🛒 **추가 필요 재료:** {', '.join(r['missing_ingredients']) if r['missing_ingredients'] else '없음'}")
                                            st.markdown(f"**조리법:**\n\n{r['instructions']}")
                                else:
                                    for i, r in enumerate(recipes, 1):
                                        st.markdown(f"### 🏆 {i}. {r['recipe_name']}")
                                        st.write(f"✅ **사용하는 재료:** {', '.join(r['matched_ingredients'])}")
                                        st.write(f"🛒 **필요한 추가 재료:** {', '.join(r['missing_ingredients']) if r['missing_ingredients'] else '없음'}")
                                        st.markdown(f"🍳 **조리법:**\n\n{r['instructions']}")
                                        st.divider()
                                        
                    except Exception as e:
                        st.error(f"레시피 추천 중 오류가 발생했습니다: {e}")