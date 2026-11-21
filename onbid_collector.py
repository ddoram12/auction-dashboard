import os
import re
import json
from datetime import datetime
import requests
import xmltodict
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
    url = "https://apis.data.go.kr/B010003/OnbidRlstListSrvc2/getRlstCltrList2"
    collected_items = []
    seen_ids = set()

    for pvct in ["N", "Y"]:
        pvct_label = "일반경쟁" if pvct == "N" else "수의계약"
        if progress_callback:
            progress_callback(10 if pvct == "N" else 25, f"온비드 공유재산({pvct_label}) 전수 수집 중...")
        page = 1
        while True:
            params = {
                "serviceKey": api_key, "pageNo": str(page), "numOfRows": "100",
                "prptDivCd": "0002", "pvctTrgtYn": pvct, "dspsMthodCd": "0001"
            }
            try:
                resp = requests.get(url, params=params, timeout=12)
                if resp.status_code != 200: break
                parsed = xmltodict.parse(resp.text)
                body = parsed.get("response", {}).get("body", {})
                total_cnt = int(body.get("totalCount", 0))
                items_raw = body.get("items", {}).get("item", [])
                if not items_raw: break
                if isinstance(items_raw, dict): items_raw = [items_raw]

                for item in items_raw:
                    mng_no = item.get("cltrMngNo") or item.get("onbidCltrno")
                    if mng_no and mng_no in seen_ids: continue
                    seen_ids.add(mng_no)
                    collected_items.append(_parse_item(item, "공유재산"))

                if len(items_raw) < 100 or len(collected_items) >= total_cnt: break
                page += 1
            except Exception:
                break

    # 신탁재산 (0004)
    if progress_callback:
        progress_callback(35, "온비드 신탁/수탁재산 수집 중...")
    for pvct in ["N", "Y"]:
        try:
            resp = requests.get(url, params={
                "serviceKey": api_key, "pageNo": "1", "numOfRows": "100",
                "prptDivCd": "0004", "pvctTrgtYn": pvct, "dspsMthodCd": "0001"
            }, timeout=10)
            if resp.status_code == 200:
                parsed = xmltodict.parse(resp.text)
                items_raw = parsed.get("response", {}).get("body", {}).get("items", {}).get("item", [])
                if isinstance(items_raw, dict): items_raw = [items_raw]
                for item in items_raw:
                    mng_no = item.get("cltrMngNo") or item.get("onbidCltrno")
                    if mng_no and mng_no not in seen_ids:
                        seen_ids.add(mng_no)
                        collected_items.append(_parse_item(item, "신탁재산"))
        except Exception:
            pass

    # 기타일반재산 (0005)
    if progress_callback:
        progress_callback(40, "온비드 일반매각 부지 대량 수집 중...")
    for page in range(1, 16):
        pct = int(40 + (page * 3.5))
        if progress_callback:
            progress_callback(pct, f"온비드 일반 매각 부지 분석 중... ({page}/15 페이지, 현재 {len(collected_items)}건 수집됨)")
        params = {
            "serviceKey": api_key, "pageNo": str(page), "numOfRows": "100",
            "prptDivCd": "0005", "pvctTrgtYn": "N", "dspsMthodCd": "0001"
        }
        try:
            resp = requests.get(url, params=params, timeout=12)
            if resp.status_code != 200: continue
            parsed = xmltodict.parse(resp.text)
            items_raw = parsed.get("response", {}).get("body", {}).get("items", {}).get("item", [])
            if not items_raw: continue
            if isinstance(items_raw, dict): items_raw = [items_raw]
            for item in items_raw:
                mng_no = item.get("cltrMngNo") or item.get("onbidCltrno")
                if mng_no and mng_no in seen_ids: continue
                seen_ids.add(mng_no)
                collected_items.append(_parse_item(item, "기타일반재산"))
        except Exception:
            continue

    # 기타일반재산 수의계약 (Y)
    for page in range(1, 6):
        params = {
            "serviceKey": api_key, "pageNo": str(page), "numOfRows": "100",
            "prptDivCd": "0005", "pvctTrgtYn": "Y", "dspsMthodCd": "0001"
        }
        try:
            resp = requests.get(url, params=params, timeout=12)
            if resp.status_code != 200: continue
            parsed = xmltodict.parse(resp.text)
            items_raw = parsed.get("response", {}).get("body", {}).get("items", {}).get("item", [])
            if not items_raw: continue
            if isinstance(items_raw, dict): items_raw = [items_raw]
            for item in items_raw:
                mng_no = item.get("cltrMngNo") or item.get("onbidCltrno")
                if mng_no and mng_no in seen_ids: continue
                seen_ids.add(mng_no)
                collected_items.append(_parse_item(item, "기타일반재산(수의계약)"))
        except Exception:
            continue

    # 4. 14대 신탁사 및 대형 개발부지 실시간 스캔 & 크롤링
    try:
        from live_dev_site_collector import collect_live_trust_and_dev_sites
        live_trust_items = collect_live_trust_and_dev_sites(progress_callback=progress_callback)
        new_cnt = 0
        for t_it in live_trust_items:
            mng_no = t_it.get("물건관리번호") or t_it.get("물건명")
            if mng_no and mng_no not in seen_ids:
                seen_ids.add(mng_no)
                collected_items.append(t_it)
                new_cnt += 1
    except Exception as e:
        print(f"Live trust scrape error: {e}")

    if progress_callback:
        progress_callback(100, f"온비드 및 신탁사 공매 데이터 실시간 수집 완료! (총 {len(collected_items)}건 수집됨)")

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
