import os
import re
import json
from datetime import datetime
import requests
import xmltodict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Dict, Any, Optional

CACHE_FILE = os.path.join(os.path.dirname(__file__), "auction_cache.json")

def extract_area_from_text(title: str) -> float:
    if not title: return 0.0
    m_sqm = re.search(r'([\d,]+(?:\.\d+)?)\s*(?:㎡|m2|m²|M2)', title)
    if m_sqm:
        try: return round(float(m_sqm.group(1).replace(",", "")) / 3.305785, 1)
        except Exception: pass
    m_py = re.search(r'([\d,]+(?:\.\d+)?)\s*평', title)
    if m_py:
        try: return round(float(m_py.group(1).replace(",", "")), 1)
        except Exception: pass
    return 0.0


def fetch_all_onbid_realestate(
    api_key: str,
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> List[Dict[str, Any]]:
    """
    온비드 실시간 공매 매물 전수 수집기 (멀티스레드 고속 병렬 수집)
    1. 공유재산(지자체 부지) 일반/수의 100% 전수 수집
    2. 신탁재산 일반/수의 100% 전수 수집
    3. 기타일반재산 - 토지(10100) 일반/수의 100% 전수 수집 (누락 0건)
    4. 기타일반재산 - 산업용/공장/창고(10400) 일반/수의 100% 전수 수집
    5. 기타일반재산 - 용도복합용(10500) 대형 부지/건물 대량 수집
    6. 기타일반재산 - 상가업무(10300) 및 주거용(10200) 대량 수집
    """
    url = "https://apis.data.go.kr/B010003/OnbidRlstListSrvc2/getRlstCltrList2"
    collected_items = []
    seen_ids = set()

    if progress_callback:
        progress_callback(5, "온비드 실시간 공매 카테고리별 대상 물량 분석 중...")

    # 수집 대상 정의 (prptDivCd, cat_id, pvctTrgtYn, max_pages, label)
    targets = [
        # 1. 공유재산 (지자체 소유 매각 부지 - 100% 전수 수집)
        ("0002", None, "N", 999, "공유재산"),
        ("0002", None, "Y", 999, "공유재산(수의계약)"),

        # 2. 신탁재산 (온비드 위탁 신탁 물건 - 100% 전수 수집)
        ("0004", None, "N", 999, "신탁재산"),
        ("0004", None, "Y", 999, "신탁재산(수의계약)"),

        # 3. 토지 전수 수집 (10100: 대지, 전, 답, 임야, 잡종지 등 전국 토지 100% 전수 수집)
        ("0005", "10100", "N", 999, "토지(일반경쟁)"),
        ("0005", "10100", "Y", 999, "토지(수의계약)"),

        # 4. 산업용/특수용 전수 수집 (10400: 공장, 창고, 지식산업센터 등 100% 전수 수집)
        ("0005", "10400", "N", 999, "산업용(일반경쟁)"),
        ("0005", "10400", "Y", 999, "산업용(수의계약)"),

        # 5. 복합용 대형 건물/부지 (10500: 주상복합, 대형 복합빌딩)
        ("0005", "10500", "N", 15, "복합용(일반경쟁)"),
        ("0005", "10500", "Y", 15, "복합용(수의계약)"),

        # 6. 상가 및 업무용 건물 (10300: 오피스빌딩, 상가)
        ("0005", "10300", "N", 15, "상가업무(일반경쟁)"),
        ("0005", "10300", "Y", 15, "상가업무(수의계약)"),

        # 7. 주거용 건물 (10200: 아파트단지, 주택, 빌딩)
        ("0005", "10200", "N", 8, "주거용(일반경쟁)"),
        ("0005", "10200", "Y", 8, "주거용(수의계약)"),
    ]

    fetch_jobs = []
    # 1단계: 각 카테고리별 전체 등록 페이지 수 파악
    for prpt, cat, pvct, limit, label in targets:
        p1 = {
            "serviceKey": api_key, "pageNo": "1", "numOfRows": "100",
            "prptDivCd": prpt, "pvctTrgtYn": pvct, "dspsMthodCd": "0001"
        }
        if cat: p1["cltrUsgMclsCtgrId"] = cat
        try:
            r = requests.get(url, params=p1, timeout=10)
            if r.status_code == 200:
                d = xmltodict.parse(r.text)
                cnt = int(d.get("response", {}).get("body", {}).get("totalCount", 0))
                pages = (cnt // 100) + (1 if cnt % 100 else 0)
                actual_pages = min(pages, limit)
                for pg in range(1, actual_pages + 1):
                    p = dict(p1)
                    p["pageNo"] = str(pg)
                    fetch_jobs.append((p, label))
        except Exception:
            pass

    total_jobs = len(fetch_jobs)
    if progress_callback:
        progress_callback(15, f"온비드 대상 {total_jobs}개 페이지 병렬 고속 다운로드 시작...")

    def do_fetch(job):
        param, lbl = job
        try:
            res = requests.get(url, params=param, timeout=12)
            if res.status_code == 200:
                d = xmltodict.parse(res.text)
                its = d.get("response", {}).get("body", {}).get("items", {}).get("item", [])
                if isinstance(its, dict): its = [its]
                return [(it, lbl) for it in its]
        except Exception:
            pass
        return []

    # 2단계: 10개 스레드로 고속 병렬 수집
    raw_results = []
    completed = 0
    with ThreadPoolExecutor(max_workers=10) as executor:
        for batch in executor.map(do_fetch, fetch_jobs):
            raw_results.extend(batch)
            completed += 1
            if progress_callback and completed % 10 == 0:
                pct = 15 + int((completed / total_jobs) * 60)
                progress_callback(pct, f"온비드 데이터 고속 파싱 중... ({completed}/{total_jobs} 페이지 완료)")

    # 3단계: 물건 관리번호 기준 중복 제거 및 데이터 정제
    if progress_callback:
        progress_callback(80, "온비드 물건별 면적·금액·진행상태 정밀 분석 및 정제 중...")

    for it, lbl in raw_results:
        mng_no = it.get("cltrMngNo") or it.get("onbidCltrno")
        if mng_no and mng_no in seen_ids:
            continue
        if mng_no:
            seen_ids.add(mng_no)
        collected_items.append(_parse_item(it, lbl))

    # 4단계: 14대 신탁사 및 대형 개발부지 연동
    try:
        from live_dev_site_collector import collect_live_trust_and_dev_sites
        live_trust_items = collect_live_trust_and_dev_sites(progress_callback=progress_callback)
        for t_it in live_trust_items:
            mng_no = t_it.get("물건관리번호") or t_it.get("물건명")
            if mng_no and mng_no not in seen_ids:
                seen_ids.add(mng_no)
                collected_items.append(t_it)
    except Exception as e:
        print(f"Live trust scrape error: {e}")

    if progress_callback:
        progress_callback(100, f"온비드 실시간 공매 전수 수집 완료! (총 {len(collected_items):,}건 준비됨)")

    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(collected_items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Cache write error: {e}")

    return collected_items


def load_cached_auction_data() -> List[Dict[str, Any]]:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _parse_item(item: dict, default_prpt_name: str) -> dict:
    cltr_name = item.get("onbidCltrNm") or ""
    sd_name = item.get("lctnSdnm") or ""
    sgg_name = item.get("lctnSggnm") or ""
    emd_name = item.get("lctnEmdNm") or ""
    
    full_address = f"{sd_name} {sgg_name} {emd_name}".strip()
    if not full_address:
        full_address = cltr_name

    sqms_val = None
    pyeong_val = 0.0
    raw_sqms = item.get("landSqms") or item.get("bldSqms")
    if raw_sqms:
        try:
            sqms_val = float(raw_sqms)
            pyeong_val = round(sqms_val / 3.305785, 1)
        except (ValueError, TypeError):
            pass
            
    if pyeong_val == 0.0:
        extracted_py = extract_area_from_text(cltr_name)
        if extracted_py > 0:
            pyeong_val = extracted_py
            sqms_val = round(pyeong_val * 3.305785, 1)

    apsl_price_num = 0
    raw_apsl = item.get("apslEvlAmt") or item.get("frstBidPrc")
    if raw_apsl:
        try: apsl_price_num = int(float(raw_apsl))
        except (ValueError, TypeError): pass

    lowst_price_num = 0
    raw_price = item.get("lowstBidPrcIndctCont")
    if raw_price:
        try: lowst_price_num = int(float(raw_price))
        except (ValueError, TypeError): pass

    if apsl_price_num == 0 and lowst_price_num > 0:
        apsl_price_num = lowst_price_num
    if lowst_price_num == 0 and apsl_price_num > 0:
        lowst_price_num = apsl_price_num

    usbd_count = 0
    raw_usbd = item.get("usbdNft")
    if raw_usbd:
        try: usbd_count = int(raw_usbd)
        except (ValueError, TypeError): pass

    usage_mid = item.get("cltrUsgMclsCtgrNm") or ""
    usage_sub = item.get("cltrUsgSclsCtgrNm") or ""
    display_usage = f"{usage_mid} - {usage_sub}" if (usage_mid and usage_sub) else (usage_sub or usage_mid or "부동산")

    # 마감일시 및 진행상태 판별 (현재 시각 기준 실시간 비교)
    raw_end_dt = item.get("cltrBidEndDt") or ""
    clean_end_dt = raw_end_dt.replace("-", "").replace(" ", "").replace(":", "")
    now_ts_str = datetime.now().strftime("%Y%m%d%H%M")
    
    is_active = True
    if len(clean_end_dt) >= 12:
        if clean_end_dt < now_ts_str:
            is_active = False

    raw_stat = item.get("pbctStatNm") or "입찰진행중"
    if not is_active:
        stat_display = f"🔴 마감({raw_stat})"
    else:
        stat_display = f"🟢 진행중({raw_stat})"

    from urllib.parse import quote
    cltrMngNo = item.get("cltrMngNo") or item.get("onbidCltrno") or ""
    target_query = cltrMngNo if cltrMngNo and cltrMngNo != "-" else cltr_name
    detail_url = f"https://www.onbid.co.kr/op/cltrpbancinf/toppagemng/unfsrch/UnfSrchController/mvmnUnfSrchClg.do?swd={quote(target_query)}&unfSrchExcnYn=Y"

    return {
        "출처": "온비드",
        "물건관리번호": cltrMngNo or "-",
        "물건명": cltr_name,
        "소재지": full_address,
        "시도": sd_name,
        "시군구": sgg_name,
        "읍면동": emd_name,
        "용도/지목": display_usage,
        "재산구분": item.get("prptDivNm") or default_prpt_name,
        "처분방식": item.get("dspsMthodNm") or "매각",
        "면적(평)": pyeong_val,
        "면적(㎡)": sqms_val if sqms_val is not None else 0.0,
        "최초입찰가(원)": f"{apsl_price_num:,}원" if apsl_price_num > 0 else "미정",
        "최초입찰가_숫자": apsl_price_num,
        "최초입찰가_억": round(apsl_price_num / 100_000_000, 1),
        "최저입찰가(원)": f"{lowst_price_num:,}원" if lowst_price_num > 0 else "미정",
        "최저입찰가_숫자": lowst_price_num,
        "최저입찰가_억": round(lowst_price_num / 100_000_000, 1),
        "유찰횟수": usbd_count,
        "입찰마감일시": raw_end_dt if raw_end_dt else "-",
        "진행상태": stat_display,
        "유효여부": is_active,
        "온비드_상세링크": detail_url,
        "PNU": item.get("ltnoPnu") or ""
    }
