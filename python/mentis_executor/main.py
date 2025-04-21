# -*- coding: utf-8 -*-
from fastapi import FastAPI, HTTPException, Response
from IPython.core.interactiveshell import InteractiveShell
from contextlib import redirect_stdout, redirect_stderr
import json
import subprocess
import io
import os
import requests
import logging
import traceback # Import traceback
from datetime import datetime, timezone # Added for timestamp

print("<<<<<< EXECUTOR CODE VERSION: TIMESTAMP_FIXED >>>>>>", flush=True)

# Import Pydantic models from sandboxai library if possible,
# otherwise define minimal ones here if needed for request validation/typing.
# Assuming they are accessible via sandboxai.api.v1 as before
try:
    from sandboxai.api.v1 import (
        RunIPythonCellRequest,
        # RunIPythonCellResult, # Not used directly as response model anymore
        RunShellCommandRequest,
        # RunShellCommandResult, # Not used directly as response model anymore
    )
except ImportError:
    # Define minimal Pydantic models if import fails (basic structure)
    from pydantic import BaseModel, Field
    from typing import Optional
    logger.warning("Could not import Pydantic models from sandboxai.api.v1, using fallback definitions.")

    class RunIPythonCellRequest(BaseModel):
        code: str
        split_output: Optional[bool] = False
        action_id: Optional[str] = None

    class RunShellCommandRequest(BaseModel):
        command: str
        split_output: Optional[bool] = False
        action_id: Optional[str] = None


