"use client";

import { useEffect, useState } from "react";
import Dashboard from "@/components/Dashboard";
import {
  getDashboard,
  getHealth,
  getTeams,
  withRetry,
  type DashboardResponse,
  type TeamsMeta,
} from "@/lib/api";

const uniqueSorted = (xs: number[]) => Array.from(new Set(xs)).sort((a, b) => a - b);

export default function Home() {
  const [meta, setMeta] = useState<TeamsMeta | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const [phase, setPhase] = useState<"connecting" | "ready" | "offline">("connecting");
  const [team, setTeam] = useState("");
  const [opp, setOpp] = useState("");
  const [week, setWeek] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DashboardResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const h = await withRetry(() => getHealth());
        const m = await getTeams();
        if (cancelled) return;
        setVersion(h.version);
        setMeta(m);
        setPhase("ready");
      } catch (e) {
        if (cancelled) return;
        setPhase("offline");
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const opponentsOf = (t: number) =>
    meta ? uniqueSorted(meta.fixtures.filter((f) => f.team_id === t).map((f) => f.opponent_id)) : [];
  const weeksOf = (t: number, o: number) =>
    meta
      ? uniqueSorted(meta.fixtures.filter((f) => f.team_id === t && f.opponent_id === o).map((f) => f.week))
      : [];

  const teamId = Number(team) || 0;
  const oppId = Number(opp) || 0;
  const opponents = teamId ? opponentsOf(teamId) : [];
  const weeks = teamId && oppId ? weeksOf(teamId, oppId) : [];
  const season = meta?.seasons[0] ?? 23;

  function reset() {
    setResult(null);
    setError(null);
  }

  function onTeam(v: string) {
    reset();
    setTeam(v);
    const opps = v ? opponentsOf(Number(v)) : [];
    const nextOpp = opps.length === 1 ? String(opps[0]) : "";
    setOpp(nextOpp);
    const ws = nextOpp ? weeksOf(Number(v), Number(nextOpp)) : [];
    setWeek(ws.length === 1 ? String(ws[0]) : "");
  }

  function onOpp(v: string) {
    reset();
    setOpp(v);
    const ws = v ? weeksOf(teamId, Number(v)) : [];
    setWeek(ws.length === 1 ? String(ws[0]) : "");
  }

  async function run() {
    if (!teamId || !oppId || !week) {
      setError("Please select both teams and a week.");
      return;
    }
    setRunning(true);
    setError(null);
    try {
      const data = await getDashboard({
        team_id: teamId,
        opponent_id: oppId,
        season,
        week: Number(week),
      });
      setResult(data);
    } catch (e) {
      setResult(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  const statusText =
    phase === "ready"
      ? `Engine online${version ? ` · v${version}` : ""}`
      : phase === "offline"
        ? "Engine unavailable"
        : "Connecting to AI engine… the free server can take up to a minute to wake up";

  const dotColor = phase === "ready" ? "bg-[#8be0c3]" : phase === "offline" ? "bg-[#ff8f9d]" : "bg-[#ffd37a]";

  return (
    <main className="mx-auto max-w-[1280px] px-4 pb-14 pt-7 sm:px-6">
      <header className="mb-7 flex items-center justify-between gap-5">
        <div className="flex items-center gap-3">
          <div className="logo grid h-[42px] w-[42px] place-items-center rounded-[13px] border border-[#315071] font-black">
            FI
          </div>
          <div>
            <div className="eyebrow">Football Intelligence</div>
            <div className="muted text-[11px]">AI performance &amp; tactical analytics</div>
          </div>
        </div>
        <div className="flex items-center gap-2 text-right text-xs">
          <span className={`h-2 w-2 shrink-0 rounded-full ${dotColor}`} />
          <span>{statusText}</span>
        </div>
      </header>

      <section className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-[1.5fr_0.8fr]">
        <div className="panel p-7">
          <div className="eyebrow">AI Match Lab</div>
          <h1 className="my-2 text-[clamp(28px,4vw,46px)] font-extrabold leading-tight tracking-tight">
            Turn match data into football intelligence.
          </h1>
          <p className="muted">
            A decision-support prototype combining performance analytics, tactical profiling and goal forecasting.
          </p>
        </div>
        <div className="panel flex flex-col justify-between p-[22px]">
          <div>
            <div className="eyebrow">Model stack</div>
            <h2 className="mt-2 text-lg font-bold">XGBoost · Skellam · K-Means</h2>
            <p className="muted mt-3 text-[11px]">Time-aware features • pre-match inference • interpretable outputs</p>
          </div>
          <div className="muted mt-4 text-[11px]">Research → Prototype → MVP</div>
        </div>
      </section>

      <section className="panel grid grid-cols-1 gap-2.5 p-4 md:grid-cols-[1.2fr_1.2fr_0.8fr_0.8fr_auto]">
        <select className="select" value={team} disabled={phase !== "ready"} onChange={(e) => onTeam(e.target.value)}>
          <option value="">Team 1 (required)</option>
          {(meta?.teams ?? []).map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select className="select" value={opp} disabled={!teamId} onChange={(e) => onOpp(e.target.value)}>
          <option value="">Team 2 (required)</option>
          {opponents.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select className="select" value={season} disabled>
          <option value={season}>{season}</option>
        </select>
        <select
          className="select"
          value={week}
          disabled={!teamId || !oppId}
          onChange={(e) => {
            reset();
            setWeek(e.target.value);
          }}
        >
          <option value="">Week</option>
          {weeks.map((w) => (
            <option key={w} value={w}>
              {w}
            </option>
          ))}
        </select>
        <button className="btn" onClick={run} disabled={running || phase !== "ready"}>
          {running ? "Analyzing…" : "Analyze match"}
        </button>
      </section>

      {error && <div className="mt-4 text-sm text-[#ff8f9d]">{error}</div>}

      {result && <Dashboard data={result} />}
    </main>
  );
}