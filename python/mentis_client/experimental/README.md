# Mentis沙箱实验性功能

本目录包含Mentis沙箱的实验性功能和集成。这些功能可能在未来版本中发生变化或被移除，请谨慎使用。

## 目前支持的集成

- [CrewAI](#crewai集成) - 将Mentis沙箱与CrewAI代理框架集成
- [LangGraph](#langgraph集成) - 将Mentis沙箱与LangGraph代理框架集成

## 安装依赖

要使用实验性功能，您需要安装相应的依赖：

```bash
# 安装CrewAI集成所需依赖
pip install crewai

# 安装LangGraph集成所需依赖
pip install langgraph
```

## CrewAI集成

CrewAI集成允许您在CrewAI代理中使用Mentis沙箱执行Python代码和Shell命令。

### 基本用法

```python
from mentis_client.experimental import MentisIPythonTool, MentisShellTool
from crewai import Agent, Task, Crew

# 创建Mentis工具
python_tool = MentisIPythonTool()
shell_tool = MentisShellTool()

# 创建使用Mentis工具的代理
data_scientist = Agent(
    role="数据科学家",
    goal="分析数据并生成见解",
    backstory="你是一位经验丰富的数据科学家，擅长数据分析和可视化。",
    tools=[python_tool, shell_tool]
)

# 创建任务
analysis_task = Task(
    description="分析提供的数据集并生成摘要统计信息",
    agent=data_scientist
)

# 创建并运行Crew
crew = Crew(
    agents=[data_scientist],
    tasks=[analysis_task]
)

result = crew.kickoff()
print(result)
```

### 高级用法

您可以在初始化工具时提供现有的沙箱实例：

```python
from mentis_client import MentisSandbox
from mentis_client.experimental import MentisIPythonTool, MentisShellTool

# 创建沙箱实例
sandbox = MentisSandbox.create()

# 使用现有沙箱创建工具
python_tool = MentisIPythonTool(sandbox=sandbox)
shell_tool = MentisShellTool(sandbox=sandbox)
```

## LangGraph集成

LangGraph集成允许您在LangGraph工作流中使用Mentis沙箱执行Python代码和Shell命令。

### 基本用法

```python
from mentis_client.experimental import MentisPythonTool, LangGraphMentisShellTool, MentisToolNode
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI

# 创建语言模型
llm = ChatOpenAI()

# 创建Mentis工具
python_tool = MentisPythonTool()
shell_tool = LangGraphMentisShellTool()

# 创建工具节点
tool_node = MentisToolNode.create(tools=[python_tool, shell_tool], llm=llm)

# 创建状态图
workflow = StateGraph()

# 添加节点
workflow.add_node("tool_executor", tool_node)

# 添加边
workflow.add_edge("tool_executor", END)

# 编译图
executable = workflow.compile()

# 执行图
result = executable.invoke({"input": "分析以下数据并生成摘要统计信息"})
print(result)
```

### 高级用法

您可以自定义工具配置：

```python
from mentis_client.experimental import MentisPythonTool, LangGraphMentisShellTool, MentisPythonToolConfig, MentisShellToolConfig

# 自定义Python工具配置
python_config = MentisPythonToolConfig(
    name="python_executor",
    description="在安全的沙箱环境中执行Python数据分析代码",
    timeout=60  # 设置超时时间为60秒
)

# 自定义Shell工具配置
shell_config = MentisShellToolConfig(
    name="shell_executor",
    description="在安全的沙箱环境中执行数据处理命令",
    timeout=30,  # 设置超时时间为30秒
    work_dir="/data"  # 设置工作目录
)

# 创建自定义配置的工具
python_tool = MentisPythonTool(config=python_config)
shell_tool = LangGraphMentisShellTool(config=shell_config)
```

## 注意事项

- 实验性功能可能在未来版本中发生变化或被移除。
- 请确保您的环境中已安装相应的依赖（CrewAI或LangGraph）。
- 沙箱资源会在工具对象被垃圾回收时自动清理，但建议在不再需要时显式调用`delete()`方法释放资源。

## 贡献

欢迎为Mentis沙箱的实验性功能做出贡献。如果您有任何建议或发现问题，请提交issue或pull request。