const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export type Fixture = { team_id: number; opponent_id: number; week: number };

export type TeamsMeta = {
  teams: number[];
  seasons: number[];
  weeks: number[];
  fixtures: Fixture[];
};

export type MatchRequest = {
  team_id: number;
  opponent_id: number;
  season: number;
  week: number;
};

export type ComparisonMetric = { team: number; opponent: number; difference: number };

export type TacticalStyle = "conservative" | "transitional" | "offensive" | "balanced";

export type TacticalProfile = {
  cluster: number;
  style: TacticalStyle;
  style_fa: string;
  supporting_metrics: Record<string, number>;
};

export type Outcome = "win" | "draw" | "loss";

export type Prediction = {
  expected_goals_team: number;
  expected_goals_opponent: number;
  outcome_probabilities: Record<Outcome, number>;
  predicted_result: Outcome;
  decision_signal: number;
};

export type DashboardResponse = {
  match: MatchRequest;
  comparison: { comparison: Record<string, ComparisonMetric> };
  tactical: {
    team: number;
    tactical: TacticalProfile;
    opponent: number;
    opponent_tactical: TacticalProfile;
  };
  prediction: Prediction;
  trend: { window: number; values: number[] };
  insights: string[];
};

function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((x) =>
        x && typeof x === "object" && "msg" in x
          ? String((x as { msg: unknown }).msg)
          : JSON.stringify(x),
      )
      .join("; ");
  }
  return "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    /* body is not JSON */
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    throw new Error(formatDetail(detail) || `HTTP ${res.status}`);
  }
  return data as T;
}

export const getHealth = () => request<{ status: string; version: string }>("/health");

export const getTeams = () => request<TeamsMeta>("/teams");

export const getDashboard = (body: MatchRequest) =>
  request<DashboardResponse>("/dashboard", { method: "POST", body: JSON.stringify(body) });

// سرور رایگان Render بعد از بیکاری می‌خوابه؛ چند بار دوباره تلاش می‌کنیم تا بیدار بشه
export async function withRetry<T>(fn: () => Promise<T>, attempts = 6, delayMs = 5000): Promise<T> {
  let lastError: unknown;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (e) {
      lastError = e;
      if (i < attempts - 1) await new Promise((r) => setTimeout(r, delayMs));
    }
  }
  throw lastError;
}