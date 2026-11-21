import os
import re
import json
import time
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "court_auctions_cache.json")
COURT_BASE_URL = "https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ151F00.xml"

def parse_area(area_str):
    if not area_str:
        return 0.0, 0.0
    m = re.search(r'([\d,]+(?:\.\d+)?)\s*(?:㎡|m2|m²)', str(area_str))
    if m:
        sqm = float(m.group(1).replace(',', ''))
        pyeong = round(sqm / 3.305785, 1)
        return pyeong, sqm
    m2 = re.search(r'([\d,]+(?:\.\d+)?)', str(area_str))
    if m2:
        val = float(m2.group(1).replace(',', ''))
        return round(val / 3.305785, 1), val
    return 0.0, 0.0

def fetch_court_auctions(max_pages_100b=20, max_pages_500p=10):
    import requests
    s = requests.Session()
    
    headers_nav = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    try:
        s.get('https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ151M01.xml', headers=headers_nav, timeout=10)
    except Exception as e:
        logger.error(f"Failed to initialize court auction session: {e}")
        return []

    headers_post = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Content-Type': 'application/json;charset=UTF-8',
        'Origin': 'https://www.courtauction.go.kr',
        'Referer': 'https://www.courtauction.go.kr/pgj/index.on?w2xPath=/pgj/ui/pgj100/PGJ151M01.xml',
        'submissionid': 'sbm_selectGdsDtlSrch'
    }

    today_str = datetime.today().strftime('%Y%m%d')
    end_str = (datetime.today() + timedelta(days=14)).strftime('%Y%m%d')

    collected_dict = {}

    queries = [
        {"name": "100억이상", "aeeEvlAmtMin": "10000000000", "objctArDtsMin": "", "max_pages": max_pages_100b},
        {"name": "500평이상", "aeeEvlAmtMin": "", "objctArDtsMin": "1650", "max_pages": max_pages_500p}
    ]

    for q in queries:
        for page in range(1, q["max_pages"] + 1):
            srch_info = {
                "mvprpRletDvsCd": "00031R",
                "cortAuctnSrchCondCd": "0004601",
                "cortStDvs": "1",
                "cortOfcCd": "",
                "bidBgngYmd": today_str,
                "bidEndYmd": end_str,
                "pgmId": "PGJ151M01"
            }
            if q["aeeEvlAmtMin"]:
                srch_info["aeeEvlAmtMin"] = q["aeeEvlAmtMin"]
            if q["objctArDtsMin"]:
                srch_info["objctArDtsMin"] = q["objctArDtsMin"]

            payload = {
                "dma_pageInfo": {
                    "pageNo": str(page),
                    "pageSize": "40",
                    "totalYn": "Y" if page == 1 else "N"
                },
                "dma_srchGdsDtlSrchInfo": srch_info
            }

            try:
                r = s.post('https://www.courtauction.go.kr/pgj/pgjsearch/searchControllerMain.on',
                           headers=headers_post, json=payload, timeout=12)
                data = r.json()
                raw_items = data.get('data', {}).get('dlt_srchResult', [])
                if not raw_items:
                    break

                for raw in raw_items:
                    sa_no = raw.get("srnSaNo", "").strip()
                    if not sa_no:
                        continue
                    
                    mok_ser = raw.get("mokmulSer", "1")
                    mae_ser = raw.get("maemulSer", "1")
                    key = f"{sa_no}_{mae_ser}_{mok_ser}"
                    if key in collected_dict:
                        continue

                    court_name = raw.get("jiwonNm", "").strip() or "법원경매"
                    dept_name = raw.get("jpDeptNm", "").strip()
                    tel = raw.get("tel", "").strip()
                    addr = (raw.get("printSt", "") or raw.get("convAddr", "")).strip()
                    usage = raw.get("dspslUsgNm", "").strip() or "부동산"
                    
                    # Prices
                    try:
                        appr_won = int(raw.get("gamevalAmt", 0))
                    except:
                        appr_won = 0
                    try:
                        min_won = int(raw.get("minmaePrice", 0))
                    except:
                        min_won = 0
                    try:
                        yuchal = int(raw.get("yuchalCnt", 0))
                    except:
                        yuchal = 0

                    # Area
                    area_raw = raw.get("areaList", "") or raw.get("minArea", "")
                    pyeong, sqm = parse_area(area_raw)

                    # Date
                    mae_giil_raw = raw.get("maeGiil", "").strip()
                    if len(mae_giil_raw) == 8:
                        giil_formatted = f"{mae_giil_raw[:4]}-{mae_giil_raw[4:6]}-{mae_giil_raw[6:8]}"
                    else:
                        giil_formatted = mae_giil_raw

                    # Address tokens for sido/sigungu
                    tokens = addr.split()
                    sido_std = ""
                    sigungu_std = ""
                    if tokens:
                        s0 = tokens[0]
                        for s_candidate in ["서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]:
                            if s0.startswith(s_candidate):
                                sido_std = s_candidate
                                break
                        if not sido_std:
                            sido_std = s0[:2]
                        if len(tokens) > 1:
                            sigungu_std = tokens[1]

                    item = {
                        "출처": "법원경매",
                        "물건관리번호": sa_no,
                        "물건명": f"[{court_name}] {addr} ({usage})",
                        "소재지": addr,
                        "용도/지목": usage,
                        "용도지역": raw.get("jimokList", "") or "대지/토지/건물",
                        "재산구분": "법원경매부동산",
                        "처분방식": "법원경매",
                        "면적(평)": pyeong,
                        "면적(㎡)": sqm,
                        "건물면적(㎡)": 0.0,
                        "최초입찰가(원)": f"{appr_won:,}원" if appr_won > 0 else "미정",
                        "최초입찰가_숫자": appr_won,
                        "최초입찰가_억": round(appr_won / 100_000_000, 1),
                        "최저입찰가(원)": f"{min_won:,}원" if min_won > 0 else "미정",
                        "최저입찰가_숫자": min_won,
                        "최저입찰가_억": round(min_won / 100_000_000, 1),
                        "유찰횟수": yuchal,
                        "진행상태": f"⚖️ 법원경매 진행중 (매각기일: {giil_formatted})" if giil_formatted else "⚖️ 법원경매 진행중",
                        "유효여부": True,
                        "온비드_상세링크": COURT_BASE_URL,
                        "링크유형": "법원경매",
                        "link_type": "법원경매",
                        "관할법원": court_name,
                        "담당계": dept_name,
                        "사건번호": sa_no,
                        "신탁사": "",
                        "신탁사연락처": tel,
                        "대리금융기관": court_name,
                        "대리금융기관연락처": tel,
                        "세부진행상황": raw.get("mulBigo", "") or f"매각기일: {giil_formatted}",
                        "수의계약가능여부": "불가(법원입찰)",
                        "매각기일": giil_formatted,
                        "시도": sido_std,
                        "시군구": sigungu_std,
                        "raw_docid": raw.get("docid", ""),
                        "raw_bocd": raw.get("boCd", "")
                    }
                    collected_dict[key] = item

                logger.info(f"Court auction {q['name']} page {page}: {len(raw_items)} items fetched. Total collected: {len(collected_dict)}")
                time.sleep(0.05)
            except Exception as e:
                logger.error(f"Error fetching court auctions page {page}: {e}")
                break

    items_list = list(collected_dict.values())
    if items_list:
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(items_list, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved {len(items_list)} court auctions to {CACHE_FILE}")
        except Exception as e:
            logger.error(f"Failed to write court auction cache: {e}")

    return items_list

def load_court_auctions(force_refresh=False):
    if not force_refresh and os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception as e:
            logger.warning(f"Failed to read court cache: {e}")
    return fetch_court_auctions()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = fetch_court_auctions(max_pages_100b=10, max_pages_500p=5)
    print(f"Collected total {len(res)} live court auctions!")
