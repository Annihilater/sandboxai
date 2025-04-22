# mentis_client/experimental/langgraph.py
import logging
import queue
import asyncio
import traceback
import functools
from typing import Type, Optional, Dict, Any, List, Union
from pydantic import BaseModel, Field, PrivateAttr

# Attempt to import BaseTool, handle ImportError
try:
    from langchain_core.tools import BaseTool
    LANGCHAIN_CORE_AVAILABLE = True
except ImportError:
    # Define a dummy BaseTool if langchain_core is not available
    class BaseTool:
        name: str = "dummy_tool"
        description: str = "Dummy tool"
        args_schema: Optional[Type[BaseModel]] = None
        
        def _run(self, *args: Any, **kwargs: Any) -> str:
            raise NotImplementedError("langchain_core not installed")
            
        async def _arun(self, *args: Any, **kwargs: Any) -> str:
            raise NotImplementedError("langchain_core not installed")

    LANGCHAIN_CORE_AVAILABLE = False
    logging.warning("langchain_core not installed. Mentis LangGraph tools will inherit from a dummy BaseTool.")


# Attempt to import langgraph components
try:
    from langgraph.graph import StateGraph, END
    from langgraph.prebuilt import ToolNode
    LANGGRAPH_AVAILABLE = True
except ImportError:
    # Define dummy classes if langgraph is not installed
    class StateGraph:
        def __init__(self, *args, **kwargs): pass
        def add_node(self, *args, **kwargs): raise NotImplementedError("langgraph not installed")
        def add_edge(self, *args, **kwargs): raise NotImplementedError("langgraph not installed")
        def compile(self, *args, **kwargs): raise NotImplementedError("langgraph not installed")
    END = "__end__"
    class ToolNode:
        # Make ToolNode callable even if langgraph isn't installed, to avoid immediate errors
        # It will raise NotImplementedError only when actually called.
        def __init__(self, *args, **kwargs):
            self.tools = kwargs.get('tools', [])
        def __call__(self, *args, **kwargs):
             raise NotImplementedError("langgraph not installed, ToolNode cannot be executed")
            
    LANGGRAPH_AVAILABLE = False
    logging.warning("langgraph not installed. LangGraph-specific features are unavailable.")

from mentis_client.client import MentisSandbox
from ..embedded import EmbeddedMentisSandbox, start_server, stop_server # Ensure imports are correct

logger = logging.getLogger(__name__)

# --- Helper to ensure sandbox has a queue ---
def _ensure_sandbox_with_queue(sandbox: Optional[MentisSandbox]) -> MentisSandbox:
    """Ensures a sandbox instance exists and has an observation queue."""
    if sandbox:
        if not hasattr(sandbox, '_observation_queue') or not sandbox._observation_queue:
             logger.warning("Provided MentisSandbox instance missing observation_queue, attempting to add one.")
             sandbox._observation_queue = queue.Queue()
        return sandbox
    else:
        logger.info("No sandbox provided, creating embedded sandbox with queue for LangGraph tool.")
        obs_queue = queue.Queue()
        try:
            embedded_sandbox_wrapper = EmbeddedMentisSandbox(observation_queue=obs_queue)
            if hasattr(embedded_sandbox_wrapper, 'sandbox') and isinstance(embedded_sandbox_wrapper.sandbox, MentisSandbox):
                 # Ensure the queue is set on the actual sandbox instance if the wrapper holds it
                 if not embedded_sandbox_wrapper.sandbox._observation_queue:
                     embedded_sandbox_wrapper.sandbox._observation_queue = obs_queue
                 return embedded_sandbox_wrapper.sandbox
            elif isinstance(embedded_sandbox_wrapper, MentisSandbox):
                 return embedded_sandbox_wrapper
            else:
                 raise TypeError("EmbeddedMentisSandbox did not provide a valid MentisSandbox instance.")
        except Exception as e:
            logger.error(f"Failed to create embedded sandbox: {e}", exc_info=True)
            raise RuntimeError(f"Could not create or obtain a MentisSandbox: {e}")


# --- Input Schemas ---
class MentisPythonToolInput(BaseModel):
    """Input schema for MentisPythonTool."""
    code: str = Field(description="The Python code to execute in the sandbox.")

class MentisShellToolInput(BaseModel):
    """Input schema for MentisShellTool."""
    command: str = Field(description="The shell command to execute in the sandbox.")
    work_dir: Optional[str] = Field(None, description="Optional working directory for the command.")


