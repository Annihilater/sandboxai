# mentis_client/experimental/crewai.py
import logging
import queue
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

from mentis_client.client import MentisSandbox
from ..embedded import EmbeddedMentisSandbox

logger = logging.getLogger(__name__)

# --- Helper to ensure sandbox has a queue --- 
def _ensure_sandbox_with_queue(sandbox: Optional[MentisSandbox]) -> MentisSandbox:
    """Ensures a sandbox instance exists and has an observation queue."""
    if sandbox:
        if not sandbox._observation_queue:
            # If a sandbox is provided, it *must* have a queue configured
            raise ValueError("Provided MentisSandbox instance must be initialized with an observation_queue.")
        return sandbox
    else:
        # Create an embedded sandbox with a queue
        logger.info("No sandbox provided, creating embedded sandbox with queue for CrewAI tool.")
        # Need to create queue here as EmbeddedMentisSandbox passes kwargs
        obs_queue = queue.Queue()
        embedded_sandbox_wrapper = EmbeddedMentisSandbox(observation_queue=obs_queue)
        # The wrapper's __enter__ returns the actual MentisSandbox instance
        return embedded_sandbox_wrapper.sandbox 


class MentisIPythonToolArgs(BaseModel):
    """MentisIPythonTool的参数模型"""
    code: str = Field(..., description="在ipython单元格中执行的代码。")
    timeout: Optional[int] = Field(None, description="执行超时时间（秒）。")


class MentisIPythonTool(BaseTool):
    """用于在MentisSandbox中执行Python代码的CrewAI工具"""
    name: str = "运行Python代码"
    description: str = "在安全的沙箱环境中运行Python代码和shell命令。Shell命令应该在新行上并以'!'开头。"
    args_schema: Type[BaseModel] = MentisIPythonToolArgs

    def __init__(self, sandbox: Optional[MentisSandbox] = None, sync_timeout: float = 60.0, *args, **kwargs):
        """
        初始化工具。
        
        Args:
            sandbox: 现有的MentisSandbox实例。如果未提供，将创建一个嵌入式沙箱。
            sync_timeout: 等待同步执行结果的最长时间（秒）。
            *args, **kwargs: 传递给BaseTool的其他参数。
        """
        super().__init__(*args, **kwargs)
        self._sandbox = _ensure_sandbox_with_queue(sandbox)
        self._owns_sandbox = sandbox is None
        self._sync_timeout = sync_timeout
        # No need for self._obs_queue anymore, it's managed by the sandbox instance

    def _run(self, code: str, timeout: Optional[int] = None) -> str:
        """Run Python code in the sandbox synchronously and return the result."""
        # Note: the 'timeout' arg from the schema is passed to the server-side execution limit
        # The self._sync_timeout is used for the client-side wait.
        logger.debug(f"CrewAI Tool executing IPython code (sync timeout: {self._sync_timeout}s): {code[:100]}...")
        try:
            # Use the new synchronous method. The server-side timeout is handled by run_ipython_cell if needed.
            # We primarily rely on the client-side _wait_for_action_results timeout.
            result = self._sandbox.execute_ipython_cell_sync(code=code, timeout=self._sync_timeout)
            logger.debug(f"CrewAI Tool IPython execution result:\n{result}")
            return result
        except Exception as e:
            logger.error(f"Error executing code via CrewAI tool: {e}", exc_info=True)
            return f"Error executing code: {e}"


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

    def __init__(self, sandbox: Optional[MentisSandbox] = None, sync_timeout: float = 60.0, *args, **kwargs):
        """
        初始化工具。
        
        Args:
            sandbox: 现有的MentisSandbox实例。如果未提供，将创建一个嵌入式沙箱。
            sync_timeout: 等待同步执行结果的最长时间（秒）。
            *args, **kwargs: 传递给BaseTool的其他参数。
        """
        super().__init__(*args, **kwargs)
        self._sandbox = _ensure_sandbox_with_queue(sandbox)
        self._owns_sandbox = sandbox is None
        self._sync_timeout = sync_timeout

    def _run(self, command: str, timeout: Optional[int] = None, work_dir: Optional[str] = None) -> str:
        """
        Run a shell command in the sandbox synchronously and return the result.
        
        Args:
            command: The shell command to execute.
            timeout: Optional server-side execution timeout (seconds).
            work_dir: Optional working directory.
            
        Returns:
            str: Execution result (stdout, stderr, errors).
        """
        logger.debug(f"CrewAI Tool executing shell command (sync timeout: {self._sync_timeout}s): {command}")
        try:
            # Use the new synchronous method.
            # Pass the schema's timeout to the server-side limit if provided.
            result = self._sandbox.execute_shell_command_sync(
                command=command,
                work_dir=work_dir,
                timeout=self._sync_timeout, # Client-side wait timeout
                # The server-side timeout is passed via run_shell_command inside execute_shell_command_sync if needed, 
                # but the primary control here is the client wait timeout.
                # Consider if the API should expose both distinctly.
            )
            logger.debug(f"CrewAI Tool Shell execution result:\n{result}")
            return result
        except Exception as e:
            logger.error(f"Error executing command via CrewAI tool: {e}", exc_info=True)
            return f"Error executing command: {e}"