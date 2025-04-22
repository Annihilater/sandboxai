# -*- coding: utf-8 -*-
"""
LangGraph 示例：连接到现有的 Mentis Runtime 实例 (修复版)

**前提条件:**
1.  确保已安装所需的库:
    pip install langgraph langchain-core mentis-client httpx
2.  确保有一个 Mentis Runtime/Sandbox 实例正在运行，并且可以通过下面的 BASE_URL 访问。
"""
import logging
import operator
import queue
import os
from typing import TypedDict, Annotated, Sequence, List, Optional, Dict, Any

# --- 配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mentis-langgraph-fixed-example")
BASE_URL = os.environ.get("MENTIS_BASE_URL", "http://localhost:5266")
logger.info(f"将连接到 Mentis Runtime: {BASE_URL}")

# --- 尝试导入 LangGraph 和 LangChain 模块 ---
try:
    from langgraph.graph import StateGraph, END
    from langgraph.graph.message import add_messages
    from langgraph.prebuilt import ToolNode
    from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage, AIMessage
    # 不再需要导入 langchain_core.pydantic_v1 或定义自定义 ToolCall/FunctionCall
except ImportError as e:
    logger.error(f"导入错误: {e}. 请确保已安装 langgraph, langchain-core.")
    print("\n错误：缺少必要的库。请运行:")
    print("pip install langgraph langchain-core mentis-client httpx")
    exit(1)

# --- 导入 Mentis 客户端和 LangGraph 工具 ---
try:
    from mentis_client.client import MentisSandbox
    from mentis_client.experimental.langgraph import MentisPythonTool
except ImportError:
    logger.error("导入 mentis_client 失败。请确保已安装 mentis-client.")
    print("\n错误：缺少 mentis-client 库。请运行:")
    print("pip install mentis-client")
    exit(1)

# --- 定义状态 ---
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

# --- 初始化工具和 ToolNode ---
# (这部分代码保持不变)
try:
    logger.info(f"初始化 MentisSandbox，连接到现有 Runtime: {BASE_URL}...")
    obs_queue: queue.Queue = queue.Queue()
    sandbox = MentisSandbox.create(
        base_url=BASE_URL,
        observation_queue=obs_queue
    )
    python_tool = MentisPythonTool(sandbox=sandbox, sync_timeout=120.0)

    if not hasattr(python_tool, 'name'):
         logger.warning("MentisPythonTool 实例似乎没有 'name' 属性。将使用默认名称 'mentis_python_executor'。请验证这是否正确。")
         MENTIS_TOOL_NAME = "mentis_python_executor"
    else:
         MENTIS_TOOL_NAME = python_tool.name
         logger.info(f"Mentis Python 工具 '{MENTIS_TOOL_NAME}' 初始化成功。")

    tools = [python_tool]
    tool_node = ToolNode(tools)
    logger.info("ToolNode 初始化成功。")

except Exception as e:
    logger.exception("初始化 Mentis 工具或 ToolNode 时发生严重错误。")
    raise

# --- 定义节点 ---