# --- Mentis Python Tool ---
class MentisPythonTool(BaseTool):
    """
    Executes Python code within a secure Mentis Sandbox environment.
    """
    name: str = "mentis_python_executor"
    description: str = (
        "Executes Python code in a secure, isolated sandbox environment. "
        "Input MUST be a JSON object with a 'code' key containing the Python code string. "
        "Use 'print()' to output results. Returns a string containing the execution result (stdout/stderr)."
    )
    args_schema: Type[BaseModel] = MentisPythonToolInput

    # Use PrivateAttr for internal state not part of the schema
    _sandbox: Optional[MentisSandbox] = PrivateAttr(default=None)
    _owns_sandbox: bool = PrivateAttr(default=False)
    # sync_timeout is a configuration field, so keep Field()
    sync_timeout: float = Field(default=60.0) 

    def __init__(self, sandbox: Optional[MentisSandbox] = None, sync_timeout: float = 60.0, **kwargs):
        super().__init__(**kwargs) # Call super().__init__ first
        try:
            # Initialize private attributes directly
            self._sandbox = _ensure_sandbox_with_queue(sandbox)
            self._owns_sandbox = sandbox is None
            # sync_timeout is handled by Pydantic/BaseTool initialization if passed via kwargs
            # If passed directly, assign it. BaseTool might handle this automatically.
            # Let's explicitly assign it for clarity if it's a direct arg.
            self.sync_timeout = sync_timeout 
        except Exception as e:
            logger.error(f"Failed to initialize MentisPythonTool sandbox: {e}", exc_info=True)
            self._sandbox = None # Ensure sandbox is None if init fails

    def _run(self, code: str) -> str:
        """Execute Python code synchronously."""
        logger.debug(f"Executing Python code (sync timeout: {self.sync_timeout}s): {code[:100]}...")
        if not self._sandbox:
             return "Error: Mentis Sandbox is not available (failed during initialization)."
        try:
            result = self._sandbox.execute_ipython_cell_sync(code=code, timeout=self.sync_timeout)
            logger.debug(f"Python execution result:\n{result}")
            return str(result) if result is not None else "Execution finished with no output."
        except Exception as e:
            logger.error(f"Error executing Python code via tool: {e}", exc_info=True)
            tb_str = traceback.format_exc()
            # Escape newlines for the final string
            escaped_tb = tb_str.replace('\n', '\\n').replace('\r', '\\r') # Also escape carriage returns
            return f"Error executing code: {type(e).__name__}: {e}\n{escaped_tb}"

    async def _arun(self, code: str) -> str:
        """Execute Python code asynchronously."""
        logger.debug(f"Executing Python code asynchronously (timeout: {self.sync_timeout}s): {code[:100]}...")
        if not self._sandbox:
             return "Error: Mentis Sandbox is not available (failed during initialization)."
             
        if hasattr(self._sandbox, 'execute_ipython_cell_async'):
            try:
                result = await self._sandbox.execute_ipython_cell_async(code=code, timeout=self.sync_timeout)
                logger.debug(f"Async Python execution result:\n{result}")
                return str(result) if result is not None else "Execution finished with no output."
            except Exception as e:
                logger.error(f"Error executing async Python code via tool: {e}", exc_info=True)
                tb_str = traceback.format_exc()
                # Escape newlines for the final string
                escaped_tb = tb_str.replace('\n', '\\n').replace('\r', '\\r')
                return f"Error executing async code: {type(e).__name__}: {e}\n{escaped_tb}"
        else:
            logger.warning("Async method not found on sandbox, running sync method in executor.")
            try:
                loop = asyncio.get_running_loop()
                sync_run_with_args = functools.partial(self._run, code=code)
                result = await loop.run_in_executor(None, sync_run_with_args)
                return result
            except Exception as e:
                logger.error(f"Error running sync Python code in executor: {e}", exc_info=True)
                tb_str = traceback.format_exc()
                # Escape newlines for the final string
                escaped_tb = tb_str.replace('\n', '\\n').replace('\r', '\\r')
                return f"Error in async wrapper: {type(e).__name__}: {e}\n{escaped_tb}"

    def close(self):
        """Clean up resources, especially if the tool owns the sandbox."""
        if self._owns_sandbox and self._sandbox:
            logger.info("Closing owned Mentis Sandbox...")
            try:
                if hasattr(self._sandbox, 'delete'):
                    self._sandbox.delete()
                logger.info("Owned Mentis Sandbox closed.")
            except Exception as e:
                logger.error(f"Error closing owned Mentis Sandbox: {e}", exc_info=True)
            finally:
                self._sandbox = None

    model_config = {
        "arbitrary_types_allowed": True
    }


