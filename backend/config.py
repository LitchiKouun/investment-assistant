'''配置'''

import os
from pathlib import Path
from typing import List

_BACKEND_DIR = Path(__file__).resolve().parent
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

class Settings(BaseSettings):
    """
    配置类
    """
    # LLM API配置
    llm_api_key: str = ""
    llm_api_url: str = ""
    llm_model_id: str = ""

    # TickFlow API配置
    tickflow_api_key: str = ""

    # RAG配置
    embedding_model_name: str = "Qwen/Qwen3-Embedding-4B"
    ollama_base_url: str = "http://localhost:11434"
    vector_db_path: str = "./vector_db"
    chunk_size: int = 500
    chunk_overlap: int = 50
    top_k_retrieval: int = 3

    # 对话存储（SQLite）
    conversation_db_path: Path = _BACKEND_DIR / "data" / "conversations.db"

    #  BaseSettings 会自动从环境变量或 .env 文件中读取对应名称的值 不需要手动调用 os.getenv()
    class Config:
        env_file = ".env"  # 指定从 .env 文件读取

#全局变量实例
settings = Settings()

#获取配置
def get_settings():
    return settings

#验证配置
def verify_settings():
    errors = []
    if not settings.llm_api_key:
        errors.append("llm_api_key未配置")
    if not settings.llm_api_url:
        errors.append("llm_api_url未配置")
    if not settings.llm_model_id:
        errors.append("llm_model_id未配置")

