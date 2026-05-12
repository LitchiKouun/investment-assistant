from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.agent.investment_agent import (
    format_stream_event_as_markdown,
    iter_investment_analysis_event_dicts,
)
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


async def _ndjson_analysis_stream(
    query: str,
    *,
    conversation_id: Optional[str] = None,
) -> AsyncIterator[bytes]:
    """NDJSON 流：stage / tool / delta 等事件逐行 JSON，最后 type=done；错误为 type=error。"""
    q = (query or "").strip()
    if not q:
        yield (json.dumps({"type": "error", "message": "查询内容不能为空"}, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        return

    if conversation_id is not None:
        if not conv_db.conversation_exists(conversation_id):
            yield (json.dumps({"type": "error", "message": "会话不存在"}, ensure_ascii=False) + "\n").encode(
                "utf-8"
            )
            return
        conv_db.append_message(conversation_id, "user", q)
        conv_db.maybe_set_title_from_first_message(conversation_id, q)

    pieces: list[str] = []
    try:
        for ev in iter_investment_analysis_event_dicts(q):
            md = format_stream_event_as_markdown(ev)
            if md:
                pieces.append(md)
            line = json.dumps(ev, ensure_ascii=False) + "\n"
            yield line.encode("utf-8")
        full = "".join(pieces)
        if conversation_id is not None:
            conv_db.append_message(conversation_id, "assistant", full)
        yield (json.dumps({"type": "done"}, ensure_ascii=False) + "\n").encode("utf-8")
    except Exception as e:
        logger.exception("分析流式输出失败")
        partial = "".join(pieces)
        err_text = (partial + f"\n\n（输出中断：{e}）") if partial else f"发生错误：{e}"
        if conversation_id is not None:
            conv_db.append_message(conversation_id, "assistant", err_text)
        yield (json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False) + "\n").encode("utf-8")


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


@app.post("/conversations/{conversation_id}/messages")
async def post_conversation_message(conversation_id: str, body: ConversationMessageCreate):
    if not conv_db.conversation_exists(conversation_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return StreamingResponse(
        _ndjson_analysis_stream(body.content, conversation_id=conversation_id),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/analyze")
async def analyze(req: AnalysisRequest):
    if req.conversation_id:
        if not conv_db.conversation_exists(req.conversation_id):
            raise HTTPException(status_code=404, detail="会话不存在")
        logger.info("分析请求（会话 %s）", req.conversation_id)
        return StreamingResponse(
            _ndjson_analysis_stream(req.query, conversation_id=req.conversation_id),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    logger.info("收到分析请求: %s", req.query)
    return StreamingResponse(
        _ndjson_analysis_stream(req.query),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
