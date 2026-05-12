import json
from typing import Any, Iterator

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_openai import ChatOpenAI

from backend.config import get_settings

from . import tools

# 角色：意图分析与信息提取 Agent（智能投研助手 · 一号Agent）
system_prompt1 = '''

你是一名智能投研助手的第一个处理节点。你的核心职责是：**理解用户输入，识别用户真正想问的问题（如查询某只股票、某个板块、大盘行情），并调用可用工具获取必要的辅助信息（如当前时间、实时市场数据），最终输出一个清晰、结构化的问题描述，供后续 Agent 使用。**

## 可用工具
1. **get_current_datetime**（基于 Python datetime）  
   - 功能：获取当前的系统日期与时间。  
   - 使用场景：当用户问题中缺少明确的时间限定（如“今天”“本周”“最近几天”）或你需要明确“最新”数据的截止时间时，必须调用此工具获得准确的当前日期。  
   - 示例：用户问“万科现在股价多少”，你需要调用该工具得到今天的日期，以便后续查询最新行情。

2. **get_stock_info**（支持 A 股大盘、板块、个股信息）  
   - 功能：通过 Tushare 接口获取 A 股数据，包括：  
     - 大盘指数（上证、深证、创业板等）  
     - 板块行情（行业板块、概念板块）  
     - 个股信息（实时/历史行情、财务指标、公司概况等）  
   - 使用规则：  
     - 当用户提及具体的股票名称或代码（如“贵州茅台”“000858”）时，应调用本工具获取该股票的基础信息或行情。  
     - 当用户提及板块名称（如“新能源板块”“医药行业”）时，调用本工具获取板块行情或成分股数据。  
     - 当用户询问大盘走势时，调用本工具获取主要指数数据。  
     - **注意**：你不需要实际执行查询，只需在输出的问题中指明需要调用该工具的哪些参数（股票/板块/指数标识）。但若为了理解用户意图而必须参考实时数据（例如用户说“最近涨得最好的板块”），你可模拟调用（思路：先通过 tushare_api 获取板块涨跌排名，再据此判断用户问题的具体所指）。由于你是提示词定义阶段，允许你在输出中描述“应当使用 tushare_api 查询 XXX 数据”。

## 任务流程
当收到用户的自然语言输入后，请按以下步骤处理：

1. **解析用户输入**  
   - 识别其中的金融实体：  
     - 股票（名称/代码，例如“比亚迪”“002594”）  
     - 板块（行业板块/概念板块，例如“光伏”“白酒”“半导体”）  
     - 大盘/指数（例如“上证指数”“大盘”“创业板指”）  
   - 识别用户的操作意图：查询行情？对比？分析趋势？获取财务数据？还是询问事件影响？

2. **补充时间上下文（强制调用 get_current_datetime）**  
   - 无论用户是否提及时间，**第一步总是调用 `get_current_datetime`** 获取当前日期时间。  
   - 如果用户提到“今天”“本周”“本月”“最近3天”等相对时间，用当前时间作为基准进行推算（在输出中注明推算结果）。  
   - 如果用户提到具体日期（如“2025年4月1日”），则以该日期为准，但仍需记录当前时间用于判断数据是否已发布（如财报是否已出）。

3. **search_knowledge_base**（RAG知识库检索）  
   - 功能：从本地知识库中检索与投资分析相关的背景知识、行业报告、政策解读等信息。  
   - 使用场景：  
     - 当用户询问行业趋势、政策影响、投资理念等需要背景知识的问题时  
     - 当需要补充股票基本面分析所需的行业信息时  
     - 当用户问题涉及专业术语解释或投资策略建议时  
   - 示例：  
     - 用户问"医药行业未来发展前景如何"，应调用此工具检索医药行业的相关研究报告  
     - 用户问"什么是PE估值"，应调用此工具检索估值方法的相关知识  
     - 用户问"美联储加息对A股的影响"，应调用此工具检索货币政策相关的分析

4. **判断是否需要调用 get_stock_info 来获取数据**  
   - 当用指出明确股票名称、代码时，请调用akshare_api获取股票数据：
     - get_stock_info(stock_code: str, start_date: str, end_date: str)
     - 股票代码需要带有后缀后缀：
        SH	上海证券交易所	沪市 A 股、ETF、债券等
        SZ	深圳证券交易所	深市 A 股、创业板、ETF 等
        BJ	北京证券交易所	北交所股票
     - 若用户没有提及开始、结束时间，默认为今天
     - 例如：用户输入“药明康德股票分析” 调用akshare_api->akshare_api(603259.SH, 20250427, 20250427)
   - 当用户提问模糊时，你可以模拟调用 akshare_api 来获取候选信息。例如：  
     - 用户问“最近哪个板块最火”，你可以内部思考：需要 akshare_api 获取近5日板块涨幅排名。  
     - 但你的最终输出不是原始数据，而是**提炼出的明确问题**，例如：“用户想知道近5日（2026年4月21日至4月26日）A股概念板块中涨幅排名前3的板块名称及其涨跌幅”。
   - 阅读get_stock_info返回的数据
   
5. **结构化输出**  
   输出格式必须为 JSON，包含以下字段：  

   ```json
   {
     "original_query": "用户原话",
     "current_datetime": "YYYYMMDD",
     "normalized_time_range": {
       "start_date": "YYYYMMDD",
       "end_date": "YYYYMMDD",
       "description": "例如'今天'、'近一周'、'2025-04-01'"
     },
     "entities": {
       "stocks": [{"name": "股票名称", "code": "代码（如有）"}],
       "sectors": [{"name": "板块名称", "type": "行业/概念"}],
       "indices": ["上证指数", "深证成指", ...]
     },
     "intent": "查询行情 | 查询财务数据 | 对比分析 | 趋势预测 | 事件影响 | 其他",
     "required_data_from_tushare": "具体描述需要从 tushare 获取哪些数据，例如：个股000858最近5个交易日的日线行情，包含开盘、收盘、最高、最低价；或者：新能源板块当日成分股涨跌分布",
     "clarified_question": "经过解析和补全后，清晰、无歧义的问题描述，可直接交给后续Agent处理"
   }
'''

