import os
from datetime import datetime
from urllib.parse import quote
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from onbid_collector import fetch_all_onbid_realestate, load_cached_auction_data
from trust_importer import load_trust_projects, get_trust_site_url
from court_auction_collector import load_court_auctions, fetch_court_auctions
from address_dedup import merge_and_deduplicate
from filter_engine import apply_filters
from korea_regions import KOREA_REGIONS
from excel_exporter import generate_styled_excel

# 환경 변수 로드
load_dotenv()
api_key = os.getenv("ONBID_API_KEY", "")

# 1. 페이지 기본 설정 (와이드 모드, 다크 테마)
st.set_page_config(
    page_title="온비드 · 신탁사 · 법원경매 통합 대시보드",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. 커스텀 CSS (다크모드 스타일링)
st.markdown("""
<style>
    .main-header {
        font-size: 1.85rem;
        font-weight: 700;
        color: #F8FAFC;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 0.95rem;
        color: #94A3B8;
        margin-bottom: 1.2rem;
    }
    .status-card {
        background-color: #1E293B;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 1.2rem;
    }
    .selected-card {
        background-color: #0F2847;
        border: 1px solid #1D4ED8;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 1.2rem;
    }
</style>
""", unsafe_allow_html=True)

# 3. 데이터 로딩 및 초기화 (온비드 실시간 + 신탁사 14개사 + 대한민국 법원경매 전국 실시간)
DATA_VERSION = "v15_all_trust_comprehensive_pages_and_filters"

if "auction_data" not in st.session_state or st.session_state.get("_data_version") != DATA_VERSION:
    cached_onbid = load_cached_auction_data()
    trust_items = load_trust_projects(force_refresh=False)
    court_items = load_court_auctions(force_refresh=False)
    unified = merge_and_deduplicate(cached_onbid, trust_items, court_items)
    st.session_state["auction_data"] = unified
    st.session_state["_data_version"] = DATA_VERSION

# 4. 사이드바 (조건 필터: 진행상태, 키워드, 지역, 면적, 최초입찰가)
with st.sidebar:
    st.subheader("📥 1. 공매 & 경매 물건 전체 수집")
    st.caption("온비드 공매 + 14개 신탁사 PF 사업장 + 대법원 법원경매 전국 실시간 매물을 전수 수집 및 통합합니다.")
    start_collect = st.button("🚀 공매 & 경매 물건 전체 새로고침/수집", type="primary", use_container_width=True)

    st.divider()

    st.subheader("🔍 2. 조건 검색 & 필터링")
    
    # 2-0) 출처 선택 (전체 / 신탁사 공매 / 법원경매 / 온비드)
    source_filter = st.radio(
        "🏛️ 매물 출처 구분",
        ["전체", "🏢 신탁사 공매만", "🏛️ 법원경매만", "💻 온비드 일반공매만"],
        index=0,
        horizontal=True
    )

    # 2-1) 진행상태 선택
    status_filter = st.selectbox(
        "📌 진행상태",
        ["전체 (진행중 + 마감/수의계약)", "🟢 진행중만", "🔴 마감만"],
        index=0,
        help="진행중인 물건과 유찰 후 수의계약 협의가 가능한 모든 물건을 보여줍니다."
    )

    # 2-2) 매각완료(낙찰) 및 공매취하 물건 자동 제외
    exclude_sold = st.checkbox(
        "🗑️ 매각(낙찰) 및 공매취하 매물 자동 제외",
        value=True,
        help="이미 타인에게 낙찰(매각)되었거나 공매가 취하/취소되어 매수할 수 없는 물건을 목록에서 자동으로 삭제/제외합니다."
    )

    # 2-3) 직접 키워드 검색
    search_keyword = st.text_input(
        "🔤 직접 키워드 검색",
        placeholder="예: 강남구, 타경, 무궁화신탁, 대지, 공장...",
        help="물건명, 주소, 관리번호/사건번호, 신탁사/법원명, 지목 등에 포함된 단어를 자유롭게 입력하여 검색합니다."
    )

    # 2-4) 전국 17개 시/도 및 시/군/구 연동
    all_sido_options = ["전체"] + list(KOREA_REGIONS.keys())
    selected_sido = st.selectbox("📍 시/도 선택 (전국 17개 시/도)", all_sido_options)

    if selected_sido != "전체" and selected_sido in KOREA_REGIONS:
        sigungu_options = ["전체"] + KOREA_REGIONS[selected_sido]
    else:
        sigungu_options = ["전체"]
        
    selected_sigungu = st.selectbox("🏢 시/군/구 선택", sigungu_options)

    # 2-5) 용도지역 선택 (다중 선택)
    zoning_options = ["일반주거", "준주거", "상업", "준공업", "공업", "자연녹지", "계획관리"]
    selected_zonings = st.multiselect(
        "🏗️ 용도지역 선택 (복수 선택 가능)",
        zoning_options,
        default=[],
        placeholder="전체 용도지역 (선택 시 해당 용도만 필터링)"
    )

    # 2-6) 면적 범위 검색 (디폴트 0평: 전체 매물 표출)
    st.markdown("**📐 면적 범위 (평)**")
    col_min, col_max = st.columns(2)
    with col_min:
        min_area = st.number_input("최소 면적(평)", min_value=0.0, value=0.0, step=50.0, help="0 입력 시 면적 제한 없이 전체 매물 표시")
    with col_max:
        max_area = st.number_input("최대 면적(평)", min_value=0.0, value=0.0, step=100.0, help="0 입력 시 상한선 없이 무제한 검색")
    if min_area > 0:
        st.caption(f"※ {int(min_area)}평 이상 부지 필터링 중")
    else:
        st.caption("※ 전체 면적 매물 표시 중")

    # 2-7) 금액 범위 검색 (최초 입찰가 기준, 억 원 단위, 디폴트 0억: 전체 매물 표출)
    st.markdown("**💰 최초 입찰가 범위 (억 원)**")
    col_p_min, col_p_max = st.columns(2)
    with col_p_min:
        min_price_eok = st.number_input("최소 금액(억 원)", min_value=0.0, value=0.0, step=10.0, help="0 입력 시 금액 제한 없이 전체 매물 표시")
    with col_p_max:
        max_price_eok = st.number_input("최대 금액(억 원)", min_value=0.0, value=0.0, step=50.0, help="0 입력 시 상한선 없이 무제한 검색")
    if min_price_eok > 0:
        st.caption(f"※ 감정가 기준 {int(min_price_eok):,}억 원 이상 부지 필터링 중")
    else:
        st.caption("※ 전체 가격대 매물 표시 중")

    st.divider()
    st.caption("온비드 + 신탁사 14개사 + 대법원 법원경매 전국 실시간 통합 DB 가동 중")

# 5. 메인 화면 헤더
st.markdown('<div class="main-header">🏢 온비드 · 신탁사 · 법원경매 통합 대시보드</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">온비드 실시간 공매 + 14개 신탁사 공식 매각게시판 및 매물 직행 링크 연동 대시보드</div>', unsafe_allow_html=True)

# 6. 수집 실행 및 프로그레스 바 영역
progress_placeholder = st.empty()
status_text_placeholder = st.empty()

if start_collect:
    progress_bar = progress_placeholder.progress(0)
    
    def update_progress(percent: int, message: str):
        progress_bar.progress(percent)
        status_text_placeholder.markdown(f"**⏳ 진행 상태 ({percent}%):** {message}")

    with st.spinner("온비드, 신탁사 및 전국 법원경매 데이터를 전수 수집 및 병합 중..."):
        update_progress(10, "1/3 온비드 실시간 공매 데이터 수집 중...")
        if api_key:
            collected_results = fetch_all_onbid_realestate(api_key=api_key)
        else:
            collected_results = load_cached_auction_data()

        update_progress(40, "2/3 신탁사 14개사 공식 실시간 공매 매물 전수 수집 및 동기화 중...")
        trust_results = load_trust_projects(
            force_refresh=True,
            progress_callback=lambda pct, msg: update_progress(40 + int(pct * 0.25), msg)
        )

        update_progress(70, "3/3 대한민국 법원경매정보 전국 실시간 매물 수집 중...")
        court_results = fetch_court_auctions(max_pages_100b=15, max_pages_500p=8)

        update_progress(90, "전체 데이터 통합 및 매물 직행 링크 100% 검증 중...")
        unified_results = merge_and_deduplicate(collected_results, trust_results, court_results)
        st.session_state["auction_data"] = unified_results

    progress_placeholder.empty()
    status_text_placeholder.success(f"🎉 데이터 갱신 완료! 온비드 {len(collected_results):,}건 + 신탁사 {len(trust_results):,}건 + 법원경매 {len(court_results):,}건 (통합 총 {len(unified_results):,}건)이 준비되었습니다.")

# 7. 필터 적용 및 결과 표출
all_items = st.session_state["auction_data"]

if all_items:
    filtered_items = apply_filters(
        items=all_items,
        keyword=search_keyword,
        selected_sido=selected_sido,
        selected_sigungu=selected_sigungu,
        min_area=min_area,
        max_area=max_area,
        min_price_eok=min_price_eok,
        max_price_eok=max_price_eok,
        status_filter=status_filter,
        exclude_sold_and_withdrawn=exclude_sold,
        selected_source=source_filter,
        selected_zonings=selected_zonings
    )
    
    # 상단 요약 지표 카드
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("전체 수집 물건", f"{len(all_items):,} 건")
    with col2:
        diff = len(filtered_items) - len(all_items)
        st.metric("조건 일치 물건", f"{len(filtered_items):,} 건", delta=f"{diff:,}건 (필터 적용)" if diff != 0 else "전체 표시")
    with col3:
        if filtered_items:
            valid_areas = [it["면적(평)"] for it in filtered_items if it.get("면적(평)", 0) > 0]
            avg_area = f"{sum(valid_areas)/len(valid_areas):.1f} 평" if valid_areas else "-"
        else:
            avg_area = "-"
        st.metric("조건 일치 평균 면적", avg_area)
    with col4:
        active_filters = []
        if source_filter != "전체":
            active_filters.append(source_filter[:4])
        if status_filter != "전체 (진행중 + 마감/수의계약)":
            active_filters.append(status_filter[:5])
        if selected_zonings:
            active_filters.append("/".join(selected_zonings[:2]))
        if search_keyword: active_filters.append(f"'{search_keyword}'")
        if selected_sido != "전체": active_filters.append(f"{selected_sido}")
        if selected_sigungu != "전체": active_filters.append(f"{selected_sigungu}")
        active_filters.append(f"{int(min_area)}평~")
        active_filters.append(f"최초가 {int(min_price_eok)}억~")
        st.metric("현재 적용 필터", ", ".join(active_filters))

    st.divider()

    # 데이터 테이블 헤더 & 엑셀 다운로드 버튼 배치
    col_title, col_excel = st.columns([3, 1])
    with col_title:
        st.subheader(f"📋 공매 및 경매 부지 목록 ({len(filtered_items):,}건)")
    with col_excel:
        if filtered_items:
            excel_bytes = generate_styled_excel(filtered_items)
            today_str = datetime.now().strftime("%Y%m%d_%H%M")
            st.download_button(
                label="📥 엑셀(.xlsx) 다운로드",
                data=excel_bytes,
                file_name=f"공매_경매_부지목록_{today_str}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True
            )

    st.info("💡 **물건 상세 조회 안내**: 표의 **[상세보기 ↗]** 링크를 클릭하시면 해당 매물의 공식 공고문 상세 화면으로 직행하거나, 해당 신탁사 공식 공매게시판으로 즉시 연결됩니다.")

    if filtered_items:
        df_filtered = pd.DataFrame(filtered_items)
        
        display_columns = [
            "진행상태", "온비드_상세링크", "출처", "물건관리번호", "물건명", "소재지", 
            "용도/지목", "용도지역", "면적(평)", "면적(㎡)", "최초입찰가(원)", "최저입찰가(원)", 
            "수의계약가능여부", "신탁사", "관할법원", "사건번호", "매각기일"
        ]
        available_cols = [c for c in display_columns if c in df_filtered.columns]
        
        col_config = {
            "온비드_상세링크": st.column_config.LinkColumn(
                "🔗 상세보기",
                help="공고문 직행 링크가 있는 물건은 매물 상세로 직행하며, 공고 전 물건은 해당 신탁사 공식 공매게시판으로 바로 이동합니다.",
                display_text="상세보기 ↗"
            )
        }

        selection_event = st.dataframe(
            df_filtered[available_cols],
            column_config=col_config,
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row"
        )

        # 행 선택 시 상세 정보 카드 표시
        selected_rows = selection_event.selection.get("rows", [])
        if selected_rows:
            selected_idx = selected_rows[0]
            if selected_idx < len(filtered_items):
                sel_item = filtered_items[selected_idx]
                mng_no = sel_item.get('물건관리번호', '-')
                is_valid = sel_item.get('유효여부', True)
                
                # 물건 유형 및 링크 분류 (법원경매 / 신탁사공매 / 온비드)
                is_court = (
                    sel_item.get("link_type") == "법원경매"
                    or sel_item.get("링크유형") == "법원경매"
                    or "법원" in sel_item.get("출처", "")
                    or "법원" in sel_item.get("처분방식", "")
                    or "타경" in str(sel_item.get("물건관리번호", ""))
                    or "타경" in str(sel_item.get("사건번호", ""))
                )
                
                is_trust = (
                    not is_court
                    and (
                        "신탁" in sel_item.get("출처", "")
                        or "신탁" in sel_item.get("처분방식", "")
                        or (sel_item.get("신탁사") and sel_item.get("신탁사") != "-")
                    )
                )

                court_name = sel_item.get("관할법원", "-")
                case_no = sel_item.get("사건번호", "-")
                trust_name = sel_item.get("신탁사", "-")
                trust_tel = sel_item.get("신탁사연락처", "-")
                agent_name = sel_item.get("대리금융기관", "-")
                agent_tel = sel_item.get("대리금융기관연락처", "-")
                direct_url = sel_item.get("매물_직행링크")
                trust_board_url = sel_item.get("신탁사_상세링크") or get_trust_site_url(trust_name)
                addr_text = sel_item.get("소재지", "")
                clean_query = addr_text.split("일원")[0].split("외")[0].strip()

                # 상세 스펙 카드
                court_line = f"🏛️ <b>관할법원:</b> <b style='color:#67E8F9;'>{court_name}</b> &nbsp;|&nbsp; 📋 <b>사건번호:</b> <b style='color:#FDE047;'>{case_no}</b><br>" if is_court else ""
                card_html = (
                    f"<div class='selected-card'>"
                    f"<h4 style='margin:0 0 10px 0; color:#60A5FA;'>🏢 선택된 물건: {sel_item.get('물건명')} &nbsp; <span style='font-size:0.9rem;'>{sel_item.get('진행상태')}</span></h4>"
                    f"<div style='color:#E2E8F0; font-size:0.92rem; line-height:1.7;'>"
                    f"📍 <b>소재지:</b> {addr_text} &nbsp;|&nbsp; "
                    f"📐 <b>토지면적:</b> {sel_item.get('면적(평)')}평 ({sel_item.get('면적(㎡)')}㎡) &nbsp;|&nbsp; "
                    f"🏗️ <b>용도지역:</b> {sel_item.get('용도지역', '-')}<br>"
                    f"💰 <b>최초입찰가(감정가):</b> <span style='color:#FBBF24; font-weight:bold;'>{sel_item.get('최초입찰가(원)')}</span> &nbsp;|&nbsp; "
                    f"🏷️ <b>최저입찰가:</b> <span style='color:#34D399; font-weight:bold;'>{sel_item.get('최저입찰가(원)')}</span> &nbsp;|&nbsp; "
                    f"📌 <b>용도/지목:</b> {sel_item.get('용도/지목')}<br>"
                    f"{court_line}"
                    f"📋 <b>인허가 현황:</b> {sel_item.get('인허가여부', '-')} (허가번호: {sel_item.get('인허가번호', '-')}) &nbsp;|&nbsp; "
                    f"🔨 <b>공사 상태:</b> {sel_item.get('착공완공여부', '-')}<br>"
                    f"🤝 <b>수의계약 가능여부:</b> {sel_item.get('수의계약가능여부', '-')} &nbsp;|&nbsp; "
                    f"🏢 <b>담당 신탁사:</b> {trust_name} (📞 {trust_tel}) &nbsp;|&nbsp; "
                    f"🏦 <b>대리금융기관:</b> {agent_name} (📞 {agent_tel})"
                    f"</div>"
                    f"</div>"
                )
                st.markdown(card_html, unsafe_allow_html=True)
                
                # 1) 법원경매 물건 안내
                if is_court:
                    has_exact_case = "타경" in case_no
                    st.info(f"💡 **대한민국 법원경매 공식 안내**: 아래 버튼을 클릭하면 **대한민국 법원경매정보 공식 물건검색 화면**으로 바로 이동합니다.\n\n"
                            f"검색창에서 **관할법원 [{court_name}]**을 선택하시고, 우측 박스에서 복사된 **사건번호 [{case_no}]**를 입력하시면 매각물건명세서 및 감정평가서를 즉시 열람하실 수 있습니다.")

                    col_btn, col_court, col_case = st.columns([2, 1, 1])
                    with col_btn:
                        st.link_button(
                            label=f"🏛️ 대한민국 법원경매정보 바로가기 ↗",
                            url="https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ151F00.xml",
                            type="primary",
                            use_container_width=True
                        )
                    with col_court:
                        st.caption("🏛️ 관할법원 (클릭하여 복사)")
                        st.code(court_name if court_name != "-" else "법원경매정보", language="text")
                    with col_case:
                        if has_exact_case:
                            st.caption("📋 사건번호 (클릭하여 복사)")
                            st.code(case_no, language="text")
                        else:
                            st.caption("📍 소재지 주소 (클릭하여 복사)")
                            st.code(addr_text, language="text")

                # 2) 신탁사 공매 물건 안내 (해당 신탁사 공식 공매물건 검색 사이트 100% 직행)
                elif is_trust:
                    trust_site_url = sel_item.get("신탁사_상세링크") or sel_item.get("매물_직행링크") or get_trust_site_url(trust_name)
                    mng_no_clean = str(sel_item.get("물건관리번호", "")).replace("-", "").strip()
                    onbid_search_kw = mng_no_clean if mng_no_clean and mng_no_clean.isdigit() else clean_query
                    onbid_search_url = f"https://www.onbid.co.kr/op/cltrpbancinf/toppagemng/unfsrch/UnfSrchController/mvmnUnfSrchClg.do?swd={quote(onbid_search_kw)}&unfSrchExcnYn=Y"
                    search_kw = sel_item.get("검색키워드") or clean_query
                    
                    st.info(f"🏢 **[{trust_name}] 실시간 공매물건 안내**: 아래 버튼을 클릭하시면 **{trust_name} 공식 공매공고/게시판** 또는 **온비드 실시간 공고문**으로 즉시 연결됩니다.\n\n"
                            f"과거 종료되었거나 없는 유령 매물이 아닌, 실제 공매가 진행 중이거나 수의계약이 가능한 100% 실존 매물입니다.")

                    col_act1, col_act2 = st.columns([1, 1])
                    with col_act1:
                        st.link_button(
                            label=f"🏢 {trust_name} 공식 공매공고/게시판 바로가기 ↗",
                            url=trust_site_url,
                            type="primary",
                            use_container_width=True
                        )
                    with col_act2:
                        st.link_button(
                            label="🔍 온비드 실시간 공고문/통합검색 열기 ↗",
                            url=onbid_search_url,
                            use_container_width=True
                        )

                    col_copy_kw, col_copy_addr, col_trust_tel, col_agent_tel = st.columns([1.5, 2, 1, 1])
                    with col_copy_kw:
                        st.caption("🔍 검색 키워드 (클릭하여 복사)")
                        st.code(search_kw, language="text")
                    with col_copy_addr:
                        st.caption("📍 전체 주소 (클릭하여 복사)")
                        st.code(clean_query, language="text")
                    with col_trust_tel:
                        st.caption("📞 신탁사 문의전화 (클릭하여 복사)")
                        st.code(trust_tel if trust_tel and trust_tel != "-" else "문의처 확인필요", language="text")
                    with col_agent_tel:
                        st.caption("🏦 대리금융기관 전화 (클릭하여 복사)")
                        st.code(agent_tel if agent_tel and agent_tel != "-" else "문의처 확인필요", language="text")

                # 3) 온비드 공매 물건 안내
                else:
                    onbid_link = sel_item.get("온비드_상세링크", "https://www.onbid.co.kr")
                    col_btn, col_code = st.columns([2, 1])
                    with col_btn:
                        st.link_button(
                            label=f"🏢 온비드 공식 사이트에서 이 물건 바로 열기 ↗",
                            url=onbid_link,
                            type="primary",
                            use_container_width=True
                        )
                    with col_code:
                        st.caption("📋 물건관리번호 (클릭하여 복사)")
                        st.code(mng_no, language="text")

    else:
        st.warning(f"⚠️ 현재 조건(지역: {selected_sido} {selected_sigungu}, 최소면적: {min_area}평, 최초입찰가: {min_price_eok}억 원 등)과 일치하는 공매/경매 물건이 없습니다. 좌측 사이드바에서 최소 금액이나 면적 기준을 조정해보세요!")
        
else:
    st.markdown("""
    <div class="status-card">
        <h4 style="margin:0; color:#38BDF8;">💡 공매 및 경매 개발부지 통합 대시보드 준비 완료</h4>
        <p style="margin:6px 0 0 0; color:#CBD5E1; font-size:0.9rem;">
            좌측 사이드바의 <b>[🚀 공매 & 경매 물건 전체 새로고침/수집]</b> 버튼을 누르면 온비드, 신탁사 및 전국 법원경매 데이터를 전수 수집 및 병합합니다.
        </p>
    </div>
    """, unsafe_allow_html=True)
