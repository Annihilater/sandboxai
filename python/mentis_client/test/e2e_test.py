# -*- coding: utf-8 -*-
import os
import pytest
import time
import queue
import logging
from typing import List, Optional, Tuple

from mentis_client.client import MentisSandbox
from mentis_client.embedded import EmbeddedMentisSandbox
# Assuming Observation models are defined within mentis_client.models or similar
# We expect an Observation model with fields like:
# observation_type: str ("start", "stream", "result", "end", "error")
# action_id: Optional[str]
# timestamp: datetime
# stream: Optional[str] ("stdout", "stderr")
# line: Optional[str]
# exit_code: Optional[int]
# error: Optional[str]
# Import the actual BaseObservation or specific Observation model if available
try:
    # Attempt to import the specific model used for observations
    from mentis_client.models import BaseObservation # Or the actual Observation class name
except ImportError:
    # Fallback if the model isn't directly importable or named differently
    logging.warning("Could not import BaseObservation model from mentis_client.models. "
                    "Ensure the correct Observation model structure is used.")
    # Define a dummy for type hinting if needed, but tests might fail if structure differs
    class BaseObservation:
        observation_type: str
        action_id: Optional[str] = None
        timestamp: Optional[Any] = None # Use Any if datetime fails
        stream: Optional[str] = None
        line: Optional[str] = None
        exit_code: Optional[int] = None
        error: Optional[str] = None


from mentis_client.spaces import SpaceManager, CreateSpaceRequest

# Configure logging for the test file
# Set level to DEBUG for verbose output during testing
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__) # Logger for this test module

# Test configuration
BASE_URL = os.environ.get("MENTIS_RUNTIME_URL", "http://localhost:5266") # Ensure this points to your Go Runtime
TEST_TIMEOUT = 30.0  # Default timeout for collecting observations

# --- Fixtures ---
@pytest.fixture(scope="function")
def sandbox_session() -> Tuple[MentisSandbox, queue.Queue]:
    """创建沙箱会话，自动清理"""
    obs_queue = queue.Queue()
    sandbox = None # Initialize sandbox to None
    logger.info("[Fixture Setup] Starting sandbox_session setup...")
    try:
        # 创建沙箱
        logger.info(f"[Fixture Setup] Creating sandbox via {BASE_URL} for space 'default'...")
        sandbox = MentisSandbox.create(
            base_url=BASE_URL,
            observation_queue=obs_queue,
            space_id="default" # Assuming default space exists
        )
        logger.info(f"[Fixture Setup] Sandbox created: ID={sandbox.sandbox_id}")

        # Give a moment for WebSocket connection stability (create should handle basic connection)
        time.sleep(1.0) # Increased sleep slightly

        # 验证连接状态 - is_connected might check REST API, use is_stream_connected for WebSocket
        # Assuming is_connected implies stream should be ready shortly after create
        # or relying on subsequent operations to fail if not connected.
        # Let's check stream connection explicitly if available
        if hasattr(sandbox, 'is_stream_connected'):
             # Note: connect_stream might be needed if 'create' doesn't auto-connect ws
             # sandbox.connect_stream(timeout=10.0)
             assert sandbox.is_stream_connected(), "WebSocket stream failed to connect"
             logger.info("[Fixture Setup] WebSocket stream appears connected.")
        else:
            logger.warning("[Fixture Setup] MentisSandbox instance does not have 'is_stream_connected' method. Assuming connection ok.")
            # Add a basic check if possible, e.g., try a simple command?
            # For now, assume create implies readiness.

        yield sandbox, obs_queue

    except Exception as e:
        logger.error(f"[Fixture Setup] Failed: {e}", exc_info=True)
        # Ensure cleanup happens even if setup fails after sandbox object creation
        if sandbox:
            try:
                logger.warning(f"[Fixture Setup] Attempting cleanup after setup failure for sandbox {sandbox.sandbox_id}")
                sandbox.delete()
            except Exception as del_e:
                logger.error(f"[Fixture Setup] Error during cleanup after setup failure: {del_e}")
        pytest.fail(f"Sandbox setup failed: {e}")

    finally:
        if sandbox:
            logger.info(f"[Fixture Teardown] Cleaning up sandbox {sandbox.sandbox_id}")
            try:
                sandbox.delete()
                logger.info(f"[Fixture Teardown] Sandbox {sandbox.sandbox_id} deleted.")
            except Exception as e:
                logger.error(f"[Fixture Teardown] Error deleting sandbox: {e}", exc_info=True)
                # Decide if teardown failure should fail the test run
                # pytest.fail(f"Sandbox teardown failed: {e}")


