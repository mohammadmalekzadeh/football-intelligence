from app.engine import load_data, add_prematch_features

d = load_data()
p = add_prematch_features(d)
assert len(d) == 1914 and len(p) > 0
assert {"team_id", "opponent_id", "season", "week", "goals_for", "goals_against"}.issubset(p.columns)
print("SMOKE OK", d.shape, p.shape)