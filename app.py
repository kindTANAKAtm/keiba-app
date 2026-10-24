import re
from itertools import combinations

import pandas as pd
import streamlit as st

WIDE_PAYOUT_RATE = 0.775  # JRAワイドの払戻率（参考表示のみ）
LAMBDAS = (1.0, 0.9, 0.8)  # 感度分析用。1.0 = Harville。較正値ではない


# =========================================================
# 1. 計算エンジン（Streamlitに依存しない）
# =========================================================
def win_probs(odds: list[float]) -> list[float]:
    """単勝オッズの逆数を正規化して勝率にする（控除率ぶんのオーバーラウンドを除去）"""
    inv = [1.0 / o for o in odds]
    s = sum(inv)
    return [x / s for x in inv]


def top3_set_probs(nos: list[int], p: list[float], lam: float = 1.0) -> dict:
    """
    「3着以内に入った3頭の組」ごとの確率（順序は合算済み）。
    1着は勝率p、2・3着はp**lamで残りを正規化する。lam=1.0がHarville、
    lam<1.0は人気馬の2・3着確率を割り引く（Henery型の簡易版）。合計は必ず1。
    """
    n = len(p)
    q = [x ** lam for x in p]
    q_sum = sum(q)
    res: dict = {}
    for i in range(n):
        d2 = q_sum - q[i]
        for j in range(n):
            if j == i:
                continue
            d3 = d2 - q[j]
            for k in range(n):
                if k == i or k == j:
                    continue
                pr = p[i] * (q[j] / d2) * (q[k] / d3)
                key = frozenset((nos[i], nos[j], nos[k]))
                res[key] = res.get(key, 0.0) + pr
    return res


def pair_probs(sets: dict) -> dict:
    """ワイド的中確率（2頭がともに3着以内）"""
    res: dict = {}
    for s, pr in sets.items():
        for pair in combinations(sorted(s), 2):
            res[pair] = res.get(pair, 0.0) + pr
    return res