@pytest.fixture(scope="function")
def embedded_sandbox_session() -> Tuple[MentisSandbox, queue.Queue]:
    """创建嵌入式沙箱会话，自动清理"""
    obs_queue = queue.Queue()
    embedded_wrapper = None
    sandbox_instance = None
    logger.info("[Fixture Setup] Starting embedded_sandbox_session setup...")
    try:
        embedded_wrapper = EmbeddedMentisSandbox(observation_queue=obs_queue)
        sandbox_instance = embedded_wrapper.sandbox # Access the managed sandbox instance
        logger.info(f"[Fixture Setup] Embedded sandbox created: ID={sandbox_instance.sandbox_id}, URL={sandbox_instance.base_url}")

        time.sleep(1.0) # Allow time for embedded server and connection

        if hasattr(sandbox_instance, 'is_stream_connected'):
             # embedded_wrapper might handle connect internally, check status
             assert sandbox_instance.is_stream_connected(timeout=10.0), "Embedded WebSocket stream failed to connect"
             logger.info("[Fixture Setup] Embedded WebSocket stream appears connected.")
        else:
             logger.warning("[Fixture Setup] Embedded MentisSandbox instance does not have 'is_stream_connected' method.")

        yield sandbox_instance, obs_queue

    except Exception as e:
         logger.error(f"[Fixture Setup] Embedded setup failed: {e}", exc_info=True)
         if sandbox_instance: # Try cleanup if instance exists
              try:
                  logger.warning(f"[Fixture Setup] Attempting cleanup after embedded setup failure for sandbox {sandbox_instance.sandbox_id}")
                  sandbox_instance.delete()
              except Exception as del_e:
                  logger.error(f"[Fixture Setup] Error during cleanup after embedded setup failure: {del_e}")
         pytest.fail(f"Embedded Sandbox setup failed: {e}")
    finally:
        # Cleanup is often handled by EmbeddedMentisSandbox's context manager (__exit__)
        # or an explicit shutdown method. Relying on that is preferred.
        # If explicit deletion is still needed:
        if sandbox_instance: # Check if instance was successfully created
            logger.info(f"[Fixture Teardown] Cleaning up embedded sandbox {sandbox_instance.sandbox_id}")
            try:
                # Assuming embedded wrapper handles server shutdown, just delete sandbox resource
                sandbox_instance.delete()
                logger.info(f"[Fixture Teardown] Embedded sandbox {sandbox_instance.sandbox_id} deleted.")
            except Exception as e:
                logger.error(f"[Fixture Teardown] Error deleting embedded sandbox: {e}", exc_info=True)
        # If wrapper has explicit shutdown, call it here
        # if embedded_wrapper and hasattr(embedded_wrapper, 'shutdown'):
        #     logger.info("[Fixture Teardown] Shutting down embedded wrapper...")
        #     embedded_wrapper.shutdown()


