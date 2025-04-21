# mentis_client/experimental/crewai.py
from typing import Type, Optional
from pydantic import BaseModel, Field

# 尝试导入crewai，如果不可用则提供占位符类
try:
    from crewai.tools import BaseTool
except ImportError:
    # 如果crewai未安装，提供一个基本的占位符类
    class BaseTool:
        """当crewai未安装时的占位符类"""
        name: str = ""
        description: str = ""
        
        def __init__(self, *args, **kwargs):
            pass
        
        def _run(self, *args, **kwargs):
            raise NotImplementedError("crewai未安装，无法使用此工具")

from mentis_client.client import MentisSandbox, collect_observations
from ..embedded import EmbeddedMentisSandbox


class MentisIPythonToolArgs(BaseModel):
    """MentisIPythonTool的参数模型"""
    code: str = Field(..., description="在ipython单元格中执行的代码。")
    timeout: Optional[int] = Field(None, description="执行超时时间（秒）。")


class MentisIPythonTool(BaseTool):
    """用于在MentisSandbox中执行Python代码的CrewAI工具"""
    name: str = "运行Python代码"
    description: str = "在安全的沙箱环境中运行Python代码和shell命令。Shell命令应该在新行上并以'!'开头。"
    args_schema: Type[BaseModel] = MentisIPythonToolArgs

    def __init__(self, sandbox: Optional[MentisSandbox] = None, *args, **kwargs):
        """
        初始化工具。
        
        Args:
            sandbox: 现有的MentisSandbox实例。如果未提供，将创建一个嵌入式沙箱。
            *args, **kwargs: 传递给BaseTool的其他参数。
        """
        super().__init__(*args, **kwargs)
        # 如果未提供沙箱，则创建一个嵌入式沙箱
        # 注意：沙箱只有在Python程序退出时才会关闭
        self._sandbox = sandbox or EmbeddedMentisSandbox().sandbox
        self._owns_sandbox = sandbox is None  # 跟踪我们是否创建了沙箱

    def _run(self, code: str) -> str:
        """Run Python code in the sandbox and return the result."""
        action_id = self._sandbox.run_ipython_cell(code)
        observations = collect_observations(self._obs_queue, action_id)
        return "".join([obs.line for obs in observations if hasattr(obs, 'line')])
    
    def __del__(self):
        """在对象被垃圾回收时清理资源"""
        if hasattr(self, '_owns_sandbox') and self._owns_sandbox and hasattr(self, '_sandbox'):
            try:
                self._sandbox.delete()
            except Exception:
                pass  # 忽略清理错误


class MentisShellToolArgs(BaseModel):
    """MentisShellTool的参数模型"""
    command: str = Field(..., description="要执行的bash命令。")
    timeout: Optional[int] = Field(None, description="执行超时时间（秒）。")
    work_dir: Optional[str] = Field(None, description="执行命令的工作目录。")


class MentisShellTool(BaseTool):
    """用于在MentisSandbox中执行Shell命令的CrewAI工具"""
    name: str = "运行Shell命令"
    description: str = "在安全的沙箱环境中运行bash shell命令。"
    args_schema: Type[BaseModel] = MentisShellToolArgs

    def __init__(self, sandbox: Optional[MentisSandbox] = None, *args, **kwargs):
        """
        初始化工具。
        
        Args:
            sandbox: 现有的MentisSandbox实例。如果未提供，将创建一个嵌入式沙箱。
            *args, **kwargs: 传递给BaseTool的其他参数。
        """
        super().__init__(*args, **kwargs)
        # 如果未提供沙箱，则创建一个嵌入式沙箱
        self._sandbox = sandbox or EmbeddedMentisSandbox().sandbox
        self._owns_sandbox = sandbox is None  # 跟踪我们是否创建了沙箱

    def _run(self, command: str, timeout: Optional[int] = None, work_dir: Optional[str] = None) -> str:
        """
        在沙箱中执行Shell命令。
        
        Args:
            command: 要执行的Shell命令。
            timeout: 可选的执行超时时间（秒）。
            work_dir: 可选的工作目录。
            
        Returns:
            str: 执行结果。
        """
        result = self._sandbox.run_shell_command(command, timeout=timeout, work_dir=work_dir)
        return result
    
    def __del__(self):
        """在对象被垃圾回收时清理资源"""
        if hasattr(self, '_owns_sandbox') and self._owns_sandbox and hasattr(self, '_sandbox'):
            try:
                self._sandbox.delete()
            except Exception:
                pass  # 忽略清理错误