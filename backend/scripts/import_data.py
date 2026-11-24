import os
import numpy as np
import pandas as pd
import psycopg
from dotenv import load_dotenv

load_dotenv()
XLSX = "data/football_data_wide_normalized.xlsx"
GOAL_SCALE = 7

DDL = """
create table if not exists public.teams (
  team_id integer primary key
);

create table if not exists public.team_matches (
  season smallint not null,
  week smallint not null check (week between 1 and 30),
  team_id integer not null references public.teams(team_id),
  opponent_id integer not null references public.teams(team_id),

  xg_for double precision,
  shots_for double precision,
  sot_for double precision,
  possession_for double precision,
  duels_success_for double precision,
  metrica_for double precision,
  goals_for smallint,

  xg_against double precision,
  shots_against double precision,
  sot_against double precision,
  possession_against double precision,
  duels_success_against double precision,
  metrica_against double precision,
  goals_against smallint,

  primary key (season, week, team_id),
  check (team_id <> opponent_id)
);

create index if not exists team_matches_team_idx
  on public.team_matches (team_id, season, week);
"""

df = pd.read_excel(XLSX)
assert df.shape[1] == 18, f"expected 18 columns, got {df.shape[1]}"
df.columns = [
    "season", "week", "team_id", "opponent_id",
    "xg_for", "shots_for", "sot_for", "possession_for",
    "duels_success_for", "metrica_for", "goals_norm_for",
    "xg_against", "shots_against", "sot_against", "possession_against",
    "duels_success_against", "metrica_against", "goals_norm_against",
]

for side in ("for", "against"):
    raw = df[f"goals_norm_{side}"] * GOAL_SCALE
    ints = np.rint(raw)
    assert np.allclose(raw, ints, atol=1e-3), f"goals_{side} is not a multiple of 1/{GOAL_SCALE}"
    df[f"goals_{side}"] = ints.astype(int)

cols = [
    "season", "week", "team_id", "opponent_id",
    "xg_for", "shots_for", "sot_for", "possession_for",
    "duels_success_for", "metrica_for", "goals_for",
    "xg_against", "shots_against", "sot_against", "possession_against",
    "duels_success_against", "metrica_against", "goals_against",
]
rows = df[cols].astype(object).values.tolist()
teams = sorted(set(df.team_id) | set(df.opponent_id))

insert_sql = (
    f"insert into public.team_matches ({', '.join(cols)}) "
    f"values ({', '.join(['%s'] * len(cols))})"
)

with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
    with conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute("truncate public.team_matches, public.teams")
        cur.executemany("insert into public.teams (team_id) values (%s)", [(int(t),) for t in teams])
        cur.executemany(insert_sql, rows)
    conn.commit()

print(f"imported {len(rows)} rows, {len(teams)} teams")