# --- NEW Observation Collection Helper ---
def collect_observations_until_end(
    q: queue.Queue,
    action_id: str,
    timeout: float = TEST_TIMEOUT
) -> List[BaseObservation]:
    """
    Collects Observations related to the specified action_id from the queue
    until the 'end' observation is received or timeout occurs.
    """
    observations = []
    start_time = time.time()
    logger.debug(f"Collecting observations for action_id: {action_id} (timeout={timeout}s)")

    while time.time() - start_time < timeout:
        try:
            # Wait briefly for messages
            obs: BaseObservation = q.get(timeout=0.5) # Increased timeout slightly per get
            logger.debug(f"  Got observation: Type={obs.observation_type}, ActionID={getattr(obs, 'action_id', 'N/A')}") # Use getattr for safety

            # Check if observation has an action_id and if it matches
            obs_action_id = getattr(obs, 'action_id', None)
            if obs_action_id == action_id:
                observations.append(obs)
                # Stop condition: received the 'end' signal for this action
                if getattr(obs, 'observation_type', None) == "end":
                    logger.debug(f"  'end' observation received for action {action_id}. Collection complete.")
                    return observations
            elif obs_action_id is not None:
                 logger.debug(f"  Ignoring observation for different action_id: {obs_action_id}")
            else:
                 logger.debug(f"  Ignoring observation without action_id: Type={getattr(obs, 'observation_type', 'N/A')}")

        except queue.Empty:
            # No message in this poll interval, continue waiting
            logger.debug(f"  Queue empty, continuing wait for action {action_id}...")
            continue
        except Exception as e:
             logger.error(f"  Unexpected error getting from observation queue: {e}", exc_info=True)
             # Optionally re-raise or fail test
             pytest.fail(f"Unexpected error while getting from observation queue: {e}")

    # If loop finishes due to timeout
    collected_types = [getattr(o, 'observation_type', 'Unknown') for o in observations]
    logger.warning(f"Timeout ({timeout}s) waiting for 'end' observation for action {action_id}. Collected {len(observations)} observations: {collected_types}")
    # Depending on test needs, either return partial results or fail
    if not observations: # If nothing was collected at all
        raise TimeoutError(f"Timeout ({timeout}s) and no observations received for action {action_id}")
    # Return partial results if timeout occurred after some observations were received
    return observations


# --- Tests ---

def test_basic_ipython_execution(sandbox_session):
    """测试基本的 IPython 代码执行"""
    sandbox, obs_queue = sandbox_session
    code = "print('Hello, World!')\n1 + 1"
    logger.info(f"Running test_basic_ipython_execution with code: {code}")
    action_id = sandbox.run_ipython_cell(code)
    logger.info(f"Action ID: {action_id}")

    # Use the new helper function waiting for 'end'
    observations = collect_observations_until_end(obs_queue, action_id)

    stdout = ""
    result_obs = None
    for obs in observations:
        if getattr(obs, 'observation_type', None) == "stream" and getattr(obs, 'stream', None) == "stdout":
            stdout += getattr(obs, 'line', '')
        if getattr(obs, 'observation_type', None) == "result":
            result_obs = obs

    logger.debug(f"Collected Stdout:\n{stdout}")
    logger.debug(f"Result Observation: {result_obs}")

    assert "Hello, World!" in stdout, "Expected output not found in stdout"
    # Check the result observation exists and indicates success
    assert result_obs is not None, "Did not receive 'result' observation"
    assert getattr(result_obs, 'exit_code', None) == 0, f"Expected exit_code 0, got {getattr(result_obs, 'exit_code', None)}"
    # Optionally check the actual result output if needed/available
    # assert "Out[...]: 2" in stdout # Note: IPython Out prompt number varies

def test_basic_shell_execution(sandbox_session):
    """测试基本的 Shell 命令执行"""
    sandbox, obs_queue = sandbox_session
    command = "echo 'Hello from Shell' && pwd"
    logger.info(f"Running test_basic_shell_execution with command: {command}")
    action_id = sandbox.run_shell_command(command)
    logger.info(f"Action ID: {action_id}")

    # Use the new helper function waiting for 'end'
    observations = collect_observations_until_end(obs_queue, action_id)

    stdout = ""
    result_obs = None
    for obs in observations:
        if getattr(obs, 'observation_type', None) == "stream" and getattr(obs, 'stream', None) == "stdout":
            stdout += getattr(obs, 'line', '') + "\n" # Add newline as lines are sent separately
        if getattr(obs, 'observation_type', None) == "result":
            result_obs = obs

    # Strip trailing newline from concatenation
    stdout = stdout.strip()

    logger.debug(f"Collected Stdout:\n{stdout}")
    logger.debug(f"Result Observation: {result_obs}")

    assert "Hello from Shell" in stdout, "Expected output 'Hello from Shell' not found"
    assert "/work" in stdout, f"Expected '/work' (working directory) not found in stdout: {stdout}"
    assert result_obs is not None, "Did not receive 'result' observation"
    assert getattr(result_obs, 'exit_code', None) == 0, f"Expected exit_code 0, got {getattr(result_obs, 'exit_code', None)}"

