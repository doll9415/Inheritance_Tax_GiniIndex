# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import numpy as np
import io
import re
from pathlib import Path
import matplotlib.pyplot as plt

TITLE = "최근 7년간 상속현황 지니계수 분석"

st.set_page_config(page_title=TITLE, layout="wide")
st.title(TITLE)

st.markdown(
    """
    이 앱은 국세통계 엑셀 파일(예: **상속세 결정 현황(YYYY년 총상속재산가액 기준).xlsx**)을 불러와
    상위 분위(10%~100%) 및 `경정[B]` 행을 표로 정리하고, **로렌츠 곡선과 지니계수(상속재산 기준·결정세액 기준)**를 계산/시각화합니다.
    - 좌측 사이드바에서 파일을 선택/업로드하고 연도를 선택하세요.
    - 원본에 점유비(%) 열이 없으면 금액을 기준으로 자동 계산합니다.
    """
)

# ---------- 파일 입력 ----------
default_path = Path("./상속세 결정 현황(2025년총상속재산가액 기준).xlsx")  # 로컬 실행 시 같은 폴더에 두면 자동 사용
uploaded = st.sidebar.file_uploader("엑셀 파일 업로드", type=["xlsx"])

if uploaded is not None:
    xls = pd.ExcelFile(uploaded)
elif default_path.exists():
    xls = pd.ExcelFile(default_path)
else:
    st.info("좌측에서 엑셀 파일을 업로드해주세요. (xlsx)")
    st.stop()

sheet_names = xls.sheet_names
st.sidebar.write("감지된 시트 수 :", len(sheet_names))

# 연도(또는 시트) 선택
selected_sheet = st.sidebar.selectbox("연도(시트) 선택", options=sheet_names)

# ---------- 테이블 파싱 도우미 ----------
def find_table_from_sheet(xls, sheet_name):
    raw = pd.read_excel(xls, sheet_name=sheet_name, header=None)
    # 헤더 힌트 탐색
    header_hints = ["구분", "총상속", "결정세액", "점유비"]
    header_row = None
    for i in range(min(40, len(raw))):
        row_text = " ".join([str(x) for x in raw.iloc[i].tolist()])
        if all(h in row_text for h in header_hints):
            header_row = i
            break
    if header_row is None:
        header_row = (raw.dropna(how="all").index.min() or 0)

    df = pd.read_excel(xls, sheet_name=sheet_name, header=header_row)
    df.columns = [str(c).strip().replace("\\n", "") for c in df.columns]
    df = df.dropna(axis=1, how="all")

    # 구분 컬럼 찾기
    col_group = None
    for c in df.columns:
        if "구분" in str(c):
            col_group = c
            break
    if col_group is None:
        col_group = df.columns[0]

    def normalize_group(x):
        s = str(x).strip()
        s = s.replace("경정 [B]", "경정[B]")
        return s

    df[col_group] = df[col_group].map(normalize_group)

    desired_cols_map = {
        "구분": ["구분", "분류", "분위", "분위수", "계층"],
        "총상속재산가액(백만원)": ["총상속재산가액(백만원)", "총상속재산가액", "총상속 재산가액", "총상속재산 금액", "총상속재산액", "총상속재산"],
        "총상속재산가액 점유비(%)": ["총상속재산가액 점유비(%)", "총상속재산가액 점유비", "재산가액 점유비", "총상속재산 점유비", "재산 점유비(%)", "재산 점유비"],
        "총결정세액(백만원)": ["총결정세액(백만원)", "총결정세액", "결정세액(백만원)", "결정세액"],
        "총결정세액 점유비(%)": ["총결정세액 점유비(%)", "총결정세액 점유비", "결정세액 점유비(%)", "결정세액 점유비"],
    }

    def find_col(df, candidates):
        for name in candidates:
            for c in df.columns:
                if name == c:
                    return c
            for c in df.columns:
                if name.replace(" ", "") in str(c).replace(" ", ""):
                    return c
        return None

    col_amt1 = find_col(df, desired_cols_map["총상속재산가액(백만원)"])
    col_share1 = find_col(df, desired_cols_map["총상속재산가액 점유비(%)"])
    col_amt2 = find_col(df, desired_cols_map["총결정세액(백만원)"])
    col_share2 = find_col(df, desired_cols_map["총결정세액 점유비(%)"])

    wanted_order = [f"상위 {i}%" for i in range(10, 101, 10)] + ["경정[B]"]
    mask = df[col_group].isin(wanted_order)
    if not mask.any():
        mask = df[col_group].astype(str).str.contains("상위|경정", na=False)
    df = df.loc[mask].copy()

    def to_numeric(s):
        return pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False), errors="coerce")

    # 점유비가 없으면 계산
    if col_share1 is None and col_amt1 is not None:
        total1 = to_numeric(df[col_amt1]).sum()
        df["__share1"] = to_numeric(df[col_amt1]) / total1 * 100
        col_share1 = "__share1"
    if col_share2 is None and col_amt2 is not None:
        total2 = to_numeric(df[col_amt2]).sum()
        df["__share2"] = to_numeric(df[col_amt2]) / total2 * 100
        col_share2 = "__share2"

    # 최종 테이블
    final_cols = {
        "구분": col_group,
        "총상속재산가액(백만원)": col_amt1,
        "총상속재산가액 점유비(%)": col_share1,
        "총결정세액(백만원)": col_amt2,
        "총결정세액 점유비(%)": col_share2,
    }
    final_cols = {k: v for k, v in final_cols.items() if v is not None}

    table = df[list(final_cols.values())].copy()
    table.columns = list(final_cols.keys())

    order_map = {label: idx for idx, label in enumerate(wanted_order)}
    if "구분" in table.columns:
        table["__order"] = table["구분"].map(order_map)
        table = table.sort_values("__order").drop(columns="__order", errors="ignore")

    # 숫자형 컬럼 보관(계산용)
    num_cols = {}
    for c in ["총상속재산가액(백만원)", "총상속재산가액 점유비(%)", "총결정세액(백만원)", "총결정세액 점유비(%)"]:
        if c in table.columns:
            num_cols[c] = pd.to_numeric(table[c].astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False), errors="coerce")

    return table, num_cols