def allocate(total: int, weights: list[float]) -> list[int]:
    """100円単位で、合計が必ず予算に一致する配分（最大剰余法）"""
    raw = [total * w for w in weights]
    amt = [int(r // 100) * 100 for r in raw]
    rem = int((total - sum(amt)) // 100)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - amt[i], reverse=True)
    for i in order[:rem]:
        amt[i] += 100
    return amt


def evaluate(sets: dict, bets: list[dict], budget: int) -> dict:
    """複数買い目の同時的中を含めた、レース全体の払戻分布"""
    exp_ret = p_none = p_ge_budget = 0.0
    for s, pr in sets.items():
        payout = sum(
            b["購入額"] * b["オッズ"]
            for b in bets
            if b["pair"][0] in s and b["pair"][1] in s
        )
        exp_ret += pr * payout
        if payout == 0:
            p_none += pr
        if payout >= budget:
            p_ge_budget += pr
    return {"exp_ret": exp_ret, "p_none": p_none, "p_ge_budget": p_ge_budget}


_HEADER = re.compile(r"^\d+(?:\s+\d+)?$")  # 「枠 馬番」または「馬番」だけの行
_SEXAGE = re.compile(r"^(?:牡|牝|セン|セ)\d+$")  # 牝2 など。データ行の先頭トークン
_FLOAT = re.compile(r"^\d+\.\d+$")
_INT = re.compile(r"^\d+$")
_NOISE = {"--", "-", "ー", "編集", "◎", "○", "▲", "△", "☆", "注", "×", "穴"}


def parse_race_card(text: str) -> tuple[pd.DataFrame, list[str]]:
    """
    出馬表の貼り付けテキストから「馬番・馬名・単勝オッズ」を取り出す。
    データ行（牝2 55.0 騎手 厩舎 馬体重 オッズ 人気）を基準に、
    直前の「枠 馬番」行と馬名行を遡って対応づける。取消・除外馬は除く。
    """
    lines = [ln.replace("\u3000", " ").strip() for ln in text.splitlines()]
    data_idx = [i for i, ln in enumerate(lines) if ln and _SEXAGE.match(ln.split()[0])]
    rows, notes = [], []
    prev_end = -1
    for idx in data_idx:
        header_i = None
        for j in range(idx - 1, prev_end, -1):
            if _HEADER.match(lines[j]):
                header_i = j
                break
        prev_end = idx
        if header_i is None:
            notes.append(f"馬番を特定できない行を飛ばしました: {lines[idx][:24]}")
            continue
        no = int(lines[header_i].split()[-1])
        block = lines[header_i : idx + 1]
        if any(w in ln for ln in block for w in ("取消", "除外")):
            notes.append(f"{no}番は取消・除外のため除外しました。")
            continue
        names = [ln for ln in lines[header_i + 1 : idx] if ln and ln not in _NOISE]
        name = names[-1] if names else ""

        tokens = lines[idx].split()
        odds = float("nan")
        if tokens and _FLOAT.match(tokens[-1]):
            odds = float(tokens[-1])
        elif len(tokens) >= 2 and _INT.match(tokens[-1]) and _FLOAT.match(tokens[-2]):
            odds = float(tokens[-2])
        rows.append({"no": no, "name": name, "odds": odds})

    df = pd.DataFrame(rows, columns=["no", "name", "odds"])
    if df.empty:
        return df, notes
    if df["no"].duplicated().any():
        notes.append("馬番が重複しています。貼り付け範囲を確認してください。")
    if df["odds"].isna().any():
        missing = "・".join(str(n) for n in df.loc[df["odds"].isna(), "no"])
        notes.append(f"単勝オッズを読み取れなかった馬: {missing}番（手入力してください）")
    return df.sort_values("no").reset_index(drop=True), notes


# =========================================================
# 2. UI
# =========================================================
@st.cache_data(show_spinner=False)
def cached_pair_probs(nos: tuple, odds: tuple, lam: float):
    sets = top3_set_probs(list(nos), win_probs(list(odds)), lam)
    return sets, pair_probs(sets)


st.set_page_config(page_title="ワイド資金配分", page_icon="🏇", layout="wide")
st.title("🏇 ワイド専用 資金配分ツール")
st.caption(
    "全頭の単勝オッズ → 市場勝率 → ワイド的中確率。ワイドオッズは手入力のみ。"
    "このツールは期待値を上げるものではなく、買い目構成のリスクの形を確認するものです。"
)

budget = int(st.sidebar.number_input("総予算 (円)", 1000, 500000, 10000, 100))
mode = st.sidebar.radio(
    "配分方式",
    ["均等払戻（ダッチング）", "均等購入"],
    help="どちらも期待値は変えません。変わるのは的中時の払戻の揃い方だけです。",
)

# ---- ① 全頭入力 ----
st.subheader("① 全頭の単勝オッズと役割")
st.markdown("確率の正規化に**出走全頭**が必要です。一部だけ入力すると確率が過大になります。")

if "horses_df" not in st.session_state:
    st.session_state["horses_df"] = pd.DataFrame(
        [
            {"no": 1, "name": "", "odds": 2.3, "role": "軸"},
            {"no": 2, "name": "", "odds": 3.8, "role": "相手"},
            {"no": 3, "name": "", "odds": 5.2, "role": "相手"},
            {"no": 4, "name": "", "odds": 7.2, "role": "相手"},
            {"no": 5, "name": "", "odds": 10.5, "role": "無印"},
            {"no": 6, "name": "", "odds": 17.0, "role": "無印"},
            {"no": 7, "name": "", "odds": 30.0, "role": "無印"},
            {"no": 8, "name": "", "odds": 55.0, "role": "無印"},
        ]
    )
    st.session_state["horses_ver"] = 0

with st.expander("出馬表を貼り付けて、馬番・馬名・単勝オッズを自動入力"):
    st.caption(
        "出馬表をそのまま貼り付けてください。役割（軸・相手）は自分で設定します。"
        "オッズ更新のために同じレースを貼り直した場合、馬番と馬名が一致する馬の役割は引き継ぎます。"
    )
    raw = st.text_area("出馬表", height=220, key="paste_raw", label_visibility="collapsed")
    if st.button("反映する"):
        parsed, notes = parse_race_card(raw)
        if parsed.empty:
            st.error("馬を読み取れませんでした。「牝2 55.0 騎手 …」の行を含めて貼り付けてください。")
        else:
            prev = st.session_state.get("horses_current")
            kept = {}
            if prev is not None:
                kept = {
                    (int(n), str(nm)): r
                    for n, nm, r in zip(prev["no"], prev["name"], prev["role"])
                    if pd.notna(n) and pd.notna(nm) and str(nm) != "" and pd.notna(r)
                }
            parsed["role"] = [kept.get((n, nm), "無印") for n, nm in zip(parsed["no"], parsed["name"])]
            st.session_state["horses_df"] = parsed
            st.session_state["horses_ver"] += 1
            st.success(f"{len(parsed)}頭を反映しました。")
        for n in notes:
            st.warning(n)

horses = st.data_editor(
    st.session_state["horses_df"],
    num_rows="dynamic",
    column_config={
        "no": st.column_config.NumberColumn("馬番", min_value=1, max_value=18, step=1, required=True),
        "name": st.column_config.TextColumn("馬名"),
        "odds": st.column_config.NumberColumn("単勝オッズ", min_value=1.0, max_value=999.9, step=0.1, required=True),
        "role": st.column_config.SelectboxColumn("役割", options=["軸", "相手", "無印"], required=True),
    },
    key=f"horses_{st.session_state['horses_ver']}",
)
st.session_state["horses_current"] = horses

errors = []
if horses[["no", "odds", "role"]].isna().any().any():
    errors.append("空欄があります。")
else:
    if horses["no"].duplicated().any():
        errors.append("馬番が重複しています。")
    if len(horses) < 3:
        errors.append("3頭以上入力してください。")
    if not (horses["role"] == "軸").any():
        errors.append("軸を1頭以上指定してください。")
    if len(horses) and (horses["role"] != "無印").sum() < 2:
        errors.append("軸と相手を合わせて2頭以上指定してください。")
if errors:
    for e in errors:
        st.error(e)
    st.stop()

nos = [int(x) for x in horses["no"]]
odds_win = [float(x) for x in horses["odds"]]

inv_sum = sum(1.0 / o for o in odds_win)
if not 1.15 <= inv_sum <= 1.40:
    st.warning(
        f"単勝オッズの逆数の合計が {inv_sum:.2f} です（全頭入力なら通常1.25前後）。"
        "未入力の馬があるか、入力ミスの可能性があります。"
    )

axes = [int(r.no) for r in horses.itertuples() if r.role == "軸"]
members = [int(r.no) for r in horses.itertuples() if r.role != "無印"]
pairs = sorted({tuple(sorted((a, m))) for a in axes for m in members if a != m})

# ---- ② ワイドオッズ ----
st.subheader("② ワイドオッズ（実オッズの下限値）")
st.markdown(
    "ワイドは幅表示のため**下限値**を入力してください（払戻を保守的に見積もります）。"
    "「購入」を外した買い目は除外されます。購入対象はすべて入力が必要です。"
)
df_pairs = pd.DataFrame(
    {
        "買い目": [f"{a} - {b}" for a, b in pairs],
        "ワイド下限オッズ": [float("nan")] * len(pairs),
        "購入": [True] * len(pairs),
    }
)
edited = st.data_editor(
    df_pairs,
    column_config={
        "買い目": st.column_config.TextColumn("買い目", disabled=True),
        "ワイド下限オッズ": st.column_config.NumberColumn(
            "ワイド下限オッズ", min_value=1.1, max_value=9999.9, step=0.1, format="%.1f"
        ),
        "購入": st.column_config.CheckboxColumn("購入"),
    },
    key=f"wide_{hash(tuple(pairs))}",
)

chosen = [
    (pair, float(o))
    for pair, o, buy in zip(pairs, edited["ワイド下限オッズ"], edited["購入"])
    if buy and pd.notna(o)
]
n_selected = int(edited["購入"].sum())
if n_selected == 0:
    st.warning("購入する買い目を1つ以上選んでください。")
    st.stop()
if len(chosen) < n_selected:
    st.warning("購入対象のすべてにワイドオッズを入力してください。")
    st.stop()

# ---- ③ 配分と評価 ----
if mode.startswith("均等払戻"):
    inv = [1.0 / o for _, o in chosen]
    weights = [x / sum(inv) for x in inv]
else:
    weights = [1.0 / len(chosen)] * len(chosen)

amounts = allocate(budget, weights)
bets = [
    {"pair": pair, "買い目": f"{pair[0]} - {pair[1]}", "オッズ": o, "購入額": a}
    for (pair, o), a in zip(chosen, amounts)
    if a > 0
]
dropped = len(chosen) - len(bets)
if dropped:
    st.warning(f"100円単位に収まらず、{dropped}点が購入額0円になり除外されました。買い目を減らすか予算を増やしてください。")

scen = {lam: cached_pair_probs(tuple(nos), tuple(odds_win), lam) for lam in LAMBDAS}
base_pairs = scen[1.0][1]
low_pairs = scen[0.8][1]

st.subheader("③ 配分結果")
st.dataframe(
    pd.DataFrame(
        [
            {
                "買い目": b["買い目"],
                "ワイド下限オッズ": b["オッズ"],
                "的中確率(λ=1.0)": f"{base_pairs[b['pair']] * 100:.1f}%",
                "確率×オッズ(λ=1.0)": round(base_pairs[b["pair"]] * b["オッズ"], 2),
                "確率×オッズ(λ=0.8)": round(low_pairs[b["pair"]] * b["オッズ"], 2),
                "購入額": b["購入額"],
                "単独的中時の払戻(下限)": int(b["購入額"] * b["オッズ"]),
            }
            for b in bets
        ]
    )
)

payouts = [b["購入額"] * b["オッズ"] for b in bets]
rows = []
for lam in LAMBDAS:
    r = evaluate(scen[lam][0], bets, budget)
    rows.append(
        {
            "λ": lam,
            "期待回収率": f"{r['exp_ret'] / budget * 100:.1f}%",
            "元本以上を回収する確率": f"{r['p_ge_budget'] * 100:.1f}%",
            "全外れの確率": f"{r['p_none'] * 100:.1f}%",
        }
    )

c1, c2, c3 = st.columns(3)
c1.metric("総購入額", f"{sum(b['購入額'] for b in bets):,} 円")
c2.metric("単独的中時の払戻(最小)", f"{int(min(payouts)):,} 円")
c3.metric("単独的中時の払戻(最大)", f"{int(max(payouts)):,} 円")

st.markdown("##### モデル誤差を想定した範囲")
st.dataframe(pd.DataFrame(rows), hide_index=True)
st.caption(
    "λ=1.0はHarville。λが小さいほど人気馬の2・3着確率を割り引きます。"
    "λの値は較正していないため、確率モデルの不確かさの幅を見るための感度分析です。"
    "期待回収率は購入額で加重した、買い目全体の値です（最大値でも単純平均でもありません）。"
)

ev_base = evaluate(scen[1.0][0], bets, budget)["exp_ret"] / budget
ev_low = evaluate(scen[0.8][0], bets, budget)["exp_ret"] / budget
if ev_base < 1.0:
    st.warning(
        f"市場確率基準の期待回収率は{ev_base * 100:.1f}%で、平均的には損失になる構成です"
        f"（ワイドの払戻率は{WIDE_PAYOUT_RATE * 100:.1f}%）。"
    )
elif ev_low < 1.0:
    st.info("100%超はλの置き方で消える程度です。モデル誤差の範囲内で、優位性とは言えません。")
else:
    st.info(
        "どのλでも100%超ですが、確率は市場オッズ由来で独自情報を含みません。"
        "下限オッズ基準で払戻は保守的でも、確率側の誤差は残ります。"
    )
