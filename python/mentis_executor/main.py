from fastapi import FastAPI, HTTPException, Response
from IPython.core.interactiveshell import InteractiveShell
from contextlib import redirect_stdout, redirect_stderr
import json
import subprocess
import io
import os
import requests
import logging

from sandboxai.api.v1 import (
    RunIPythonCellRequest,
    RunIPythonCellResult,
    RunShellCommandRequest,
    RunShellCommandResult,
)

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mentis-executor")

# Initialize FastAPI app
app = FastAPI(
    title="Mentis Executor",
    version="1.0",
    description="The server that runs python code and shell commands in a MentisSandbox environment.",
)

# Initialize IPython shell
ipy = InteractiveShell.instance()


@app.get(
    "/healthz",
    summary="Check the health of the API",
    response_model=None,
)
async def healthz():
    return {"status": "OK"}


@app.post(
    "/tools:run_ipython_cell",
    response_model=RunIPythonCellResult,
    summary="Invoke a cell in a stateful IPython (Jupyter) kernel",
)
async def run_ipython_cell(request: RunIPythonCellRequest):
    """
    Execute code in an IPython kernel and return the results.

    Args:
        request: The cell execution request containing the code to run

    Returns:
        The execution results including output, stdout, and stderr
    """
    # 从请求对象获取 action_id
    action_id = getattr(request, 'action_id', None)
    
    # 尝试从请求中获取 action_id (多种可能的方法)
    if action_id is None:
        # 尝试作为属性获取
        try:
            if hasattr(request, 'dict'):
                if callable(request.dict):
                    # 如果 dict 是一个方法
                    req_dict = request.dict()
                    if isinstance(req_dict, dict):
                        action_id = req_dict.get('action_id')
                else:
                    # 如果 dict 是一个属性
                    if isinstance(request.dict, dict):
                        action_id = request.dict.get('action_id')
        except Exception as e:
            logger.warning(f"[AGENT] Error extracting action_id: {str(e)}")
            
        # 还可以尝试从请求体获取
        try:
            if hasattr(request, 'body'):
                if isinstance(request.body, dict):
                    action_id = request.body.get('action_id')
        except Exception:
            pass
    
    # 输出日志用于调试
    logger.info(f"[AGENT] Extracted action_id: {action_id}")
    
    sandbox_id = os.environ.get('SANDBOX_ID')
    runtime_observation_url = os.environ.get('RUNTIME_OBSERVATION_URL')
    
    logger.info(f"[AGENT] Running IPython cell with action_id: {action_id}, Runtime URL: {runtime_observation_url}")
    
    try:
        if getattr(request, 'split_output', False):
            # Capture stdout and stderr separately
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()

            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                ipy.run_cell(request.code)

            stdout = stdout_buf.getvalue()
            stderr = stderr_buf.getvalue()
            
            logger.info(f"[AGENT] IPython execution complete. stdout: {len(stdout)} chars, stderr: {len(stderr)} chars")
            
            # Send observations to runtime if URL is provided
            if runtime_observation_url and action_id:
                logger.info(f"[AGENT] Sending IPython output observations to {runtime_observation_url}")
                if stdout:
                    send_observation(runtime_observation_url, {
                        "type": "stream",
                        "action_id": action_id,
                        "stream": "stdout",
                        "line": stdout
                    })
                if stderr:
                    send_observation(runtime_observation_url, {
                        "type": "stream",
                        "action_id": action_id,
                        "stream": "stderr",
                        "line": stderr
                    })
                # Always send result observation
                logger.info(f"[AGENT] Sending IPython result observation")
                send_observation(runtime_observation_url, {
                    "type": "result",
                    "action_id": action_id,
                    "exit_code": 0
                })
            else:
                logger.warning(f"[AGENT] Cannot send observations: URL={runtime_observation_url}, action_id={action_id}")

            return RunIPythonCellResult(
                stdout=stdout, stderr=stderr
            )
        else:
            # Capture combined output
            output_buf = io.StringIO()
            with redirect_stdout(output_buf), redirect_stderr(output_buf):
                ipy.run_cell(request.code)

            output = output_buf.getvalue()
            
            logger.info(f"[AGENT] IPython execution complete. Combined output: {len(output)} chars")
            
            # Send observations to runtime if URL is provided
            if runtime_observation_url and action_id:
                logger.info(f"[AGENT] Sending IPython output observations to {runtime_observation_url}")
                if output:
                    send_observation(runtime_observation_url, {
                        "type": "stream",
                        "action_id": action_id,
                        "stream": "stdout",
                        "line": output
                    })
                # Always send result observation
                logger.info(f"[AGENT] Sending IPython result observation")
                send_observation(runtime_observation_url, {
                    "type": "result",
                    "action_id": action_id,
                    "exit_code": 0
                })
            else:
                logger.warning(f"[AGENT] Cannot send observations: URL={runtime_observation_url}, action_id={action_id}")

            return RunIPythonCellResult(output=output)

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[AGENT] IPython cell execution error: {error_msg}")
        
        # Send error observation if URL is provided
        if runtime_observation_url and action_id:
            send_observation(runtime_observation_url, {
                "type": "stream",
                "action_id": action_id,
                "stream": "stderr",
                "line": error_msg
            })
            send_observation(runtime_observation_url, {
                "type": "result",
                "action_id": action_id,
                "exit_code": 1,
                "error": error_msg
            })
            
        raise HTTPException(status_code=500, detail=error_msg)