system_prompt2 = '''
# 角色
你是一位专业、审慎的证券分析师，专注于根据已发生的日内行情数据，对个股的短期走势进行客观解读，并给出具有参考价值的投资观察与建议。你必须基于数据说话，避免主观臆测。

# 输入说明
你将收到一个 JSON 对象，其中包含两个部分：
1. `agent1_analysis` : 来自上游 Agent 的语义解析结果，结构如下：
   - original_query : 用户原始提问
   - current_datetime : 当前系统日期（分析视角所在日期）
   - normalized_time_range : 用户关注的具体交易日范围
   - entities.stocks : 关注的股票（含名称、代码）
   - intent : 用户意图
   - clarified_question : 对用户需求的明确描述
2. `stock_data` : 由数据工具返回的目标股票在关注交易日的主要行情数据，至少包含：
   - trade_date : 交易日
   - open, high, low, close : 开盘价、最高价、最低价、收盘价
   - pre_close : 前收盘价
   - change / pct_chg : 涨跌额 / 涨跌幅(%)
   - vol / amount : 成交量 / 成交额
   如果是单日查询，可能只有该日数据；如果是区间，可能会有多个交易日的列表。

# 核心任务
基于以上信息，完成对目标股票在指定日期的 **走势分析**，并给出 **投资建议**（仅供参考，不构成实质操作指令）。

# 分析要求
请按照以下维度进行结构化分析，缺一不可：

1. **行情全貌回顾**  
   - 统计当日（或区间）的开盘、收盘、最高、最低、涨跌幅、成交量等关键指标。  
   - 对比前收盘价，描述当天是跳空高开/低开还是平开，盘中是否突破了关键价位。

2. **日内走势特征解读**  
   - 分析价格运行区间（最高-最低）、振幅大小，推测当日多空博弈激烈程度。  
   - 判断收盘价在当日价格区间的相对位置（是靠近高点、低点还是中部），以此解读收盘时的市场倾向（偏强/偏弱/犹豫）。  
   - 如果只有单日数据，尽量挖掘盘中可能的价格行为信号（如冲高回落、探底回升、窄幅震荡等）。

3. **成交量与价格配合分析**  
   - 结合涨跌幅和成交量，判断量价配合是否健康（例如：放量上涨、缩量下跌、放量滞涨等）。  
   - 若系统提供了换手率或其他指标，应一并纳入考量；若无，请说明数据局限，仅基于成交量绝对值做出谨慎推论。

4. **投资建议**  
   - 根据上述分析，给出对短期趋势的观察结论（例如：强势突破信号、弱势回调信号、方向不明横盘震荡等）。  
   - 给出一种或两种可能的后续关注情景，并分别提出相应的观察策略（如关注支撑/压力位，建议等待放量确认等）。  
   - **必须明确声明**：“以上分析仅基于历史行情数据，不构成投资建议，股市有风险，入市需谨慎。”

# 输出格式
请严格按照以下 Markdown 格式输出，以便下游系统或用户阅读：
[股票名称]（[股票代码]）[交易日] 走势分析
1. 行情全貌回顾
（详细描述，列出具体数字）

2. 日内走势特征解读
（解读盘中行为，给出强弱判断）

3. 成交量与价格配合分析
（量价关系分析，同时注明数据如有缺失则说明）

4. 投资建议与风险提示
（得出结论，给出跟踪策略）

⚠️ 以上分析仅基于历史行情数据，不构成投资建议，股市有风险，入市需谨慎。

text

# 注意事项
- 保持语言专业、客观、平实，不夸大、不渲染情绪。  
- 如果仅有一天数据，不要强行预测未来涨跌，只能基于当天的信号解读市场态度。  
- 如果没有足够信息（例如缺少成交量），请明确指出局限性，不能虚构数据。  
- 分析中必须体现对用户原始问题的回应（参考 `clarified_question`）。  
- 所有结论都要有数据支撑，分析逻辑要显式呈现。
'''

