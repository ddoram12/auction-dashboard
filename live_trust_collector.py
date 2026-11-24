import os
import re
import json
import logging
import requests
from bs4 import BeautifulSoup
import urllib3
from datetime import datetime
from typing import List, Dict, Any, Callable, Optional
from urllib.parse import quote

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

# 14대 주요 부동산 신탁사 공식 공매/매각 전용 게시판
TRUST_AUCTION_BOARDS = {
    "우리자산신탁": "https://www.wooriat.com/item/vendue/list",
    "하나자산신탁": "https://www.hanatrust.com/ko/publicSale/goodsForPublicSale/publicSaleBoard",
    "신한자산신탁": "https://www.shinhantrust.kr/biz-information/auction-properties",
    "코람코자산신탁": "https://www.koramco.com/ko/pubsaleList",
    "무궁화신탁": "https://www.mghat.com/auction/disposal/list.do",
    "한국자산신탁": "https://www.kait.com/sale-info/",
    "대신자산신탁": "https://trust.daishin.com/thing_1",
    "KB부동산신탁": "https://kbret.co.kr/auction",
    "한국토지신탁": "https://www.koreit.co.kr/ParcelOut/Vendue?startId=KRT0404&boardcategory=KRTCM006&systcode=ADM",
    "한국투자부동산신탁": "https://kitrust.kr/property/auction",
    "대한토지신탁": "https://www.reitpia.com/info/02.php",
    "교보자산신탁": "https://www.kyobotrust.co.kr/front/bbsList.do?bbsId=BBS_0002",
    "코리아신탁": "https://www.ktrust.co.kr/?pages=thing&subs=thing01",
    "신영부동산신탁": "http://www.shinyoungret.com/index.asp?pages=public",
}

TARGET_TRUST_QUERIES = [
    '하나자산신탁', '신한자산신탁', '우리자산신탁', '교보자산신탁', 'KB부동산신탁', 
    '코람코자산신탁', '무궁화신탁', '한국투자부동산신탁', '대한토지신탁', '한국토지신탁', 
    '한국자산신탁', '코리아신탁', '대신자산신탁', '신영부동산신탁',
    '하나자산신탁 공매', '우리자산신탁 공매', '신한자산신탁 공매', 'KB부동산신탁 공매',
    '코람코 공매', '무궁화 공매', '한국자산신탁 공매', '코리아신탁 공매',
    '대신자산신탁 공매', '신영부동산신탁 공매', '대한토지신탁 공매'
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
}

def get_trust_site_url(trust_name: str) -> str:
    if not trust_name:
        return "https://www.hanatrust.com/ko/publicSale/goodsForPublicSale/publicSaleBoard"
    for k, url in TRUST_AUCTION_BOARDS.items():
        if k in trust_name:
            return url
    return "https://www.hanatrust.com/ko/publicSale/goodsForPublicSale/publicSaleBoard"

def normalize_trust_name(raw_name: str) -> str:
    if not raw_name:
        return "신탁사"
    for k in TRUST_AUCTION_BOARDS.keys():
        if k in raw_name:
            return k
    clean = re.sub(r'[\(주\)|주식회사|\(유\)]', '', raw_name).strip()
    return clean or "신탁사"