# --- Mentis Shell Tool ---
class MentisShellTool(BaseTool):
    """
    Executes shell commands within a secure Mentis Sandbox environment.
    """
    name: str = "mentis_shell_executor"
    description: str = (
        "Executes shell commands in a secure, isolated sandbox environment. "
        "Input MUST be a JSON object with a 'command' key containing the shell command string. "
        "Optionally include 'work_dir' for the working directory. "
        "Returns a string containing the execution result (stdout/stderr)."
    )
    args_schema: Type[BaseModel] = MentisShellToolInput

    # Use PrivateAttr for internal state
    _sandbox: Optional[MentisSandbox] = PrivateAttr(default=None)
    _owns_sandbox: bool = PrivateAttr(default=False)
    # sync_timeout is configuration
    sync_timeout: float = Field(default=60.0)

    def __init__(self, sandbox: Optional[MentisSandbox] = None, sync_timeout: float = 60.0, **kwargs):
        super().__init__(**kwargs) # Call super().__init__ first
        try:
            # Initialize private attributes directly
            self._sandbox = _ensure_sandbox_with_queue(sandbox)
            self._owns_sandbox = sandbox is None
            # Explicitly assign sync_timeout for clarity
            self.sync_timeout = sync_timeout
        except Exception as e:
            logger.error(f"Failed to initialize MentisShellTool sandbox: {e}", exc_info=True)
            self._sandbox = None # Ensure sandbox is None if init fails

    def _run(self, command: str, work_dir: Optional[str] = None) -> str:
        """Execute shell command synchronously."""
        logger.debug(f"Executing shell command (sync timeout: {self.sync_timeout}s, work_dir: {work_dir}): {command}")
        if not self._sandbox:
             return "Error: Mentis Sandbox is not available (failed during initialization)."
        try:
            result = self._sandbox.execute_shell_command_sync(
                command=command,
                work_dir=work_dir,
                timeout=self.sync_timeout
            )
            logger.debug(f"Shell execution result:\n{result}")
            return str(result) if result is not None else "Execution finished with no output."
        except Exception as e:
            logger.error(f"Error executing shell command via tool: {e}", exc_info=True)
            tb_str = traceback.format_exc()
            # Escape newlines for the final string
            escaped_tb = tb_str.replace('\n', '\\n').replace('\r', '\\r')
            return f"Error executing command: {type(e).__name__}: {e}\n{escaped_tb}"

    async def _arun(self, command: str, work_dir: Optional[str] = None) -> str:
        """Execute shell command asynchronously."""
        logger.debug(f"Executing shell command asynchronously (timeout: {self.sync_timeout}s, work_dir: {work_dir}): {command}")
        if not self._sandbox:
             return "Error: Mentis Sandbox is not available (failed during initialization)."
             
        if hasattr(self._sandbox, 'execute_shell_command_async'):
             try:
                 result = await self._sandbox.execute_shell_command_async(
                     command=command,
                     work_dir=work_dir,
                     timeout=self.sync_timeout
                 )
                 logger.debug(f"Async Shell execution result:\n{result}")
                 return str(result) if result is not None else "Execution finished with no output."
             except Exception as e:
                 logger.error(f"Error executing async shell command via tool: {e}", exc_info=True)
                 tb_str = traceback.format_exc()
                 # Escape newlines for the final string
                 escaped_tb = tb_str.replace('\n', '\\n').replace('\r', '\\r')
                 return f"Error executing async command: {type(e).__name__}: {e}\n{escaped_tb}"
        else:
            logger.warning("Async method not found on sandbox, running sync shell method in executor.")
            try:
                loop = asyncio.get_running_loop()
                sync_run_with_args = functools.partial(self._run, command=command, work_dir=work_dir)
                result = await loop.run_in_executor(None, sync_run_with_args)
                return result
            except Exception as e:
                logger.error(f"Error running sync shell command in executor: {e}", exc_info=True)
                tb_str = traceback.format_exc()
                # Escape newlines for the final string
                escaped_tb = tb_str.replace('\n', '\\n').replace('\r', '\\r')
                return f"Error in async wrapper: {type(e).__name__}: {e}\n{escaped_tb}"

    def close(self):
        """Clean up resources."""
        if self._owns_sandbox and self._sandbox:
            logger.info("Closing owned Mentis Sandbox (Shell Tool)...")
            try:
                if hasattr(self._sandbox, 'delete'):
                    self._sandbox.delete()
                logger.info("Owned Mentis Sandbox closed (Shell Tool).")
            except Exception as e:
                logger.error(f"Error closing owned Mentis Sandbox (Shell Tool): {e}", exc_info=True)
            finally:
                self._sandbox = None

    model_config = {
        "arbitrary_types_allowed": True
    }

# Note: The ToolNode in langgraph expects a list of tools that are either
# BaseTool instances or functions decorated with @tool.
# Now that MentisPythonTool and MentisShellTool inherit from BaseTool,
# they can be directly passed in a list to ToolNode.