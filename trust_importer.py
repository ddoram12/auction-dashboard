import os
import re
import json
import logging
from datetime import datetime
from urllib.parse import quote
import openpyxl
from court_case_resolver import resolve_court_case

logger = logging.getLogger(__name__)

# 14대 주요 부동산 신탁사 공매공고/매각공고 전용 게시판 (메인 홈이 아닌 실제 공매게시판)
TRUST_AUCTION_BOARDS = {
    "무궁화신탁": "https://www.mghat.com/auction/disposal/list.do",
    "무궁화": "https://www.mghat.com/auction/disposal/list.do",
    "우리자산신탁": "https://www.wooriat.com/item/vendue/list",
    "우리": "https://www.wooriat.com/item/vendue/list",
    "대신자산신탁": "https://trust.daishin.com/public_1",
    "대신": "https://trust.daishin.com/public_1",
    "한국토지신탁": "https://www.koreit.co.kr/ParcelOut/Vendue?startId=KRT0404&boardcategory=KRTCM006&systcode=ADM",
    "한토신": "https://www.koreit.co.kr/ParcelOut/Vendue?startId=KRT0404&boardcategory=KRTCM006&systcode=ADM",
    "한국자산신탁": "https://www.kait.com/sale-info/",
    "한자신": "https://www.kait.com/sale-info/",
    "한국투자부동산신탁": "https://kitrust.kr/property/auction",
    "한투부": "https://kitrust.kr/property/auction",
    "한투": "https://kitrust.kr/property/auction",
    "대한토지신탁": "https://www.reitpia.com/info/02.php",
    "대토신": "https://www.reitpia.com/info/02.php",
    "코리아신탁": "https://www.ktrust.co.kr/?pages=thing&subs=thing01",
    "코리아": "https://www.ktrust.co.kr/?pages=thing&subs=thing01",
    "신영부동산신탁": "http://www.shinyoungret.com/index.asp?pages=public",
    "신영": "http://www.shinyoungret.com/index.asp?pages=public",
    "하나자산신탁": "https://www.hanatrust.com/ko/publicSale/goodsForPublicSale/publicSaleBoard",
    "하나": "https://www.hanatrust.com/ko/publicSale/goodsForPublicSale/publicSaleBoard",
    "신한자산신탁": "https://www.shinhantrust.kr/biz-information/auction-properties",
    "신한": "https://www.shinhantrust.kr/biz-information/auction-properties",
    "KB부동산신탁": "https://kbret.co.kr/auction/distribution",
    "국민": "https://kbret.co.kr/auction/distribution",
    "KB": "https://kbret.co.kr/auction/distribution",
    "교보자산신탁": "https://www.kyobotrust.co.kr/front/bbsList.do?bbsId=BBS_0002",
    "교보": "https://www.kyobotrust.co.kr/front/bbsList.do?bbsId=BBS_0002",
    "코람코자산신탁": "https://www.koramco.com/ko/pubsaleList",
    "코람코": "https://www.koramco.com/ko/pubsaleList",
}

def get_trust_site_url(trust_name: str) -> str:
    if not trust_name:
        return "https://www.hanatrust.com/ko/publicSale/goodsForPublicSale/publicSaleBoard"
    for k, url in TRUST_AUCTION_BOARDS.items():
        if k in trust_name:
            return url
    return "https://www.hanatrust.com/ko/publicSale/goodsForPublicSale/publicSaleBoard"

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
    
    # 1. 하나자산신탁 (?search_text=...)
    if any(k in trust_name for k in ["하나"]):
        return f"https://www.hanatrust.com/ko/publicSale/goodsForPublicSale/publicSaleBoard?search_text={encoded_q}"
    # 2. 무궁화신탁 (?keyword=...)
    if any(k in trust_name for k in ["무궁화"]):
        return f"https://www.mghat.com/auction/disposal/list.do?keyword={encoded_q}"
    # 3. 우리자산신탁 (?searchWord=...)
    if any(k in trust_name for k in ["우리"]):
        return f"https://www.wooriat.com/item/vendue/list?searchWord={encoded_q}"
    # 4. 한국자산신탁 (?keyword=...)
    if any(k in trust_name for k in ["한국자산", "한자신"]):
        return f"https://www.kait.com/sale-info/?mod=list&pageid=1&keyword={encoded_q}"
    # 5. 코람코자산신탁 (?keyword=...)
    if any(k in trust_name for k in ["코람코"]):
        return f"https://www.koramco.com/ko/pubsaleList?keyword={encoded_q}"
    # 6. 대신자산신탁 (?keyword=...)
    if any(k in trust_name for k in ["대신"]):
        return f"https://trust.daishin.com/public_1?keyword={encoded_q}"
    # 7. KB부동산신탁 (?search=...)
    if any(k in trust_name for k in ["KB", "국민"]):
        return f"https://kbret.co.kr/auction/distribution?search={encoded_q}"
    
    # 그 외 신탁사(공매 전용 게시판 200 OK 직행)
    return base_board

