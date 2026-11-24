import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

from .engine import (
    load_bundle,
    load_data,
    team_analysis,
    compare,
    tactical,
    predict,
    dashboard,
    model_diagnostics,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_bundle()  # loads data from PostgreSQL + models once at startup
    yield


app = FastAPI(title="Football Intelligence API", version="0.5.0", lifespan=lifespan)

origins = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class MatchRequest(BaseModel):
    team_id: int
    opponent_id: int
    season: int
    week: int = Field(ge=1, le=30)

    @model_validator(mode="after")
    def teams_must_differ(self):
        if self.team_id == self.opponent_id:
            raise ValueError("team_id and opponent_id must be different")
        return self


def _err(e: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "football-intelligence-api",
        "version": "0.5.0",
        "api": "/docs",
    }


@app.get("/teams")
def teams():
    d = load_data()
    # Product rule: only season 23 is selectable in the UI.
    season = 23
    d23 = d[d.season == season]
    fixtures = [
        {
            "team_id": int(r.team_id),
            "opponent_id": int(r.opponent_id),
            "week": int(r.week),
        }
        for r in d23[["team_id", "opponent_id", "week"]].itertuples(index=False)
    ]
    return {
        "teams": sorted(int(x) for x in d23.team_id.unique().tolist()),
        "seasons": [season],
        "weeks": sorted(int(x) for x in d23.week.unique().tolist()),
        "fixtures": fixtures,
    }


@app.get("/teams/{team_id}/analysis")
def analysis(team_id: int, season: int | None = None, week: int | None = None):
    try:
        return team_analysis(team_id, season, week)
    except Exception as e:
        raise _err(e)


@app.post("/compare")
def compare_endpoint(req: MatchRequest):
    try:
        return {
            "match": req.model_dump(),
            "comparison": compare(req.team_id, req.opponent_id, req.season, req.week),
        }
    except Exception as e:
        raise _err(e)


@app.post("/tactical/classify")
def tactical_endpoint(req: MatchRequest):
    try:
        return {
            "team": req.team_id,
            "tactical": tactical(req.team_id, req.season, req.week),
            "opponent": req.opponent_id,
            "opponent_tactical": tactical(req.opponent_id, req.season, req.week),
        }
    except Exception as e:
        raise _err(e)


@app.post("/predict/goals")
def goals(req: MatchRequest):
    try:
        return {
            "match": req.model_dump(),
            "prediction": predict(req.team_id, req.opponent_id, req.season, req.week),
        }
    except Exception as e:
        raise _err(e)


@app.post("/predict/outcome")
def outcome(req: MatchRequest):
    try:
        return {
            "match": req.model_dump(),
            "prediction": predict(req.team_id, req.opponent_id, req.season, req.week),
        }
    except Exception as e:
        raise _err(e)


@app.get("/models/diagnostics")
def diagnostics():
    try:
        return model_diagnostics()
    except Exception as e:
        raise _err(e)


@app.post("/dashboard")
def dashboard_endpoint(req: MatchRequest):
    try:
        return dashboard(req.team_id, req.opponent_id, req.season, req.week)
    except Exception as e:
        raise _err(e)