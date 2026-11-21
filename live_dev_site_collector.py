import requests
import json
import re
from datetime import datetime
from typing import List, Dict, Any, Callable, Optional
from urllib.parse import quote
from korea_regions import KOREA_REGIONS, SIDO_ALIASES
from trust_importer import normalize_sido_name, extract_dong_bunji, get_trust_site_url

def extract_sigungu(sido: str, addr: str) -> str:
    if not sido or not addr:
        return ""
    if sido in KOREA_REGIONS:
        for sgg in KOREA_REGIONS[sido]:
            if sgg in addr:
                return sgg
    m = re.search(r'([가-힣]+(?:시|군|구))', addr)
    if m:
        return m.group(1)
    return ""

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
}

TARGET_QUERIES = [
    '하나자산신탁', '신한자산신탁', '우리자산신탁', '교보자산신탁', 'KB부동산신탁', 
    '코람코자산신탁', '무궁화신탁', '한국투자부동산신탁', '대한토지신탁', '한국토지신탁', 
    '한국자산신탁', '코리아신탁', '대신자산신탁', '신영부동산신탁',
    '공동주택용지', '도시개발사업', '토지 일괄매각', '아파트 부지', '물류센터 부지'
]

def parse_web_item(raw_it: dict, default_org: str = "") -> dict:
    cltr_name = raw_it.get("onbidCltrNm") or ""
    cltr_name = re.sub(r'<[^>]+>', '', cltr_name).strip()
    
    addr = raw_it.get("zadrNm") or raw_it.get("cltrRadr") or cltr_name
    addr = re.sub(r'<[^>]+>', '', addr).strip()
    
    sd_name = raw_it.get("sdnm") or ""
    sgg_name = raw_it.get("sggnm") or ""
    emd_name = raw_it.get("emdNm") or ""
    
    sido_std = normalize_sido_name(sd_name) if sd_name else ""
    if not sido_std:
        for s_std, aliases in SIDO_ALIASES.items():
            if s_std in addr or any(a in addr for a in aliases):
                sido_std = s_std
                break
                
    sgg_std = sgg_name or extract_sigungu(sido_std, addr)
    dong_bunji = extract_dong_bunji(addr)

    sqm_val = 0.0
    raw_ldar = raw_it.get("cltrBasLdar") or raw_it.get("bldSqms")
    if raw_ldar:
        try:
            sqm_val = float(str(raw_ldar).replace(",", ""))
        except Exception:
            pass
            
    pyeong_val = round(sqm_val / 3.305785, 1) if sqm_val > 0 else 0.0

    apsl_won = 0
    raw_apsl = raw_it.get("apslEvlAmt") or raw_it.get("onbidApslAmt")
    if raw_apsl:
        try:
            apsl_won = int(float(str(raw_apsl).replace(",", "")))
        except Exception:
            pass

    lowst_won = 0
    raw_lowst = raw_it.get("lowstBidPrc") or raw_it.get("onbidBidAmt")
    if raw_lowst:
        try:
            lowst_won = int(float(str(raw_lowst).replace(",", "")))
        except Exception:
            pass

    if apsl_won == 0 and lowst_won > 0:
        apsl_won = lowst_won
    if lowst_won == 0 and apsl_won > 0:
        lowst_won = apsl_won

    reg_org = raw_it.get("regOrgNm") or default_org or "신탁사"
    reg_org = re.sub(r'<[^>]+>', '', reg_org).strip()

    cltr_mng = str(raw_it.get("cltrMngNo") or "").strip()
    if len(cltr_mng) == 14 and cltr_mng.isdigit():
        cltr_mng = f"{cltr_mng[:4]}-{cltr_mng[4:8]}-{cltr_mng[8:]}"

    pbct_ddln = raw_it.get("pbctDdlnDt") or raw_it.get("pbctLastDdlnDt") or ""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    stat_raw = raw_it.get("pbctStatNm") or raw_it.get("pbancPbctCltrStatNm") or ""
    is_active = True
    if pbct_ddln and pbct_ddln < now_str:
        is_active = False
    if "유찰" in stat_raw or "완료" in stat_raw or "마감" in stat_raw:
        is_active = False

    if is_active:
        stat_display = f"🟢 진행중({stat_raw or '입찰진행'})"
    else:
        stat_display = f"🔴 마감/유찰({stat_raw or '기한종료'})"

    ctgr_nm = raw_it.get("ctgrNm") or raw_it.get("ctgrFullNm") or "부동산/토지"
    
    # 신탁사 물건은 해당 신탁사 공식 홈페이지/공매게시판으로 바로 연결
    if "신탁" in reg_org:
        trust_site_url = get_trust_site_url(reg_org)
        final_link = trust_site_url
        link_type = "신탁사공매"
    else:
        target_q = cltr_mng if cltr_mng and cltr_mng != "-" else (dong_bunji.replace("_", " ") if dong_bunji else cltr_name)
        final_link = f"https://www.onbid.co.kr/op/cltrpbancinf/toppagemng/unfsrch/UnfSrchController/mvmnUnfSrchClg.do?swd={quote(target_q)}&unfSrchExcnYn=Y"
        link_type = "온비드"

    return {
        "출처": f"신탁사({reg_org})" if "신탁" in reg_org else "온비드개발부지",
        "물건관리번호": cltr_mng or "-",
        "물건명": cltr_name,
        "소재지": addr,
        "시도": sido_std,
        "시군구": sgg_std,
        "읍면동": emd_name or (dong_bunji.split("_")[0] if dong_bunji else ""),
        "동번지키": dong_bunji,
        "용도/지목": ctgr_nm,
        "용도지역": "-",
        "재산구분": raw_it.get("prptDivNm") or "신탁재산",
        "처분방식": raw_it.get("dspsMthodNm") or "신탁사공매",
        "면적(평)": pyeong_val,
        "면적(㎡)": sqm_val,
        "최초입찰가(원)": f"{apsl_won:,}원" if apsl_won > 0 else "미정",
        "최초입찰가_숫자": apsl_won,
        "최초입찰가_억": round(apsl_won / 100_000_000, 1),
        "최저입찰가(원)": f"{lowst_won:,}원" if lowst_won > 0 else "미정",
        "최저입찰가_숫자": lowst_won,
        "최저입찰가_억": round(lowst_won / 100_000_000, 1),
        "유찰횟수": int(raw_it.get("usbdNft") or 0),
        "입찰마감일시": pbct_ddln or "-",
        "진행상태": stat_display,
        "유효여부": is_active,
        "수의계약가능여부": "유찰시 가능" if not is_active else "진행중",
        "인허가여부": "-",
        "인허가번호": "-",
        "착공완공여부": "-",
        "세부상황": raw_it.get("onbidPbancNm") or "",
        "신탁사": reg_org,
        "신탁사연락처": "-",
        "대리금융기관": "-",
        "대리금융기관연락처": "-",
        "온비드_상세링크": final_link,
        "신탁사_상세링크": final_link,
        "링크유형": link_type,
        "link_type": link_type
    }

def collect_live_trust_and_dev_sites(progress_callback: Optional[Callable[[int, str], None]] = None) -> List[Dict[str, Any]]:
    results = []
    seen = set()
    total_q = len(TARGET_QUERIES)

    for i, q in enumerate(TARGET_QUERIES):
        if progress_callback:
            percent = 10 + int((i / total_q) * 80)
            progress_callback(percent, f"신탁사 및 개발부지 탐색 중: '{q}' ({i+1}/{total_q})")
        
        url = "https://www.onbid.co.kr/op/cltrpbancinf/toppagemng/unfsrch/UnfSrchController/mvmnUnfSrchClg.do"
        params = {
            "swd": q,
            "unfSrchExcnYn": "Y"
        }
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=8)
            if r.status_code == 200:
                m = re.search(r'var\s+searchResult\s*=\s*(\[\{.*?\}\]);', r.text, re.DOTALL)
                if m:
                    data = json.loads(m.group(1))
                    for it in data:
                        parsed = parse_web_item(it, default_org=q if '신탁' in q else "")
                        key = parsed.get("물건관리번호") or parsed.get("물건명")
                        if key and key not in seen:
                            seen.add(key)
                            results.append(parsed)
        except Exception:
            pass

    return results
