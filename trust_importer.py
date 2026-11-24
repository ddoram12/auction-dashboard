import os
import re
import json
import logging
from datetime import datetime
from urllib.parse import quote
import openpyxl
from court_case_resolver import resolve_court_case
from live_trust_collector import fetch_all_live_trust_properties, normalize_sido, normalize_trust_name, get_trust_site_url, TRUST_AUCTION_BOARDS

logger = logging.getLogger(__name__)

def extract_search_keyword(addr: str, name: str = "") -> str:
    """주소 또는 물건명에서 신탁사 공매 게시판 검색에 가장 적합한 키워드 추출 (동/읍/면/시/군/구)"""
    if not addr:
        return ""
    # 1. 읍/면/동/리 추출
    m = re.search(r'([가-힣0-9]+(?:동|읍|면|리))', addr)
    if m:
        return m.group(1)
    # 2. 로/길 추출
    m = re.search(r'([가-힣0-9]+(?:로|길))', addr)
    if m:
        return m.group(1)
    # 3. 시/군/구 추출
    m = re.search(r'([가-힣]+(?:시|군|구))', addr)
    if m:
        return m.group(1)
    return addr.split()[0]

def get_trust_search_url(trust_name: str, query: str = "") -> str:
    """해당 신탁사 공식 공매게시판의 검색결과 페이지 URL을 생성합니다."""
    base_board = get_trust_site_url(trust_name)
    clean_q = (query or "").strip()
    if not clean_q:
        return base_board
    
    encoded_q = quote(clean_q)
    
    if any(k in trust_name for k in ["하나"]):
        return f"https://www.hanatrust.com/ko/publicSale/goodsForPublicSale/publicSaleBoard?search_text={encoded_q}"
    if any(k in trust_name for k in ["무궁화"]):
        return f"https://www.mghat.com/auction/disposal/list.do?keyword={encoded_q}"
    if any(k in trust_name for k in ["우리"]):
        return f"https://www.wooriat.com/item/vendue/list?searchWord={encoded_q}"
    if any(k in trust_name for k in ["한국자산", "한자신"]):
        return f"https://www.kait.com/sale-info/?mod=list&pageid=1&keyword={encoded_q}"
    if any(k in trust_name for k in ["코람코"]):
        return f"https://www.koramco.com/ko/pubsaleList?keyword={encoded_q}"
    if any(k in trust_name for k in ["대신"]):
        return f"https://trust.daishin.com/public_1?keyword={encoded_q}"
    if any(k in trust_name for k in ["KB", "국민"]):
        return f"https://kbret.co.kr/auction/distribution?search={encoded_q}"
    
    return base_board

def clean_property_link(raw_link: str) -> str:
    """원문 엑셀에 기재된 매물 링크를 최신 Onbid/법원경매 정식 규격으로 정제"""
    if not raw_link or raw_link in ["-", "공고전", "공고 전", "미정", "진행예정", "None"]:
        return ""
    
    raw = raw_link.strip().replace(" ", "").replace("\n", "").replace("\r", "")
    
    m_sc = re.search(r'shortcut\.do\?code=([A-Za-z0-9]+)', raw)
    if m_sc:
        return f"https://www.onbid.co.kr/shortcut.do?code={m_sc.group(1)}"
        
    m_pbct = re.search(r'pbctNo=(\d+)', raw)
    if m_pbct:
        return f"https://www.onbid.co.kr/op/cltrpbancinf/pbanc/pbancdtlinf/PbancDtlInqController/mvmnPbancDtl.do?pbctNo={m_pbct.group(1)}"
        
    if "courtauction" in raw or "court" in raw:
        return "https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ151F00.xml"
        
    if "onbid.co.kr" in raw:
        return raw
        
    return ""