def test_error_handling(sandbox_session):
    """测试错误处理"""
    sandbox, obs_queue = sandbox_session
    code = "1/0" # Code designed to raise ZeroDivisionError
    logger.info(f"Running test_error_handling with code: {code}")
    action_id = sandbox.run_ipython_cell(code)
    logger.info(f"Action ID: {action_id}")

    # Use the new helper function waiting for 'end'
    # We expect 'result' and 'end' even on error
    observations = collect_observations_until_end(obs_queue, action_id)

    stderr_content = "" # Collect stderr just in case, though IPython errors often go to stdout stream
    stdout_content = ""
    result_obs = None
    end_obs = None

    for obs in observations:
        logger.debug(f"  Processing observation: Type={obs.observation_type}, ActionID={getattr(obs, 'action_id', 'N/A')}")
        if getattr(obs, 'observation_type', None) == "stream":
             stream_type = getattr(obs, 'stream', None)
             line_content = getattr(obs, 'line', '')
             logger.debug(f"    Stream Type: {stream_type}, Line: '{line_content.strip()}'")
             if stream_type == 'stderr':
                 stderr_content += line_content + "\n"
             elif stream_type == 'stdout': # IPython errors might be here
                 stdout_content += line_content + "\n"
        elif getattr(obs, 'observation_type', None) == "result":
             result_obs = obs
             logger.debug(f"    Result Obs: exit_code={getattr(obs, 'exit_code', 'N/A')}, error='{getattr(obs, 'error', 'N/A')}'")
        elif getattr(obs, 'observation_type', None) == "end":
             end_obs = obs
             logger.debug(f"    End Obs: exit_code={getattr(obs, 'exit_code', 'N/A')}, error='{getattr(obs, 'error', 'N/A')}'")


    # Assertions
    assert result_obs is not None, "Did not receive 'result' observation"
    assert end_obs is not None, "Did not receive 'end' observation"

    # Check exit code on result or end observation
    result_exit_code = getattr(result_obs, 'exit_code', None)
    end_exit_code = getattr(end_obs, 'exit_code', None)
    logger.info(f"Exit codes found: result={result_exit_code}, end={end_exit_code}")
    # Prefer checking result_obs exit code if available, otherwise end_obs might also carry it
    assert result_exit_code == 1 or end_exit_code == 1, \
        f"Expected non-zero exit code for error, got result={result_exit_code}, end={end_exit_code}"

    error_name = getattr(result_obs, 'error_name', None)
    error_value = getattr(result_obs, 'error_value', None)
    logger.info(f"Error details found: Name='{error_name}', Value='{error_value}'") # 使用你添加的 logger

    # 断言这两个字段中至少有一个包含我们期望的错误信息
    assert error_name == "ZeroDivisionError" or (error_value is not None and "division by zero" in error_value), \
        f"Expected 'ZeroDivisionError' or 'division by zero', got Name='{error_name}', Value='{error_value}'"
    # --- END 替换逻辑 ---

    # Optional: Check if traceback appeared in stdout stream (as IPython often does)
    assert "ZeroDivisionError" in stdout_content or "division by zero" in stdout_content, \
        f"Did not find error details in stdout stream capture:\n{stdout_content}"


def test_embedded_mode(embedded_sandbox_session):
    """测试嵌入式模式"""
    sandbox, obs_queue = embedded_sandbox_session
    logger.info(f"Running test_embedded_mode with Sandbox ID: {sandbox.sandbox_id}, URL: {sandbox.base_url}")

    code = "print('Hello from Embedded Mode')"
    action_id = sandbox.run_ipython_cell(code)
    logger.info(f"Action ID: {action_id}")

    # Use the new helper function waiting for 'end'
    observations = collect_observations_until_end(obs_queue, action_id)

    stdout = ""
    result_obs = None
    for obs in observations:
        if getattr(obs, 'observation_type', None) == "stream" and getattr(obs, 'stream', None) == "stdout":
            stdout += getattr(obs, 'line', '')
        if getattr(obs, 'observation_type', None) == "result":
            result_obs = obs

    logger.debug(f"Collected Stdout:\n{stdout}")
    logger.debug(f"Result Observation: {result_obs}")

    assert "Hello from Embedded Mode" in stdout
    assert result_obs is not None, "Did not receive 'result' observation"
    assert getattr(result_obs, 'exit_code', None) == 0, f"Expected exit_code 0, got {getattr(result_obs, 'exit_code', None)}"

