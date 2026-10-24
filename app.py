import math
import pandas as pd
import streamlit as st

# =========================================================
# 1. 予測・計算エンジン (UltimateHorseRaceOptimizer)
# =========================================================


class UltimateHorseRaceOptimizer:

    def __init__(self, budget: int = 10000):
        self.budget = budget

    def get_base_probabilities(self, odds: float, total_horses: int = 16) -> dict:
        """
        オッズ帯および出走頭数(total_horses)に基づく基本着順確率
        【JRA統計データ準拠】
        """
        # 頭数補正スケール (16頭を基準とし、頭数が少ないほど上位人気の着順確率が上昇)
        head_scale = 16.0 / max(total_horses, 5)
        head_scale_clamped = max(0.85, min(head_scale, 1.45))

        if odds <= 1.2:
            p1, p2, p3 = 0.65, 0.16, 0.08
        elif odds <= 1.4:
            p1, p2, p3 = 0.55, 0.18, 0.10
        elif odds <= 1.9:
            p1, p2, p3 = 0.42, 0.20, 0.13
        elif odds <= 2.4:
            p1, p2, p3 = 0.33, 0.21, 0.14
        elif odds <= 2.9:
            p1, p2, p3 = 0.27, 0.20, 0.14
        elif odds <= 3.9:
            p1, p2, p3 = 0.21, 0.18, 0.15
        elif odds <= 6.9:
            p1, p2, p3 = 0.14, 0.16, 0.14
        elif odds <= 14.9:
            p1, p2, p3 = 0.07, 0.10, 0.11
        elif odds <= 29.9:
            p1, p2, p3 = 0.03, 0.05, 0.07
        else:
            p1, p2, p3 = 0.01, 0.02, 0.03

        # 少頭数時は上位確率が上振れ、多頭数時は分散
        if odds <= 3.9:
            p1 = min(p1 * head_scale_clamped, 0.85)
            p2 = min(p2 * head_scale_clamped, 0.35)
            p3 = min(p3 * head_scale_clamped, 0.25)

        return {"p1": p1, "p2": p2, "p3": p3}

    def get_venue_style_modifier(
        self, venue: str, track: str, style: str
    ) -> float:
        """開催場×トラックごとの脚質補正"""
        if track == "ダート":
            if venue in ["函館", "小倉", "新潟", "札幌"]:
                return 1.10 if style in ["逃げ", "先行"] else 0.92
            elif venue in ["中山", "京都", "中京", "阪神", "福島"]:
                return 1.05 if style in ["逃げ", "先行"] else 0.96
            else:  # 東京
                return 0.97 if style in ["逃げ", "先行"] else 1.03
        else:  # 芝
            if venue in ["小倉", "中山", "函館"]:
                return 1.08 if style in ["逃げ", "先行"] else 0.93
            elif venue in ["阪神", "福島", "札幌"]:
                return 1.04 if style in ["逃げ", "先行"] else 0.96
            elif venue in ["東京", "新潟"]:
                return 0.95 if style in ["逃げ", "先行"] else 1.05
            else:  # 京都・中京
                return 1.01 if style in ["逃げ", "先行"] else 0.99

    def get_class_style_modifier(self, race_class: str, style: str) -> float:
        """クラス・条件による補正"""
        if "未勝利" in race_class or "新馬" in race_class:
            return 1.06 if style in ["逃げ", "先行"] else 0.94
        elif "オープン" in race_class or "重賞" in race_class:
            return 0.95 if style in ["逃げ", "先行"] else 1.05
        else:
            return 1.01 if style in ["逃げ", "先行"] else 0.99

    def get_distance_style_modifier(
        self, track: str, dist: int, style: str
    ) -> float:
        """距離×トラックごとの脚質補正"""
        if track == "ダート":
            if dist <= 1200:
                return 1.10 if style in ["逃げ", "先行"] else 0.90
            elif dist == 1600:
                return 0.95 if style in ["逃げ", "先行"] else 1.05
            elif dist in [1700, 1800, 2500]:
                return 1.08 if style in ["逃げ", "先行"] else 0.92
            else:
                return 1.03 if style in ["逃げ", "先行"] else 0.97
        else:  # 芝
            if dist >= 3000:
                return 1.12 if style in ["逃げ", "先行"] else 0.88
            elif dist <= 1400:
                return 1.04 if style in ["逃げ", "先行"] else 0.96
            else:
                return 1.01 if style in ["逃げ", "先行"] else 0.99

    def get_track_style_position_modifier(
        self, track: str, style: str
    ) -> dict:
        """着順別（1, 2, 3着）偏重補正"""
        if track == "ダート":
            if style == "逃げ":
                return {"p1": 1.06, "p2": 1.00, "p3": 0.95}
            elif style == "先行":
                return {"p1": 1.03, "p2": 1.02, "p3": 0.98}
            elif style == "差し":
                return {"p1": 0.94, "p2": 0.97, "p3": 1.06}
            else:  # 追込
                return {"p1": 0.90, "p2": 0.94, "p3": 1.04}
        else:  # 芝
            if style == "逃げ":
                return {"p1": 1.04, "p2": 0.98, "p3": 0.95}
            elif style == "先行":
                return {"p1": 1.02, "p2": 1.01, "p3": 0.99}
            elif style == "差し":
                return {"p1": 0.97, "p2": 1.00, "p3": 1.05}
            else:  # 追込
                return {"p1": 0.93, "p2": 0.96, "p3": 1.04}

    def get_frame_modifier(
        self, venue: str, track: str, dist: int, frame: int
    ) -> float:
        """枠順(1-8枠) 3着以内率補正"""
        if frame < 1 or frame > 8:
            return 1.0

        if venue == "新潟" and dist == 1000 and track == "芝":
            if frame in [7, 8]:
                return 1.18
            elif frame in [1, 2]:
                return 0.82
        elif track == "ダート" and dist == 1000:
            if frame in [7, 8]:
                return 1.12
            elif frame in [1, 2]:
                return 0.88

        if venue == "中京" and frame in [1, 2]:
            return 1.06

        if track == "ダート" and frame in [7, 8]:
            return 1.04

        return 1.0

    def get_jockey_modifier(self, jockey: str) -> float:
        """騎手データに基づく補正"""
        if not jockey or jockey == "その他":
            return 1.0

        if "ルメール" in jockey or "川田" in jockey:
            return 1.10
        elif any(
            j in jockey
            for j in ["戸崎", "松山", "武豊", "坂井", "横山武", "岩田望"]
        ):
            return 1.05
        elif any(
            j in jockey
            for j in [
                "鮫島克",
                "西村淳",
                "丹内",
                "横山和",
                "菅原明",
                "団野",
                "三浦",
                "津村",
            ]
        ):
            return 1.02
        return 1.0

    def adjust_probabilities(
        self, race_info: dict, horse: dict, rank: int
    ) -> dict[str, float]:
        """
        【出走頭数考慮型モデル】市場効率性を尊重したShrinkage（オッズ回帰）確率算出
        """
        odds = float(horse["odds"])
        mark = int(horse["mark"])
        style = horse["style"]
        frame = int(horse.get("frame", 4))
        jockey = str(horse.get("jockey", "その他"))
        total_horses = int(race_info.get("total_horses", 16))

        # 1. 単勝オッズからの市場事前勝率（JRA控除率20%を考慮した市場確率）
        market_p1 = min(max(0.80 / odds, 0.001), 0.85)

        base = self.get_base_probabilities(odds, total_horses)
        p1, p2, p3 = base["p1"], base["p2"], base["p3"]

        # 2. 印による補正
        if mark == 4:
            p1 *= 1.08
            p2 *= 1.04
        elif mark == 3:
            p2 *= 1.05
            p3 *= 1.05
        elif mark == 2:
            # 1着確率0%固定。1着確率の約30%分のみを2着(60%)・3着(40%)に分配
            p2 += p1 * 0.30
            p3 += p1 * 0.20
            p1 = 0.0

        # 3. 各種条件マルチプライヤーの加算型平滑化
        venue_mod = self.get_venue_style_modifier(
            race_info["venue"], race_info["track"], style
        ) - 1.0
        class_mod = self.get_class_style_modifier(
            race_info.get("race_class", "1勝/2勝/3勝クラス"), style
        ) - 1.0
        dist_mod = self.get_distance_style_modifier(
            race_info["track"], race_info["dist"], style
        ) - 1.0
        frame_mod = self.get_frame_modifier(
            race_info["venue"], race_info["track"], race_info["dist"], frame
        ) - 1.0
        jockey_mod = self.get_jockey_modifier(jockey) - 1.0

        pace = race_info.get("pace", "ミドル")
        pace_mod = 0.0
        if pace == "ハイ":
            pace_mod = -0.04 if style in ["逃げ", "先行"] else 0.05
        elif pace == "スロー":
            pace_mod = 0.05 if style in ["逃げ", "先行"] else -0.04

        condition = race_info.get("condition", "良")
        cond_mod = 0.0
        if race_info["track"] == "ダート" and condition in ["重", "不良"]:
            if style in ["逃げ", "先行"]:
                cond_mod = 0.04

        # 全条件の合成補正（上限+12%, 下限-12%に制限）
        sum_mod = venue_mod + class_mod + dist_mod + frame_mod + jockey_mod + pace_mod + cond_mod
        clipped_mod = 1.0 + max(min(sum_mod, 0.12), -0.12)

        pos_mods = self.get_track_style_position_modifier(
            race_info["track"], style
        )

        raw_p1 = p1 * clipped_mod * pos_mods["p1"]
        raw_p2 = p2 * clipped_mod * pos_mods["p2"]
        raw_p3 = p3 * clipped_mod * pos_mods["p3"]

        # 4. 市場オッズ確率への強力なベイズ回帰 (Shrinkage: 市場75%, モデル25%)
        if mark == 2:
            final_p1 = 0.0
        else:
            final_p1 = 0.75 * market_p1 + 0.25 * raw_p1

        final_p2 = 0.75 * (market_p1 * 0.65) + 0.25 * raw_p2
        final_p3 = 0.75 * (market_p1 * 0.50) + 0.25 * raw_p3

        return {
            "p1": final_p1,
            "p2": final_p2,
            "p3": final_p3,
        }

    def generate_strategy(
        self, race_info: dict, horses: list[dict]
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """買い目データと頭数考慮型確率の生成"""
        sorted_horses = sorted(horses, key=lambda x: float(x["odds"]))
        for idx, h in enumerate(sorted_horses):
            h["probs"] = self.adjust_probabilities(race_info, h, rank=idx + 1)

        wide_bets, umaren_bets, umatan_bets = [], [], []

        axes = [h for h in horses if int(h["mark"]) in [3, 4]]
        num_axes = len(axes)

        # 1. ワイド
        for ax in axes:
            opponents = [h for h in horses if int(h["no"]) != int(ax["no"])]
            for op in opponents:
                p_top3_ax = ax["probs"]["p1"] + ax["probs"]["p2"] + ax["probs"]["p3"]
                p_top3_op = op["probs"]["p1"] + op["probs"]["p2"] + op["probs"]["p3"]

                p_wide = min(p_top3_ax * (p_top3_op / max(1.8 - 0.4 * p_top3_ax, 0.8)), 0.45)
                est_wide_odds = max(round(0.775 / max(p_wide, 1e-4), 1), 1.5)
                w_pair = sorted([int(ax["no"]), int(op["no"])])
                wide_bets.append(
                    {
                        "券種": "ワイド",
                        "買い目": f"{w_pair[0]} - {w_pair[1]}",
                        "オッズ": est_wide_odds,
                        "prob": p_wide,
                    }
                )

        # 2. 馬連 (軸2頭以上の時に推奨)
        if num_axes >= 2:
            for i in range(len(axes)):
                for j in range(i + 1, len(axes)):
                    ax1, ax2 = axes[i], axes[j]
                    p1_1, p2_1 = ax1["probs"]["p1"], ax1["probs"]["p2"]
                    p1_2, p2_2 = ax2["probs"]["p1"], ax2["probs"]["p2"]
                    
                    denom1 = max(1.0 - p2_1, 0.2)
                    denom2 = max(1.0 - p2_2, 0.2)
                    p_umaren = (p1_1 * (p2_2 / denom1)) + (p1_2 * (p2_1 / denom2))
                    p_umaren = min(p_umaren, 0.25)
                    est_umaren_odds = max(round(0.775 / max(p_umaren, 1e-4), 1), 2.5)
                    pair = sorted([int(ax1["no"]), int(ax2["no"])])
                    umaren_bets.append(
                        {
                            "券種": "馬連",
                            "買い目": f"{pair[0]} - {pair[1]}",
                            "オッズ": est_umaren_odds,
                            "prob": p_umaren,
                        }
                    )
            for ax in axes:
                opponents = [h for h in horses if int(h["mark"]) in [1, 2]]
                for op in opponents:
                    p1_ax, p2_ax = ax["probs"]["p1"], ax["probs"]["p2"]
                    p1_op, p2_op = op["probs"]["p1"], op["probs"]["p2"]
                    
                    denom_ax = max(1.0 - p2_ax, 0.2)
                    denom_op = max(1.0 - p2_op, 0.2)
                    p_umaren = (p1_ax * (p2_op / denom_ax)) + (p1_op * (p2_ax / denom_op))
                    p_umaren = min(p_umaren, 0.25)
                    est_umaren_odds = max(round(0.775 / max(p_umaren, 1e-4), 1), 2.5)
                    pair = sorted([int(ax["no"]), int(op["no"])])
                    umaren_bets.append(
                        {
                            "券種": "馬連",
                            "買い目": f"{pair[0]} - {pair[1]}",
                            "オッズ": est_umaren_odds,
                            "prob": p_umaren,
                        }
                    )

        # 3. 馬単 (軸1頭の時に推奨)
        if num_axes == 1:
            ax = axes[0]
            opponents = [h for h in horses if int(h["no"]) != int(ax["no"])]
            for op in opponents:
                p1_ax = ax["probs"]["p1"]
                p2_op = op["probs"]["p2"]
                
                denom_ax = max(1.0 - ax["probs"]["p2"], 0.2)
                p_umatan = p1_ax * (p2_op / denom_ax)
                p_umatan = min(p_umatan, 0.20)
                if p_umatan > 0:
                    est_umatan_odds = max(
                        round(0.750 / max(p_umatan, 1e-4), 1), 3.0
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

        return wide_bets, umaren_bets, umatan_bets

    def allocate_budget(
        self, bets: list[dict], mode: str, custom_budget: int = None
    ) -> pd.DataFrame:
        """資金配分アルゴリズム"""
        target_budget = custom_budget if custom_budget is not None else self.budget
        if not bets or target_budget <= 0:
            return pd.DataFrame()

        if mode == "dutching":
            sum_inv = sum(1.0 / max(b["オッズ"], 1.0) for b in bets)
            if sum_inv == 0:
                return pd.DataFrame()
            weights = [(1.0 / max(b["オッズ"], 1.0)) / sum_inv for b in bets]
        else:
            ev_list = [b["prob"] * b["オッズ"] for b in bets]
            sum_ev = sum(ev_list)
            if sum_ev <= 0:
                weights = [1.0 / len(bets)] * len(bets)
            else:
                weights = [ev / sum_ev for ev in ev_list]

        allocated_total = 0
        results = []
        for b, w in zip(bets, weights):
            raw_val = target_budget * w
            amount = math.floor(raw_val / 100) * 100
            results.append({**b, "購入額": amount, "_rem": raw_val - amount})
            allocated_total += amount

        rem_budget = int((target_budget - allocated_total) // 100)
        results.sort(key=lambda x: x["_rem"], reverse=True)
        for i in range(min(rem_budget, len(results))):
            results[i]["購入額"] += 100

        df = pd.DataFrame(results)
        df["期待値(EV)"] = (df["prob"] * df["オッズ"]).round(2)
        df["想定払戻金"] = (df["購入額"] * df["オッズ"]).astype(int)
        df["想定回収率"] = (
            (df["想定払戻金"] / target_budget) * 100
        ).map("{:.1f}%".format)

        return df[
            [
                "券種",
                "買い目",
                "オッズ",
                "期待値(EV)",
                "購入額",
                "想定払戻金",
                "想定回収率",
                "prob",
            ]
        ]


# =========================================================
# 2. Streamlit UI 画面構築
# =========================================================

st.set_page_config(
    page_title="競馬傾斜買い計算機", page_icon="🏇", layout="wide"
)

st.title("🏇 競馬オッズ・ベイズ傾斜買い計算アプリ (頭数考慮モデル搭載)")
st.caption(
    "出走頭数(5〜18頭)×市場オッズ集積知のベイズ回帰 | 期待値上振れを徹底防衛した現実的資金配分"
)

# サイドバー設定
st.sidebar.header("⚙️ レース条件設定")

total_budget = st.sidebar.number_input(
    "総予算 (円)", min_value=1000, max_value=500000, value=10000, step=1000
)

total_horses = st.sidebar.number_input(
    "出走頭数 (頭)", min_value=5, max_value=18, value=16, step=1,
    help="レース全体の頭数を設定します（頭数に応じて人気順の着順確率や配分が調整されます）"
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

# メインエリア: 馬情報の入力
st.subheader("🐴 対象馬情報の入力")
st.markdown(
    """
**【印の定義と使い方】**  
- **4**: 超本命（軸馬） | **3**: 本命（軸馬） | **2**: 相手/ヒモ（**1着確率0%固定**） | **1**: 大穴  
💡 **不要な馬**は馬番を「**0**」にするか、ゴミ箱アイコンで削除してください。  
💡 下記の理論オッズ生成後、JRAの**実際のリアルタイムオッズに書き換える**ことで高精度な配分が計算されます！
"""
)

default_data = pd.DataFrame(
    [
        {"no": 1, "frame": 1, "mark": 3, "style": "逃げ", "jockey": "Ｃ．ルメール", "odds": 2.2},
        {"no": 3, "frame": 2, "mark": 2, "style": "先行", "jockey": "戸崎圭太", "odds": 5.8},
        {"no": 5, "frame": 3, "mark": 2, "style": "差し", "jockey": "川田将雅", "odds": 8.5},
    ]
)

jockey_options = [
    "Ｃ．ルメール",
    "川田将雅",
    "戸崎圭太",
    "松山弘平",
    "武豊",
    "坂井瑠星",
    "横山武史",
    "岩田望来",
    "鮫島克駿",
    "西村淳也",
    "丹内祐次",
    "横山和生",
    "菅原明良",
    "団野大成",
    "三浦皇成",
    "津村明秀",
    "その他",
]

edited_df = st.data_editor(
    default_data,
    num_rows="dynamic",
    column_config={
        "no": st.column_config.NumberColumn(
            "馬番 (0で無視)", min_value=0, max_value=18, step=1, required=True
        ),
        "frame": st.column_config.NumberColumn(
            "枠順 (1-8)", min_value=1, max_value=8, step=1, required=True
        ),
        "mark": st.column_config.SelectboxColumn(
            "印",
            options=[4, 3, 2, 1],
            help="4:超本命, 3:本命軸, 2:1着なし2-3着, 1:大穴",
            required=True,
        ),
        "style": st.column_config.SelectboxColumn(
            "脚質",
            options=["逃げ", "先行", "差し", "追込"],
            required=True,
        ),
        "jockey": st.column_config.SelectboxColumn(
            "騎手",
            options=jockey_options,
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
    # キャッシュされた編集表キーを消去して最新計算データで画面強制更新
    for k in ["combined_editor", "wide_editor", "umaren_editor", "umatan_editor"]:
        if k in st.session_state:
            del st.session_state[k]

    raw_horses_list = edited_df.to_dict(orient="records")

    horses_list = [
        h for h in raw_horses_list 
        if h.get("no") is not None and int(h.get("no", 0)) > 0
    ]

    race_info = {
        "venue": venue,
        "track": track,
        "dist": dist,
        "weather": weather,
        "condition": condition,
        "pace": pace,
        "race_class": race_class,
        "total_horses": total_horses,
    }

    has_axis = any(int(h["mark"]) in [3, 4] for h in horses_list)
    if not has_axis:
        st.error(
            "⚠️ 軸馬（印「4」または「3」）を少なくとも1頭指定してください。"
        )
    elif len(horses_list) < 2:
        st.error("⚠️ 計算対象となる馬（馬番1以上）を2頭以上入力してください。")
    else:
        optimizer = UltimateHorseRaceOptimizer(budget=total_budget)
        wide_raw, umaren_raw, umatan_raw = optimizer.generate_strategy(
            race_info, horses_list
        )

        st.session_state["wide_raw"] = wide_raw
        st.session_state["umaren_raw"] = umaren_raw
        st.session_state["umatan_raw"] = umatan_raw
        st.session_state["calculated"] = True

if st.session_state.get("calculated", False):
    optimizer = UltimateHorseRaceOptimizer(budget=total_budget)

    st.divider()
    st.subheader("📊 資金配分シミュレーション＆オッズ調整")

    raw_horses_list = edited_df.to_dict(orient="records")
    horses_list = [h for h in raw_horses_list if h.get("no") is not None and int(h.get("no", 0)) > 0]
    num_axes_input = len([h for h in horses_list if int(h.get("mark", 0)) in [3, 4]])

    if num_axes_input == 1:
        st.info(f"💡 **【軸1頭戦略 / {total_horses}頭立て】**: 軸馬が1頭のため、**「馬単（1着固定）」＋「ワイド」**の構成で買い目を自動生成しました。")
    elif num_axes_input >= 2:
        st.info(f"💡 **【軸{num_axes_input}頭マルチ戦略 / {total_horses}頭立て】**: 軸馬が複数頭のため、1着取りこぼしを防ぐ**「馬連（軸同士・軸相手）」＋「ワイド」**の構成で買い目を自動生成しました。")

    tab_combined, tab1, tab2, tab3 = st.tabs(
        [
            "🎯 【推参・複合ポートフォリオ】ミックス配分",
            "🛡️ 【単一】ワイド (ダッチング/均等払戻)",
            "⚖️ 【単一】馬連 (軸2頭以上時に自動推奨)",
            "🔥 【単一】馬単 (軸1頭時に自動推奨)",
        ]
    )

    wide_raw = st.session_state.get("wide_raw", [])
    umaren_raw = st.session_state.get("umaren_raw", [])
    umatan_raw = st.session_state.get("umatan_raw", [])

    # タブ0: 複合ポートフォリオ
    with tab_combined:
        st.markdown("#### 🎯 券種ミックス複合ポートフォリオ（推奨リスク分散戦略）")

        st.markdown("##### ⚙️ 券種ごとの資金配分比率（合計 100%）")
        col_r1, col_r2, col_r3 = st.columns(3)
        with col_r1:
            ratio_wide = st.slider("ワイド配分比率 (%)", 0, 100, 50 if num_axes_input == 1 else 40, step=5)
        with col_r2:
            ratio_umaren = st.slider("馬連配分比率 (%)", 0, 100, 0 if num_axes_input == 1 else 60, step=5)
        with col_r3:
            ratio_umatan = st.slider("馬単配分比率 (%)", 0, 100, 50 if num_axes_input == 1 else 0, step=5)

        b_wide = int(total_budget * (ratio_wide / 100.0))
        b_umaren = int(total_budget * (ratio_umaren / 100.0))
        b_umatan = int(total_budget * (ratio_umatan / 100.0))

        combined_list = []
        for b in wide_raw:
            combined_list.append({**b, "type_sort": 1})
        for b in umaren_raw:
            combined_list.append({**b, "type_sort": 2})
        for b in umatan_raw:
            combined_list.append({**b, "type_sort": 3})

        if combined_list:
            df_combined_input = pd.DataFrame(combined_list)[["券種", "買い目", "オッズ", "prob", "type_sort"]]
            
            st.markdown("##### 📝 全買い目・オッズ編集（JRA実オッズ入力）")
            edited_combined = st.data_editor(
                df_combined_input,
                column_config={
                    "券種": st.column_config.TextColumn("券種", disabled=True),
                    "買い目": st.column_config.TextColumn("買い目", disabled=True),
                    "オッズ": st.column_config.NumberColumn(
                        "オッズ (手入力可)", min_value=1.1, max_value=999.9, step=0.1, format="%.1f"
                    ),
                    "prob": None,
                    "type_sort": None,
                },
                key="combined_editor",
                use_container_width=True,
            )

            updated_combined_bets = edited_combined.to_dict(orient="records")
            
            c_wide_bets = [b for b in updated_combined_bets if b["券種"] == "ワイド"]
            c_umaren_bets = [b for b in updated_combined_bets if b["券種"] == "馬連"]
            c_umatan_bets = [b for b in updated_combined_bets if b["券種"] == "馬単"]

            df_res_wide = optimizer.allocate_budget(c_wide_bets, mode="dutching", custom_budget=b_wide) if b_wide > 0 else pd.DataFrame()
            df_res_umaren = optimizer.allocate_budget(c_umaren_bets, mode="kelly", custom_budget=b_umaren) if b_umaren > 0 else pd.DataFrame()
            df_res_umatan = optimizer.allocate_budget(c_umatan_bets, mode="kelly", custom_budget=b_umatan) if b_umatan > 0 else pd.DataFrame()

            df_mix_final = pd.concat([df_res_wide, df_res_umaren, df_res_umatan], ignore_index=True)

            if not df_mix_final.empty:
                max_mix_ev = df_mix_final["期待値(EV)"].max()
                
                if max_mix_ev < 1.0:
                    st.error(
                        "⚠️ **【見送り推奨】数学的に買わない方が得です（購入すると損をする可能性が高いです）。**"
                    )
                    st.caption(
                        f"※理由: {total_horses}頭立ての厳格ベイズ試算において全買い目の最高期待値(EV)が1.0未満（JRA控除率の壁を越える構造的優位性なし）のため、購入すると長期的に損失を出す可能性が極めて高いです。"
                    )
                else:
                    st.success(
                        "✅ **【購入推奨】プラス期待値（EV ≥ 1.0）の優位性ある買い目が含まれています。**"
                    )

                st.markdown("##### 📊 最終マルチ資金配分表")
                st.dataframe(df_mix_final.drop(columns=["prob"]), use_container_width=True)

                col_m1, col_m2 = st.columns(2)
                with col_m1:
                    total_allocated = df_mix_final["購入額"].sum()
                    st.metric("総購入予定額", f"{total_allocated:,} 円", delta=f"予算 {total_budget:,} 円")
                with col_m2:
                    max_payout = df_mix_final["想定払戻金"].max()
                    st.metric("最大想定払戻金 (跳ね時)", f"{max_payout:,} 円", delta=f"最高回収率 {max_payout / total_budget * 100:.1f}%")

    # タブ1: ワイド
    with tab1:
        st.markdown("#### ワイド単一買い（均等払戻ダッチング配分）")
        if wide_raw:
            df_wide_input = pd.DataFrame(wide_raw)[["券種", "買い目", "オッズ", "prob"]]
            edited_wide = st.data_editor(
                df_wide_input,
                column_config={
                    "オッズ": st.column_config.NumberColumn(
                        "オッズ (編集可能)", min_value=1.1, max_value=999.9, step=0.1, format="%.1f"
                    ),
                    "prob": None,
                },
                disabled=["券種", "買い目"],
                key="wide_editor",
                use_container_width=True,
            )
            
            updated_wide_bets = edited_wide.to_dict(orient="records")
            df_wide = optimizer.allocate_budget(updated_wide_bets, mode="dutching")

            max_ev_wide = df_wide["期待値(EV)"].max()
            min_ret = df_wide["想定払戻金"].min()

            if max_ev_wide < 1.0 or min_ret < total_budget:
                st.error(
                    "⚠️ **【見送り推奨】数学的に買わない方が得です（購入すると損をする可能性が高いです）。**"
                )
                st.caption(
                    "※理由: 最高期待値(EV)が1.0未満、または的中しても回収率100%未満（トリガミ）となります。"
                )
            else:
                st.success(
                    "✅ **【購入推奨】十分な期待値と元本保証ラインが確保されています。**"
                )

            st.dataframe(df_wide.drop(columns=["prob"]), use_container_width=True)
            st.metric(
                label="的中時 最小想定払戻金",
                value=f"{min_ret:,} 円",
                delta=f"回収率 {min_ret / total_budget * 100:.1f}%",
            )
        else:
            st.warning("条件に該当するワイドの買い目がありません。")

    # タブ2: 馬連
    with tab2:
        st.markdown("#### 馬連単一買い（期待値ケリー傾斜配分）")
        if umaren_raw:
            df_umaren_input = pd.DataFrame(umaren_raw)[["券種", "買い目", "オッズ", "prob"]]
            edited_umaren = st.data_editor(
                df_umaren_input,
                column_config={
                    "オッズ": st.column_config.NumberColumn(
                        "オッズ (編集可能)", min_value=1.1, max_value=999.9, step=0.1, format="%.1f"
                    ),
                    "prob": None,
                },
                disabled=["券種", "買い目"],
                key="umaren_editor",
                use_container_width=True,
            )

            updated_umaren_bets = edited_umaren.to_dict(orient="records")
            df_umaren = optimizer.allocate_budget(updated_umaren_bets, mode="kelly")

            max_ev_umaren = df_umaren["期待値(EV)"].max()

            if max_ev_umaren < 1.0:
                st.error(
                    "⚠️ **【見送り推奨】数学的に買わない方が得です（購入すると損をする可能性が高いです）。**"
                )
                st.caption(
                    "※理由: 買い目全体の最高期待値(EV)が1.0未満のため、賭け続けると理論上マイナス収支になります。"
                )
            else:
                st.success(
                    "✅ **【購入推奨】プラス期待値（EV ≥ 1.0）の買い目が含まれています。**"
                )

            st.dataframe(df_umaren.drop(columns=["prob"]), use_container_width=True)
            max_ret = df_umaren["想定払戻金"].max()
            st.metric(
                label="最大想定払戻金",
                value=f"{max_ret:,} 円",
                delta=f"最高回収率 {max_ret / total_budget * 100:.1f}%",
            )
        else:
            st.warning("条件に該当する馬連の買い目がありません。")

    # タブ3: 馬単
    with tab3:
        st.markdown("#### 馬単単一買い（「印2＝1着0%」傾斜配分）")
        if umatan_raw:
            df_umatan_input = pd.DataFrame(umatan_raw)[["券種", "買い目", "オッズ", "prob"]]
            edited_umatan = st.data_editor(
                df_umatan_input,
                column_config={
                    "オッズ": st.column_config.NumberColumn(
                        "オッズ (編集可能)", min_value=1.1, max_value=999.9, step=0.1, format="%.1f"
                    ),
                    "prob": None,
                },
                disabled=["券種", "買い目"],
                key="umatan_editor",
                use_container_width=True,
            )

            updated_umatan_bets = edited_umatan.to_dict(orient="records")
            df_umatan = optimizer.allocate_budget(updated_umatan_bets, mode="kelly")

            max_ev_umatan = df_umatan["期待値(EV)"].max()

            if max_ev_umatan < 1.0:
                st.error(
                    "⚠️ **【見送り推奨】数学的に買わない方が得です（購入すると損をする可能性が高いです）。**"
                )
                st.caption(
                    "※理由: 1着0%切り補正を行っても最高期待値(EV)が1.0未満のため、見送りを推奨します。"
                )
            else:
                st.success(
                    "✅ **【購入推奨】高回収率を狙える高期待値（EV ≥ 1.0）の買い目です。**"
                )

            st.dataframe(df_umatan.drop(columns=["prob"]), use_container_width=True)
            max_ret = df_umatan["想定払戻金"].max()
            st.metric(
                label="最大想定払戻金",
                value=f"{max_ret:,} 円",
                delta=f"最高回収率 {max_ret / total_budget * 100:.1f}%",
            )
        else:
            st.warning("条件に該当する馬単の買い目がありません。")
