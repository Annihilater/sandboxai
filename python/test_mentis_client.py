# Create the new test file
# filepath: /Users/peng/Dev/AI_CODING/sandboxai/python/mentis_client/test_mentis_client.py
# -*- coding: utf-8 -*-

import pytest
import time
import os
import threading
import json
from queue import Queue, Empty
from typing import Callable, Dict, Any, List, Optional

# Assuming your client library is installed or accessible in the Python path
from mentis_client import MentisSandbox, ConnectionError, APIError, WebSocketError
# Assuming Observation models are also packaged or accessible
from mentis_client.models import BaseObservation, parse_observation

# --- Test Configuration ---
# Get Runtime URL from environment variable or use default
BASE_URL = os.environ.get("MENTIS_RUNTIME_URL", "http://127.0.1:5266")
# Maximum time (seconds) to wait for Observations in tests
OBSERVATION_TIMEOUT = 30.0
# Timeout for connecting the stream
CONNECT_TIMEOUT = 15.0

# --- Helper Fixture for Sandbox Management ---
@pytest.fixture(scope="function") # Use a separate sandbox for each test function
def sandbox_session():
    """
    Pytest fixture: Creates a MentisSandbox instance, connects the stream,
    and automatically deletes it after the test.
    Yields a tuple: (sandbox_instance, observation_queue)
    """
    obs_queue = Queue() # Use a queue for safe data transfer between test main thread and callback
    error_list = [] # Collect errors from the listener thread
    disconnect_event = threading.Event() # Signal: whether disconnected
    connect_event = threading.Event() # Signal: whether successfully connected

    def observation_callback(obs: BaseObservation): # Expect Pydantic model
        # print(f"DEBUG [Callback]: {obs.observation_type}") # Debugging
        obs_queue.put(obs) # Put the model instance in the queue

    def error_callback(err: Exception):
        print(f"\n--- STREAM ERROR DETECTED by Callback ---\n{err}\n---")
        error_list.append(err)
        # Optionally signal disconnect on error, or let reconnect logic handle it
        # disconnect_event.set()

    def disconnect_callback():
        print("\n--- STREAM DISCONNECTED detected by Callback ---")
        disconnect_event.set() # Signal disconnect

    def connect_callback():
        print("\n--- STREAM CONNECTED detected by Callback ---")
        connect_event.set() # Signal connect

    box: Optional[MentisSandbox] = None
    try:
        print(f"\n[Fixture Setup] Creating sandbox via {BASE_URL}...")
        box = MentisSandbox.create(
            base_url=BASE_URL,
            # Pass the queue to receive Pydantic models
            observation_queue=obs_queue,
            # Or use the callback which now receives Pydantic models
            # on_observation_callback=observation_callback,
            on_error_callback=error_callback,
            on_disconnect_callback=disconnect_callback,
            on_connect_callback=connect_callback
        )
        print(f"[Fixture Setup] Sandbox created: {box.sandbox_id}")

        print("[Fixture Setup] Connecting to stream...")
        box.connect_stream(timeout=CONNECT_TIMEOUT) # Wait for connection
        assert box.is_stream_connected(), "Fixture failed to connect to WebSocket stream"
        # Wait for the connect_callback to be triggered
        assert connect_event.wait(timeout=5.0), "Connect callback was not triggered"
        print("[Fixture Setup] Stream connected.")

        yield box, obs_queue # Provide sandbox instance and queue to the test function

        # Check for errors occurred during test via callback
        if error_list:
             pytest.fail(f"WebSocket listener reported errors during test: {error_list}")
        # Check if unexpectedly disconnected (might be flaky)
        # assert not disconnect_event.is_set(), "WebSocket disconnected unexpectedly during test run"

    except (ConnectionError, APIError) as e:
         pytest.fail(f"Sandbox creation or connection failed during setup: {e}")
    except Exception as e:
        pytest.fail(f"Unexpected error during sandbox setup: {e}")
    finally:
        if box:
            print(f"\n[Fixture Teardown] Deleting sandbox {box.sandbox_id}...")
            try:
                # disconnect_stream is called within delete()
                box.delete()
            except Exception as e:
                print(f"Error during sandbox deletion in teardown: {e}")
                # Fail the test if teardown fails critically
                pytest.fail(f"Sandbox deletion failed in teardown: {e}")
            print(f"[Fixture Teardown] Sandbox {box.sandbox_id} deleted.")