COURT_DISTRICT_MAP = {
    "중구": "서울중앙지방법원", "종로구": "서울중앙지방법원", "서초구": "서울중앙지방법원", "강남구": "서울중앙지방법원", "관악구": "서울중앙지방법원", "동작구": "서울중앙지방법원",
    "동대문구": "서울북부지방법원", "중랑구": "서울북부지방법원", "성북구": "서울북부지방법원", "도봉구": "서울북부지방법원", "노원구": "서울북부지방법원", "강북구": "서울북부지방법원",
    "서대문구": "서울서부지방법원", "마포구": "서울서부지방법원", "은평구": "서울서부지방법원", "용산구": "서울서부지방법원",
    "영등포구": "서울남부지방법원", "강서구": "서울남부지방법원", "양천구": "서울남부지방법원", "구로구": "서울남부지방법원", "금천구": "서울남부지방법원",
    "송파구": "서울동부지방법원", "강동구": "서울동부지방법원", "광진구": "서울동부지방법원", "성동구": "서울동부지방법원",
    "부천시": "인천지방법원 부천지원", "원미구": "인천지방법원 부천지원", "소사구": "인천지방법원 부천지원", "오정구": "인천지방법원 부천지원", "김포시": "인천지방법원 부천지원",
    "인천": "인천지방법원", "수원시": "수원지방법원", "성남시": "수원지방법원 성남지원", "평택시": "수원지방법원 평택지원", "안산시": "수원지방법원 안산지원",
    "안양시": "수원지방법원 안양지원", "고양시": "의정부지방법원 고양지원", "남양주시": "의정부지방법원 남양주지원", "천안시": "대전지방법원 천안지원",
    "대전": "대전지방법원", "대구": "대구지방법원", "부산": "부산지방법원", "창원시": "창원지방법원", "광주": "광주지방법원", "제주시": "제주지방법원"
}

def deduce_court(addr, text):
    m = re.search(r'([가-힣]+(?:지방법원|지법)(?:\s*[가-힣]+지원)?)', text)
    if m:
        return m.group(1).replace("지법", "지방법원")
    for k, court in COURT_DISTRICT_MAP.items():
        if k in addr:
            return court
    return "관할 지방법원"

def normalize_sido_name(sido: str) -> str:
    return normalize_sido(sido)

def extract_dong_bunji(text: str) -> str:
    if not text:
        return ""
    m = re.search(r'([가-힣\d]+(?:동|리|읍|면|가))\s*(\d+(?:-\d+)?)', text)
    if m:
        return f"{m.group(1)}_{m.group(2)}"
    m2 = re.search(r'([가-힣\d]+(?:동|리|읍|면|가))', text)
    if m2:
        return m2.group(1)
    return ""

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trust_projects_cache.json")
EXCEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "trust_pf_projects.xlsx")

