from akshare.fund.fund_amac import headers
from langchain.tools import tool
from datetime import datetime, timedelta
import time
import logging
import random
from schemas import SearchtDate, StockInfo
from tickflow import TickFlow
import requests
from .rag_system import retrieve_relevant_info


tf = TickFlow(api_key="tk_6d7c6bd439a94e8d9c50ed4b5331652f")

@tool
def get_current_datetime() -> str:
    """获取当前的系统日期和时间，并计算最近交易日"""
    print('=' * 30)
    print("正在调用get_current_datetime")
    now = datetime.now()
    current_date = now.strftime("%Y%m%d")
    weekday = now.weekday()

    if weekday == 0:
        last_trading_day = now - timedelta(days=3)
    elif weekday == 6:
        last_trading_day = now - timedelta(days=2)
    else:
        last_trading_day = now - timedelta(days=1)

    last_trading_date = last_trading_day.strftime("%Y%m%d")
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    result = (
        f"当前日期: {current_date} ({weekday_names[weekday]})\n"
        f"最近交易日: {last_trading_date}"
    )

    print(result)
    print('=' * 30)
    return result

@tool
def search_knowledge_base(query: str) -> str:
    """从知识库中检索与投资相关的信息"""
    print('=' * 30)
    print("正在调用search_knowledge_base")
    print(f"查询内容: {query}")
    print('=' * 30)

    try:
        result = retrieve_relevant_info(query)
        print(f"检索结果长度: {len(result)}")
        return result
    except Exception as e:
        error_msg = f"知识库检索失败: {str(e)}"
        print(error_msg)
        return error_msg

@tool(args_schema=StockInfo)
def get_stock_info(stock_code: str, start_date: str, end_date: str) -> str:
    """获取指定股票的行情信息"""
    print('=' * 30)
    print("正在调用get_stock_info")
    print(f"股票代码: {stock_code}")
    print(f"开始日期: {start_date}")
    print(f"结束日期: {end_date}")
    print('=' * 30)

    start_timestamp = int(datetime.strptime(start_date, "%Y%m%d").timestamp() * 1000)
    end_timestamp = int(datetime.strptime(end_date, "%Y%m%d").timestamp() * 1000)

    df = tf.klines.get(
        stock_code,
        period="1d",
        start_time=start_timestamp,
        end_time=end_timestamp,
        count=10000,
        as_dataframe=True
    )

    if df is None or len(df) == 0:
        error_msg = f"警告: 未获取到股票 {stock_code} 在 {start_date} 至 {end_date} 期间的数据"
        print(error_msg)
        return error_msg

    print(f"获取到{len(df)}根k线")
    print(df.tail())
    return df