# --- Helper function to collect observations ---
def collect_observations(
    q: Queue,
    action_id: str,
    stop_condition: Callable[[BaseObservation], bool], # Expects Pydantic model
    timeout: float = OBSERVATION_TIMEOUT
) -> List[BaseObservation]: # Returns list of Pydantic models
    """
    Collects Observations related to the specified action_id from the queue
    until stop_condition returns True or timeout occurs.
    """
    observations = []
    start_time = time.time()
    print(f"\nCollecting observations for action_id: {action_id} (timeout={timeout}s)")
    while time.time() - start_time < timeout:
        try:
            # Wait briefly to avoid busy-waiting and allow time for WebSocket reception
            obs: BaseObservation = q.get(timeout=0.2) # Expect Pydantic model
            print(f"  Got observation: {obs.observation_type} (action_id={obs.action_id})") # Debug

            # Collect only observations matching the target action_id
            if obs.action_id == action_id:
                observations.append(obs)
                # Check stop condition
                if stop_condition(obs):
                    print(f"Stop condition met for action_id: {action_id}")
                    return observations
            elif obs.action_id is not None:
                # Log observations for other actions if needed for debugging
                 print(f"  (Ignoring observation for different action_id: {obs.action_id})")
            else:
                 # Handle observations without action_id (e.g., AgentStateObservation)
                 print(f"  (Ignoring observation without action_id: {obs.observation_type})")
                 # Optionally collect them too?
                 # observations.append(obs)

        except Empty:
            # print("  Queue empty, continuing to wait...") # Verbose logging
            time.sleep(0.1) # Slight pause if queue is empty
            continue # Continue waiting
        except Exception as e:
             pytest.fail(f"Unexpected error while getting from observation queue: {e}")

    # Timeout if loop finishes without meeting stop condition
    collected_types = [o.observation_type for o in observations]
    raise TimeoutError(f"Timeout ({timeout}s) waiting for stop condition for action {action_id}. Collected observations: {collected_types}")

# --- Test Cases (Rewritten using Pytest and Observation Collection) ---

def test_shell_echo(sandbox_session):
    """Tests running a simple shell command and receiving streamed output."""
    sandbox, q = sandbox_session
    command = "echo 'Hello Mentis!' && echo 'Second Line'"
    action_id = sandbox.run_shell_command(command)
    assert isinstance(action_id, str)

    def stop_on_end(obs: BaseObservation):
        return obs.observation_type == "CmdEndObservation"

    try:
        observations = collect_observations(q, action_id, stop_on_end)

        # --- Assertions on Observations (using Pydantic models) ---
        start_obs = next((o for o in observations if o.observation_type == "CmdStartObservation"), None)
        assert start_obs is not None, "Missing CmdStartObservation"
        assert start_obs.command == command

        stdout_parts = [o.data for o in observations if o.observation_type == "CmdOutputObservationPart" and o.stream == "stdout"]
        # Output might come in one or multiple parts
        full_stdout = "".join(stdout_parts)
        assert "Hello Mentis!" in full_stdout, f"Stdout missing expected text: {full_stdout}"
        assert "Second Line" in full_stdout, f"Stdout missing expected text: {full_stdout}"

        end_obs = next((o for o in observations if o.observation_type == "CmdEndObservation"), None)
        assert end_obs is not None, "Missing CmdEndObservation"
        assert end_obs.exit_code == 0, f"Incorrect exit code: {end_obs}"

    except TimeoutError as e:
        pytest.fail(f"Test timed out collecting observations: {e}")

def test_shell_stderr_and_exit_code(sandbox_session):
    """Tests a shell command producing stderr and non-zero exit code."""
    sandbox, q = sandbox_session
    command = "echo 'Error Message' >&2 && exit 42"
    action_id = sandbox.run_shell_command(command)

    def stop_on_end(obs: BaseObservation):
        return obs.observation_type == "CmdEndObservation"

    try:
        observations = collect_observations(q, action_id, stop_on_end)

        stderr_parts = [o.data for o in observations if o.observation_type == "CmdOutputObservationPart" and o.stream == "stderr"]
        full_stderr = "".join(stderr_parts)
        assert "Error Message" in full_stderr, f"Stderr missing expected text: {full_stderr}"

        end_obs = next((o for o in observations if o.observation_type == "CmdEndObservation"), None)
        assert end_obs is not None, "Missing CmdEndObservation"
        assert end_obs.exit_code == 42, f"Incorrect exit code: {end_obs}"

    except TimeoutError as e:
        pytest.fail(f"Test timed out collecting observations: {e}")