# 1. Agent 节点 (模拟 LLM 决策)
def agent_node(state: AgentState):
    """模拟 Agent 行为：接收消息，决定是否调用工具。"""
    logger.debug(f"--- Agent Node 开始 ---")

    # *** 确保这部分代码存在 ***
    current_messages = state['messages']
    # 添加一个检查，以防消息列表为空（虽然在图的这个点通常不会）
    if not current_messages:
        logger.warning("Agent Node 收到空消息列表，无法处理。")
        # 可以返回一个错误消息或空更新
        return {"messages": [AIMessage(content="错误：消息列表为空。")]}

    last_message = current_messages[-1] # 定义 last_message
    logger.info(f"Agent Node 收到最后一条消息类型: {type(last_message).__name__}")
    logger.debug(f"最后一条消息内容: {getattr(last_message, 'content', '[无内容]')}")
    # *** 结束确保部分 ***

    # 现在这个 if 语句应该可以正常工作了
    if isinstance(last_message, HumanMessage):
        logger.info("Agent 收到 HumanMessage，决定调用工具执行 Python 代码。")
        code_to_run = "import datetime; now = datetime.datetime.now(); print(f'Hello from LangGraph via Mentis Sandbox at {now}'); result = 2 + 3; print(f'Calculation: 2 + 3 = {result}'); result"
        logger.info(f"Agent 准备运行代码: {code_to_run}")
        tool_call_id = f"call_mentis_{hash(code_to_run)}_{len(current_messages)}"

        ai_message = AIMessage(
            content="好的，我将在连接的 Mentis 沙箱中为您执行这段 Python 代码。",
            tool_calls=[
                {
                    "id": tool_call_id,
                    "name": MENTIS_TOOL_NAME,
                    "args": {"code": code_to_run}
                }
            ]
        )
        logger.info(f"Agent 生成了包含工具调用 (ID: {tool_call_id}, Name: {MENTIS_TOOL_NAME}) 的 AIMessage。")
        return {"messages": [ai_message]}

    elif isinstance(last_message, ToolMessage):
        logger.info("Agent 收到 ToolMessage (工具执行结果)，流程即将结束。")
        final_response = AIMessage(content=f"工具 '{MENTIS_TOOL_NAME}' 已执行。流程结束。")
        logger.debug("Agent 生成最终响应消息。")
        return {"messages": [final_response]}

    elif isinstance(last_message, AIMessage):
        # ... (逻辑不变)
        if not getattr(last_message, 'tool_calls', None) or not last_message.tool_calls:
             logger.info("Agent 收到不含工具调用的 AIMessage，视为流程结束信号。")
             return {}
        else:
            logger.warning("Agent Node 异常地收到了包含 tool_calls 的 AIMessage。为防止循环，将强制结束。")
            return {"messages": [AIMessage(content="检测到意外状态，强制结束。")]}
    else:
        # ... (逻辑不变)
        logger.warning(f"Agent Node 收到未处理的消息类型: {type(last_message).__name__}。流程结束。")
        return {"messages": [AIMessage(content="收到未知消息类型，流程结束。")]}

# --- 定义图的条件边 ---
# (这部分代码保持不变)
def should_continue(state: AgentState) -> str:
    """决定下一步是调用工具还是结束流程。"""
    logger.debug(f"--- Conditional Edge 'should_continue' 开始 ---")
    last_message = state['messages'][-1]
    logger.info(f"Conditional Edge 检查最后消息类型: {type(last_message).__name__}")

    # **标准检查**: 如果最后的消息是 AI 发出的，并且包含有效的工具调用请求
    # getattr(..., None) 用于安全访问，然后检查 tool_calls 是否为真（非空列表）
    if isinstance(last_message, AIMessage) and getattr(last_message, "tool_calls", None):
        if last_message.tool_calls: # 确保列表不为空
            logger.info(f"检测到 AIMessage 中的 tool_calls (数量: {len(last_message.tool_calls)})。路由到 ToolNode。")
            return "sandbox_tool"
        else:
            logger.info("检测到 AIMessage，但其 tool_calls 列表为空。路由到 END。")
            return END
    else:
        logger.info("最后消息不是带工具调用的 AIMessage。路由到 END。")
        return END

# --- 构建图 ---
# (这部分代码保持不变)
logger.info("开始构建 LangGraph...")
graph_builder = StateGraph(AgentState)
graph_builder.add_node("agent", agent_node)
graph_builder.add_node("sandbox_tool", tool_node)
graph_builder.set_entry_point("agent")
graph_builder.add_conditional_edges(
    "agent",
    should_continue,
    {
        "sandbox_tool": "sandbox_tool",
        END: END
    }
)
graph_builder.add_edge("sandbox_tool", "agent")