# Configure logging
# Ensure level is DEBUG to see the new logs
logging.basicConfig(level=logging.DEBUG, # <-- Set level to DEBUG
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mentis-executor")

# Initialize FastAPI app
app = FastAPI(
    title="Mentis Executor",
    version="1.0",
    description="The server that runs python code and shell commands in a MentisSandbox environment.",
)

# Initialize IPython shell
# Use a try-except block for robustness, especially in container environments
try:
    # Suppress unnecessary IPython warnings if possible during init
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # Disable noisy startup messages if possible (might depend on IPython version)
        ipy = InteractiveShell.instance(banner1='', exit_msg='')
    logger.info("IPython InteractiveShell initialized successfully.")
except Exception as ipy_init_err:
    logger.error(f"Failed to initialize IPython InteractiveShell: {ipy_init_err}", exc_info=True)
    ipy = None # Set ipy to None if initialization fails

@app.get(
    "/health",
    summary="Check the health of the API",
    response_model=None, # No response body for simple health check
    status_code=200,     # Explicitly set success status code
)
def health():
    # Optionally add checks here (e.g., is ipy initialized?)
    if ipy is None:
         # Return 503 Service Unavailable if IPython failed
         # logger.warning("Health check failed: IPython shell not available.")
         # raise HTTPException(status_code=503, detail="IPython shell not available")
         pass # For now, consider agent healthy if FastAPI is running
    return Response(status_code=200)


@app.post(
    "/tools:run_ipython_cell",
    summary="Invoke a cell in a stateful IPython (Jupyter) kernel",
    response_description="NDJSON stream of observations (stdout, stderr, result)",
    status_code=200, # Return 200 OK immediately
)
def run_ipython_cell(request: RunIPythonCellRequest):
    """
    Execute code in an IPython kernel. Observations are pushed asynchronously
    to the RUNTIME_OBSERVATION_URL.
    Returns an immediate 200 OK if the request is accepted.
    """
    if ipy is None:
        logger.error("IPython shell not initialized, cannot run cell.")
        raise HTTPException(status_code=503, detail="IPython shell not available")

    # --- Use correct action_id from request ---
    action_id = request.action_id
    # ---

    sandbox_id = os.environ.get('SANDBOX_ID')
    runtime_observation_url = os.environ.get('RUNTIME_OBSERVATION_URL')

    logger.info(f"[AGENT] Received IPython cell request. ActionID: {action_id}, SandboxID: {sandbox_id}")

    if not runtime_observation_url:
        logger.error("[AGENT] RUNTIME_OBSERVATION_URL environment variable not set. Cannot send observations.")
        # Optionally raise error if this is critical
    if action_id is None:
         logger.warning("[AGENT] action_id not found in request. Observations cannot be correlated.")
         # Optionally raise error if this is critical

    exit_code = 0
    error_message = None
    tb_lines = []

    try:
        # Capture stdout and stderr separately
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec_result = ipy.run_cell(request.code, store_history=True)

        stdout = stdout_buf.getvalue()
        stderr = stderr_buf.getvalue()

        logger.info(f"[AGENT] IPython execution finished. ActionID: {action_id}. Success: {exec_result.success}. Stdout: {len(stdout)} chars. Stderr: {len(stderr)} chars.")

        # --- Send Observations ---
        if runtime_observation_url and action_id:
            # Send stdout if any
            if stdout:
                send_observation(runtime_observation_url, {
                    "observation_type": "stream", # Correct key
                    "action_id": action_id,
                    "stream": "stdout",
                    "line": stdout
                })

            # Send stderr if any
            if stderr:
                 send_observation(runtime_observation_url, {
                    "observation_type": "stream", # Correct key
                    "action_id": action_id,
                    "stream": "stderr",
                    "line": stderr
                })

            # Send result observation
            if exec_result.error_before_exec or exec_result.error_in_exec:
                exit_code = 1
                try:
                    ex_type, ex_value, tb = ipy.InteractiveTB.get_exc_info(exec_result.error_in_exec or exec_result.error_before_exec)
                    stb = ipy.InteractiveTB.structured_traceback(ex_type, ex_value, tb)
                    tb_lines = ipy.InteractiveTB.format_structured_traceback(stb)
                    error_message = "".join(tb_lines)
                    logger.error(f"[AGENT] IPython execution error captured. ActionID: {action_id}\n{error_message}")
                except Exception as format_err:
                    logger.error(f"[AGENT] Failed to format IPython traceback. ActionID: {action_id}. Error: {format_err}")
                    error_message = str(exec_result.error_in_exec or exec_result.error_before_exec) or "Unknown IPython execution error"

                send_observation(runtime_observation_url, {
                    "observation_type": "result", # Correct key
                    "action_id": action_id,
                    "exit_code": exit_code,
                    "error": error_message
                })
            else:
                exit_code = 0
                send_observation(runtime_observation_url, {
                    "observation_type": "result", # Correct key
                    "action_id": action_id,
                    "exit_code": exit_code
                    # Include exec_result.result if needed
                    # "result_data": exec_result.result # This can be complex
                })
        else:
             logger.warning(f"[AGENT] Cannot send observations: URL={runtime_observation_url}, action_id={action_id}")

        return Response(status_code=200)

    except Exception as e:
        exit_code = -1
        error_msg = f"Internal agent error during IPython execution: {e}"
        tb_str = traceback.format_exc()
        logger.error(f"[AGENT] {error_msg}. ActionID: {action_id}\n{tb_str}")

        if runtime_observation_url and action_id:
            send_observation(runtime_observation_url, {
                "observation_type": "result", # Correct key
                "action_id": action_id,
                "exit_code": exit_code,
                "error": error_msg
            })
        raise HTTPException(status_code=500, detail=error_msg)


@app.post(
    "/tools:run_shell_command",
    summary="Invoke a shell command.",
    response_description="NDJSON stream of observations (stdout, stderr, result)",
    status_code=200, # Return 200 OK immediately
)
def run_shell_command(request: RunShellCommandRequest):
    """
    Execute a shell command. Observations are pushed asynchronously
    to the RUNTIME_OBSERVATION_URL.
    Returns an immediate 200 OK if the request is accepted.
    """
    # --- Use correct action_id from request ---
    action_id = request.action_id
     # ---

    sandbox_id = os.environ.get('SANDBOX_ID')
    runtime_observation_url = os.environ.get('RUNTIME_OBSERVATION_URL')

    logger.info(f"[AGENT] Received shell command request: '{request.command}'. ActionID: {action_id}, SandboxID: {sandbox_id}")

    if not runtime_observation_url:
        logger.error("[AGENT] RUNTIME_OBSERVATION_URL environment variable not set. Cannot send observations.")
    if action_id is None:
         logger.warning("[AGENT] action_id not found in request. Observations cannot be correlated.")

    exit_code = -1
    error_output = None

    try:
        process = subprocess.Popen(
            request.command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        stdout, stderr = process.communicate()
        exit_code = process.returncode

        logger.info(f"[AGENT] Shell command finished. ActionID: {action_id}. ExitCode: {exit_code}. Stdout: {len(stdout)} chars. Stderr: {len(stderr)} chars.")

        # --- Send Observations ---
        if runtime_observation_url and action_id:
            # Send stdout lines
            if stdout:
                stdout_lines = stdout.rstrip('\n').split('\n')
                for line in stdout_lines:
                    if line:
                        send_observation(runtime_observation_url, {
                            "observation_type": "stream", # Correct key
                            "action_id": action_id,
                            "stream": "stdout",
                            "line": line
                        })

            # Send stderr lines
            if stderr:
                stderr_lines = stderr.rstrip('\n').split('\n')
                if exit_code != 0:
                    error_output = stderr.strip()

                for line in stderr_lines:
                    if line:
                         send_observation(runtime_observation_url, {
                            "observation_type": "stream", # Correct key
                            "action_id": action_id,
                            "stream": "stderr",
                            "line": line
                        })

            # Send final result observation
            send_observation(runtime_observation_url, {
                "observation_type": "result", # Correct key
                "action_id": action_id,
                "exit_code": exit_code,
                "error": error_output,
            })
        else:
             logger.warning(f"[AGENT] Cannot send observations: URL={runtime_observation_url}, action_id={action_id}")

        return Response(status_code=200)

    except Exception as e:
        exit_code = -1
        error_msg = f"Internal agent error during shell execution: {e}"
        tb_str = traceback.format_exc()
        logger.error(f"[AGENT] {error_msg}. ActionID: {action_id}\n{tb_str}")

        if runtime_observation_url and action_id:
             send_observation(runtime_observation_url, {
                "observation_type": "result", # Correct key
                "action_id": action_id,
                "exit_code": exit_code,
                "error": error_msg
            })

        raise HTTPException(status_code=500, detail=error_msg)


def send_observation(url: str, data: dict):
    """
    Send observation data to the runtime service. Logs errors.
    Args:
        url: The URL to send the observation to.
        data: The observation data dictionary to send as JSON.
            Must include "observation_type" and "action_id".
    """
    if not url:
        # Log once if URL is missing? Or rely on caller's check?
        # logger.error("[AGENT] send_observation called with no URL.")
        return # Cannot send without URL

    action_id = data.get("action_id", "UNKNOWN") # Get action_id for logging
    obs_type = data.get("observation_type", "UNKNOWN") # Get type for logging

    # --- 确保添加 Timestamp ---
    if "timestamp" not in data:
        data["timestamp"] = datetime.now(timezone.utc).isoformat()
    # ---

    # --- 添加详细的 Debug 日志 (包含 action_id 和 observation_type) ---
    try:
        # 使用 ensure_ascii=False 以便日志中能正确显示非 ASCII 字符
        data_str = json.dumps(data, ensure_ascii=False)
    except Exception as dump_err:
        # 如果数据无法序列化为 JSON（理论上不应发生），记录错误
        logger.error(f"[AGENT SENDING] Failed to dump observation data to JSON string. ActionID: {action_id}, Type: {obs_type}, Error: {dump_err}")
        data_str = f"RAW_DATA_ERROR: {data}" # 提供原始数据快照
    # 打印即将发送的完整数据
    logger.debug(f"[AGENT SENDING] URL: {url}, ActionID: {action_id}, Type: {obs_type}, Data: {data_str}")
    # ---

    try:
        response = requests.post(
            url,
            json=data, # requests 会自动设置 Content-Type: application/json
            headers={"Content-Type": "application/json"}, # 明确设置以防万一
            timeout=10 # 设置请求超时
        )
        response.raise_for_status() # 对 4xx/5xx 状态码抛出异常
        # 发送成功后可以只记录 Info 或 Debug 级别的日志
        logger.debug(f"[AGENT] Observation sent successfully. ActionID: {action_id}, Type: {obs_type}, Status: {response.status_code}")

    except requests.exceptions.Timeout:
        logger.warning(f"[AGENT] Timeout sending observation to runtime. ActionID: {action_id}, Type: {obs_type}, URL: {url}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"[AGENT] Failed to send observation to runtime. ActionID: {action_id}, Type: {obs_type}, URL: {url}, Error: {e}")
    except Exception as e:
        # 捕获其他潜在错误
         logger.error(f"[AGENT] Unexpected error in send_observation. ActionID: {action_id}, Type: {obs_type}, Error: {e}", exc_info=True)

if __name__ == "__main__":
    import uvicorn

    # Use environment variables for configuration or defaults
    port = int(os.environ.get("MENTIS_EXECUTOR_PORT", 8000)) # Use a more specific env var name
    host = os.environ.get("MENTIS_EXECUTOR_HOST", "0.0.0.0") # Use a more specific env var name
    log_level = os.environ.get("MENTIS_EXECUTOR_LOG_LEVEL", "debug").lower() # Allow configuring log level

    # Reconfigure logging based on environment variable
    logging.basicConfig(level=log_level.upper(), # Set level based on env var
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    logger.info(f"[AGENT] Starting Mentis Executor on {host}:{port} with log level {log_level}")
    uvicorn.run(app, host=host, port=port, log_level=log_level) # Pass log_level to uvicorn