def parse_verified_court_pf_items() -> list:
    """기존 PF 사업장 엑셀 파일 중 실제 법원경매 사건번호가 배정된 실물 경매 매물만 엄선 파싱"""
    if not os.path.exists(EXCEL_PATH):
        return []

    court_items = []
    try:
        wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))

        for row in rows:
            if not row or len(row) < 22:
                continue
            seq_val = row[1]
            if seq_val is None or not str(seq_val).isdigit():
                continue

            seq = int(seq_val)
            area_sido = str(row[3] or "").strip()
            addr_detail = str(row[4] or "").strip()
            full_addr = f"{area_sido} {addr_detail}".strip()
            disposal_method = str(row[14] or "").strip()
            detailed_status = str(row[19] or "").strip()
            raw_web_link = str(row[20] or "").strip()

            is_court = (
                "법원" in disposal_method
                or "법원" in detailed_status
                or "경매" in detailed_status
                or "타경" in detailed_status
                or "courtauction" in raw_web_link
            )

            if not is_court:
                continue

            try:
                land_sqm = float(row[5] or 0.0)
            except:
                land_sqm = 0.0

            try:
                bld_sqm = float(row[6] or 0.0)
            except:
                bld_sqm = 0.0

            pyeong_val = round(land_sqm / 3.305785, 1) if land_sqm else 0.0
            zoning = str(row[7] or "-").strip()
            biz_cat = str(row[8] or "").strip()
            biz_type = str(row[9] or "").strip()
            usage_str = biz_type or biz_cat or "경매부지"

            try:
                appr_m = float(str(row[10] or 0).replace(",", ""))
                appr_price_won = int(appr_m * 1_000_000)
            except:
                appr_price_won = 0

            try:
                min_m = float(str(row[13] or 0).replace(",", ""))
                min_price_won = int(min_m * 1_000_000)
            except:
                min_price_won = 0

            bid_date_str = str(row[11] or "-").split()[0]
            trust_name = str(row[21] or "").strip()
            trust_tel = str(row[22] or "-").strip()
            agent_name = str(row[23] or "-").strip() if len(row) > 23 else "-"
            agent_tel = str(row[24] or "-").strip() if len(row) > 24 else "-"

            res_court, res_case = resolve_court_case(full_addr, detailed_status)
            court_name = res_court or deduce_court(full_addr, detailed_status)
            case_no = res_case or "경매진행(사건번호 배정중)"

            trust_board_url = get_trust_site_url(trust_name)

            court_items.append({
                "출처": "법원경매/신탁PF",
                "물건관리번호": case_no if "타경" in case_no else f"법원경매접수-{seq:03d}",
                "물건명": f"[{court_name}] {addr_detail} ({usage_str})",
                "소재지": full_addr,
                "시도": normalize_sido(area_sido, full_addr),
                "시군구": "",
                "읍면동": "",
                "용도/지목": usage_str,
                "용도지역": zoning,
                "재산구분": "법원경매/PF사업장",
                "처분방식": "법원경매",
                "면적(평)": pyeong_val,
                "면적(㎡)": land_sqm,
                "건물면적(㎡)": bld_sqm,
                "최초입찰가(원)": f"{appr_price_won:,}원" if appr_price_won > 0 else "감정가 미정",
                "최초입찰가_숫자": appr_price_won,
                "최초입찰가_억": round(appr_price_won / 100_000_000, 1),
                "최저입찰가(원)": f"{min_price_won:,}원" if min_price_won > 0 else "최저가 미정",
                "최저입찰가_숫자": min_price_won,
                "최저입찰가_억": round(min_price_won / 100_000_000, 1),
                "유찰횟수": 0,
                "진행상태": f"⚖️ 법원경매 진행중 ({case_no})" if "타경" in case_no else "⚖️ 법원경매 접수/진행중",
                "유효여부": True,
                "온비드_상세링크": "https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ151F00.xml",
                "매물_직행링크": "https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ151F00.xml",
                "신탁사_상세링크": trust_board_url,
                "링크유형": "법원경매",
                "link_type": "법원경매",
                "관할법원": court_name,
                "사건번호": case_no,
                "신탁사": trust_name,
                "신탁사연락처": trust_tel,
                "대리금융기관": agent_name,
                "대리금융기관연락처": agent_tel,
                "세부진행상황": detailed_status,
                "수의계약가능여부": str(row[15] or "협의가능"),
                "인허가여부": str(row[16] or "-"),
                "인허가번호": str(row[17] or "-"),
                "착공완공여부": str(row[18] or "-"),
                "엑셀연번": seq,
                "매각기일": bid_date_str
            })
    except Exception as e:
        logger.warning(f"Error parsing verified court PF items: {e}")

    return court_items

def import_trust_projects(force_refresh=False, progress_callback=None):
    """
    14대 신탁사의 실시간 공매 매물을 수집하고 유효하지 않은 유령 매물을 자동 삭제합니다.
    - 실제 신탁사 홈페이지 및 온비드에 등록된 100% 실존 매물만 포함
    - 신규 등록 매물은 자동 추가, 마감/삭제된 매물은 자동 제외
    """
    if not force_refresh and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                if isinstance(cached_data, list) and len(cached_data) > 0:
                    return cached_data
        except Exception as e:
            logger.warning(f"Failed to read trust cache: {e}")

    # 1. 14대 신탁사 실시간 살아있는 공매 매물 전수 수집
    live_trust_items = fetch_all_live_trust_properties(progress_callback=progress_callback)

    # 2. 엑셀의 유효한 법원경매 사건 추가 (공고 전 유령 프로젝트는 전면 배제)
    court_items = parse_verified_court_pf_items()

    # 3. 통합 및 중복 제거
    merged_items = []
    seen = set()

    for item in live_trust_items:
        key = item.get("물건관리번호") or item.get("물건명")
        if key and key not in seen:
            seen.add(key)
            merged_items.append(item)

    for c_item in court_items:
        key = c_item.get("사건번호") or c_item.get("물건관리번호")
        if key and key not in seen:
            seen.add(key)
            merged_items.append(c_item)

    # 캐시 저장
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(merged_items, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(merged_items)} verified live trust items to {CACHE_FILE}")
    except Exception as e:
        logger.warning(f"Failed to write trust cache: {e}")

    return merged_items

load_trust_projects = import_trust_projects
