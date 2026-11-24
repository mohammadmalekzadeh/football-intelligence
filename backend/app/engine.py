from __future__ import annotations

import os
import psycopg
from dotenv import load_dotenv
from pathlib import Path
import json
import math
import joblib
import numpy as np
import pandas as pd
from scipy.stats import skellam, poisson
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score, mean_absolute_error, mean_squared_error, accuracy_score, f1_score, log_loss
from xgboost import XGBRegressor

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
DATA_PATH = ROOT / "data" / "football_data_wide_normalized.xlsx"
MODEL_DIR = ROOT / "models"
MODEL_DIR.mkdir(exist_ok=True)
EPS = 1e-6

COLS = {
    "season":"فصل", "week":"هفته", "team":"تیم_ID", "opp":"حریف_ID",
    "xg":"عدد تیم_امید گل", "shots":"عدد تیم_شوت", "sot":"عدد تیم_شوت در چارچوب",
    "poss":"عدد تیم_مالکیت توپ", "duels":"عدد تیم_موفقيت در نبردها", "metrica":"عدد تیم_نمره متریکا",
    "goals":"عدد تیم_گل", "opp_xg":"عدد حریف_امید گل", "opp_shots":"عدد حریف_شوت",
    "opp_sot":"عدد حریف_شوت در چارچوب", "opp_poss":"عدد حریف_مالکیت توپ",
    "opp_duels":"عدد حریف_موفقيت در نبردها", "opp_metrica":"عدد حریف_نمره متریکا", "opp_goals":"عدد حریف_گل",
}
BASE = ["xg_for","xg_against","shots_for","shots_against","sot_for","sot_against",
        "goals_for","goals_against","possession_for","duels_success_for","metrica_for"]


