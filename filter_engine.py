from datetime import datetime
from typing import List, Dict, Any, Optional
from korea_regions import match_sido, match_sigungu

# 매각 완료 및 공매 취하/취소 식별 키워드
SOLD_WITHDRAWN_KEYWORDS = [
    "낙찰", "매각완료", "공매취하", "경매취하", "취하", "공매취소", "경매취소", "취소", "중지"
]

def is_sold_or_withdrawn(item: Dict[str, Any]) -> bool:
    """
    물건이 이미 매각(낙찰)되었거나 공매가 취하/취소되어 더 이상 매수할 수 없는 상태인지 판별합니다.
    """
    # 1. 진행상태 태그 확인
    stat = str(item.get("진행상태", ""))
    for kw in ["낙찰", "매각완료", "취하", "취소"]:
        if kw in stat:
            return True

    # 2. 세부상황 및 수의계약 조건 대조 (단, '소 취하 후 추가공매', '경매취하 후 수의계약추진' 같은 재추진 건은 제외)
    detail = str(item.get("세부상황", ""))
    private_contract = str(item.get("수의계약가능여부", ""))

    if "낙찰완료" in detail or "매각완료" in detail or "낙찰" in private_contract:
        return True

    if "공매취하" in detail or "취하완료" in detail or "공매취소" in detail:
        # 단, '재경매'나 '수의계약 추진' 등 계속 진행 의사가 명시된 건은 제외
        if not ("재경매" in detail or "수의계약" in detail or "추가 공매" in detail or "진행 예정" in detail):
            return True

    return False

def apply_filters(
    items: List[Dict[str, Any]],
    keyword: str = "",
    selected_sido: str = "전체",
    selected_sigungu: str = "전체",
    min_area: float = 0.0,
    max_area: float = 0.0,
    min_price_eok: float = 0.0,
    max_price_eok: float = 0.0,
    status_filter: str = "전체 (진행중 + 마감/수의계약)",
    exclude_sold_and_withdrawn: bool = True,
    selected_source: str = "전체",
    selected_zonings: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    통합 공매 및 신탁사 물건 목록에 필터를 적용합니다.
    - 매각완료(낙찰) 및 공매취하 물건은 기본적으로 자동 삭제/제외합니다.
    - 기본값: 진행중 + 유찰/수의계약 협의가능 물건 표출
    - 조건: 출처(신탁사/법원/온비드), 키워드, 시/도, 시/군/구, 용도지역, 최소/최대 면적(평), 최소/최대 최초입찰가(억 원)
    """
    filtered = []
    clean_keyword = keyword.strip().lower() if keyword else ""
    now_ts_str = datetime.now().strftime("%Y%m%d%H%M")
    
    for item in items:
        # 1. 이미 매각(낙찰)되었거나 공매 취하/취소된 물건 자동 삭제/제외
        if exclude_sold_and_withdrawn and is_sold_or_withdrawn(item):
            continue

        # 2. 출처 필터 (전체 / 신탁사공매 / 법원경매 / 온비드)
        is_court = (
            "법원" in str(item.get("출처", ""))
            or "법원" in str(item.get("처분방식", ""))
            or "타경" in str(item.get("사건번호", ""))
            or "타경" in str(item.get("물건관리번호", ""))
        )
        is_trust = (
            not is_court
            and (
                "신탁" in str(item.get("출처", ""))
                or "신탁" in str(item.get("처분방식", ""))
                or (item.get("신탁사") and item.get("신탁사") != "-")
            )
        )

        if selected_source == "🏢 신탁사 공매만" and not is_trust:
            continue
        elif selected_source == "🏛️ 법원경매만" and not is_court:
            continue
        elif selected_source == "💻 온비드 일반공매만" and (is_trust or is_court):
            continue

        # 3. 진행상태 필터링 (기본: 전체 표출)
        if status_filter == "🟢 진행중만":
            is_valid = item.get("유효여부", True)
            end_dt = str(item.get("입찰마감일시", "")).replace("-", "").replace(" ", "").replace(":", "")
            if len(end_dt) >= 12 and end_dt < now_ts_str:
                is_valid = False
            # 수의계약 가능 물건은 협의 가능한 활성 상태로 인정
            if "수의계약" in str(item.get("진행상태", "")):
                is_valid = True
            if not is_valid:
                continue
        elif status_filter == "🔴 마감만":
            is_valid = item.get("유효여부", True)
            end_dt = str(item.get("입찰마감일시", "")).replace("-", "").replace(" ", "").replace(":", "")
            if len(end_dt) >= 12 and end_dt < now_ts_str:
                is_valid = False
            if is_valid and "진행중" in str(item.get("진행상태", "")):
                continue

        # 4. 다차원 키워드 검색 (물건명, 소재지, 관리번호, 용도/지목, 용도지역, 신탁사, 대리금융기관 등)
        full_text = f"{item.get('물건명', '')} {item.get('소재지', '')} {item.get('물건관리번호', '')} {item.get('용도/지목', '')} {item.get('용도지역', '')} {item.get('시도', '')} {item.get('시군구', '')} {item.get('신탁사', '')} {item.get('대리금융기관', '')} {item.get('인허가번호', '')} {item.get('세부상황', '')}".lower()
        if clean_keyword and clean_keyword not in full_text:
            continue

        # 5. 지역 필터 (시/도)
        if selected_sido and selected_sido != "전체":
            addr_for_sido = f"{item.get('시도', '')} {item.get('소재지', '')} {item.get('물건명', '')}"
            if not match_sido(addr_for_sido, selected_sido):
                continue

        # 6. 지역 필터 (시/군/구)
        if selected_sigungu and selected_sigungu != "전체":
            addr_for_sgg = f"{item.get('시군구', '')} {item.get('소재지', '')} {item.get('물건명', '')}"
            if not match_sigungu(addr_for_sgg, selected_sigungu):
                continue

        # 7. 용도지역 필터 (체크박스 다중 선택)
        if selected_zonings and len(selected_zonings) > 0 and "전체" not in selected_zonings:
            item_zoning = f"{item.get('용도지역', '')} {item.get('용도/지목', '')}"
            matched_zone = any(z in item_zoning for z in selected_zonings)
            if not matched_zone:
                continue

        # 8. 면적 필터 (평 단위)
        item_pyeong = item.get("면적(평)", 0.0) or 0.0
        if min_area > 0 and item_pyeong < min_area:
            continue
        if max_area > 0 and item_pyeong > max_area:
            continue

        # 9. 금액 필터 (최초 입찰가 기준, 억 원 단위)
        item_price_won = item.get("최초입찰가_숫자", 0) or item.get("최저입찰가_숫자", 0) or 0
        item_price_eok = item_price_won / 100_000_000.0

        if min_price_eok > 0 and item_price_eok < min_price_eok:
            continue
        if max_price_eok > 0 and item_price_eok > max_price_eok:
            continue

        filtered.append(item)

    return filtered
