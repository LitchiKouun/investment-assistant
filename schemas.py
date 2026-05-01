from langchain.tools import tool
from pydantic import BaseModel, Field

class SearchtDate(BaseModel):
    """日期格式"""
    date : str = Field(..., description="日期，格式为YYYYMMDD")

class StockInfo(BaseModel):
    """股票信息"""
    stock_code: str = Field(..., description="股票代码，格式为XXXXXX")
    start_date: str = Field(..., description="开始日期，格式为YYYYMMDD")
    end_date: str = Field(..., description="结束日期，格式为YYYYMMDD")