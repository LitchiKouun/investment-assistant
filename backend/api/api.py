import json

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.agent.investment_agent import iter_investment_analysis_event_dicts

app = FastAPI(title="Investment Assistant API")


class AnalysisRequest(BaseModel):
    query: str


async def _ndjson_analyze_only(query: str):
    q = (query or "").strip()
    if not q:
        yield (json.dumps({"type": "error", "message": "查询内容不能为空"}, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        return
    try:
        for ev in iter_investment_analysis_event_dicts(q):
            yield (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")
        yield (json.dumps({"type": "done"}, ensure_ascii=False) + "\n").encode("utf-8")
    except Exception as e:
        yield (json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False) + "\n").encode("utf-8")


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/analyze")
async def analyze(req: AnalysisRequest):
    return StreamingResponse(
        _ndjson_analyze_only(req.query),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