@app.post(
    "/tools:run_shell_command",
    # response_model=RunShellCommandResult, # Keep commented out
    summary="Invoke a shell command and return NDJSON.",
)
async def run_shell_command(request: RunShellCommandRequest):
    """
    Execute a shell command, capture output, and return results as NDJSON.
    NOTE: This does not stream in real-time from the agent.
    """
    logger.info(f"[AGENT] Running command synchronously: {request.command}")
    ndjson_lines = []
    error_output = None
    exit_code = -1
    
    action_id = request.action_id if hasattr(request, 'action_id') else None
    runtime_observation_url = os.environ.get('RUNTIME_OBSERVATION_URL')

    try:
        # Run the command synchronously, capturing stdout and stderr
        result = subprocess.run(
            request.command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True, # Decode output as text
            check=False # Don't raise exception on non-zero exit code
        )
        exit_code = result.returncode
        logger.info(f"[AGENT] Command finished with exit code: {exit_code}")

        # Add stdout lines to NDJSON
        if result.stdout:
            # Split stdout into lines correctly
            stdout_lines = result.stdout.strip().split('\n') if result.stdout else []
            for line in stdout_lines:
                if line: # Avoid empty lines
                    payload = json.dumps({
                        "type": "stream",
                        "stream": "stdout",
                        "line": line,
                    })
                    ndjson_lines.append(payload)
                    logger.info(f"[AGENT] Adding stdout line: {payload}")
                    
                    # Send observation to runtime if URL is provided
                    if runtime_observation_url and action_id:
                        send_observation(runtime_observation_url, {
                            "type": "stream",
                            "action_id": action_id,
                            "stream": "stdout",
                            "line": line
                        })

        # Add stderr lines to NDJSON
        if result.stderr:
            # Split stderr into lines correctly
            stderr_lines = result.stderr.strip().split('\n') if result.stderr else []
            for line in stderr_lines:
                if line: # Avoid empty lines
                    payload = json.dumps({
                        "type": "stream",
                        "stream": "stderr",
                        "line": line,
                    })
                    ndjson_lines.append(payload)
                    logger.info(f"[AGENT] Adding stderr line: {payload}")
                    
                    # Send observation to runtime if URL is provided
                    if runtime_observation_url and action_id:
                        send_observation(runtime_observation_url, {
                            "type": "stream",
                            "action_id": action_id,
                            "stream": "stderr",
                            "line": line
                        })

        # If exit code was non-zero, capture stderr as the error
        if exit_code != 0 and result.stderr:
            error_output = result.stderr.strip()

    except Exception as e:
        logger.error(f"[AGENT] Exception during command execution: {e}")
        error_output = f"Agent failed to execute command: {e}"
        
        # Send error observation to runtime if URL is provided
        if runtime_observation_url and action_id:
            send_observation(runtime_observation_url, {
                "type": "stream",
                "action_id": action_id,
                "stream": "stderr",
                "line": str(e)
            })

    # Add the final result line
    result_payload = json.dumps({
        "type": "result",
        "exit_code": exit_code,
        "error": error_output,
    })
    ndjson_lines.append(result_payload)
    logger.info(f"[AGENT] Adding final result: {result_payload}")
    
    # Send result observation to runtime if URL is provided
    if runtime_observation_url and action_id:
        send_observation(runtime_observation_url, {
            "type": "result",
            "action_id": action_id,
            "exit_code": exit_code,
            "error": error_output
        })

    # Join all NDJSON lines with newline characters
    ndjson_body = "\n".join(ndjson_lines) + "\n" # Ensure trailing newline

    logger.info("[AGENT] Returning complete NDJSON response with media_type='application/x-ndjson'")
    # 确保content_type正确，且返回的是字符串而不是bytes
    return Response(content=ndjson_body, media_type="application/x-ndjson", headers={"Content-Type": "application/x-ndjson"})


def send_observation(url, data):
    """
    Send observation data to the runtime service.
    
    Args:
        url: The URL to send the observation to
        data: The observation data to send
    """
    try:
        response = requests.post(
            url,
            json=data,
            headers={"Content-Type": "application/json"},
            timeout=5
        )
        if response.status_code >= 400:
            logger.warning(f"[AGENT] Failed to send observation to runtime: {response.status_code} {response.text}")
    except Exception as e:
        logger.warning(f"[AGENT] Exception sending observation to runtime: {e}")


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    
    logger.info(f"[AGENT] Starting Mentis Executor on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
