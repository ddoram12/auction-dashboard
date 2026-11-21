import io
from datetime import datetime
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from typing import List, Dict, Any

def generate_styled_excel(items: List[Dict[str, Any]]) -> bytes:
    """
    공매 및 신탁사 PF 사업장 물건 목록 데이터를 전문적이고 깔끔한 서식의 엑셀(.xlsx) 파일로 변환합니다.
    - 헤더 네이비 스타일링 & 틀 고정(Freeze Panes)
    - 자동 열 너비 계산 (한글 폭 보정)
    - 온비드 및 법원경매 하이퍼링크 적용
    - 최초입찰가/최저입찰가/면적 정밀 숫자 서식 적용
    - 신탁사 문의처, 인허가 현황, 수의계약 가능여부 포함
    """
    output = io.BytesIO()
    
    # 표시할 컬럼 지정 및 명칭 매핑
    export_cols = [
        ("출처", "출처"),
        ("진행상태", "진행상태"),
        ("물건관리번호", "물건관리번호"),
        ("관할법원", "관할법원"),
        ("사건번호", "사건번호"),
        ("물건명", "물건명"),
        ("소재지", "소재지"),
        ("시도", "시/도"),
        ("시군구", "시/군/구"),
        ("용도/지목", "사업용도/지목"),
        ("용도지역", "용도지역"),
        ("면적(평)", "면적(평)"),
        ("면적(㎡)", "면적(㎡)"),
        ("최초입찰가_숫자", "최초입찰가(원)"),
        ("최저입찰가_숫자", "최저입찰가(원)"),
        ("수의계약가능여부", "수의계약가능여부"),
        ("인허가여부", "인허가여부"),
        ("착공완공여부", "착공/공사진행"),
        ("신탁사", "신탁사"),
        ("신탁사연락처", "신탁사연락처"),
        ("대리금융기관", "대리금융기관"),
        ("매각기일", "매각기일/마감일"),
        ("온비드_상세링크", "공매/경매 바로가기")
    ]
    
    # 엑셀 워크북 생성
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "공매_및_개발부지_목록"
    ws.views.sheetView[0].showGridLines = True
    
    # 스타일 정의
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid") # 짙은 네이비
    header_font = Font(name="맑은 고딕", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="맑은 고딕", size=10)
    link_font = Font(name="맑은 고딕", size=10, color="0000FF", underline="single")
    
    thin_border_side = Side(style="thin", color="D1D5DB")
    data_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
    
    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")
    
    # 헤더 작성
    headers = [col[1] for col in export_cols]
    ws.append(headers)
    ws.row_dimensions[1].height = 28
    
    for col_idx, cell in enumerate(ws[1], 1):
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = align_center
        cell.border = data_border
        
    # 데이터 행 작성
    for row_idx, item in enumerate(items, start=2):
        row_values = []
        for src_col, target_col in export_cols:
            val = item.get(src_col, "")
            row_values.append(val)
        ws.append(row_values)
        ws.row_dimensions[row_idx].height = 22
        
        for col_idx, col_name in enumerate(headers, 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = data_font
            cell.border = data_border
            
            # 서식 및 정렬 규칙
            if col_name in ["출처", "진행상태", "물건관리번호", "관할법원", "사건번호", "시/도", "시/군/구", "용도지역", "수의계약가능여부", "인허가여부", "착공/공사진행", "신탁사", "신탁사연락처", "대리금융기관", "매각기일/마감일"]:
                cell.alignment = align_center
            elif col_name in ["물건명", "소재지", "사업용도/지목"]:
                cell.alignment = align_left
            elif col_name in ["면적(평)", "면적(㎡)"]:
                cell.alignment = align_right
                cell.number_format = '#,##0.0'
            elif col_name in ["최초입찰가(원)", "최저입찰가(원)"]:
                cell.alignment = align_right
                cell.number_format = '#,##0'
            elif col_name == "공매/경매 바로가기":
                url = item.get("온비드_상세링크", "")
                if url:
                    cell.hyperlink = url
                    cell.value = "사이트 바로가기 ↗"
                    cell.font = link_font
                    cell.alignment = align_center
                url = item.get("온비드_상세링크", "")
                if url:
                    cell.hyperlink = url
                    cell.value = "물건 바로보기 ↗"
                    cell.font = link_font
                    cell.alignment = align_center
                    
    # 틀 고정 (헤더 고정)
    ws.freeze_panes = "A2"
    
    # 자동 필터 활성화
    ws.auto_filter.ref = ws.dimensions
    
    # 열 너비 자동 맞춤
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        
        for cell in col:
            val = str(cell.value or "")
            # 한글은 폭을 더 넓게 계산
            char_len = sum(2 if ord(c) > 127 else 1 for c in val)
            if char_len > max_len:
                max_len = char_len
                
        # 여유 공간 확보 (최소 10, 최대 50)
        adjusted_width = min(50, max(max_len + 4, 11))
        ws.column_dimensions[col_letter].width = adjusted_width

    wb.save(output)
    output.seek(0)
    return output.getvalue()