def test_ipython_print_and_result(sandbox_session):
    """Tests an IPython cell with print statements and a final result."""
    sandbox, q = sandbox_session
    code = "print('Line 1 from IPython')\nprint('Line 2')\nresult = 1 + 2\nresult"
    action_id = sandbox.run_ipython_cell(code)

    def stop_on_result(obs: BaseObservation):
        # Stop when we get the final result observation
        return obs.observation_type == "IPythonResultObservation"

    try:
        observations = collect_observations(q, action_id, stop_on_result)

        assert any(o.observation_type == "IPythonStartObservation" for o in observations)

        # Check stdout parts
        stdout_data = [o.data for o in observations if o.observation_type == "IPythonOutputObservationPart" and o.stream == "stdout"]
        full_stdout = "".join(stdout_data)
        assert "Line 1 from IPython" in full_stdout
        assert "Line 2" in full_stdout

        # Check execute_result part
        exec_result_obs = next((o for o in observations if o.observation_type == "IPythonOutputObservationPart" and o.stream == "execute_result"), None)
        assert exec_result_obs is not None, "Missing execute_result observation"
        # Accessing data depends on the structure defined in IPythonOutputObservationPart
        assert isinstance(exec_result_obs.data, dict)
        assert exec_result_obs.data.get("text/plain") == "3", "Incorrect execute_result data"

        # Check final result status
        final_result_obs = next((o for o in observations if o.observation_type == "IPythonResultObservation"), None)
        assert final_result_obs is not None, "Missing final IPythonResultObservation"
        assert final_result_obs.status == "ok"
        assert isinstance(final_result_obs.execution_count, int)

    except TimeoutError as e:
        pytest.fail(f"Test timed out collecting observations: {e}")

def test_ipython_error(sandbox_session):
    """Tests an IPython cell that raises an exception."""
    sandbox, q = sandbox_session
    code = "print('About to crash')\n1 / 0"
    action_id = sandbox.run_ipython_cell(code)

    def stop_on_result(obs: BaseObservation):
        return obs.observation_type == "IPythonResultObservation"

    try:
        observations = collect_observations(q, action_id, stop_on_result)

        stdout_obs = next((o for o in observations if o.observation_type == "IPythonOutputObservationPart" and o.stream == "stdout"), None)
        assert stdout_obs is not None and "About to crash" in stdout_obs.data

        # Error might also appear on stderr stream in some cases
        # error_obs_part = next((o for o in observations if o.observation_type == "IPythonOutputObservationPart" and o.stream == "error"), None)

        final_result_obs = next((o for o in observations if o.observation_type == "IPythonResultObservation"), None)
        assert final_result_obs is not None, "Missing final IPythonResultObservation"
        assert final_result_obs.status == "error"
        assert final_result_obs.error_name == "ZeroDivisionError"
        assert "division by zero" in final_result_obs.error_value
        assert isinstance(final_result_obs.traceback, list) and len(final_result_obs.traceback) > 0

    except TimeoutError as e:
        pytest.fail(f"Test timed out collecting observations: {e}")

def test_long_running_shell_streaming(sandbox_session):
    """Tests streaming output from a longer shell command."""
    sandbox, q = sandbox_session
    # Command that prints numbers with delays
    command = "for i in {1..4}; do echo \"Count $i\"; sleep 0.5; done; echo 'Final Count'"
    action_id = sandbox.run_shell_command(command)

    def stop_on_end(obs: BaseObservation):
        return obs.observation_type == "CmdEndObservation"

    try:
        observations = collect_observations(q, action_id, stop_on_end, timeout=15.0) # Longer timeout

        assert any(o.observation_type == "CmdStartObservation" for o in observations)

        output_parts = [o for o in observations if o.observation_type == "CmdOutputObservationPart" and o.stream == "stdout"]
        assert len(output_parts) >= 5, f"Expected at least 5 stdout parts, got {len(output_parts)}"

        # Check if outputs arrived somewhat spread out (crude check using timestamps)
        timestamps = [o.timestamp for o in output_parts]
        # Basic check: time difference between first and last output part > delay
        # This is very basic and might be flaky. A better test might check the content order.
        if len(timestamps) >= 2:
            time_diff = timestamps[-1] - timestamps[0]
            assert time_diff.total_seconds() > 1.0 # Based on sleep delays (4 * 0.5 = 2s total sleep)

        # Check content
        full_stdout = "".join(o.data for o in output_parts)
        assert "Count 1" in full_stdout
        assert "Count 2" in full_stdout
        assert "Count 3" in full_stdout
        assert "Count 4" in full_stdout
        assert "Final Count" in full_stdout

        end_obs = next((o for o in observations if o.observation_type == "CmdEndObservation"), None)
        assert end_obs is not None and end_obs.exit_code == 0

    except TimeoutError as e:
        pytest.fail(f"Test timed out collecting observations: {e}")

# --- Placeholder for Future Tests (Phase 3) ---
# @pytest.mark.skip(reason="File actions not implemented in Phase 1")
# def test_file_write_and_read(sandbox_session):
#     sandbox, q = sandbox_session
#     # ... test sandbox.write_file(...) ...
#     # ... collect observations ...
#     # ... test sandbox.read_file(...) ...
#     # ... collect observations and assert content ...
#     pass

# @pytest.mark.skip(reason="Browser actions not implemented in Phase 1")
# def test_browser_navigation_and_screenshot(sandbox_session):
#     sandbox, q = sandbox_session
#     # ... test sandbox.browse_url(...) ...
#     # ... collect BrowserOutputObservation ...
#     # ... assert screenshot data exists ...
#     pass