def clean_property_link(raw_link: str) -> str:
    """원문 엑셀에 기재된 매물 링크를 최신 Onbid/법원경매 정식 규격으로 정제"""
    if not raw_link or raw_link in ["-", "공고전", "공고 전", "미정", "진행예정", "None"]:
        return ""
    
    raw = raw_link.strip().replace(" ", "").replace("\n", "").replace("\r", "")
    
    # 1. shortcut.do (온비드 단축 링크 -> 해당 매물 상세로 302 직행)
    m_sc = re.search(r'shortcut\.do\?code=([A-Za-z0-9]+)', raw)
    if m_sc:
        return f"https://www.onbid.co.kr/shortcut.do?code={m_sc.group(1)}"
        
    # 2. pbctNo 파라미터가 포함된 구형 링크 -> 신형 온비드 공고상세 컨트롤러로 직접 연결
    m_pbct = re.search(r'pbctNo=(\d+)', raw)
    if m_pbct:
        return f"https://www.onbid.co.kr/op/cltrpbancinf/pbanc/pbancdtlinf/PbancDtlInqController/mvmnPbancDtl.do?pbctNo={m_pbct.group(1)}"
        
    # 3. 법원경매
    if "courtauction" in raw or "court" in raw:
        return "https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ151F00.xml"
        
    # 4. 기타 정식 온비드 링크
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
    if not sido:
        return ""
    for s_candidate in ["서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]:
        if sido.startswith(s_candidate):
            return s_candidate
    return sido[:2]

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

def import_trust_projects(force_refresh=False):
    if not force_refresh and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                if isinstance(cached_data, list) and len(cached_data) > 0:
                    return cached_data
        except Exception as e:
            logger.warning(f"Failed to read trust cache: {e}")

    if not os.path.exists(EXCEL_PATH):
        logger.warning(f"Trust Excel file not found: {EXCEL_PATH}")
        return []

    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    items = []
    for r_idx, row in enumerate(rows):
        if not row or len(row) < 22:
            continue
        seq_val = row[1]
        if seq_val is None or not str(seq_val).isdigit():
            continue

        seq = int(seq_val)
        region_type = str(row[2] or "").strip()
        area_sido = str(row[3] or "").strip()
        addr_detail = str(row[4] or "").strip()
        full_addr = f"{area_sido} {addr_detail}".strip()

        try:
            land_sqm = float(row[5] or 0.0)
        except:
            land_sqm = 0.0

        try:
            bld_sqm = float(row[6] or 0.0)
        except:
            bld_sqm = 0.0

        pyeong_val = round(land_sqm / 3.305785, 1) if land_sqm else 0.0
        zoning = str(row[7] or "").strip()
        biz_cat = str(row[8] or "").strip()
        biz_type = str(row[9] or "").strip()
        usage_str = biz_type or biz_cat or "토지/개발부지"

        # 금액 파싱 (단위 : 백만원 -> 원 단위 변환)
        try:
            appr_m = float(str(row[10] or 0).replace(",", ""))
            appr_price_won = int(appr_m * 1_000_000)
        except:
            appr_price_won = 0

        # 매각기일
        bid_date_str = str(row[11] or "").split()[0] if row[11] else "-"

        try:
            min_m = float(str(row[13] or 0).replace(",", ""))
            min_price_won = int(min_m * 1_000_000)
        except:
            min_price_won = 0

        disposal_method = str(row[14] or "온비드").strip()
        private_contract = str(row[15] or "").strip()
        perm_yn = str(row[16] or "").strip()
        perm_no = str(row[17] or "").strip()
        const_stat = str(row[18] or "").strip()
        detailed_status = str(row[19] or "").strip()

        # [20] 공매공고문∙감정평가서 등 정보 제공 웹페이지
        raw_web_link = str(row[20] or "").strip()
        
        # [21] 신탁사 회사명, [22] 연락처
        trust_name = str(row[21] or "").strip()
        trust_tel = str(row[22] or "").strip()

        # [23] 대리금융기관, [24] 연락처
        agent_name = str(row[23] or "").strip() if len(row) > 23 else ""
        agent_tel = str(row[24] or "").strip() if len(row) > 24 else ""

        # 링크 분석
        direct_prop_url = clean_property_link(raw_web_link)
        trust_board_url = get_trust_site_url(trust_name)

        is_court = (
            "법원" in disposal_method
            or "법원" in detailed_status
            or "경매" in detailed_status
            or "courtauction" in raw_web_link
        )

        # 검색용 정제 쿼리
        clean_search_query = addr_detail.split("일원")[0].split("외")[0].strip()
        onbid_search_url = f"https://www.onbid.co.kr/op/cltrpbancinf/toppagemng/unfsrch/UnfSrchController/mvmnUnfSrchClg.do?swd={quote(clean_search_query)}&unfSrchExcnYn=Y"

        if is_court:
            res_court, res_case = resolve_court_case(full_addr, detailed_status)
            court_name = res_court or deduce_court(full_addr, detailed_status)
            case_no = res_case or "경매진행(사건번호 배정중)"

            item_entry = {
                "출처": "법원경매/신탁PF",
                "물건관리번호": case_no if "타경" in case_no else f"법원경매접수-{seq:03d}",
                "물건명": f"[{court_name}] {addr_detail} ({biz_type or biz_cat or '경매부지'})",
                "소재지": full_addr,
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
                "수의계약가능여부": private_contract,
                "인허가여부": perm_yn,
                "인허가번호": perm_no,
                "착공완공여부": const_stat,
                "엑셀연번": seq,
                "매각기일": bid_date_str
            }
        else:
            # 신탁사 공매 물건:
            # 사용자 요구: "그러면 그냥 각 신탁사 공매물건 검색 사이트로만 연결해줘."
            # 파라미터나 검색어 오작동 없이 14개 신탁사 공식 공매물건 검색 사이트(공매게시판)로 100% 직행합니다.
            trust_site_url = get_trust_site_url(trust_name)
            search_kw = extract_search_keyword(addr_detail, biz_type or biz_cat)

            item_entry = {
                "출처": f"신탁사({trust_name})" if trust_name else "신탁사공매",
                "물건관리번호": f"신탁공매-{seq:03d}",
                "물건명": f"[{trust_name or '신탁사'}] {addr_detail} ({biz_type or biz_cat or '개발부지'})",
                "소재지": full_addr,
                "용도/지목": usage_str,
                "용도지역": zoning,
                "재산구분": "신탁공매부지",
                "처분방식": "신탁사공매",
                "면적(평)": pyeong_val,
                "면적(㎡)": land_sqm,
                "건물면적(㎡)": bld_sqm,
                "최초입찰가(원)": f"{appr_price_won:,}원" if appr_price_won > 0 else "미정",
                "최초입찰가_숫자": appr_price_won,
                "최초입찰가_억": round(appr_price_won / 100_000_000, 1),
                "최저입찰가(원)": f"{min_price_won:,}원" if min_price_won > 0 else "협의요망",
                "최저입찰가_숫자": min_price_won,
                "최저입찰가_억": round(min_price_won / 100_000_000, 1),
                "유찰횟수": 0,
                "진행상태": "🏢 신탁사 공매진행/수의계약",
                "유효여부": True,
                "온비드_상세링크": trust_site_url,
                "매물_직행링크": trust_site_url,
                "신탁사_검색링크": trust_site_url,
                "신탁사_상세링크": trust_site_url,
                "온비드_검색링크": onbid_search_url,
                "검색키워드": search_kw,
                "링크유형": "신탁사공매",
                "link_type": "신탁사공매",
                "관할법원": "-",
                "사건번호": "-",
                "신탁사": trust_name,
                "신탁사연락처": trust_tel,
                "대리금융기관": agent_name,
                "대리금융기관연락처": agent_tel,
                "세부진행상황": detailed_status,
                "수의계약가능여부": private_contract if private_contract else "협의가능",
                "인허가여부": perm_yn,
                "인허가번호": perm_no,
                "착공완공여부": const_stat,
                "엑셀연번": seq,
                "매각기일": bid_date_str
            }

        # 시도 / 시군구 표준화
        addr_tokens = full_addr.split()
        sido_std = ""
        sigungu_std = ""
        if addr_tokens:
            s0 = addr_tokens[0]
            for s_candidate in ["서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]:
                if s0.startswith(s_candidate):
                    sido_std = s_candidate
                    break
            if not sido_std:
                sido_std = s0[:2]
            if len(addr_tokens) > 1:
                sigungu_std = addr_tokens[1]
        item_entry["시도"] = sido_std
        item_entry["시군구"] = sigungu_std

        items.append(item_entry)

    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(items)} items to {CACHE_FILE}")
    except Exception as e:
        logger.warning(f"Failed to write trust cache: {e}")

    return items

load_trust_projects = import_trust_projects
