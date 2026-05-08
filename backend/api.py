from __future__ import annotations

import logging
import traceback
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.agent.investment_agent import run_investment_analysis
from backend.config import get_settings
from backend.db import conversation_db as conv_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    conv_db.configure(settings.conversation_db_path)
    conv_db.init_db()
    logger.info("对话数据库已初始化: %s", settings.conversation_db_path)
    yield


app = FastAPI(title="Investment Assistant API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 对话 API 模型 ---


class ConversationCreate(BaseModel):
    title: str = "新会话"


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: int
    updated_at: int
    message_count: int


class MessageItem(BaseModel):
    id: str
    role: str
    content: str
    created_at: int


class ConversationDetail(BaseModel):
    id: str
    title: str
    created_at: int
    updated_at: int
    messages: List[MessageItem]


class ConversationTitlePatch(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class ConversationMessageCreate(BaseModel):
    content: str = Field(..., min_length=1)


class AnalysisRequest(BaseModel):
    query: str
    conversation_id: Optional[str] = None


class AnalysisResponse(BaseModel):
    result: str


def _run_persisted_analysis(conversation_id: str, query: str) -> str:
    """在已存在的会话中写入用户与助手消息；分析失败时仍写入助手错误文案并返回该文案。"""
    if not conv_db.conversation_exists(conversation_id):
        raise ValueError("conversation_not_found")
    text = query.strip()
    conv_db.append_message(conversation_id, "user", text)
    conv_db.maybe_set_title_from_first_message(conversation_id, text)
    try:
        result = run_investment_analysis(text)
    except Exception as e:
        logger.exception("分析失败（已持久化用户消息）")
        err_text = f"发生错误：{e}"
        conv_db.append_message(conversation_id, "assistant", err_text)
        return err_text
    conv_db.append_message(conversation_id, "assistant", result)
    return result


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/conversations", response_model=ConversationDetail)
async def create_conversation(body: ConversationCreate):
    def _create() -> dict:
        cid = conv_db.create_conversation(body.title.strip() or "新会话")
        detail = conv_db.get_conversation(cid)
        assert detail is not None
        return detail

    return await run_in_threadpool(_create)


@app.get("/conversations", response_model=List[ConversationSummary])
async def list_conversations():
    rows = await run_in_threadpool(conv_db.list_conversations)
    return [ConversationSummary(**r) for r in rows]


@app.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str):
    def _get() -> dict:
        row = conv_db.get_conversation(conversation_id)
        if row is None:
            raise ValueError("not_found")
        return row

    try:
        row = await run_in_threadpool(_get)
    except ValueError:
        raise HTTPException(status_code=404, detail="会话不存在")
    return ConversationDetail(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        messages=[MessageItem(**m) for m in row["messages"]],
    )


@app.patch("/conversations/{conversation_id}", response_model=ConversationSummary)
async def patch_conversation_title(conversation_id: str, body: ConversationTitlePatch):
    def _patch() -> dict:
        ok = conv_db.update_conversation_title(conversation_id, body.title.strip())
        if not ok:
            raise ValueError("not_found")
        rows = conv_db.list_conversations()
        for r in rows:
            if r["id"] == conversation_id:
                return r
        raise ValueError("not_found")

    try:
        row = await run_in_threadpool(_patch)
    except ValueError:
        raise HTTPException(status_code=404, detail="会话不存在")
    return ConversationSummary(**row)


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    def _del() -> bool:
        return conv_db.delete_conversation(conversation_id)

    ok = await run_in_threadpool(_del)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@app.post("/conversations/{conversation_id}/messages", response_model=AnalysisResponse)
async def post_conversation_message(conversation_id: str, body: ConversationMessageCreate):
    try:
        result = await run_in_threadpool(
            _run_persisted_analysis, conversation_id, body.content
        )
    except ValueError as e:
        if str(e) == "conversation_not_found":
            raise HTTPException(status_code=404, detail="会话不存在")
        raise HTTPException(status_code=400, detail=str(e))
    return AnalysisResponse(result=result)


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(req: AnalysisRequest):
    if req.conversation_id:
        try:
            result = await run_in_threadpool(
                _run_persisted_analysis, req.conversation_id, req.query
            )
            logger.info("分析完成（已写入会话 %s）", req.conversation_id)
            return AnalysisResponse(result=result)
        except ValueError as e:
            if str(e) == "conversation_not_found":
                raise HTTPException(status_code=404, detail="会话不存在")
            raise HTTPException(status_code=400, detail=str(e))

    try:
        logger.info("收到分析请求: %s", req.query)
        result = await run_in_threadpool(run_investment_analysis, req.query)
        logger.info("分析完成")
        return AnalysisResponse(result=result)
    except Exception as e:
        error_traceback = traceback.format_exc()
        logger.error("分析失败: %s\n%s", str(e), error_traceback)
        raise HTTPException(
            status_code=500,
            detail=f"{str(e)}\n\n详细堆栈:\n{error_traceback}",
        )