table, num_cols = find_table_from_sheet(xls, selected_sheet)

# ---------- 출력 테이블(표 형식) ----------
def fmt_amount(x):
    if pd.isna(x):
        return ""
    try:
        v = float(str(x).replace(",", ""))
    except:
        return x
    return f"{int(round(v)):,}"

def fmt_pct(x):
    if pd.isna(x):
        return ""
    try:
        v = float(str(x).replace(",", "").replace("%", ""))
    except:
        return x
    return f"{v:.1f}"

table_show = table.copy()
if "총상속재산가액(백만원)" in table_show.columns:
    table_show["총상속재산가액(백만원)"] = table_show["총상속재산가액(백만원)"].map(fmt_amount)
if "총결정세액(백만원)" in table_show.columns:
    table_show["총결정세액(백만원)"] = table_show["총결정세액(백만원)"].map(fmt_amount)
if "총상속재산가액 점유비(%)" in table_show.columns:
    table_show["총상속재산가액 점유비(%)"] = table_show["총상속재산가액 점유비(%)"].map(fmt_pct)
if "총결정세액 점유비(%)" in table_show.columns:
    table_show["총결정세액 점유비(%)"] = table_show["총결정세액 점유비(%)"].map(fmt_pct)

st.subheader("요약표")
st.dataframe(table_show, use_container_width=True)

# ---------- 지니계수 & 로렌츠 곡선 ----------
st.subheader("로렌츠 곡선 & 지니계수")

def lorenz_and_gini(shares_pct: pd.Series):
    """shares_pct: 하위->상위 순으로 누적해야 하므로, '상위 10%~100%'를 역순 정렬하여 하위부터 누적"""
    shares = shares_pct.dropna().astype(float).values
    if shares.size == 0:
        return None, None, None
    # shares는 "각 분위의 점유비(%)" -> 총합 100으로 가정
    # 하위 집단부터 누적하기 위해 상위 100% -> 상위 10% 순서로 역정렬
    shares_bottom_up = shares[::-1] / 100.0
    cum_pop = np.linspace(0, 1, len(shares_bottom_up) + 1)
    cum_share = np.concatenate([[0], np.cumsum(shares_bottom_up)])
    cum_share = cum_share / cum_share[-1]  # 혹시 합계가 1이 아니라면 정규화
    # 지니계수 = 1 - 2 * (로렌츠 곡선 아래 면적)
    area = np.trapz(cum_share, cum_pop)
    gini = 1 - 2 * area
    return cum_pop, cum_share, gini

col1, col2 = st.columns(2)

# (A) 상속재산 기준
with col1:
    st.markdown("**상속재산 기준**")
    if "총상속재산가액 점유비(%)" in num_cols and num_cols["총상속재산가액 점유비(%)"].notna().any():
        shares = num_cols["총상속재산가액 점유비(%)"]
    elif "총상속재산가액(백만원)" in num_cols:
        s = num_cols["총상속재산가액(백만원)"]
        shares = (s / s.sum()) * 100
    else:
        shares = None

    if shares is not None:
        cum_pop, cum_share, gini = lorenz_and_gini(shares)
        fig = plt.figure()
        plt.plot(cum_pop, cum_share, marker="o")
        plt.plot([0, 1], [0, 1], linestyle="--")
        plt.xlabel("누적 인구 비율")
        plt.ylabel("누적 상속재산 비율")
        plt.title("로렌츠 곡선 (상속재산)")
        st.pyplot(fig)
        st.metric("지니계수 (상속재산)", f"{gini:.3f}")
    else:
        st.warning("상속재산 기준 점유비/금액 정보를 찾을 수 없어 지니계를 계산하지 못했습니다.")

# (B) 결정세액 기준
with col2:
    st.markdown("**결정세액 기준**")
    if "총결정세액 점유비(%)" in num_cols and num_cols["총결정세액 점유비(%)"].notna().any():
        shares2 = num_cols["총결정세액 점유비(%)"]
    elif "총결정세액(백만원)" in num_cols:
        s2 = num_cols["총결정세액(백만원)"]
        shares2 = (s2 / s2.sum()) * 100
    else:
        shares2 = None

    if shares2 is not None:
        cum_pop2, cum_share2, gini2 = lorenz_and_gini(shares2)
        fig2 = plt.figure()
        plt.plot(cum_pop2, cum_share2, marker="o")
        plt.plot([0, 1], [0, 1], linestyle="--")
        plt.xlabel("누적 인구 비율")
        plt.ylabel("누적 결정세액 비율")
        plt.title("로렌츠 곡선 (결정세액)")
        st.pyplot(fig2)
        st.metric("지니계수 (결정세액)", f"{gini2:.3f}")
    else:
        st.warning("결정세액 기준 점유비/금액 정보를 찾을 수 없어 지니계를 계산하지 못했습니다.")

# ---------- 다운로드 ----------
st.subheader("결과 다운로드")
buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
    table_show.to_excel(writer, index=False, sheet_name="요약표")
buffer.seek(0)
st.download_button("요약표 엑셀 다운로드", data=buffer, file_name="상속현황_요약표.xlsx")

st.caption("※ 참고: 로렌츠곡선/지니계수는 선택된 시트(연도)에 대해 계산됩니다. 여러 연도를 비교하려면 시트를 바꿔 확인하세요.")