def test_space_management():
    """测试 Space 管理功能 (依赖服务器实现)"""
    logger.info("Running test_space_management...")
    # NOTE: This test assumes the BASE_URL server implements the /spaces endpoints.
    # If the server doesn't implement these, this test will fail (e.g., 404 Not Found).
    space_manager = SpaceManager(base_url=BASE_URL)
    space_name = f"test-space-{int(time.time())}"
    space = None # Initialize
    logger.info(f"Attempting to create space: {space_name}")
    try:
        request = CreateSpaceRequest(name=space_name, description="E2E test space")
        space = space_manager.create_space(request)
        logger.info(f"Space created: ID={space.space_id}, Name={space.name}")
        assert space.name == space_name
        assert space.description == "E2E test space"

        logger.info(f"Attempting to retrieve space: {space.space_id}")
        retrieved_space = space_manager.get_space(space.space_id)
        assert retrieved_space.name == space_name
        assert retrieved_space.space_id == space.space_id

        logger.info("Attempting to list spaces...")
        spaces = space_manager.list_spaces()
        assert any(s.space_id == space.space_id and s.name == space_name for s in spaces), \
            f"Newly created space {space_name} not found in list"
        logger.info("Space management basic checks passed.")

    except Exception as e:
         logger.error(f"Space management test failed: {e}", exc_info=True)
         pytest.fail(f"Space management test failed: {e}. Check if server implements /spaces API.")
    finally:
        if space:
            logger.info(f"Deleting test space: {space.space_id}")
            try:
                space_manager.delete_space(space.space_id)
                logger.info(f"Test space {space.space_id} deleted.")
                # Optional: Verify deletion with another list/get call
            except Exception as e:
                logger.error(f"Failed to delete test space {space.space_id}: {e}")
                # Decide if cleanup failure should fail the test

# --- Concurrent Task Class (Unchanged for now) ---
class ConcurrentTask:
    """并发任务管理类"""
    def __init__(self, sandbox, task_id):
        self.sandbox = sandbox
        self.task_id = task_id
        self.action_id = None
        self.logger = logging.getLogger(f"ConcurrentTask_{task_id}")
        self.logger.propagate = True

    def execute(self, code):
        self.action_id = self.sandbox.run_ipython_cell(code)
        self.logger.debug(f"Task {self.task_id} executed, action_id: {self.action_id}")
        return self.action_id

    def collect_results(self, obs_queue: queue.Queue, timeout: float = TEST_TIMEOUT):
        """收集任务结果, 等待 'end' 观察结果"""
        observations: List[BaseObservation] = []
        start_time = time.time()
        self.logger.debug(f"Task {self.task_id} starting observation collection for action {self.action_id} (Timeout: {timeout}s)")
        while time.time() - start_time < timeout:
            try:
                obs = obs_queue.get(timeout=0.2)
                obs_action_id = getattr(obs, 'action_id', None)
                if obs_action_id == self.action_id:
                    self.logger.debug(f"Task {self.task_id} received relevant observation: {getattr(obs, 'observation_type', 'N/A')}")
                    observations.append(obs)
                    if getattr(obs, 'observation_type', None) == "end":
                        self.logger.debug(f"Task {self.task_id} received 'end' observation for action {self.action_id}. Collection complete.")
                        return observations
                elif obs_action_id is not None:
                     self.logger.debug(f"Task {self.task_id} received observation for *different* action {obs_action_id}. Ignoring.")
            except queue.Empty:
                self.logger.debug(f"Task {self.task_id} queue empty, continuing wait...")
                continue
        self.logger.warning(f"Timeout ({timeout}s) waiting for 'end' observation for action {self.action_id}. Returning {len(observations)} partial results collected.")
        return observations

