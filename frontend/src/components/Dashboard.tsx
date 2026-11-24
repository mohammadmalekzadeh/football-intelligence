import type { DashboardResponse, Outcome, TacticalProfile, TacticalStyle } from "@/lib/api";

const METRIC_LABELS: Record<string, string> = {
  xG: "Expected goals",
  shots: "Shots",
  shots_on_target: "Shots on target",
  possession: "Possession",
  duels_success: "Successful duels",
  metrica: "Metrica rating",
};

const STYLE_NAMES: Record<TacticalStyle, string> = {
  offensive: "Offensive",
  transitional: "Transitional",
  conservative: "Conservative",
  balanced: "Balanced",
};

const STYLE_TEXT: Record<TacticalStyle, string> = {
  offensive: "Higher attacking production and chance-generation profile.",
  transitional: "Profile associated with transition-oriented performance patterns.",
  conservative: "Lower attacking output and more cautious performance profile.",
  balanced: "Relatively even profile across the selected performance dimensions.",
};

const OUTCOMES: Outcome[] = ["win", "draw", "loss"];
const OUTCOME_LABELS: Record<Outcome, string> = { win: "Win", draw: "Draw", loss: "Loss" };

const fmt = (n: number, digits = 2) => (Number.isFinite(n) ? n.toFixed(digits) : "—");

function Kpi({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="panel p-[18px]">
      <div className="muted text-[11px] uppercase tracking-widest">{label}</div>
      <div className="mt-2 text-2xl font-extrabold">{value}</div>
      <div className="muted text-[11px]">{sub}</div>
    </div>
  );
}