model = ChatOpenAI(
    model=get_settings().llm_model_id,
    api_key=get_settings().llm_api_key,
    base_url=get_settings().llm_api_url
)

# 初步分析agent
agent1 = create_agent(
    model=model,
    tools=[tools.get_current_datetime, tools.get_stock_info, tools.search_knowledge_base],
    system_prompt=system_prompt1
)

# 进一步分析agent
agent2 = create_agent(
    model=model,
    system_prompt=system_prompt2,
)


def parse_agent1_output(response: dict) -> dict:
    """
    解析Agent1的输出，提取结构化数据

    参数:
        response: Agent1的原始响应

    返回:
        包含agent1_analysis和stock_data的字典
    """
    agent1_result = response["messages"][-1].content

    print("\nAgent1 分析结果:")
    print(agent1_result)

    # 尝试解析JSON格式的结构化输出
    try:
        if isinstance(agent1_result, str):
            json_str = agent1_result
            if "```json" in agent1_result:
                json_str = agent1_result.split("```json", 1)[1].split("```", 1)[0]
            elif "```" in agent1_result:
                json_str = agent1_result.split("```", 1)[1].split("```", 1)[0]

            structured_data = json.loads(json_str.strip())
        else:
            structured_data = agent1_result

        return {
            "agent1_analysis": structured_data,
            "stock_data": "已从Agent1的工具调用中获取相关数据"
        }

    except (json.JSONDecodeError, KeyError) as e:
        print(f"\n警告: 无法解析Agent1的JSON输出，将直接传递原始结果 ({str(e)})")
        return {
            "agent1_analysis": {"clarified_question": agent1_result},
            "stock_data": "待获取"
        }


def format_agent2_input(data: dict) -> dict:
    """
    格式化Agent2的输入提示词

    参数:
        data: 包含agent1_analysis和stock_data的字典

    返回:
        Agent2的消息格式
    """
    agent2_prompt = f"""
    请基于以下信息进行专业的股票走势分析：
    
    {json.dumps(data, ensure_ascii=False, indent=2)}
    
    请按照system_prompt2中定义的格式输出分析报告。
    """

    return {
        "messages": [
            {"role": "user", "content": agent2_prompt}
        ]
    }


def run_agent1_pipeline(user_query: str) -> dict[str, Any]:
    """Agent1 → 解析 → 组装 Agent2 输入（阻塞阶段，无流式）。"""
    agent1_input: dict[str, Any] = {
        "messages": [{"role": "user", "content": user_query}],
    }
    r1 = agent1.invoke(agent1_input)
    parsed = parse_agent1_output(r1)
    return format_agent2_input(parsed)