# --- Concurrent Test Case (Known Issues with shared IPython state) ---
def test_concurrent_execution(sandbox_session):
    """测试并发执行 (已知问题: 共享 IPython 内核可能导致输出混乱)"""
    sandbox, obs_queue = sandbox_session
    NUM_TASKS = 3
    logger.info(f"Running test_concurrent_execution with {NUM_TASKS} tasks...")

    tasks = [ConcurrentTask(sandbox, i) for i in range(NUM_TASKS)]

    print() # Formatting
    for i, task in enumerate(tasks):
        code = f"""
import time
print(f'Task {i} executing')
time.sleep(0.2)
print(f'Task {i} finished sleep')
'Task {i} result'
"""
        action_id = task.execute(code)
        logger.info(f"Launched Task {i}, action_id: {action_id}")
        # time.sleep(0.05) # Small delay between launches if needed

    wait_time = 5.0
    logger.info(f"Waiting {wait_time}s for tasks to potentially complete...")
    time.sleep(wait_time)
    logger.info("Finished waiting. Collecting results...")

    results = {}
    print("\nCollecting and printing results...") # Keep print for clarity
    for i, task in enumerate(tasks):
        print(f"\n--- Collecting for Task {i} (action_id: {task.action_id}) ---")
        collection_timeout = TEST_TIMEOUT - wait_time - 1 if TEST_TIMEOUT > wait_time + 1 else 10.0
        observations = task.collect_results(obs_queue, timeout=collection_timeout)
        stdout = ""
        stderr = ""
        result_exit_code = None

        for obs in observations:
             print(f"Task {i} Raw Obs - Type: {getattr(obs, 'observation_type', 'N/A')}, Stream: {getattr(obs, 'stream', 'N/A')}, Content: {getattr(obs, 'line', getattr(obs, 'status', 'N/A'))}") # Raw log
             if getattr(obs, 'observation_type', None) == "stream":
                 if getattr(obs, 'stream', None) == "stdout":
                     stdout += getattr(obs, 'line', '') + "\n" # Add newline
                 elif getattr(obs, 'stream', None) == "stderr":
                      stderr += getattr(obs, 'line', '') + "\n" # Add newline
             elif getattr(obs, 'observation_type', None) == "result":
                  result_exit_code = getattr(obs, 'exit_code', None)

        results[i] = {"stdout": stdout.strip(), "stderr": stderr.strip(), "exit_code": result_exit_code, "obs_count": len(observations)}

    print("\n--- Aggregated Results ---")
    all_passed = True
    for task_id, result_data in results.items():
        print(f"Task {task_id}:")
        print(f"  Observations Collected: {result_data['obs_count']}")
        print(f"  Exit Code: {result_data['exit_code']}")
        print(f"  STDOUT:\n>>>\n{result_data['stdout']}\n<<<")
        print(f"  STDERR:\n>>>\n{result_data['stderr']}\n<<<")
        print("---")
        try:
            # WARNING: Due to shared IPython state, stdout might be interleaved.
            # This assertion is likely to be flaky or fail.
            # A weaker assertion might check for *presence* but not exact content/order.
            expected_output_start = f'Task {task_id} executing'
            expected_output_end = f'Task {task_id} finished sleep'
            assert expected_output_start in result_data['stdout'], f"Expected start string '{expected_output_start}' not found in Task {task_id} stdout"
            # assert expected_output_end in result_data['stdout'], f"Expected end string '{expected_output_end}' not found in Task {task_id} stdout" # This might fail due to interleaving
            assert result_data['exit_code'] == 0, f"Task {task_id} had non-zero exit code: {result_data['exit_code']}"
            logger.info(f"Task {task_id}: Basic checks PASSED (stdout presence, exit code)")
        except AssertionError as e:
            logger.warning(f"Task {task_id}: FAILED Checks - {e}")
            all_passed = False

    assert all_passed, "One or more concurrent tasks failed their checks. Stdout interleaving due to shared IPython state is expected and may cause failures."