function CompareBar({ label, team, opponent }: { label: string; team: number; opponent: number }) {
  const total = Math.abs(team) + Math.abs(opponent);
  const share = total > 0 ? (Math.abs(team) / total) * 100 : 50;
  return (
    <div className="my-4">
      <div className="mb-2 flex justify-between gap-3 text-xs">
        <b>{label}</b>
        <span className="muted">
          {fmt(team)} vs {fmt(opponent)} · Δ {team - opponent >= 0 ? "+" : ""}
          {fmt(team - opponent)}
        </span>
      </div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-[#17283c]">
        <div className="bg-[#78a9ff]" style={{ width: `${share}%` }} />
        <div className="bg-[#8be0c3]" style={{ width: `${100 - share}%` }} />
      </div>
    </div>
  );
}

function StyleBox({ title, profile }: { title: string; profile: TacticalProfile }) {
  return (
    <div className="rounded-2xl border border-[#1b3047] bg-[#0a1624] p-4">
      <div className="text-base font-extrabold">{title}</div>
      <div className="mt-2 inline-flex items-center gap-2 rounded-full border border-[#2a4765] bg-[#162a41] px-2.5 py-1.5 text-xs">
        <span className="h-[7px] w-[7px] rounded-full bg-[#8be0c3]" />
        {STYLE_NAMES[profile.style] ?? profile.style}
      </div>
      <p className="muted mt-3 text-[11px]">{STYLE_TEXT[profile.style] ?? "Data-derived tactical profile."}</p>
    </div>
  );
}

export default function Dashboard({ data }: { data: DashboardResponse }) {
  const { match, prediction: p, tactical: t, trend, insights } = data;
  const comparison = data.comparison.comparison;
  const maxTrend = Math.max(...trend.values, 0) || 1;

  return (
    <div className="mt-4 space-y-4">
      <section className="panel p-5">
        <div className="eyebrow">Selected Match</div>
        <h2 className="my-2 text-lg font-bold">
          Team {match.team_id} vs Team {match.opponent_id}
        </h2>
        <div className="muted text-[11px]">
          Season {match.season} · Week {match.week}
        </div>
      </section>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Expected goals" value={fmt(p.expected_goals_team)} sub="Team forecast" />
        <Kpi label="Opponent xG" value={fmt(p.expected_goals_opponent)} sub="Opponent forecast" />
        <Kpi
          label="Most likely"
          value={OUTCOME_LABELS[p.predicted_result].toUpperCase()}
          sub={`${fmt(p.decision_signal * 100, 1)}% · from Team ${match.team_id}'s view`}
        />
        <Kpi label="Tactical style" value={STYLE_NAMES[t.tactical.style] ?? t.tactical.style} sub={`Cluster ${t.tactical.cluster}`} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.25fr_0.75fr]">
        <section className="panel p-5">
          <h2 className="mb-4 text-lg font-bold">Performance differential</h2>
          <div className="muted mb-2 flex gap-4 text-[11px]">
            <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-[#78a9ff]" />Team {match.team_id}</span>
            <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-[#8be0c3]" />Team {match.opponent_id}</span>
          </div>
          {Object.entries(comparison).map(([key, v]) => (
            <CompareBar key={key} label={METRIC_LABELS[key] ?? key} team={v.team} opponent={v.opponent} />
          ))}
          <p className="muted mt-4 text-[11px]">
            Match statistics come from a min–max normalized dataset (0–1 scale).
          </p>
        </section>

        <section className="panel p-5">
          <h2 className="mb-4 text-lg font-bold">Tactical identity</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-1">
            <StyleBox title={`Team ${t.team}`} profile={t.tactical} />
            <StyleBox title={`Opponent ${t.opponent}`} profile={t.opponent_tactical} />
          </div>
        </section>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.25fr_0.75fr]">
        <section className="panel p-5">
          <h2 className="mb-4 text-lg font-bold">Match forecast</h2>
          {OUTCOMES.map((k) => {
            const v = p.outcome_probabilities[k] ?? 0;
            return (
              <div key={k} className="my-4 grid grid-cols-[55px_1fr_52px] items-center gap-3 text-xs">
                <b>{OUTCOME_LABELS[k].toUpperCase()}</b>
                <div className="h-2.5 overflow-hidden rounded-full bg-[#17283c]">
                  <div className="h-full rounded-full bg-[#78a9ff]" style={{ width: `${Math.max(0, Math.min(100, v * 100))}%` }} />
                </div>
                <span>{fmt(v * 100, 1)}%</span>
              </div>
            );
          })}
          <div className="insight">
            Projected scoreline tendency: <b>{fmt(p.expected_goals_team)} – {fmt(p.expected_goals_opponent)}</b>.
            Probabilities are derived from the predicted goal distributions (win/draw/loss from Team {match.team_id}&apos;s perspective).
          </div>
        </section>

        <section className="panel p-5">
          <h2 className="mb-4 text-lg font-bold">Recent form</h2>
          {trend.values.length ? (
            <>
              <div className="flex h-[150px] items-end gap-2 px-0.5 py-2.5">
                {trend.values.map((v, i) => (
                  <div
                    key={i}
                    title={fmt(v)}
                    className="min-w-[5px] flex-1 rounded-t-[5px] rounded-b-sm bg-gradient-to-b from-[#89b4ff] to-[#426d9e]"
                    style={{ height: `${Math.max(8, Math.min(100, (v / maxTrend) * 100))}%` }}
                  />
                ))}
              </div>
              <div className="muted text-[11px]">Recent expected-goal trend · {trend.window} matches</div>
            </>
          ) : (
            <div className="muted text-[11px]">No trend data available.</div>
          )}
        </section>
      </div>

      <section className="panel p-5">
        <h2 className="mb-4 text-lg font-bold">AI insights</h2>
        {insights.length ? (
          insights.map((x, i) => (
            <div key={i} className="insight">
              {x}
            </div>
          ))
        ) : (
          <div className="muted text-[11px]">No additional insights.</div>
        )}
      </section>

      <p className="muted pt-2 text-center text-[11px]">
        Model stack: XGBoost · Skellam · K-Means. Forecasted goals are in real goal units.
      </p>
    </div>
  );
}