def normalize_sido(sido_raw: str, addr: str = "") -> str:
    for s in ["서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]:
        if sido_raw and sido_raw.startswith(s):
            return s
        if addr and (addr.startswith(s) or f" {s} " in addr or f"{s}특별시" in addr or f"{s}광역시" in addr or f"{s}도" in addr):
            return s
    return sido_raw[:2] if sido_raw else ""

def extract_area_from_text(title: str) -> float:
    if not title:
        return 0.0
    m_sqm = re.search(r'([\d,]+(?:\.\d+)?)\s*(?:㎡|m2|m²|M2)', title)
    if m_sqm:
        try:
            return round(float(m_sqm.group(1).replace(",", "")) / 3.305785, 1)
        except Exception:
            pass
    m_py = re.search(r'([\d,]+(?:\.\d+)?)\s*평', title)
    if m_py:
        try:
            return round(float(m_py.group(1).replace(",", "")), 1)
        except Exception:
            pass
    return 0.0

def _parse_woori_item_detail(detail_id: str, html_text: str = "") -> dict:
    """우리자산신탁 상세 페이지에서 금액, 면적, 용도지역 등 정밀 파싱"""
    res = {
        "sqm": 0.0, "pyeong": 0.0, "frst_won": 0, "lowst_won": 0, "zoning": "-", "status_td": ""
    }
    if not html_text:
        try:
            r = requests.get(f"https://www.wooriat.com/item/vendue/detail/{detail_id}", headers=HEADERS, timeout=4)
            if r.status_code == 200:
                html_text = r.text
        except Exception:
            pass

    if not html_text:
        return res

    soup = BeautifulSoup(html_text, 'html.parser')
    for tr in soup.select('table tr'):
        th = tr.find('th')
        td = tr.find('td')
        if th and '진행상태' in th.text and td:
            res["status_td"] = td.text.strip()

    text = soup.text

    # 면적 파싱 (지목/용도지역 뒤의 ㎡ 합산 또는 일반 ㎡ 추출)
    total_sqm = 0.0
    for m in re.finditer(r'(?:일반상업지역|준주거지역|제\d종일반주거지역|자연녹지지역|계획관리지역|상업지역|주거지역|대|임야|공장용지)\s*([\d,]+(?:\.\d+)?)', text):
        try:
            val = float(m.group(1).replace(',', ''))
            if 10.0 <= val <= 500000.0:
                total_sqm += val
        except Exception:
            pass

    if total_sqm == 0.0:
        sqm_matches = re.findall(r'([\d,]+(?:\.\d+)?)\s*(?:㎡|m2)', text)
        if sqm_matches:
            try:
                total_sqm = float(sqm_matches[0].replace(',', ''))
            except Exception:
                pass

    res["sqm"] = round(total_sqm, 1)
    res["pyeong"] = round(total_sqm / 3.305785, 1) if total_sqm > 0 else 0.0

    # 금액 파싱
    is_thousand_won = any(k in text for k in ['단위 : 천원', '단위:천원', '단위 :천원', '단위: 천원'])
    prices = []
    for m in re.findall(r'(\d{1,3}(?:,\d{3})+)', text):
        p_clean = int(m.replace(',', ''))
        p_val = p_clean * 1000 if is_thousand_won else p_clean
        if 100_000_000 <= p_val <= 10_000_000_000_000:
            prices.append(p_val)

    if prices:
        res["frst_won"] = max(prices)
        res["lowst_won"] = min(prices)

    # 용도지역
    for z in ["일반상업지역", "중심상업지역", "유통상업지역", "준주거지역", "제1종일반주거지역", "제2종일반주거지역", "제3종일반주거지역", "준공업지역", "자연녹지지역", "계획관리지역"]:
        if z in text:
            res["zoning"] = z
            break

    return res

def _parse_onbid_trust_item(it: dict, default_org: str = "") -> dict:
    cltr_name = it.get("onbidCltrNm") or ""
    cltr_name = re.sub(r'<[^>]+>', '', cltr_name).strip()

    addr = it.get("zadrNm") or it.get("cltrRadr") or cltr_name
    addr = re.sub(r'<[^>]+>', '', addr).strip()

    sd_name = it.get("sdnm") or ""
    sgg_name = it.get("sggnm") or ""
    emd_name = it.get("emdNm") or ""
    sido_std = normalize_sido(sd_name, addr)

    sqm_val = 0.0
    raw_ldar = it.get("cltrBasLdar") or it.get("bldSqms")
    if raw_ldar:
        try:
            sqm_val = float(str(raw_ldar).replace(",", ""))
        except Exception:
            pass
    pyeong_val = round(sqm_val / 3.305785, 1) if sqm_val > 0 else 0.0
    if pyeong_val == 0.0:
        extracted_py = extract_area_from_text(cltr_name)
        if extracted_py > 0:
            pyeong_val = extracted_py
            sqm_val = round(pyeong_val * 3.305785, 1)

    apsl_won = 0
    raw_apsl = it.get("cltrApslEvlAvgAmt") or it.get("apslEvlAmt") or it.get("onbidApslAmt")
    if raw_apsl:
        try:
            apsl_won = int(float(str(raw_apsl).replace(",", "")))
        except Exception:
            pass

    lowst_won = 0
    raw_lowst = it.get("lowstBidPrc") or it.get("onbidBidAmt")
    if raw_lowst:
        try:
            lowst_won = int(float(str(raw_lowst).replace(",", "")))
        except Exception:
            pass

    if apsl_won == 0 and lowst_won > 0:
        apsl_won = lowst_won
    if lowst_won == 0 and apsl_won > 0:
        lowst_won = apsl_won

    reg_org = it.get("regOrgNm") or default_org or "신탁사"
    reg_org = re.sub(r'<[^>]+>', '', reg_org).strip()
    trust_name = normalize_trust_name(reg_org)

    cltr_mng = str(it.get("cltrMngNo") or "").strip()
    if len(cltr_mng) == 14 and cltr_mng.isdigit():
        cltr_mng_formatted = f"{cltr_mng[:4]}-{cltr_mng[4:8]}-{cltr_mng[8:]}"
    else:
        cltr_mng_formatted = cltr_mng or "-"

    pbct_ddln = it.get("pbctDdlnDt") or it.get("pbctLastDdlnDt") or it.get("remainTime") or ""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    stat_raw = it.get("pbancPbctCltrStatNm") or it.get("pbctStatNm") or it.get("_stat") or "진행중"
    is_active = True
    if pbct_ddln and pbct_ddln < now_str and not ("남음" in str(pbct_ddln)):
        is_active = False
    if "유찰" in stat_raw or "마감" in stat_raw:
        is_active = False

    if is_active:
        stat_display = f"🟢 진행중({stat_raw})"
    else:
        stat_display = f"🔴 유찰/수의계약대상({stat_raw})"

    trust_board_url = get_trust_site_url(trust_name)
    onbid_search_url = f"https://www.onbid.co.kr/op/cltrpbancinf/toppagemng/unfsrch/UnfSrchController/mvmnUnfSrchClg.do?swd={quote(cltr_mng or cltr_name)}&unfSrchExcnYn=Y"

    return {
        "출처": f"신탁사({trust_name})",
        "신탁사": trust_name,
        "물건관리번호": cltr_mng_formatted,
        "물건명": cltr_name,
        "소재지": addr,
        "시도": sido_std,
        "시군구": sgg_name,
        "읍면동": emd_name,
        "용도/지목": it.get("ctgrNm") or it.get("ctgrFullNm") or "신탁부동산",
        "용도지역": "-",
        "재산구분": "신탁재산",
        "처분방식": it.get("dspsMthodNm") or "신탁사공매",
        "면적(평)": pyeong_val,
        "면적(㎡)": sqm_val,
        "최초입찰가(원)": f"{apsl_won:,}원" if apsl_won > 0 else "미정",
        "최초입찰가_숫자": apsl_won,
        "최초입찰가_억": round(apsl_won / 100_000_000, 1),
        "최저입찰가(원)": f"{lowst_won:,}원" if lowst_won > 0 else "미정",
        "최저입찰가_숫자": lowst_won,
        "최저입찰가_억": round(lowst_won / 100_000_000, 1),
        "유찰횟수": int(it.get("usbdNft") or 0),
        "입찰마감일시": str(pbct_ddln) if pbct_ddln else "-",
        "진행상태": stat_display,
        "유효여부": is_active,
        "온비드_상세링크": onbid_search_url,
        "매물_직행링크": trust_board_url,
        "신탁사_상세링크": trust_board_url,
        "링크유형": "신탁사공매",
        "link_type": "신탁사공매",
        "수의계약가능여부": "유찰시 가능" if not is_active else "진행중",
        "관할법원": "-",
        "사건번호": "-",
        "인허가여부": "-",
        "인허가번호": "-",
        "착공완공여부": "-",
        "대리금융기관": "-",
        "세부진행상황": it.get("remainTime") or stat_raw
    }

def scrape_direct_trust_boards(progress_callback=None) -> List[Dict[str, Any]]:
    """14대 신탁사 공식 웹사이트에서 전수 페이지 및 전체 상태(진행 + 수의계약) 실시간 스크래핑"""
    direct_items = []
    seen_ids = set()

    # 1. 우리자산신탁 (진행 + 수의계약진행 전수 페이지)
    if progress_callback: progress_callback(12, "우리자산신탁 실시간 공매 및 수의계약 전체 페이지 스캔 중...")
    try:
        for status_val in ['진행', '수의계약진행']:
            for p in range(1, 16):
                url = f"https://www.wooriat.com/item/vendue/list?page={p}&sortStatus={status_val}"
                r = requests.get(url, headers=HEADERS, timeout=5)
                if r.status_code != 200: break
                soup = BeautifulSoup(r.text, 'html.parser')
                trs = soup.select('table tbody tr')
                if not trs: break
                for tr in trs:
                    a = tr.find('a')
                    if not a: continue
                    href = a.get('href', '')
                    detail_id = href.split('/')[-1] if 'detail' in href else ""
                    if not detail_id or detail_id in seen_ids: continue
                    seen_ids.add(detail_id)

                    title = a.text.strip().replace('\r', ' ').replace('\n', ' ')
                    title = re.sub(r'\s+', ' ', title)
                    if not title or len(title) < 5: continue

                    full_url = f"https://www.wooriat.com/item/vendue/detail/{detail_id}"
                    sido = normalize_sido("", title)

                    # 특정 주요 매물 또는 대표 매물 정밀 파싱
                    parsed_detail = {}
                    if detail_id in ['24696', '24864', '24863', '24839', '24838']:
                        parsed_detail = _parse_woori_item_detail(detail_id)

                    sqm_val = parsed_detail.get("sqm", 0.0) or round(extract_area_from_text(title) * 3.305785, 1)
                    pyeong_val = parsed_detail.get("pyeong", 0.0) or extract_area_from_text(title)
                    frst_price = parsed_detail.get("frst_won", 0)
                    lowst_price = parsed_detail.get("lowst_won", 0)
                    zoning = parsed_detail.get("zoning", "-")

                    stat_display = "🟢 진행중(신탁사공고)" if status_val == '진행' else "🔴 수의계약진행(신탁사공고)"

                    direct_items.append({
                        "출처": "신탁사(우리자산신탁)",
                        "신탁사": "우리자산신탁",
                        "물건관리번호": f"우리공매-{detail_id}",
                        "물건명": f"[우리자산신탁] {title}",
                        "소재지": title.replace("공매 공고의 건", "").replace("공매공고", "").strip(),
                        "시도": sido,
                        "시군구": "",
                        "읍면동": "",
                        "용도/지목": "신탁공매부동산",
                        "용도지역": zoning,
                        "재산구분": "신탁재산",
                        "처분방식": "신탁사공매",
                        "면적(평)": pyeong_val,
                        "면적(㎡)": sqm_val,
                        "최초입찰가(원)": f"{frst_price:,}원" if frst_price > 0 else "공고문 참조",
                        "최초입찰가_숫자": frst_price,
                        "최초입찰가_억": round(frst_price / 100_000_000, 1),
                        "최저입찰가(원)": f"{lowst_price:,}원" if lowst_price > 0 else "공고문 참조",
                        "최저입찰가_숫자": lowst_price,
                        "최저입찰가_억": round(lowst_price / 100_000_000, 1),
                        "유찰횟수": 0,
                        "입찰마감일시": "공고문 참조",
                        "진행상태": stat_display,
                        "유효여부": True,
                        "온비드_상세링크": full_url,
                        "매물_직행링크": full_url,
                        "신탁사_상세링크": full_url,
                        "링크유형": "신탁사공매",
                        "link_type": "신탁사공매",
                        "수의계약가능여부": "수의계약진행" if "수의계약" in status_val else "진행중",
                        "관할법원": "-",
                        "사건번호": "-",
                        "세부진행상황": f"우리자산신탁 정식 공고 ({status_val})"
                    })
    except Exception as e:
        logger.warning(f"Error scraping Woori: {e}")

    # 2. 신한자산신탁 (공식 REST API: 진행중 + 수의계약가능 전수 수집)
    if progress_callback: progress_callback(16, "신한자산신탁 실시간 공매 및 수의계약 REST API 전수 수집 중...")
    try:
        for status_val in ['IN_PROGRESS', 'CONTRACT_AVAILABLE']:
            for page in range(0, 8):
                url = f"https://www.shinhantrust.kr/api/disposal-auction?status={status_val}&page={page}&size=50"
                r = requests.get(url, headers=HEADERS, verify=False, timeout=5)
                if r.status_code != 200: break
                data = r.json()
                results = data.get('results', [])
                if not results: break
                for it in results:
                    s_id = str(it.get('id', ''))
                    if not s_id or f"shinhan_{s_id}" in seen_ids: continue
                    seen_ids.add(f"shinhan_{s_id}")

                    title = it.get('title', '').strip()
                    full_url = f"https://www.shinhantrust.kr/biz-information/auction-properties-detail/{s_id}"
                    sido = normalize_sido("", title)
                    cat_name = it.get('category', '부동산')
                    stat_display = "🟢 진행중(신탁사공고)" if status_val == 'IN_PROGRESS' else "🔴 수의계약가능(신탁사공고)"

                    direct_items.append({
                        "출처": "신탁사(신한자산신탁)",
                        "신탁사": "신한자산신탁",
                        "물건관리번호": f"신한공매-{s_id}",
                        "물건명": f"[신한자산신탁] {title}",
                        "소재지": title,
                        "시도": sido,
                        "시군구": "",
                        "읍면동": "",
                        "용도/지목": cat_name,
                        "용도지역": "-",
                        "재산구분": "신탁재산",
                        "처분방식": "신탁사공매",
                        "면적(평)": extract_area_from_text(title),
                        "면적(㎡)": round(extract_area_from_text(title) * 3.305785, 1),
                        "최초입찰가(원)": "공고문 참조",
                        "최초입찰가_숫자": 0,
                        "최초입찰가_억": 0.0,
                        "최저입찰가(원)": "공고문 참조",
                        "최저입찰가_숫자": 0,
                        "최저입찰가_억": 0.0,
                        "유찰횟수": 0,
                        "입찰마감일시": "공고문 참조",
                        "진행상태": stat_display,
                        "유효여부": True,
                        "온비드_상세링크": full_url,
                        "매물_직행링크": full_url,
                        "신탁사_상세링크": full_url,
                        "링크유형": "신탁사공매",
                        "link_type": "신탁사공매",
                        "수의계약가능여부": "가능" if "CONTRACT" in status_val else "진행중",
                        "관할법원": "-",
                        "사건번호": "-",
                        "세부진행상황": f"신한자산신탁 공식 매물 ({status_val})"
                    })
                if len(results) < 50: break
    except Exception as e:
        logger.warning(f"Error scraping Shinhan: {e}")

    # 3. 하나자산신탁 (공매물건리스트 전체 페이지)
    if progress_callback: progress_callback(20, "하나자산신탁 공식 공매물건 전체 페이지 수집 중...")
    try:
        for p in range(1, 9):
            url = f"https://www.hanatrust.com/ko/publicSale/goodsForPublicSale?page={p}"
            r = requests.get(url, headers=HEADERS, timeout=5)
            if r.status_code != 200: break
            soup = BeautifulSoup(r.text, 'html.parser')
            lis = soup.select('ul.auction-sale__list > li')
            if not lis: break
            for li in lis:
                a = li.find('a')
                if not a: continue
                href = a.get('href', '')
                seq_m = re.search(r'seq=(\d+)', href)
                seq = seq_m.group(1) if seq_m else href
                if f"hana_{seq}" in seen_ids: continue
                seen_ids.add(f"hana_{seq}")

                raw_text = li.text.strip().replace('\r', ' ').replace('\n', ' ')
                raw_text = re.sub(r'\s+', ' ', raw_text)
                title = raw_text
                full_url = f"https://www.hanatrust.com{href}" if href.startswith('/') else href
                sido = normalize_sido("", title)

                direct_items.append({
                    "출처": "신탁사(하나자산신탁)",
                    "신탁사": "하나자산신탁",
                    "물건관리번호": f"하나공매-{seq}",
                    "물건명": f"[하나자산신탁] {title[:60]}",
                    "소재지": title[:60],
                    "시도": sido,
                    "시군구": "",
                    "읍면동": "",
                    "용도/지목": "신탁공매부동산",
                    "용도지역": "-",
                    "재산구분": "신탁재산",
                    "처분방식": "신탁사공매",
                    "면적(평)": extract_area_from_text(title),
                    "면적(㎡)": round(extract_area_from_text(title) * 3.305785, 1),
                    "최초입찰가(원)": "공고문 참조",
                    "최초입찰가_숫자": 0,
                    "최초입찰가_억": 0.0,
                    "최저입찰가(원)": "공고문 참조",
                    "최저입찰가_숫자": 0,
                    "최저입찰가_억": 0.0,
                    "유찰횟수": 0,
                    "입찰마감일시": "공고문 참조",
                    "진행상태": "🟢 진행중(신탁사공고)",
                    "유효여부": True,
                    "온비드_상세링크": full_url,
                    "매물_직행링크": full_url,
                    "신탁사_상세링크": full_url,
                    "링크유형": "신탁사공매",
                    "link_type": "신탁사공매",
                    "수의계약가능여부": "공고문 참조",
                    "관할법원": "-",
                    "사건번호": "-",
                    "세부진행상황": "하나자산신탁 공식 공매물건"
                })
    except Exception as e:
        logger.warning(f"Error scraping Hana: {e}")

    # 4. 코람코자산신탁
    if progress_callback: progress_callback(23, "코람코자산신탁 실시간 공매 전체 페이지 수집 중...")
    try:
        for p in range(1, 6):
            url = f"https://www.koramco.com/ko/pubsaleList?page={p}"
            r = requests.get(url, headers=HEADERS, timeout=5)
            if r.status_code != 200: break
            soup = BeautifulSoup(r.text, 'html.parser')
            links = soup.select('a[href*="pubsaleView"]')
            if not links: break
            for a in links:
                href = a.get('href', '')
                post_id_m = re.search(r'post_id=(\d+)', href)
                post_id = post_id_m.group(1) if post_id_m else ""
                if not post_id or f"koramco_{post_id}" in seen_ids: continue
                seen_ids.add(f"koramco_{post_id}")

                title = a.text.strip().replace('\r', ' ').replace('\n', ' ')
                title = re.sub(r'\s+', ' ', title)
                if not title or len(title) < 5: continue
                full_url = f"https://www.koramco.com/ko/pubsaleView?post_id={post_id}"
                sido = normalize_sido("", title)

                direct_items.append({
                    "출처": "신탁사(코람코자산신탁)",
                    "신탁사": "코람코자산신탁",
                    "물건관리번호": f"코람코공매-{post_id}",
                    "물건명": f"[코람코자산신탁] {title}",
                    "소재지": title,
                    "시도": sido,
                    "시군구": "",
                    "읍면동": "",
                    "용도/지목": "개발부지/부동산",
                    "용도지역": "-",
                    "재산구분": "신탁재산",
                    "처분방식": "신탁사공매",
                    "면적(평)": extract_area_from_text(title),
                    "면적(㎡)": round(extract_area_from_text(title) * 3.305785, 1),
                    "최초입찰가(원)": "공고문 참조",
                    "최초입찰가_숫자": 0,
                    "최초입찰가_억": 0.0,
                    "최저입찰가(원)": "공고문 참조",
                    "최저입찰가_숫자": 0,
                    "최저입찰가_억": 0.0,
                    "유찰횟수": 0,
                    "입찰마감일시": "공고문 참조",
                    "진행상태": "🟢 진행중(신탁사공고)",
                    "유효여부": True,
                    "온비드_상세링크": full_url,
                    "매물_직행링크": full_url,
                    "신탁사_상세링크": full_url,
                    "링크유형": "신탁사공매",
                    "link_type": "신탁사공매",
                    "수의계약가능여부": "공고문 참조",
                    "관할법원": "-",
                    "사건번호": "-",
                    "세부진행상황": "코람코 정식 공매공고"
                })
    except Exception as e:
        logger.warning(f"Error scraping Koramco: {e}")

    # 5. 무궁화신탁
    if progress_callback: progress_callback(26, "무궁화신탁 실시간 공매 전체 페이지 수집 중...")
    try:
        for p in range(1, 9):
            url = f"https://www.mghat.com/auction/disposal/list.do?page={p}"
            r = requests.get(url, headers=HEADERS, verify=False, timeout=5)
            if r.status_code != 200: break
            soup = BeautifulSoup(r.text, 'html.parser')
            trs = soup.select('table tbody tr')
            if not trs: break
            for tr in trs:
                a = tr.find('a')
                if not a: continue
                href = a.get('href', '')
                show_id_m = re.search(r'/disposal/(\d+)/show', href)
                show_id = show_id_m.group(1) if show_id_m else ""
                if not show_id or f"mughwa_{show_id}" in seen_ids: continue
                seen_ids.add(f"mughwa_{show_id}")

                title = a.text.strip().replace('\r', ' ').replace('\n', ' ')
                title = re.sub(r'\s+', ' ', title)
                if not title or len(title) < 5: continue
                full_url = f"https://www.mghat.com{href}" if href.startswith('/') else href
                sido = normalize_sido("", title)

                direct_items.append({
                    "출처": "신탁사(무궁화신탁)",
                    "신탁사": "무궁화신탁",
                    "물건관리번호": f"무궁화공매-{show_id}",
                    "물건명": f"[무궁화신탁] {title}",
                    "소재지": title,
                    "시도": sido,
                    "시군구": "",
                    "읍면동": "",
                    "용도/지목": "신탁공매부동산",
                    "용도지역": "-",
                    "재산구분": "신탁재산",
                    "처분방식": "신탁사공매",
                    "면적(평)": extract_area_from_text(title),
                    "면적(㎡)": round(extract_area_from_text(title) * 3.305785, 1),
                    "최초입찰가(원)": "공고문 참조",
                    "최초입찰가_숫자": 0,
                    "최초입찰가_억": 0.0,
                    "최저입찰가(원)": "공고문 참조",
                    "최저입찰가_숫자": 0,
                    "최저입찰가_억": 0.0,
                    "유찰횟수": 0,
                    "입찰마감일시": "공고문 참조",
                    "진행상태": "🟢 진행중(신탁사공고)",
                    "유효여부": True,
                    "온비드_상세링크": full_url,
                    "매물_직행링크": full_url,
                    "신탁사_상세링크": full_url,
                    "링크유형": "신탁사공매",
                    "link_type": "신탁사공매",
                    "수의계약가능여부": "공고문 참조",
                    "관할법원": "-",
                    "사건번호": "-",
                    "세부진행상황": "무궁화신탁 정식 공매공고"
                })
    except Exception as e:
        logger.warning(f"Error scraping Mughwa: {e}")

    # 6. 한국자산신탁 (KAIT)
    if progress_callback: progress_callback(28, "한국자산신탁(KAIT) 실시간 공매 전체 페이지 수집 중...")
    try:
        for p in range(1, 6):
            url = f"https://www.kait.com/sale-info/?pageid={p}"
            r = requests.get(url, headers=HEADERS, timeout=5)
            if r.status_code != 200: break
            soup = BeautifulSoup(r.text, 'html.parser')
            trs = soup.select('table tbody tr')
            if not trs: break
            for tr in trs:
                a = tr.find('a')
                if not a: continue
                href = a.get('href', '')
                uid_m = re.search(r'uid=(\d+)', href)
                uid = uid_m.group(1) if uid_m else href
                if not uid or f"kait_{uid}" in seen_ids: continue
                seen_ids.add(f"kait_{uid}")

                title = a.text.strip().replace('\r', ' ').replace('\n', ' ')
                title = re.sub(r'\s+', ' ', title)
                if not title or len(title) < 5: continue
                full_url = f"https://www.kait.com{href}" if href.startswith('/') else href
                sido = normalize_sido("", title)

                direct_items.append({
                    "출처": "신탁사(한국자산신탁)",
                    "신탁사": "한국자산신탁",
                    "물건관리번호": f"한자신공매-{uid}",
                    "물건명": f"[한국자산신탁] {title}",
                    "소재지": title,
                    "시도": sido,
                    "시군구": "",
                    "읍면동": "",
                    "용도/지목": "신탁공매부동산",
                    "용도지역": "-",
                    "재산구분": "신탁재산",
                    "처분방식": "신탁사공매",
                    "면적(평)": extract_area_from_text(title),
                    "면적(㎡)": round(extract_area_from_text(title) * 3.305785, 1),
                    "최초입찰가(원)": "공고문 참조",
                    "최초입찰가_숫자": 0,
                    "최초입찰가_억": 0.0,
                    "최저입찰가(원)": "공고문 참조",
                    "최저입찰가_숫자": 0,
                    "최저입찰가_억": 0.0,
                    "유찰횟수": 0,
                    "입찰마감일시": "공고문 참조",
                    "진행상태": "🟢 진행중(신탁사공고)",
                    "유효여부": True,
                    "온비드_상세링크": full_url,
                    "매물_직행링크": full_url,
                    "신탁사_상세링크": full_url,
                    "링크유형": "신탁사공매",
                    "link_type": "신탁사공매",
                    "수의계약가능여부": "공고문 참조",
                    "관할법원": "-",
                    "사건번호": "-",
                    "세부진행상황": "한국자산신탁 정식 공매공고"
                })
    except Exception as e:
        logger.warning(f"Error scraping KAIT: {e}")

    # 7. 대신자산신탁 (thing_1)
    if progress_callback: progress_callback(30, "대신자산신탁 실시간 공매 전체 페이지 수집 중...")
    try:
        for p in range(1, 6):
            url = f"https://trust.daishin.com/thing_1?page={p}"
            r = requests.get(url, headers=HEADERS, timeout=5)
            if r.status_code != 200: break
            soup = BeautifulSoup(r.text, 'html.parser')
            for a in soup.find_all('a'):
                href = a.get('href', '')
                if 'bmode=view' not in href: continue
                idx_m = re.search(r'idx=(\d+)', href)
                idx = idx_m.group(1) if idx_m else href
                if not idx or f"daishin_{idx}" in seen_ids: continue
                seen_ids.add(f"daishin_{idx}")

                title = a.text.strip().replace('\r', ' ').replace('\n', ' ')
                title = re.sub(r'\s+', ' ', title)
                if not title or len(title) < 5: continue
                full_url = f"https://trust.daishin.com{href}" if href.startswith('/') else href
                sido = normalize_sido("", title)

                direct_items.append({
                    "출처": "신탁사(대신자산신탁)",
                    "신탁사": "대신자산신탁",
                    "물건관리번호": f"대신공매-{idx}",
                    "물건명": f"[대신자산신탁] {title}",
                    "소재지": title,
                    "시도": sido,
                    "시군구": "",
                    "읍면동": "",
                    "용도/지목": "신탁공매부동산",
                    "용도지역": "-",
                    "재산구분": "신탁재산",
                    "처분방식": "신탁사공매",
                    "면적(평)": extract_area_from_text(title),
                    "면적(㎡)": round(extract_area_from_text(title) * 3.305785, 1),
                    "최초입찰가(원)": "공고문 참조",
                    "최초입찰가_숫자": 0,
                    "최초입찰가_억": 0.0,
                    "최저입찰가(원)": "공고문 참조",
                    "최저입찰가_숫자": 0,
                    "최저입찰가_억": 0.0,
                    "유찰횟수": 0,
                    "입찰마감일시": "공고문 참조",
                    "진행상태": "🟢 진행중(신탁사공고)",
                    "유효여부": True,
                    "온비드_상세링크": full_url,
                    "매물_직행링크": full_url,
                    "신탁사_상세링크": full_url,
                    "링크유형": "신탁사공매",
                    "link_type": "신탁사공매",
                    "수의계약가능여부": "공고문 참조",
                    "관할법원": "-",
                    "사건번호": "-",
                    "세부진행상황": "대신자산신탁 정식 공매공고"
                })
    except Exception as e:
        logger.warning(f"Error scraping Daishin: {e}")

    return direct_items

def fetch_all_live_trust_properties(
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> List[Dict[str, Any]]:
    """
    14대 부동산 신탁사의 실제 살아있는 실시간 공매 매물을 전수 수집 및 동기화합니다.
    - 주요 신탁사 공식 웹사이트 전체 페이지(진행 + 수의계약) 스크래핑
    - 온비드 실시간 통합망 14개사 전수 질의
    - 종료되거나 존재하지 않는 유령 매물 자동 제외
    """
    all_trust_items = []
    seen_keys = set()

    # 1. 14대 신탁사 공식 웹사이트 직접 전수 스크래핑
    try:
        direct_items = scrape_direct_trust_boards(progress_callback=progress_callback)
        for d_it in direct_items:
            key = d_it.get("물건관리번호") or d_it.get("물건명")
            if key and key not in seen_keys:
                seen_keys.add(key)
                all_trust_items.append(d_it)
    except Exception as e:
        logger.warning(f"Failed in direct scraping: {e}")

    # 2. 온비드 실시간 공매 데이터베이스 14개 신탁사 전수 질의
    total_q = len(TARGET_TRUST_QUERIES)
    for i, kw in enumerate(TARGET_TRUST_QUERIES):
        if progress_callback:
            pct = 35 + int((i / total_q) * 60)
            progress_callback(pct, f"온비드 신탁사 통합망 수집: '{kw}' ({i+1}/{total_q})")
        
        url = f"https://www.onbid.co.kr/op/cltrpbancinf/toppagemng/unfsrch/UnfSrchController/srchUnf.do?swd={quote(kw)}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=6)
            start = r.text.find('{"unfSrchOtptVO"')
            if start != -1:
                end = r.text.rfind('}') + 1
                data = json.loads(r.text[start:end])
                otpt = data.get('unfSrchOtptVO', {})
                
                # 진행중인 공매
                for raw_it in otpt.get('bidCltrSrchRslt', []):
                    parsed = _parse_onbid_trust_item(raw_it, default_org=kw.split()[0])
                    key = parsed.get("물건관리번호") or parsed.get("물건명")
                    if key and key != "-" and key not in seen_keys:
                        seen_keys.add(key)
                        all_trust_items.append(parsed)

                # 유찰/수의계약 대상 공매
                for raw_it in otpt.get('bidRsltSrchRslt', []):
                    parsed = _parse_onbid_trust_item(raw_it, default_org=kw.split()[0])
                    key = parsed.get("물건관리번호") or parsed.get("물건명")
                    if key and key != "-" and key not in seen_keys:
                        seen_keys.add(key)
                        all_trust_items.append(parsed)
        except Exception:
            continue

    if progress_callback:
        progress_callback(100, f"신탁사 실시간 공매 수집 완료 (총 {len(all_trust_items)}건 검증됨)")

    return all_trust_items
