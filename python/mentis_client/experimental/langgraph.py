# mentis_client/experimental/langgraph.py
from typing import Type, Optional, Dict, Any, Callable, List, Union
from pydantic import BaseModel, Field

# 尝试导入langgraph，如果不可用则提供占位符类
try:
    from langgraph.graph import StateGraph, END
    from langgraph.prebuilt import ToolNode
except ImportError:
    # 如果langgraph未安装，提供基本的占位符类
    class StateGraph:
        """当langgraph未安装时的占位符类"""
        def __init__(self, *args, **kwargs):
            pass
        
        def add_node(self, *args, **kwargs):
            raise NotImplementedError("langgraph未安装，无法使用此功能")
        
        def add_edge(self, *args, **kwargs):
            raise NotImplementedError("langgraph未安装，无法使用此功能")
        
        def compile(self, *args, **kwargs):
            raise NotImplementedError("langgraph未安装，无法使用此功能")
    
    END = "__end__"
    
    class ToolNode:
        """当langgraph未安装时的占位符类"""
        def __init__(self, *args, **kwargs):
            pass

from mentis_client.client import MentisSandbox, collect_observations
from ..embedded import EmbeddedMentisSandbox


class MentisPythonToolConfig(BaseModel):
    """MentisPythonTool的配置模型"""
    name: str = Field("python_executor", description="工具的名称")
    description: str = Field("在安全的沙箱环境中执行Python代码", description="工具的描述")
    timeout: Optional[int] = Field(None, description="执行超时时间（秒）")


class MentisShellToolConfig(BaseModel):
    """MentisShellTool的配置模型"""
    name: str = Field("shell_executor", description="工具的名称")
    description: str = Field("在安全的沙箱环境中执行Shell命令", description="工具的描述")
    timeout: Optional[int] = Field(None, description="执行超时时间（秒）")
    work_dir: Optional[str] = Field(None, description="执行命令的工作目录")


class MentisPythonTool:
    """用于在MentisSandbox中执行Python代码的LangGraph工具"""
    
    def __init__(self, sandbox: Optional[MentisSandbox] = None, config: Optional[MentisPythonToolConfig] = None):
        """
        初始化工具。
        
        Args:
            sandbox: 现有的MentisSandbox实例。如果未提供，将创建一个嵌入式沙箱。
            config: 工具配置。如果未提供，将使用默认配置。
        """
        # 如果未提供沙箱，则创建一个嵌入式沙箱
        self._sandbox = sandbox or EmbeddedMentisSandbox().sandbox
        self._owns_sandbox = sandbox is None  # 跟踪我们是否创建了沙箱
        self.config = config or MentisPythonToolConfig()
    
    def _run(self, code: str) -> str:
        """Run Python code in the sandbox and return the result."""
        action_id = self._sandbox.run_ipython_cell(code)
        observations = collect_observations(self._obs_queue, action_id)
        return "".join([obs.line for obs in observations if hasattr(obs, 'line')])
    
    def as_tool(self) -> Dict[str, Any]:
        """
        将此对象转换为LangGraph工具格式。
        
        Returns:
            Dict[str, Any]: 工具定义。
        """
        return {
            "type": "function",
            "function": {
                "name": self.config.name,
                "description": self.config.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "在ipython单元格中执行的代码"
                        }
                    },
                    "required": ["code"]
                }
            }
        }
    
    def __del__(self):
        """在对象被垃圾回收时清理资源"""
        if hasattr(self, '_owns_sandbox') and self._owns_sandbox and hasattr(self, '_sandbox'):
            try:
                self._sandbox.delete()
            except Exception:
                pass  # 忽略清理错误


class MentisShellTool:
    """用于在MentisSandbox中执行Shell命令的LangGraph工具"""
    
    def __init__(self, sandbox: Optional[MentisSandbox] = None, config: Optional[MentisShellToolConfig] = None):
        """
        初始化工具。
        
        Args:
            sandbox: 现有的MentisSandbox实例。如果未提供，将创建一个嵌入式沙箱。
            config: 工具配置。如果未提供，将使用默认配置。
        """
        # 如果未提供沙箱，则创建一个嵌入式沙箱
        self._sandbox = sandbox or EmbeddedMentisSandbox().sandbox
        self._owns_sandbox = sandbox is None  # 跟踪我们是否创建了沙箱
        self.config = config or MentisShellToolConfig()
    
    def __call__(self, command: str) -> str:
        """
        在沙箱中执行Shell命令。
        
        Args:
            command: 要执行的Shell命令。
            
        Returns:
            str: 执行结果。
        """
        result = self._sandbox.run_shell_command(
            command, 
            timeout=self.config.timeout, 
            work_dir=self.config.work_dir
        )
        return result
    
    def as_tool(self) -> Dict[str, Any]:
        """
        将此对象转换为LangGraph工具格式。
        
        Returns:
            Dict[str, Any]: 工具定义。
        """
        return {
            "type": "function",
            "function": {
                "name": self.config.name,
                "description": self.config.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "要执行的bash命令"
                        }
                    },
                    "required": ["command"]
                }
            }
        }
    
    def __del__(self):
        """在对象被垃圾回收时清理资源"""
        if hasattr(self, '_owns_sandbox') and self._owns_sandbox and hasattr(self, '_sandbox'):
            try:
                self._sandbox.delete()
            except Exception:
                pass  # 忽略清理错误


class MentisToolNode:
    """用于在LangGraph中集成Mentis工具的节点工厂"""
    
    @staticmethod
    def create(
        tools: List[Union[MentisPythonTool, MentisShellTool]],
        llm: Optional[Any] = None
    ) -> ToolNode:
        """
        创建一个包含Mentis工具的LangGraph工具节点。
        
        Args:
            tools: Mentis工具列表。
            llm: 可选的语言模型实例，用于工具节点。
            
        Returns:
            ToolNode: LangGraph工具节点。
        """
        tool_definitions = [tool.as_tool() for tool in tools]
        tool_map = {tool.config.name: tool for tool in tools}
        
        def tool_executor(tool_name: str, tool_input: Dict[str, Any]) -> Any:
            if tool_name not in tool_map:
                raise ValueError(f"未知的工具: {tool_name}")
            
            tool = tool_map[tool_name]
            if isinstance(tool, MentisPythonTool):
                return tool(tool_input.get("code", ""))
            elif isinstance(tool, MentisShellTool):
                return tool(tool_input.get("command", ""))
            else:
                raise TypeError(f"不支持的工具类型: {type(tool)}")
        
        return ToolNode(tools=tool_definitions, llm=llm, tool_executor=tool_executor)