_TOOL_PREVIEW_LIMIT = 4000


def _truncate_preview(text: str, max_len: int = _TOOL_PREVIEW_LIMIT) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n\n…（已截断）"


def _open_agent_stream(agent: Any, agent_input: dict[str, Any]) -> Iterator[Any]:
    """打开 LangGraph 流；优先 messages + updates + values（便于捕获完整 messages）。"""
    attempts: list[dict[str, Any]] = [
        {"stream_mode": ["messages", "updates", "values"], "version": "v2"},
        {"stream_mode": ["messages", "updates"], "version": "v2"},
        {"stream_mode": ["messages", "updates", "values"]},
        {"stream_mode": ["messages", "updates"]},
        {"stream_mode": "messages", "version": "v2"},
        {"stream_mode": "messages"},
    ]
    last_err: Exception | None = None
    for kwargs in attempts:
        try:
            return agent.stream(agent_input, **kwargs)
        except TypeError as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return agent.stream(agent_input)


def _iter_typed_stream_parts(raw_iter: Iterator[Any]) -> Iterator[tuple[str, Any]]:
    """统一为 (mode, payload)，mode ∈ messages | updates | values。"""
    for raw in raw_iter:
        if isinstance(raw, dict) and raw.get("type") in ("messages", "updates", "values"):
            yield str(raw["type"]), raw.get("data")
            continue
        if (
            isinstance(raw, tuple)
            and len(raw) == 2
            and isinstance(raw[0], str)
            and raw[0] in ("messages", "updates", "values")
        ):
            yield raw[0], raw[1]
            continue
        yield "messages", raw