# --- 编译图 ---
# (这部分代码保持不变)
try:
    graph = graph_builder.compile()
    logger.info("LangGraph 编译成功。")
except Exception as e:
    logger.exception("LangGraph 编译失败。")
    raise

# --- 运行图 ---
# (这部分代码基本保持不变, 确保 Python 3.8+ 支持海象运算符 :=)
if __name__ == "__main__":
    print("\n" + "="*30)
    print("--- 开始 LangGraph 执行 ---")
    print("="*30)
    # ... (其余打印和执行逻辑不变) ...

    initial_input = {"messages": [HumanMessage(content="你好，请帮我运行一段 Python 代码来打印当前时间和计算 2+3。")]}
    final_state = None

    try:
        print("开始流式执行图...\n")
        # 注意：Python 3.8+ 才支持 := 运算符
        for step, state_update in enumerate(graph.stream(initial_input, stream_mode="values")):
            final_state = state_update
            print(f"--- 第 {step + 1} 步 ---")
            # 使用 get 方法安全访问 messages
            messages = final_state.get('messages', [])
            if messages: # 确保消息列表不为空
                last_msg = messages[-1]
                print(f"节点输出类型: {type(last_msg).__name__}")
                print(f"消息内容: {getattr(last_msg, 'content', '[无内容]')}")
                # 安全检查 tool_calls
                tool_calls = getattr(last_msg, 'tool_calls', None)
                if isinstance(last_msg, AIMessage) and tool_calls:
                    print(f"工具调用请求: {tool_calls}")
                if isinstance(last_msg, ToolMessage):
                    print(f"工具调用 ID: {last_msg.tool_call_id}")
                    print(f"工具执行结果 (部分): {str(last_msg.content)[:200]}...")
            else:
                print("状态更新中无消息。")
            print("-" * 20)

        print("\n" + "="*30)
        print("--- LangGraph 执行完成 ---")
        print("="*30)
        print("最终状态消息:")

        if final_state and final_state.get('messages'):
             for i, msg in enumerate(final_state['messages']):
                 print(f"  {i+1}. 类型: {type(msg).__name__}")
                 print(f"     内容: {msg.content}")
                 tool_calls = getattr(msg, 'tool_calls', None)
                 if isinstance(msg, AIMessage) and tool_calls:
                     print(f"     工具调用: {tool_calls}")
                 if isinstance(msg, ToolMessage):
                     print(f"     工具调用 ID: {msg.tool_call_id}")
        else:
             print("  未能获取最终状态或最终状态中没有消息。")

    except Exception as e:
        logger.exception("图执行过程中发生严重错误。")
        print(f"\n!!! 图执行出错: {e} !!!")
        if final_state:
             print("\n最后已知状态:")
             # 使用 pprint 获得更易读的字典输出
             import pprint
             pprint.pprint(final_state)

    finally:
        # --- 清理资源 ---
        # (这部分代码保持不变)
        if 'sandbox' in locals() and sandbox is not None:
            logger.info("尝试关闭 Mentis Sandbox 客户端连接...")
            try:
                if hasattr(sandbox, 'close') and callable(sandbox.close):
                     sandbox.close()
                     logger.info("已调用 sandbox.close()")
                elif hasattr(sandbox, '_client') and hasattr(sandbox._client, 'close') and callable(sandbox._client.close):
                     sandbox._client.close()
                     logger.info("已调用 sandbox._client.close()")
                else:
                     logger.warning("无法找到合适的 close 方法来关闭 Mentis Sandbox 连接。")
            except Exception as e:
                logger.warning(f"关闭 Mentis Sandbox 客户端连接时出错: {e}")
        else:
            logger.info("无需关闭 Mentis Sandbox 连接。")

        print("\n" + "="*30)
        print("--- 示例脚本结束 ---")
        print("Mentis Runtime (如果之前在运行) 应保持运行状态。")
        print("="*30)