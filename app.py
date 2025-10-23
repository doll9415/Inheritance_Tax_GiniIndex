# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import numpy as np
import io
from pathlib import Path
import matplotlib.pyplot as plt
import re

TITLE = "최근 7년간 상속현황 지니계수 분석"

st.set_page_config(page_title=TITLE, layout="wide")
st.title(TITLE)

st.markdown(
    """
    - 첨부 엑셀의 **모든 시트**를 스캔하여 ‘구분/점유비/총상속재산/총결정세액’ 헤더를 **자동 탐지**합니다.
    - **상위 10% … 상위 100%, 경정[B]** 행만 추출하여 표를 구성합니다.
    - **시트 선택 버튼**을 눌러 연도(시트)를 바꾸어 볼 수 있습니다.
    - 하단의 **여러 시트 지니계수 비교**에서 모든 시트의 지니계수를 한 그래프에서 비교할 수 있습니다.
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

# Session state: 현재 표시 시트
if "current_sheet" not in st.session_state:
    st.session_state.current_sheet = sheet_names[0] if sheet_names else None

# ---------- 시트 선택 버튼 UI ----------
st.subheader("시트 선택")
# 버튼을 여러 컬럼으로 깔끔하게 배치
N_PER_ROW = 5
rows = (len(s := sheet_names) + N_PER_ROW - 1) // N_PER_ROW
idx = 0
for _ in range(rows):
    cols = st.columns(min(N_PER_ROW, len(s) - idx))
    for c in cols:
        if idx >= len(s): break
        name = s[idx]
        if c.button(name):
            st.session_state.current_sheet = name
        idx += 1

st.caption(f"현재 선택된 시트: **{st.session_state.current_sheet}**")

# ---------- 테이블 파싱/지니 함수 ----------
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

    # 원하는 행만 추출
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

    # 정렬
    order_map = {label: idx for idx, label in enumerate(wanted_order)}
    if "구분" in table.columns:
        table["__order"] = table["구분"].map(order_map)
        table = table.sort_values("__order").drop(columns="__order", errors="ignore")

    # 숫자형 컬럼(계산용)
    num_cols = {}
    for c in ["총상속재산가액(백만원)", "총상속재산가액 점유비(%)", "총결정세액(백만원)", "총결정세액 점유비(%)"]:
        if c in table.columns:
            num_cols[c] = pd.to_numeric(table[c].astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False), errors="coerce")

    return table, num_cols

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

def lorenz_and_gini(shares_pct: pd.Series):
    shares = shares_pct.dropna().astype(float).values
    if shares.size == 0:
        return None, None, None
    shares_bottom_up = shares[::-1] / 100.0  # 상위->하위 역정렬 후 비율화
    cum_pop = np.linspace(0, 1, len(shares_bottom_up) + 1)
    cum_share = np.concatenate([[0], np.cumsum(shares_bottom_up)])
    cum_share = cum_share / cum_share[-1]  # 정규화
    area = np.trapz(cum_share, cum_pop)
    gini = 1 - 2 * area
    return cum_pop, cum_share, gini

def compute_ginis_for_sheet(xls, sheet_name):
    table, num_cols = find_table_from_sheet(xls, sheet_name)
    # 상속재산 기준
    if "총상속재산가액 점유비(%)" in num_cols and num_cols["총상속재산가액 점유비(%)"].notna().any():
        shares1 = num_cols["총상속재산가액 점유비(%)"]
    elif "총상속재산가액(백만원)" in num_cols:
        s1 = num_cols["총상속재산가액(백만원)"]
        shares1 = (s1 / s1.sum()) * 100
    else:
        shares1 = None

    # 결정세액 기준
    if "총결정세액 점유비(%)" in num_cols and num_cols["총결정세액 점유비(%)"].notna().any():
        shares2 = num_cols["총결정세액 점유비(%)"]
    elif "총결정세액(백만원)" in num_cols:
        s2 = num_cols["총결정세액(백만원)"]
        shares2 = (s2 / s2.sum()) * 100
    else:
        shares2 = None

    g1 = g2 = None
    if shares1 is not None:
        _, _, g = lorenz_and_gini(shares1)
        g1 = g
    if shares2 is not None:
        _, _, g = lorenz_and_gini(shares2)
        g2 = g
    return g1, g2

# ---------- 현재 시트 표시 ----------
cur = st.session_state.current_sheet
if cur is None:
    st.stop()

table, num_cols = find_table_from_sheet(xls, cur)

# 표시용 포맷
table_show = table.copy()
if "총상속재산가액(백만원)" in table_show.columns:
    table_show["총상속재산가액(백만원)"] = table_show["총상속재산가액(백만원)"].map(fmt_amount)
if "총결정세액(백만원)" in table_show.columns:
    table_show["총결정세액(백만원)"] = table_show["총결정세액(백만원)"].map(fmt_amount)
if "총상속재산가액 점유비(%)" in table_show.columns:
    table_show["총상속재산가액 점유비(%)"] = table_show["총상속재산가액 점유비(%)"].map(fmt_pct)
if "총결정세액 점유비(%)" in table_show.columns:
    table_show["총결정세액 점유비(%)"] = table_show["총결정세액 점유비(%)"].map(fmt_pct)

st.subheader(f"요약표 · `{cur}`")
st.dataframe(table_show, use_container_width=True)

# 지니/로렌츠 (상속재산 & 결정세액)
st.subheader("로렌츠 곡선 & 지니계수")
col1, col2 = st.columns(2)

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

# 다운로드
st.subheader("결과 다운로드")
buffer = io.BytesIO()
with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
    table_show.to_excel(writer, index=False, sheet_name="요약표")
buffer.seek(0)
st.download_button("요약표 엑셀 다운로드", data=buffer, file_name=f"상속현황_요약표_{cur}.xlsx")

# ---------- 여러 시트 지니계수 비교 ----------
st.subheader("여러 시트 지니계수 비교")

# 전체 시트에 대해 지니계수 계산
records = []
for sn in sheet_names:
    g_asset, g_tax = compute_ginis_for_sheet(xls, sn)
    # 연도 추출(정렬용): 시트명에서 4자리 연도 우선
    m = re.search(r"(19|20)\\d{2}", str(sn))
    year_key = int(m.group(0)) if m else None
    records.append({"sheet": sn, "year_key": year_key, "지니(상속재산)": g_asset, "지니(결정세액)": g_tax})

# 정렬: 연도 키가 있으면 연도 오름차순, 없으면 원래 순서 유지
df_g = pd.DataFrame(records)
df_g["__order_idx"] = range(len(df_g))
df_g = df_g.sort_values(by=["year_key", "__order_idx"], na_position="last").drop(columns="__order_idx")

st.dataframe(df_g[["sheet", "지니(상속재산)", "지니(결정세액)"]], use_container_width=True)

# 라인차트 (단일 플롯, 색상 지정: 상속재산=파랑, 결정세액=빨강)
labels = df_g["sheet"].tolist()
x = list(range(len(labels)))
y1 = df_g["지니(상속재산)"].astype(float).tolist()
y2 = df_g["지니(결정세액)"].astype(float).tolist()

fig_cmp = plt.figure()
plt.plot(x, y1, marker="o", label="상속재산 기준", color="blue")
plt.plot(x, y2, marker="o", label="결정세액 기준", color="red")
plt.xticks(x, labels, rotation=45, ha="right")
plt.ylim(0, 1)
plt.ylabel("지니계수")
plt.title("시트별 지니계수 비교")
plt.legend()
st.pyplot(fig_cmp)

# 비교표 다운로드
csv_buf = io.StringIO()
df_g.to_csv(csv_buf, index=False, encoding="utf-8-sig")
st.download_button("지니계수 비교표(CSV) 다운로드", data=csv_buf.getvalue(), file_name="gini_compare_all_sheets.csv")


# ---------- 지니계수 설명 ----------
st.markdown("---")
st.subheader("지니계수란?")
st.markdown(
    """
    **지니계수(Gini coefficient)**는 분배의 불평등 정도를 0에서 1 사이의 값으로 나타내는 지표입니다.  
    로렌츠 곡선과 45도 균등분배선 사이의 면적을 전체 삼각형 면적으로 나눈 값으로 정의되며,
    다음과 같은 성질을 가집니다.
    
    - **값의 범위:** 0 ≤ Gini ≤ 1  
      - 0에 가까울수록 **균등 분배**, 1에 가까울수록 **불평등 분배**를 의미합니다.
    - **로렌츠 곡선 기반:** 하위 집단부터 누적한 분배 비율 곡선(로렌츠 곡선)이 균등분배선(45도 직선)에서 멀어질수록 지니계수가 커집니다.
    - **본 앱의 계산 방식:** 각 시트의 **분위(상위 10%~100%)**별 **점유비(%)** 또는 **금액 비중**을 바탕으로  
      로렌츠 곡선을 구성하고, 수치적분(면적)을 이용해 지니계수를 산출합니다.
    - **해석 팁:**  
      - **상속재산 기준 지니**는 상속재산의 집중도를, **결정세액 기준 지니**는 세부담(결정세액)의 집중도를 보여줍니다.  
      - 두 지니가 다르게 나타날 수 있으며, 이는 재산 분포와 세부담 구조(공제·세율·경정 등)의 차이를 반영합니다.
    - **주의사항:**  
      - 분위 구간(10분위) 자료를 사용하므로, **개별 자료를 이용한 연속적 지니계수**보다 **근사치**라는 점을 유의하세요.  
      - 표본 범위(과세표본/경정 포함 여부), 산출 연도, 지표 정의의 변동에 따라 **연도 간 비교 시 주의**가 필요합니다.
    """
)