def iter_compiled_agent_event_dicts(
    agent: Any,
    agent_input: dict[str, Any],
    *,
    agent_key: str,
    state_capture: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """
    从 create_agent 编译图产出结构化流事件：
    - delta: 模型正文 token
    - tool: event=start|end，工具名与入参/出参摘要
    若提供 state_capture，则在收到 values 时写入 state_capture 的 messages 列表。
    """
    stream_iter = _open_agent_stream(agent, agent_input)
    tool_start_ids: set[str] = set()

    for mode, data in _iter_typed_stream_parts(stream_iter):
        if mode == "values" and state_capture is not None and isinstance(data, dict):
            msgs = data.get("messages")
            if msgs is not None:
                state_capture["messages"] = list(msgs)
            continue

        if mode == "messages":
            token: Any
            if isinstance(data, tuple) and len(data) >= 1:
                token = data[0]
            else:
                token = data
            piece = _text_from_message_chunk(token)
            if piece:
                yield {"type": "delta", "agent": agent_key, "text": piece}
            if isinstance(token, AIMessageChunk):
                for ch in token.tool_call_chunks or []:
                    if not isinstance(ch, dict):
                        continue
                    tid = str(ch.get("id") or "")
                    name = ch.get("name")
                    if not name or not tid or tid in tool_start_ids:
                        continue
                    tool_start_ids.add(tid)
                    yield {
                        "type": "tool",
                        "agent": agent_key,
                        "event": "start",
                        "name": str(name),
                        "input": "",
                    }
            continue

        if mode == "updates" and isinstance(data, dict):
            for _node, update in data.items():
                if not isinstance(update, dict):
                    continue
                msgs = update.get("messages")
                if not msgs:
                    continue
                for m in msgs:
                    if isinstance(m, ToolMessage):
                        nm = getattr(m, "name", None) or ""
                        preview = _truncate_preview(str(m.content))
                        yield {
                            "type": "tool",
                            "agent": agent_key,
                            "event": "end",
                            "name": str(nm),
                            "output": preview,
                        }
                    elif isinstance(m, AIMessage) and m.tool_calls:
                        for tc in m.tool_calls:
                            tid = str(tc.get("id") or "")
                            name = str(tc.get("name") or "")
                            args = tc.get("args")
                            try:
                                inp = json.dumps(args, ensure_ascii=False, indent=2) if args is not None else ""
                            except (TypeError, ValueError):
                                inp = str(args) if args is not None else ""
                            inp = _truncate_preview(inp, max_len=1500)
                            if tid and tid not in tool_start_ids:
                                tool_start_ids.add(tid)
                                yield {
                                    "type": "tool",
                                    "agent": agent_key,
                                    "event": "start",
                                    "name": name,
                                    "input": inp,
                                }
                            elif tid and tid in tool_start_ids and inp:
                                yield {
                                    "type": "tool",
                                    "agent": agent_key,
                                    "event": "args",
                                    "name": name,
                                    "input": inp,
                                }


def format_stream_event_as_markdown(ev: dict[str, Any]) -> str:
    """将单条流事件格式化为可存入会话或展示的 Markdown。"""
    t = ev.get("type")
    if t == "stage":
        title = ev.get("title") or ""
        return f"\n\n---\n\n### {title}\n\n" if title else "\n\n"
    if t == "delta":
        return ev.get("text") or ""
    if t == "tool":
        evt = ev.get("event")
        name = ev.get("name") or ""
        if evt == "start":
            inp = (ev.get("input") or "").strip()
            if inp:
                return f"\n\n**工具** `{name}`\n\n```json\n{inp}\n```\n"
            return f"\n\n**工具** `{name}` …\n"
        if evt == "args":
            inp = (ev.get("input") or "").strip()
            if not inp:
                return ""
            return f"\n\n**工具参数** `{name}`\n\n```json\n{inp}\n```\n"
        if evt == "end":
            out = ev.get("output") or ""
            return f"\n\n**工具结果** `{name}`\n\n```\n{out}\n```\n"
    return ""


def iter_investment_analysis_event_dicts(user_query: str) -> Iterator[dict[str, Any]]:
    """完整投研链：Agent1（含工具过程）→ Agent2，产出结构化事件字典。"""
    agent1_input: dict[str, Any] = {"messages": [{"role": "user", "content": user_query}]}
    capture1: dict[str, Any] = {}

    yield {"type": "stage", "agent": "agent1", "title": "意图解析与数据获取（Agent 1）"}
    for ev in iter_compiled_agent_event_dicts(agent1, agent1_input, agent_key="agent1", state_capture=capture1):
        yield ev

    msgs = capture1.get("messages")
    if not msgs:
        r1 = agent1.invoke(agent1_input)
        msgs = r1["messages"]
    parsed = parse_agent1_output({"messages": msgs})
    agent2_input = format_agent2_input(parsed)

    yield {"type": "stage", "agent": "agent2", "title": "走势分析（Agent 2）"}
    yield from iter_compiled_agent_event_dicts(agent2, agent2_input, agent_key="agent2")


def _text_from_message_chunk(token: Any) -> str:
    if isinstance(token, ToolMessage):
        return ""
    blocks = getattr(token, "content_blocks", None)
    if blocks:
        parts: list[str] = []
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text":
                t = b.get("text")
                if t:
                    parts.append(str(t))
        if parts:
            return "".join(parts)
    content = getattr(token, "content", None)
    if isinstance(content, str) and content:
        return content
    if isinstance(content, list):
        parts = []
        for x in content:
            if isinstance(x, dict) and x.get("type") == "text":
                parts.append(str(x.get("text", "")))
        return "".join(parts)
    return ""


def iter_agent2_stream(agent2_input: dict[str, Any]) -> Iterator[str]:
    """流式产出最终分析师（Agent2）的正文片段。"""
    for ev in iter_compiled_agent_event_dicts(agent2, agent2_input, agent_key="agent2"):
        if ev.get("type") == "delta" and ev.get("text"):
            yield str(ev["text"])


def iter_investment_analysis_stream(user_query: str) -> Iterator[str]:
    """完整投研流程的 Markdown 片段流（阶段标题、工具块、模型正文）。"""
    for ev in iter_investment_analysis_event_dicts(user_query):
        md = format_stream_event_as_markdown(ev)
        if md:
            yield md


def run_investment_analysis(user_query: str) -> str:
    """
    运行完整的投研分析流程（使用Chain）

    参数:
        user_query: 用户的投资分析问题

    返回:
        最终的分析报告
    """
    print("=" * 50)
    print("开始执行投研分析链...")
    print("=" * 50)

    result = "".join(iter_investment_analysis_stream(user_query))

    print("\n" + "=" * 50)
    print("最终分析报告:")
    print("=" * 50)
    print(result)

    return result

def run():
    pass