def load_data_xlsx() -> pd.DataFrame:
    df = pd.read_excel(DATA_PATH)
    rename = {v:k for k,v in COLS.items()}
    df = df.rename(columns=rename)
    # The supplied workbook is normalized. Goal columns are quantized in steps of 1/7.
    # Convert them back to goal counts for Poisson/XGBoost target interpretation.
    for c in ["season","week","team","opp"]:
        df[c] = df[c].astype(int)
    for c in ["xg","shots","sot","poss","duels","metrica","opp_xg","opp_shots","opp_sot","opp_poss","opp_duels","opp_metrica"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["goals","opp_goals"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    max_goal = max(float(df["goals"].max()), float(df["opp_goals"].max()))
    goal_values = np.sort(df["goals"].dropna().unique())
    steps = np.diff(goal_values)
    if max_goal <= 1.0 + 1e-9 and len(steps) and np.allclose(steps, steps[0]) and np.isclose(steps[0], 1/7, atol=1e-5):
        df["goals_for"] = np.rint(df["goals"] * 7).astype(int)
        df["goals_against"] = np.rint(df["opp_goals"] * 7).astype(int)
        goal_scale = 7
    else:
        df["goals_for"] = np.rint(df["goals"]).astype(int)
        df["goals_against"] = np.rint(df["opp_goals"]).astype(int)
        goal_scale = 1
    df = df.rename(columns={"season":"season","week":"week","team":"team_id","opp":"opponent_id",
                           "xg":"xg_for","shots":"shots_for","sot":"sot_for","poss":"possession_for",
                           "duels":"duels_success_for","metrica":"metrica_for",
                           "opp_xg":"xg_against","opp_shots":"shots_against","opp_sot":"sot_against",
                           "opp_poss":"possession_against","opp_duels":"duels_success_against","opp_metrica":"metrica_against"})
    df["result_wdl"] = np.select([df.goals_for > df.goals_against, df.goals_for < df.goals_against],["W","L"],default="D")
    df.attrs["goal_scale"] = goal_scale
    return df

_DATA = None

_INT_COLS = ["season", "week", "team_id", "opponent_id", "goals_for", "goals_against"]
_DB_COLS = [
    "season", "week", "team_id", "opponent_id",
    "xg_for", "shots_for", "sot_for", "possession_for",
    "duels_success_for", "metrica_for", "goals_for",
    "xg_against", "shots_against", "sot_against", "possession_against",
    "duels_success_against", "metrica_against", "goals_against",
]


def load_data() -> pd.DataFrame:
    """Load matches from PostgreSQL once; later calls reuse the in-memory copy."""
    global _DATA
    if _DATA is not None:
        return _DATA
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            f"select {', '.join(_DB_COLS)} from public.team_matches "
            "order by season, week, team_id"
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=_DB_COLS)
    for c in _INT_COLS:
        df[c] = df[c].astype(int)
    for c in _DB_COLS:
        if c not in _INT_COLS:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["result_wdl"] = np.select(
        [df.goals_for > df.goals_against, df.goals_for < df.goals_against],
        ["W", "L"],
        default="D",
    )
    df.attrs["goal_scale"] = 7
    _DATA = df
    return _DATA

def add_prematch_features(df: pd.DataFrame, min_prev: int = 5) -> pd.DataFrame:
    d = df.sort_values(["team_id","season","week"]).copy()
    stat_cols = BASE
    for w in (3,5):
        for c in stat_cols:
            d[f"avg_{c}_last_{w}"] = d.groupby("team_id")[c].transform(lambda s: s.shift(1).rolling(w, min_periods=1).mean())
            d[f"std_{c}_last_{w}"] = d.groupby("team_id")[c].transform(lambda s: s.shift(1).rolling(w, min_periods=2).std())
    d["sot_rate_for"] = d["sot_for"]/(d["shots_for"]+1.0)
    d["xg_per_shot_for"] = d["xg_for"]/(d["shots_for"]+1.0)
    for w in (3,5):
        d[f"avg_sot_rate_for_last_{w}"] = d.groupby("team_id")["sot_rate_for"].transform(lambda s:s.shift(1).rolling(w,min_periods=1).mean())
        d[f"avg_xg_per_shot_for_last_{w}"] = d.groupby("team_id")["xg_per_shot_for"].transform(lambda s:s.shift(1).rolling(w,min_periods=1).mean())
    d["league_avg_xg_for_last_5"] = d.groupby(["season","week"])["avg_xg_for_last_5"].transform("mean")
    d["league_avg_xg_against_last_5"] = d.groupby(["season","week"])["avg_xg_against_last_5"].transform("mean")
    d["attack_strength_5"] = d["avg_xg_for_last_5"]/(d["league_avg_xg_for_last_5"]+EPS)
    d["defense_strength_5"] = d["avg_xg_against_last_5"]/(d["league_avg_xg_against_last_5"]+EPS)
    rolling_cols = [c for c in d.columns if c.startswith("avg_") or c.startswith("std_") or c in ["attack_strength_5","defense_strength_5"]]
    opp = d[["season","week","team_id"]+rolling_cols].copy().rename(columns={"team_id":"opponent_id"})
    opp = opp.rename(columns={c:f"{c}_opp" for c in rolling_cols})
    d = d.merge(opp,on=["season","week","opponent_id"],how="left")
    for a,b in [("attack_strength_5","attack_strength_5_opp"),("defense_strength_5","defense_strength_5_opp"),
                ("avg_xg_for_last_5","avg_xg_for_last_5_opp"),("avg_goals_for_last_5","avg_goals_for_last_5_opp"),
                ("avg_shots_for_last_5","avg_shots_for_last_5_opp"),("avg_xg_per_shot_for_last_5","avg_xg_per_shot_for_last_5_opp")]:
        d[f"delta_{a}"] = d[a]-d[b]
    d["n_prev_matches"] = d.groupby("team_id").cumcount()
    opp_prev = d[["season","week","team_id","n_prev_matches"]].rename(columns={"team_id":"opponent_id","n_prev_matches":"n_prev_matches_opp"})
    d = d.merge(opp_prev,on=["season","week","opponent_id"],how="left")
    d = d.sort_values(["season","week","team_id"]).reset_index(drop=True)
    ready = d[(d.n_prev_matches>=min_prev)&(d.n_prev_matches_opp>=min_prev)].copy()
    return ready


def safe_features(df: pd.DataFrame) -> list[str]:
    prefixes=("avg_","std_","attack_strength","defense_strength","league_avg_","delta_","n_prev_matches")
    cols=[]
    for c in df.columns:
        if c in {"goals_for","goals_against","team_id","opponent_id","result_wdl"}: continue
        if c.startswith(prefixes) and "match" not in c and pd.api.types.is_numeric_dtype(df[c]): cols.append(c)
    for c in ("season","week"):
        if c in df.columns: cols.append(c)
    return sorted(set(cols))


def train_models():
    raw=load_data_xlsx()
    prem=add_prematch_features(raw)
    X_cols=safe_features(prem)
    train=prem[prem.season<prem.season.max()].copy()
    test=prem[prem.season==prem.season.max()].copy()
    X_train=train[X_cols].replace([np.inf,-np.inf],np.nan).fillna(0)
    X_test=test[X_cols].replace([np.inf,-np.inf],np.nan).fillna(0)
    models={}
    evals={}
    for target,name in [("goals_for","goals_for"),("goals_against","goals_against")]:
        m=XGBRegressor(n_estimators=350,max_depth=4,learning_rate=0.035,subsample=0.85,colsample_bytree=0.9,
                       objective="count:poisson",eval_metric="poisson-nloglik",random_state=42,n_jobs=2)
        m.fit(X_train,train[target])
        pred=m.predict(X_test)
        evals[name]={"MAE":float(mean_absolute_error(test[target],pred)),"RMSE":float(mean_squared_error(test[target],pred)**0.5)}
        joblib.dump(m,MODEL_DIR/f"xgb_{name}.joblib")
        models[name]=m
    # Tactical model: exact thesis mapping C2 offensive, C1 transitional, C0 conservative, C3 balanced.
    style_cols=["possession_for","shots_for","sot_rate_for","xg_per_shot_for","metrica_for","duels_success_for"]
    s=raw.copy()
    s["sot_rate_for"]=s.sot_for/(s.shots_for+1.0)
    s["xg_per_shot_for"]=s.xg_for/(s.shots_for+1.0)
    g=s.groupby(["season","team_id"])[style_cols]
    style=pd.concat([g.mean().add_suffix("_mean"),g.std(ddof=0).fillna(0).add_suffix("_std")],axis=1).reset_index()
    feat=[c for c in style.columns if c not in ["season","team_id"]]
    scaler=StandardScaler(); Xz=scaler.fit_transform(style[feat])
    km=KMeans(n_clusters=4,n_init=50,random_state=42).fit(Xz)
    style["cluster"]=km.labels_
    joblib.dump(scaler,MODEL_DIR/"tactical_scaler.joblib")
    joblib.dump(km,MODEL_DIR/"tactical_kmeans.joblib")
    style.to_csv(MODEL_DIR/"team_style_vectors.csv",index=False)
    cent=scaler.inverse_transform(km.cluster_centers_)
    cent_df=pd.DataFrame(cent,columns=feat); cent_df.insert(0,"cluster",range(4)); cent_df.to_csv(MODEL_DIR/"cluster_centroids.csv",index=False)
    sil=float(silhouette_score(Xz,km.labels_))
    # Derive W/D/L from test-season predictions for a transparent offline check.
    p_for=models["goals_for"].predict(X_test); p_against=models["goals_against"].predict(X_test)
    p_for=np.clip(p_for,0,None); p_against=np.clip(p_against,0,None)
    pD = skellam.pmf(0, p_for, p_against)
    pW = skellam.sf(0, p_for, p_against)
    pL = skellam.cdf(-1, p_for, p_against)
    # Column order must match labels order expected by log_loss (lexicographic: D, L, W).
    labels = ["D", "L", "W"]
    probs = np.vstack([pD, pL, pW]).T
    probs = probs / np.clip(probs.sum(1, keepdims=True), EPS, None)
    pred_lbl = np.array(labels)[probs.argmax(1)]
    true_lbl = np.where(
        test.goals_for > test.goals_against,
        "W",
        np.where(test.goals_for < test.goals_against, "L", "D"),
    )
    evals["wdl"] = {
        "accuracy": float(accuracy_score(true_lbl, pred_lbl)),
        "f1_macro": float(
            f1_score(true_lbl, pred_lbl, labels=labels, average="macro")
        ),
        "log_loss": float(log_loss(true_lbl, probs, labels=labels)),
    }
    (MODEL_DIR/"evaluation.json").write_text(json.dumps(evals,ensure_ascii=False,indent=2),encoding="utf-8")
    meta={"x_features":X_cols,"train_seasons":sorted(train.season.unique().tolist()),"test_season":int(test.season.max()),
          "goal_scale":int(raw.attrs.get("goal_scale",1)),"tactical_cluster_map":{"0":"conservative","1":"transitional","2":"offensive","3":"balanced"},
          "tactical_labels_fa":{"conservative":"محافظه‌کار","transitional":"انتقالی","offensive":"تهاجمی","balanced":"متعادل"},"silhouette":sil,"evaluation":evals}
        #   "tactical_labels_fa":{"conservative":"conservative","transitional":"transitional","offensive":"transitional","balanced":"balanced"},"silhouette":sil,"evaluation":evals}
    (MODEL_DIR/"metadata.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    prem.to_pickle(MODEL_DIR/"prematch_features.pkl")
    return meta


_BUNDLE = None


def load_bundle():
    """Load models once and build pre-match features from the database."""
    global _BUNDLE
    if _BUNDLE is not None:
        return _BUNDLE
    meta = json.loads((MODEL_DIR / "metadata.json").read_text(encoding="utf-8"))
    prem = add_prematch_features(load_data())
    gfor = joblib.load(MODEL_DIR / "xgb_goals_for.joblib")
    gag = joblib.load(MODEL_DIR / "xgb_goals_against.joblib")
    scaler = joblib.load(MODEL_DIR / "tactical_scaler.joblib")
    km = joblib.load(MODEL_DIR / "tactical_kmeans.joblib")
    _BUNDLE = (meta, prem, gfor, gag, scaler, km)
    return _BUNDLE


def _row(prem, team, opp, season, week):
    q = prem[
        (prem.team_id == team)
        & (prem.opponent_id == opp)
        & (prem.season == season)
        & (prem.week == week)
    ]
    if q.empty:
        raise ValueError(
            "Match not found or insufficient pre-match history "
            "(minimum 5 prior matches required for each team)."
        )
    return q.iloc[-1]


def team_analysis(team,season=None,week=None):
    raw=load_data()
    q=raw[raw.team_id==team].sort_values(["season","week"])
    if season is not None: q=q[q.season==season]
    if week is not None: q=q[q.week<=week]
    if q.empty: raise ValueError("Team not found")
    recent=q.tail(5)
    metrics={"xG":float(recent.xg_for.mean()),"shots":float(recent.shots_for.mean()),"shots_on_target":float(recent.sot_for.mean()),
             "possession":float(recent.possession_for.mean()),"duels_success":float(recent.duels_success_for.mean()),
             "metrica":float(recent.metrica_for.mean()),"goals":float(recent.goals_for.mean())}
    return {"team_id":int(team),"matches_used":int(len(recent)),"metrics_last_5":metrics}


def tactical(team, season=None, week=None):
    meta, prem, gfor, gag, scaler, km = load_bundle()
    raw = load_data()
    q = raw[raw.team_id == team].sort_values(["season", "week"])
    if season is not None:
        q = q[q.season == season]
    if week is not None:
        q = q[q.week < week]
    if q.empty:
        q = raw[raw.team_id == team].sort_values(["season", "week"]).tail(5)
    if q.empty:
        raise ValueError(f"Team {team} not found")
    q = q.tail(30).copy()
    q["sot_rate_for"] = q.sot_for / (q.shots_for + 1.0)
    q["xg_per_shot_for"] = q.xg_for / (q.shots_for + 1.0)
    style_cols = [
        "possession_for",
        "shots_for",
        "sot_rate_for",
        "xg_per_shot_for",
        "metrica_for",
        "duels_success_for",
    ]
    vals = q[style_cols].mean()
    std = q[style_cols].std(ddof=0).fillna(0)
    vec = np.concatenate([vals.values, std.values]).reshape(1, -1)
    if hasattr(scaler, "feature_names_in_"):
        feat = list(scaler.feature_names_in_)
    else:
        # Fallback when scaler was fit without named features.
        feat = [f"{c}_mean" for c in style_cols] + [f"{c}_std" for c in style_cols]
    vec_df = pd.DataFrame(vec, columns=feat)
    z = scaler.transform(vec_df)
    cluster = int(km.predict(z)[0])
    key = meta["tactical_cluster_map"][str(cluster)]
    fa = meta["tactical_labels_fa"][key]
    return {
        "cluster": cluster,
        "style": key,
        "style_fa": fa,
        "supporting_metrics": {k: float(v) for k, v in vals.to_dict().items()},
    }


def compare(team, opp, season, week):
    if team == opp:
        raise ValueError("team_id and opponent_id must be different")
    raw = load_data()
    q = raw[
        (raw.team_id == team)
        & (raw.opponent_id == opp)
        & (raw.season == season)
        & (raw.week == week)
    ]
    if q.empty:
        raise ValueError(
            f"Match not found for team={team} vs opponent={opp} "
            f"in season={season} week={week}. "
            "Only fixtures present in the dataset can be analyzed."
        )
    r = q.iloc[0]
    keys = [
        ("xG", "xg_for", "xg_against"),
        ("shots", "shots_for", "shots_against"),
        ("shots_on_target", "sot_for", "sot_against"),
        ("possession", "possession_for", "possession_against"),
        ("duels_success", "duels_success_for", "duels_success_against"),
        ("metrica", "metrica_for", "metrica_against"),
    ]
    metrics = {}
    for label, a, b in keys:
        metrics[label] = {
            "team": float(r[a]),
            "opponent": float(r[b]),
            "difference": float(r[a] - r[b]),
        }
    return metrics


def predict(team, opp, season, week):
    if team == opp:
        raise ValueError("team_id and opponent_id must be different")
    meta, prem, gfor, gag, scaler, km = load_bundle()
    r = _row(prem, team, opp, season, week)
    feat_names = meta["x_features"]
    X = (
        pd.DataFrame([r.reindex(feat_names).to_dict()])
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0)
    )
    # Keep column order aligned with training features.
    X = X.reindex(columns=feat_names, fill_value=0)
    lf = float(gfor.predict(X)[0])
    la = float(gag.predict(X)[0])
    lf = max(0.0, lf)
    la = max(0.0, la)
    pD = float(skellam.pmf(0, lf, la))
    pW = float(skellam.sf(0, lf, la))
    pL = float(skellam.cdf(-1, lf, la))
    s = pW + pD + pL
    if s <= 0:
        s = EPS
    probs = {"win": pW / s, "draw": pD / s, "loss": pL / s}
    # Scoreline distribution from independent Poisson rates.
    max_goals = 7
    scorelines = []
    for gf in range(max_goals + 1):
        for ga in range(max_goals + 1):
            prob = float(poisson.pmf(gf, lf) * poisson.pmf(ga, la))
            scorelines.append(
                {"home_goals": gf, "away_goals": ga, "probability": prob}
            )
    scorelines = sorted(scorelines, key=lambda x: x["probability"], reverse=True)[:5]
    total_mean = lf + la
    total_probs = [float(poisson.pmf(g, total_mean)) for g in range(0, 8)]
    return {
        "expected_goals_team": lf,
        "expected_goals_opponent": la,
        "outcome_probabilities": probs,
        "predicted_result": max(probs, key=probs.get),
        "decision_signal": max(probs.values()),
        "top_scorelines": scorelines,
        "total_goals_distribution": total_probs,
    }

# ---------- Productized dashboard layer ----------
def dashboard(team: int, opp: int, season: int, week: int):
    """Single end-to-end inference response for the product UI."""
    comp = compare(team, opp, season, week)
    tac_team = tactical(team, season, week)
    tac_opp = tactical(opp, season, week)
    pred = predict(team, opp, season, week)
    raw = load_data()
    recent = raw[(raw.team_id == team) & (raw.season == season) & (raw.week <= week)].sort_values("week").tail(5)
    trend = {"window": int(len(recent)), "values": [float(x) for x in recent.xg_for.fillna(0).tolist()]}

    insights = []
    xgd = comp["xG"]["difference"]
    sotd = comp["shots_on_target"]["difference"]
    possd = comp["possession"]["difference"]
    if xgd > 0.15:
        insights.append("The team has a positive expected-goal differential versus the opponent, indicating stronger chance-generation in this matchup.")
    elif xgd < -0.15:
        insights.append("The opponent has the stronger expected-goal profile in this matchup; chance quality is the main area to monitor.")
    else:
        insights.append("Expected-goal profiles are relatively close, suggesting a more balanced chance-creation matchup.")
    if sotd > 1:
        insights.append("The team produces more shots on target than the opponent, adding support to its attacking profile.")
    elif sotd < -1:
        insights.append("The opponent leads in shots on target, which may increase pressure on the team's defensive phase.")
    if abs(possd) >= 7:
        side = "higher" if possd > 0 else "lower"
        insights.append(f"Possession differs by {abs(possd):.1f} percentage points, giving the {side}-possession side a clear territorial signal.")
    insights.append(f"The model's highest-probability outcome is {pred['predicted_result'].upper()} with an estimated {pred['outcome_probabilities'][pred['predicted_result']]*100:.1f}% probability.")
    return {
        "match": {"team_id": team, "opponent_id": opp, "season": season, "week": week},
        "comparison": {"comparison": comp},
        "tactical": {"team": team, "tactical": tac_team, "opponent": opp, "opponent_tactical": tac_opp},
        "prediction": pred,
        "trend": trend,
        "insights": insights[:5]
    }


def model_diagnostics():
    meta, *_ = load_bundle()
    gfor = joblib.load(MODEL_DIR/"xgb_goals_for.joblib")
    names = meta.get("x_features", [])
    imp = sorted(zip(names, gfor.feature_importances_), key=lambda x: x[1], reverse=True)[:12]
    return {"evaluation": meta.get("evaluation", {}), "test_season": meta.get("test_season"),
            "feature_importance": [{"feature":k,"importance":float(v)} for k,v in imp],
            "tactical_silhouette": meta.get("silhouette")}
