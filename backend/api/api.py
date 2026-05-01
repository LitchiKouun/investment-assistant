from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from backend.agent.investment_agent import run_investment_analysis

app = FastAPI(title="Investment Assistant API")


class AnalysisRequest(BaseModel):
    query: str


class AnalysisResponse(BaseModel):
    result: str


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(req: AnalysisRequest):
    try:
        # LangChain/LLM 调用通常是阻塞的，先放线程池里跑
        result = await run_in_threadpool(run_investment_analysis, req.query)
        return AnalysisResponse(result=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))