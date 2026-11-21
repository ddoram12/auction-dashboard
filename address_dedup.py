import re
from typing import List, Dict, Any, Tuple
from korea_regions import match_sido, SIDO_ALIASES
from trust_importer import normalize_sido_name, extract_dong_bunji, get_trust_site_url, clean_property_link, TRUST_AUCTION_BOARDS, get_trust_search_url, extract_search_keyword

def merge_and_deduplicate(
    onbid_items: List[Dict[str, Any]],
    trust_items: List[Dict[str, Any]],
    court_items: List[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    온비드 실시간 수집 물건 + 신탁사 PF 사업장 리스트 + 대한민국 법원경매 전국 실시간 물건을
    사건번호, 관리번호 및 동/번지 기준으로 상호 대조·병합하여 통합 데이터셋을 생성합니다.
    - 매물 직행 링크(단축코드/공고번호)가 있는 물건은 클릭 시 해당 매물 상세 페이지로 100% 직행합니다.
    - 공고 전 또는 수의계약 물건은 해당 신탁사의 '공식 공매/매각 전용 게시판'으로 연결됩니다.
    - 법원경매 물건은 대법원 법원경매정보 검색 화면으로 직행합니다.
    """
    merged_list = []
    
    # 1. 온비드 물건 색인화 (관리번호 및 동_번지 키)
    mng_index: Dict[str, int] = {}
    addr_index: Dict[Tuple[str, str], int] = {}

    for idx, item in enumerate(onbid_items):
        item_copy = dict(item)
        
        if "출처" not in item_copy:
            item_copy["출처"] = "온비드"
        if "신탁사" not in item_copy:
            item_copy["신탁사"] = "-"
        if "인허가여부" not in item_copy:
            item_copy["인허가여부"] = "-"
        if "인허가번호" not in item_copy:
            item_copy["인허가번호"] = "-"
        if "착공완공여부" not in item_copy:
            item_copy["착공완공여부"] = "-"
        if "대리금융기관" not in item_copy:
            item_copy["대리금융기관"] = "-"
        if "수의계약가능여부" not in item_copy:
            item_copy["수의계약가능여부"] = "해당없음"
        if "용도지역" not in item_copy:
            item_copy["용도지역"] = item_copy.get("용도/지목", "-")

        merged_list.append(item_copy)

        mng_no = item_copy.get("물건관리번호", "").strip()
        if mng_no and mng_no != "-":
            mng_index[mng_no] = idx

        sido = normalize_sido_name(item_copy.get("시도", ""))
        full_text = f"{item_copy.get('소재지', '')} {item_copy.get('물건명', '')}"
        dong_bunji = extract_dong_bunji(full_text)
        if sido and dong_bunji:
            addr_index[(sido, dong_bunji)] = idx

    # 2. 신탁사 사업장 매칭 및 병합
    matched_trust_indices = set()

    for t_idx, t_item in enumerate(trust_items):
        t_mng = t_item.get("물건관리번호", "").strip()
        t_sido = normalize_sido_name(t_item.get("시도", ""))
        t_dong_bunji = t_item.get("동번지키") or extract_dong_bunji(t_item.get("소재지", ""))

        matched_target_idx = None

        if t_mng and t_mng != "-" and t_mng in mng_index:
            matched_target_idx = mng_index[t_mng]
        elif (t_sido, t_dong_bunji) in addr_index:
            matched_target_idx = addr_index[(t_sido, t_dong_bunji)]

        if matched_target_idx is not None:
            target = merged_list[matched_target_idx]
            target["출처"] = f"신탁사({t_item.get('신탁사')})" if t_item.get("신탁사") else "신탁사공매"
            target["신탁사"] = t_item.get("신탁사") or target.get("신탁사", "-")
            target["신탁사연락처"] = t_item.get("신탁사연락처", "-")
            target["대리금융기관"] = t_item.get("대리금융기관", "-")
            target["대리금융기관연락처"] = t_item.get("대리금융기관연락처", "-")
            target["인허가여부"] = t_item.get("인허가여부", "-")
            target["인허가번호"] = t_item.get("인허가번호", "-")
            target["착공완공여부"] = t_item.get("착공완공여부", "-")
            target["수의계약가능여부"] = t_item.get("수의계약가능여부", "-")
            target["세부상황"] = t_item.get("세부상황", "-")
            if t_item.get("매물_직행링크"):
                target["매물_직행링크"] = t_item.get("매물_직행링크")
            if t_item.get("용도지역") and t_item.get("용도지역") != "-":
                target["용도지역"] = t_item.get("용도지역")
            matched_trust_indices.add(t_idx)
        else:
            merged_list.append(dict(t_item))

    # 3. 법원경매 전국 실시간 물건 병합 (사건번호 및 동/번지 중복 체크)
    if court_items:
        court_case_index: Dict[Tuple[str, str], int] = {}
        for idx, item in enumerate(merged_list):
            c_no = item.get("사건번호", "").strip()
            c_court = item.get("관할법원", "").strip()
            if c_no and "타경" in c_no:
                court_case_index[(c_court, c_no)] = idx
            sido = normalize_sido_name(item.get("시도", ""))
            dong_bunji = extract_dong_bunji(f"{item.get('소재지', '')} {item.get('물건명', '')}")
            if sido and dong_bunji:
                addr_index[(sido, dong_bunji)] = idx

        for c_item in court_items:
            c_no = c_item.get("사건번호", "").strip()
            c_court = c_item.get("관할법원", "").strip()
            c_sido = normalize_sido_name(c_item.get("시도", ""))
            c_dong_bunji = extract_dong_bunji(f"{c_item.get('소재지', '')} {c_item.get('물건명', '')}")

            matched_idx = None
            if (c_court, c_no) in court_case_index:
                matched_idx = court_case_index[(c_court, c_no)]
            elif (c_sido, c_dong_bunji) in addr_index:
                matched_idx = addr_index[(c_sido, c_dong_bunji)]

            if matched_idx is not None:
                target = merged_list[matched_idx]
                target["최저입찰가(원)"] = c_item.get("최저입찰가(원)", target.get("최저입찰가(원)"))
                target["최저입찰가_숫자"] = c_item.get("최저입찰가_숫자", target.get("최저입찰가_숫자"))
                target["최저입찰가_억"] = c_item.get("최저입찰가_억", target.get("최저입찰가_억"))
                target["유찰횟수"] = c_item.get("유찰횟수", target.get("유찰횟수"))
                target["진행상태"] = c_item.get("진행상태", target.get("진행상태"))
                target["사건번호"] = c_no
                target["관할법원"] = c_court
                target["출처"] = "법원경매(실시간)+신탁PF"
            else:
                merged_list.append(dict(c_item))

    # 4. [핵심] 전체 물건 링크 정밀 설정
    for it in merged_list:
        # A. 법원경매 물건인지 판별
        is_court = (
            "법원" in str(it.get("출처", ""))
            or "법원" in str(it.get("처분방식", ""))
            or "타경" in str(it.get("사건번호", ""))
            or "타경" in str(it.get("물건관리번호", ""))
        )
        if is_court:
            court_url = "https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ151F00.xml"
            it["링크유형"] = "법원경매"
            it["link_type"] = "법원경매"
            it["온비드_상세링크"] = court_url
            it["매물_직행링크"] = court_url
            continue

        # B. 신탁사 물건인지 판별
        trust_name = it.get("신탁사", "").strip()
        if not trust_name or trust_name == "-":
            for t_key in TRUST_AUCTION_BOARDS.keys():
                if t_key in str(it.get("출처", "")) or t_key in str(it.get("물건명", "")) or t_key in str(it.get("재산구분", "")):
                    trust_name = t_key
                    it["신탁사"] = t_key
                    break

        is_trust = (
            "신탁" in str(it.get("출처", ""))
            or "신탁" in str(it.get("처분방식", ""))
            or (trust_name and trust_name != "-")
        )

        if is_trust:
            trust_board_url = get_trust_site_url(trust_name or it.get("출처", ""))
            search_kw = it.get("검색키워드") or extract_search_keyword(it.get("소재지", ""), it.get("물건명", ""))

            it["신탁사_상세링크"] = trust_board_url
            it["검색키워드"] = search_kw
            it["온비드_상세링크"] = trust_board_url  # 표의 '상세보기' 클릭 시 해당 신탁사 공식 공매물건 검색 사이트로 100% 직행!
            it["링크유형"] = "신탁사공매"
            it["link_type"] = "신탁사공매"

            if not it.get("신탁사") or it.get("신탁사") == "-":
                it["신탁사"] = trust_name if trust_name else "신탁사"

    return merged_list
