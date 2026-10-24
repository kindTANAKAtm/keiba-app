import math
import pandas as pd
import streamlit as st

# =========================================================
# 1. 予測・計算エンジン (UltimateHorseRaceOptimizer)
# =========================================================


class UltimateHorseRaceOptimizer:

    def __init__(self, budget: int = 10000):
        self.budget = budget

    def get_base_probabilities(self, odds: float, rank: int = 1) -> dict:
        """
        オッズ帯および推定人気順に基づく事前確率の設定
        【反映資料: 画像1（人気別・着順確率テーブル）】
        - 1番人気: 1着 33%, 2着 19%, 3着 13%
        - 2番人気: 1着 19%, 2着 18%, 3着 14%
        - 3番人気: 1着 14%, 2着 15%, 3着 14% ...
        """
        if odds <= 1.2:
            return {"p1": 0.70, "p2": 0.14, "p3": 0.06}
        elif odds <= 1.4:
            return {"p1": 0.60, "p2": 0.15, "p3": 0.08}
        elif odds <= 1.9:
            return {"p1": 0.45, "p2": 0.18, "p3": 0.12}
        elif odds <= 2.4:
            return {"p1": 0.36, "p2": 0.21, "p3": 0.13}
        elif odds <= 2.9:
            return {"p1": 0.29, "p2": 0.20, "p3": 0.14}
        elif odds <= 3.9:
            return {"p1": 0.23, "p2": 0.19, "p3": 0.15}
        elif odds <= 6.9:
            return {"p1": 0.15, "p2": 0.18, "p3": 0.14}
        elif odds <= 14.9:
            return {"p1": 0.07, "p2": 0.10, "p3": 0.11}
        elif odds <= 29.9:
            return {"p1": 0.03, "p2": 0.04, "p3": 0.06}
        else:
            return {"p1": 0.01, "p2": 0.02, "p3": 0.03}

    def get_venue_style_modifier(
        self, venue: str, track: str, style: str
    ) -> float:
        """
        開催場×トラック(芝/ダート)ごとの脚質有利度補正
        【反映資料: 画像2（芝前残り率）・画像3（ダート前残り率）】
        - 芝: 中山(60%), 小倉(62%), 函館(59%) が逃げ・先行超有利
        - ダート: 函館(74%), 小倉(72%), 新潟(71%), 札幌(71%) が超強力前残り
        """
        if track == "ダート":
            # ダートは函館・小倉・新潟・札幌が逃げ先行70%超の超極端前残り
            if venue in ["函館", "小倉", "新潟", "札幌"]:
                return 1.30 if style in ["逃げ", "先行"] else 0.70
            elif venue in ["中山", "京都", "中京", "阪神", "福島"]:
                return 1.18 if style in ["逃げ", "先行"] else 0.82
            else:  # 東京 (差し・追込可)
                return 0.95 if style in ["逃げ", "先行"] else 1.10
        else:
            # 芝は小倉(62%)・中山(60%)・函館(59%)・阪神(57%)が前残り有利
            if venue in ["小倉", "中山", "函館"]:
                return 1.25 if style in ["逃げ", "先行"] else 0.75
            elif venue in ["阪神", "福島", "札幌"]:
                return 1.12 if style in ["逃げ", "先行"] else 0.88
            elif venue in ["東京", "新潟"]:
                return 0.90 if style in ["逃げ", "先行"] else 1.15
            else:  # 京都・中京
                return 1.05 if style in ["逃げ", "先行"] else 0.95

    def get_class_style_modifier(self, race_class: str, style: str) -> float:
        """
        クラス・年齢条件による脚質到達率補正
        【反映資料: 画像4（クラス別脚質比率）】
        - 2歳/3歳未勝利: 逃げ・先行が69~72%到達（超前残り）
        - 古馬オープン/重賞: 差し・追込比率が50%程度まで上昇
        """
        if "2歳" in race_class or "未勝利" in race_class or "新馬" in race_class:
            return 1.22 if style in ["逃げ", "先行"] else 0.78
        elif "オープン" in race_class or "重賞" in race_class:
            return 0.88 if style in ["逃げ", "先行"] else 1.18
        else:  # 1勝/2勝/3勝クラス
            return 1.02 if style in ["逃げ", "先行"] else 0.98

    def get_distance_style_modifier(
        self, track: str, dist: int, style: str
    ) -> float:
        """
        距離×トラックごとの脚質補正
        - ダート1000m/1200m/1700m/1800m/2500mの前残り補正
        - 芝3000m超の逃げ・先行補正、ダート1600mの差し補正
        """
        if track == "ダート":
            if dist <= 1200:
                return 1.35 if style in ["逃げ", "先行"] else 0.65
            elif dist == 1600:
                return 0.85 if style in ["逃げ", "先行"] else 1.25
            elif dist in [1700, 1800, 2500]:
                return 1.25 if style in ["逃げ", "先行"] else 0.80
            else:
                return 1.10 if style in ["逃げ", "先行"] else 0.90
        else:  # 芝
            if dist >= 3000:
                return 1.40 if style in ["逃げ", "先行"] else 0.60
            elif dist <= 1400:
                return 1.10 if style in ["逃げ", "先行"] else 0.90
            else:
                return 1.05 if style in ["逃げ", "先行"] else 0.95

    def get_track_style_position_modifier(
        self, track: str, style: str
    ) -> dict:
        """
        芝 vs ダートにおける「1着・2着・3着別」脚質別偏重補正
        【反映資料: 画像5（芝・着順別率）・画像6（ダート・着順別率）】
        - ダート: 逃げ馬の1着率が23%と突出。差し馬は3着率が35%と高率。
        - 芝: 逃げ馬の1着率16%、差し馬の3着率38%。
        """
        if track == "ダート":
            if style == "逃げ":
                return {"p1": 1.25, "p2": 1.00, "p3": 0.80}
            elif style == "先行":
                return {"p1": 1.10, "p2": 1.12, "p3": 0.95}
            elif style == "差し":
                return {"p1": 0.75, "p2": 0.90, "p3": 1.25}
            else:  # 追込
                return {"p1": 0.60, "p2": 0.75, "p3": 1.15}
        else:  # 芝
            if style == "逃げ":
                return {"p1": 1.15, "p2": 0.95, "p3": 0.85}
            elif style == "先行":
                return {"p1": 1.05, "p2": 1.05, "p3": 0.95}
            elif style == "差し":
                return {"p1": 0.90, "p2": 1.00, "p3": 1.30}
            else:  # 追込
                return {"p1": 0.80, "p2": 0.90, "p3": 1.20}

    def adjust_probabilities(
        self, race_info: dict, horse: dict, rank: int
    ) -> dict[str, float]:
        """各馬の勝率・連対率・複勝率のベイズ補正計算"""
        odds = float(horse["odds"])
        mark = int(horse["mark"])
        style = horse["style"]

        # 1. 事前確率（オッズ帯・人気順）
        base = self.get_base_probabilities(odds, rank)
        p1, p2, p3 = base["p1"], base["p2"], base["p3"]

        # 2. 印によるベイズ補正 (印2は1着確率完全0%固定し、2着・3着へ分配転送)
        if mark == 4:
            p1 = max(p1 * 1.35, 0.65)
            p2 = max(p2 * 1.10, 0.18)
        elif mark == 3:
            p2 = min(p2 * 1.20, 0.35)
            p3 = min(p3 * 1.20, 0.25)
        elif mark == 2:
            p2 += p1 * 0.60
            p3 += p1 * 0.40
            p1 = 0.0

        # 3. 各種資料データ補正マルチプライヤーの算出
        venue_mod = self.get_venue_style_modifier(
            race_info["venue"], race_info["track"], style
        )
        class_mod = self.get_class_style_modifier(
            race_info["race_class"], style
        )
        dist_mod = self.get_distance_style_modifier(
            race_info["track"], race_info["dist"], style
        )
        pos_mods = self.get_track_style_position_modifier(
            race_info["track"], style
        )

        pace = race_info.get("pace", "ミドル")
        pace_mod = 1.0
        if pace == "ハイ":
            pace_mod = 0.80 if style in ["逃げ", "先行"] else 1.30
        elif pace == "スロー":
            pace_mod = 1.30 if style in ["逃げ", "先行"] else 0.70

        condition = race_info.get("condition", "良")
        cond_mod = 1.0
        # 【反映資料: 画像7】ダート重・不良での逃げ先行有利
        if race_info["track"] == "ダート" and condition in ["重", "不良"]:
            if style in ["逃げ", "先行"]:
                cond_mod = 1.20

        total_general_mod = venue_mod * class_mod * dist_mod * pace_mod * cond_mod

        return {
            "p1": p1 * total_general_mod * pos_mods["p1"],
            "p2": p2 * total_general_mod * pos_mods["p2"],
            "p3": p3 * total_general_mod * pos_mods["p3"],
        }

    def _normalize_probabilities(self, horses: list[dict]) -> None:
        """全出走馬の確率総和を1.0に正規化し、各着順の排他性を担保する処理"""
        sum_p1 = sum(h["probs"]["p1"] for h in horses)
        sum_p2 = sum(h["probs"]["p2"] for h in horses)
        sum_p3 = sum(h["probs"]["p3"] for h in horses)

        for h in horses:
            if sum_p1 > 0:
                h["probs"]["p1"] /= sum_p1
            if sum_p2 > 0:
                h["probs"]["p2"] /= sum_p2
            if sum_p3 > 0:
                h["probs"]["p3"] /= sum_p3

    def generate_strategy(
        self, race_info: dict, horses: list[dict]
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """ワイド・馬連・馬単の各買い目生成および資金配分"""
        # オッズ順にソートして人気ランクを付与
        sorted_horses = sorted(
            horses, key=lambda x: float(x["odds"])
        )
        for idx, h in enumerate(sorted_horses):
            h["probs"] = self.adjust_probabilities(
                race_info, h, rank=idx + 1
            )

        # 全体の確率を1.0へ正規化
        self._normalize_probabilities(horses)

        wide_bets, umaren_bets, umatan_bets = [], [], []

        axes = [h for h in horses if int(h["mark"]) in [3, 4]]
        opponents = [h for h in horses if int(h["mark"]) in [1, 2, 3]]

        for ax in axes:
            for op in opponents:
                if int(ax["no"]) == int(op["no"]):
                    continue

                p_top3_ax = (
                    ax["probs"]["p1"] + ax["probs"]["p2"] + ax["probs"]["p3"]
                )
                p_top3_op = (
                    op["probs"]["p1"] + op["probs"]["p2"] + op["probs"]["p3"]
                )

                # 1. 【ワイド】期待値と合成オッズ算出
                p_wide = min(p_top3_ax * p_top3_op * 1.15, 0.85)
                est_wide_odds = max(
                    round(
                        (float(ax["odds"]) * float(op["odds"])) ** 0.42, 1
                    ),
                    1.4,
                )
                wide_bets.append(
                    {
                        "券種": "ワイド",
                        "買い目": f"{ax['no']} - {op['no']}",
                        "オッズ": est_wide_odds,
                        "prob": p_wide,
                    }
                )

                # 2. 【馬連】1着・2着の双方向条件付き確率合算
                p1_ax, p2_ax = ax["probs"]["p1"], ax["probs"]["p2"]
                p1_op, p2_op = op["probs"]["p1"], op["probs"]["p2"]

                p_umaren = (p1_ax * (p2_op / max(1.0 - p2_ax, 1e-5))) + (
                    p1_op * (p2_ax / max(1.0 - p2_op, 1e-5))
                )
                est_umaren_odds = max(
                    round(
                        (float(ax["odds"]) * float(op["odds"])) ** 0.52, 1
                    ),
                    1.8,
                )
                if p_umaren > 0:
                    umaren_bets.append(
                        {
                            "券種": "馬連",
                            "買い目": f"{ax['no']} - {op['no']}",
                            "オッズ": est_umaren_odds,
                            "prob": p_umaren,
                        }
                    )

                # 3. 【馬単】軸馬1着固定の条件付き確率
                p_umatan = p1_ax * (p2_op / max(1.0 - p2_ax, 1e-5))
                if p_umatan > 0:
                    est_umatan_odds = max(
                        round(
                            float(ax["odds"]) * (float(op["odds"]) ** 0.65), 1
                        ),
                        2.5,
                    )
                    umatan_bets.append(
                        {
                            "券種": "馬単",
                            "買い目": f"{ax['no']} -> {op['no']}",
                            "オッズ": est_umatan_odds,
                            "prob": p_umatan,
                        }
                    )

        # 重複買い目の削除
        wide_bets = list({b["買い目"]: b for b in wide_bets}.values())
        umaren_bets = list({b["買い目"]: b for b in umaren_bets}.values())
        umatan_bets = list({b["買い目"]: b for b in umatan_bets}.values())

        # モードに応じた資金アロケーション
        df_wide = self._allocate_budget(wide_bets, mode="dutching")
        df_umaren = self._allocate_budget(umaren_bets, mode="kelly")
        df_umatan = self._allocate_budget(umatan_bets, mode="kelly")

        return df_wide, df_umaren, df_umatan

    def _allocate_budget(self, bets: list[dict], mode: str) -> pd.DataFrame:
        """資金配分アルゴリズム（ダッチング/ケリー傾斜 & 100円単位丸め処理）"""
        if not bets:
            return pd.DataFrame()

        if mode == "dutching":
            sum_inv = sum(1.0 / b["オッズ"] for b in bets)
            weights = [(1.0 / b["オッズ"]) / sum_inv for b in bets]
        else:
            ev_list = [b["prob"] * b["オッズ"] for b in bets]
            sum_ev = max(sum(ev_list), 1e-6)
            weights = [ev / sum_ev for ev in bets]

        allocated_total = 0
        results = []
        for b, w in zip(bets, weights):
            raw_val = self.budget * w
            amount = math.floor(raw_val / 100) * 100
            results.append({**b, "購入額": amount, "_rem": raw_val - amount})
            allocated_total += amount

        rem_budget = int((self.budget - allocated_total) // 100)
        results.sort(key=lambda x: x["_rem"], reverse=True)
        for i in range(rem_budget):
            results[i]["購入額"] += 100

        df = pd.DataFrame(results)
        df["想定払戻金"] = (df["購入額"] * df["オッズ"]).astype(int)
        df["想定回収率"] = (
            (df["想定払戻金"] / self.budget) * 100
        ).map("{:.1f}%".format)

        return df[["券種", "買い目", "オッズ", "購入額", "想定払戻金", "想定回収率"]]


# =========================================================
# 2. Streamlit UI 画面構築
# =========================================================

st.set_page_config(
    page_title="競馬傾斜買い計算機", page_icon="🏇", layout="wide"
)

st.title("🏇 競馬オッズ・ベイズ傾斜買い計算アプリ (全データ統合版)")
st.caption(
    "JRA全統計データ（競馬場・クラス・距離・馬場・人気別着順率）×「印2＝1着0%」最適配分"
)

# サイドバー設定
st.sidebar.header("⚙️ レース条件設定")

total_budget = st.sidebar.number_input(
    "総予算 (円)", min_value=1000, max_value=500000, value=10000, step=1000
)

col_s1, col_s2 = st.sidebar.columns(2)
with col_s1:
    venue = st.selectbox(
        "競馬場",
        [
            "中山",
            "東京",
            "阪神",
            "京都",
            "小倉",
            "新潟",
            "福島",
            "中京",
            "札幌",
            "函館",
        ],
    )
    track = st.selectbox("トラック", ["ダート", "芝"])
    weather = st.selectbox("天候", ["晴", "曇", "雨", "雪"])
    race_class = st.selectbox(
        "クラス・条件",
        ["2歳/3歳未勝利", "2歳/3歳新馬", "1勝/2勝/3勝クラス", "オープン/重賞"],
        index=2,
    )

with col_s2:
    dist = st.selectbox(
        "距離 (m)",
        [
            1000,
            1150,
            1200,
            1400,
            1500,
            1600,
            1700,
            1800,
            2000,
            2200,
            2400,
            2500,
            2600,
            3000,
        ],
        index=7,
    )
    condition = st.selectbox("馬場状態", ["良", "稍重", "重", "不良"])
    pace = st.selectbox("展開予想", ["ハイ", "ミドル", "スロー"], index=0)

race_info = {
    "venue": venue,
    "track": track,
    "dist": dist,
    "weather": weather,
    "condition": condition,
    "pace": pace,
    "race_class": race_class,
}

# 馬情報入力
st.subheader("🐴 対象馬情報の入力")
st.markdown(
    """
**【印の定義】**  
- **4**: 超本命（勝率極高） | **3**: 本命（3着以内軸） | **2**: 相手（**1着は絶対なし**・2~3着候補） | **1**: 大穴  
"""
)

default_data = pd.DataFrame(
    [
        {"no": 1, "mark": 4, "style": "逃げ", "odds": 1.8},
        {"no": 3, "mark": 2, "style": "先行", "odds": 6.5},
        {"no": 5, "mark": 2, "style": "差し", "odds": 9.0},
        {"no": 8, "mark": 1, "style": "追込", "odds": 22.0},
    ]
)

edited_df = st.data_editor(
    default_data,
    num_rows="dynamic",
    column_config={
        "no": st.column_config.NumberColumn(
            "馬番", min_value=1, max_value=18, step=1, required=True
        ),
        "mark": st.column_config.SelectboxColumn(
            "印",
            options=[4, 3, 2, 1],
            help="4:超本命, 3:本命, 2:1着なし2-3着, 1:大穴",
            required=True,
        ),
        "style": st.column_config.SelectboxColumn(
            "脚質",
            options=["逃げ", "先行", "差し", "追込"],
            required=True,
        ),
        "odds": st.column_config.NumberColumn(
            "単勝オッズ",
            min_value=1.0,
            max_value=999.9,
            step=0.1,
            format="%.1f",
            required=True,
        ),
    },
    use_container_width=True,
)

# 計算実行処理
if st.button("🚀 最適資金配分を計算する", type="primary"):
    horses_list = edited_df.to_dict(orient="records")

    has_axis = any(int(h["mark"]) in [3, 4] for h in horses_list)
    if not has_axis:
        st.error(
            "⚠️ 軸馬（印「4」または「3」）を少なくとも1頭指定してください。"
        )
    else:
        optimizer = UltimateHorseRaceOptimizer(budget=total_budget)
        df_wide, df_umaren, df_umatan = optimizer.generate_strategy(
            race_info, horses_list
        )

        st.divider()
        st.subheader("📊 資金配分シミュレーション結果")

        tab1, tab2, tab3 = st.tabs(
            [
                "🛡️ 【安定重視】ワイド (均等払戻)",
                "⚖️ 【バランス】馬連 (期待値傾斜)",
                "🔥 【リスク重視】馬単 (1着0%切り傾斜)",
            ]
        )

        with tab1:
            st.markdown("#### ワイド（均等払戻ダッチング配分）")
            if not df_wide.empty:
                st.dataframe(df_wide, use_container_width=True)
                min_ret = df_wide["想定払戻金"].min()
                st.metric(
                    label="的中時 最小想定払戻金",
                    value=f"{min_ret:,} 円",
                    delta=f"回収率 {min_ret / total_budget * 100:.1f}%",
                )
            else:
                st.warning("条件に該当するワイドの買い目がありません。")

        with tab2:
            st.markdown("#### 馬連（期待値ケリー傾斜配分）")
            if not df_umaren.empty:
                st.dataframe(df_umaren, use_container_width=True)
                max_ret = df_umaren["想定払戻金"].max()
                st.metric(
                    label="最大想定払戻金",
                    value=f"{max_ret:,} 円",
                    delta=f"最高回収率 {max_ret / total_budget * 100:.1f}%",
                )
            else:
                st.warning("条件に該当する馬連の買い目がありません。")

        with tab3:
            st.markdown("#### 馬単（「印2＝1着0%」超効率ケリー傾斜配分）")
            if not df_umatan.empty:
                st.dataframe(df_umatan, use_container_width=True)
                max_ret = df_umatan["想定払戻金"].max()
                st.metric(
                    label="最大想定払戻金",
                    value=f"{max_ret:,} 円",
                    delta=f"最高回収率 {max_ret / total_budget * 100:.1f}%",
                )
            else:
                st.warning("条件に該当する馬単の買い目がありません。")
