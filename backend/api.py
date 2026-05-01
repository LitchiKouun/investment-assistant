from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
import traceback
import logging

from backend.agent.investment_agent import run_investment_analysis

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI(title="Investment Assistant API")
# 允许前端开发服务器跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)




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
        logger.info(f"收到分析请求: {req.query}")
        result = await run_in_threadpool(run_investment_analysis, req.query)
        logger.info("分析完成")
        return AnalysisResponse(result=result)
    except Exception as e:
        error_traceback = traceback.format_exc()
        logger.error(f"分析失败: {str(e)}\n{error_traceback}")
        raise HTTPException(status_code=500, detail=f"{str(e)}\n\n详细堆栈:\n{error_traceback}")

