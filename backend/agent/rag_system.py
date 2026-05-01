
"""
RAG检索增强生成模块
使用本地Qwen3 Embedding模型进行向量检索，结合DeepSeek API生成回答
"""
"""
RAG检索增强生成模块
使用本地Ollama Embedding模型进行向量检索，结合DeepSeek API生成回答
"""

import os
from typing import List, Dict, Any
from pathlib import Path
from langchain_community.document_loaders import TextLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document
from backend.config import get_settings


class RAGSystem:
    """RAG检索系统"""

    def __init__(self):
        self.settings = get_settings()
        self.vector_db_path = self.settings.vector_db_path
        self.chunk_size = self.settings.chunk_size
        self.chunk_overlap = self.settings.chunk_overlap
        self.top_k = self.settings.top_k_retrieval

        # 初始化embedding模型（使用Ollama）
        self.embeddings = self._init_embedding_model()

        # 初始化或加载向量数据库
        self.vectorstore = self._init_vectorstore()

    def _init_embedding_model(self):
        """初始化Ollama Embedding模型"""
        print(f"正在加载Ollama Embedding模型: {self.settings.embedding_model_name}")
        print(f"Ollama服务地址: {self.settings.ollama_base_url}")

        # 使用OllamaEmbeddings
        embeddings = OllamaEmbeddings(
            model=self.settings.embedding_model_name,
            base_url=self.settings.ollama_base_url
        )

        print("Embedding模型加载完成")
        return embeddings

    def _init_vectorstore(self):
        """初始化或加载向量数据库"""
        if os.path.exists(self.vector_db_path):
            print(f"从现有数据库加载: {self.vector_db_path}")
            return Chroma(
                persist_directory=self.vector_db_path,
                embedding_function=self.embeddings
            )
        else:
            print(f"创建新的向量数据库: {self.vector_db_path}")
            return Chroma(
                persist_directory=self.vector_db_path,
                embedding_function=self.embeddings
            )

    def add_documents_from_directory(self, directory_path: str, pattern: str = "*.txt"):
        """
        从目录加载文档并添加到向量数据库

        参数:
            directory_path: 文档目录路径
            pattern: 文件匹配模式
        """
        print(f"从目录加载文档: {directory_path}")

        # 加载文档
        loader = DirectoryLoader(
            directory_path,
            glob=pattern,
            loader_cls=TextLoader,
            loader_kwargs={'encoding': 'utf-8'}
        )
        documents = loader.load()
        print(f"加载了 {len(documents)} 个文档")

        # 分割文档
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
        )
        splits = text_splitter.split_documents(documents)
        print(f"分割为 {len(splits)} 个文本块")

        # 添加到向量数据库
        self.vectorstore.add_documents(splits)
        self.vectorstore.persist()
        print("文档已添加到向量数据库")

    def add_texts(self, texts: List[str], metadatas: List[Dict] = None):
        """
        直接添加文本到向量数据库

        参数:
            texts: 文本列表
            metadatas: 元数据列表（可选）
        """
        if metadatas is None:
            metadatas = [{} for _ in texts]

        self.vectorstore.add_texts(texts=texts, metadatas=metadatas)
        self.vectorstore.persist()
        print(f"已添加 {len(texts)} 个文本块到向量数据库")

    def retrieve(self, query: str, k: int = None) -> List[Document]:
        """
        检索相关文档

        参数:
            query: 查询文本
            k: 返回的文档数量（默认使用配置的top_k）

        返回:
            相关文档列表
        """
        if k is None:
            k = self.top_k

        print(f"检索查询: {query[:50]}...")
        relevant_docs = self.vectorstore.similarity_search(query, k=k)
        print(f"检索到 {len(relevant_docs)} 个相关文档")

        return relevant_docs

    def format_context(self, docs: List[Document]) -> str:
        """
        将检索到的文档格式化为上下文字符串

        参数:
            docs: 文档列表

        返回:
            格式化后的上下文字符串
        """
        context_parts = []
        for i, doc in enumerate(docs, 1):
            context_parts.append(f"[参考资料{i}]:\n{doc.page_content}")

        return "\n\n".join(context_parts)


# 全局RAG实例
rag_system = RAGSystem()


def initialize_rag_with_data(data_dir: str = "./data"):
    """
    初始化RAG系统并加载数据

    参数:
        data_dir: 数据目录路径
    """
    if not os.path.exists(data_dir):
        print(f"数据目录不存在: {data_dir}，跳过初始化")
        return

    rag_system.add_documents_from_directory(data_dir)


def retrieve_relevant_info(query: str) -> str:
    """
    检索与查询相关的信息

    参数:
        query: 用户查询

    返回:
        格式化后的相关上下文
    """
    docs = rag_system.retrieve(query)
    if not docs:
        return "未找到相关参考资料"

    return rag_system.format_context(docs)
