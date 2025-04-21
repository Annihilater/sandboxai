import logging
import queue # Import the queue module
import time

# Assuming your client library is installed or accessible in the path
from mentis_client.client import MentisSandbox
# Import the base model and specific observation models used for type hints/checks
from mentis_client.models import BaseObservation, IPythonOutputObservationPart, IPythonResultObservation, ErrorObservation

# Configure basic logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mentis-example-simple")

# --- Function to wait for action results --- 
def wait_for_action_results(action_id: str, obs_queue: queue.Queue, timeout: float = 10.0) -> str:
    """Waits for observations for a specific action_id and returns collected stdout."""
    stdout_buffer = ""
    start_time = time.monotonic()
    while True:
        try:
            # Wait for an observation with a timeout
            remaining_time = timeout - (time.monotonic() - start_time)
            if remaining_time <= 0:
                logger.warning(f"Timeout waiting for results for action {action_id}")
                break
                
            # obs should be an instance of a Pydantic model (e.g., IPythonOutputObservationPart)
            obs: BaseObservation = obs_queue.get(timeout=remaining_time) 
            
            # Check if the observation is for the action we are waiting for
            if obs.action_id == action_id:
                logger.debug(f"Received observation for action {action_id}: {obs}")
                # Compare using the string value of observation_type
                if obs.observation_type == "stream": 
                    # Check if it's the correct model type before accessing specific fields
                    if isinstance(obs, IPythonOutputObservationPart) and obs.stream == "stdout":
                        # Access the 'line' attribute directly from obs
                        stdout_buffer += obs.line 
                elif obs.observation_type == "end" or obs.observation_type == "result": 
                    logger.info(f"Received '{obs.observation_type}' observation for action {action_id}")
                    # Check if it's the correct model type before accessing specific fields
                    if isinstance(obs, IPythonResultObservation) and obs.exit_code is not None and obs.exit_code != 0:
                        logger.warning(f"Action {action_id} ended with non-zero exit code: {obs.exit_code}, ErrorName: {obs.error_name}, ErrorValue: {obs.error_value}")
                    break # Action finished
                elif obs.observation_type == "error": 
                    # Check if it's the correct model type before accessing specific fields
                    if isinstance(obs, ErrorObservation):
                        logger.error(f"Received 'error' observation for action {action_id}: {obs.message}")
                    else:
                        logger.error(f"Received 'error' observation (unknown format) for action {action_id}: {obs}")
                    break 
            else:
                # Put back observations for other actions if needed, or log/ignore
                logger.debug(f"Ignoring observation for different action {obs.action_id}")
                # Re-queueing might be complex if multiple actions run concurrently
                # For this simple example, we'll just log it.
                # If running actions concurrently, a more robust handler is needed.

        except queue.Empty:
            logger.warning(f"Queue empty, timeout waiting for results for action {action_id}")
            break # Timeout occurred
        except Exception as e:
            logger.error(f"Error processing observation queue for action {action_id}: {e}", exc_info=True)
            break
            
    return stdout_buffer
# --- End function --- 


def main():
    runtime_url = "http://127.0.0.1:5266"
    logger.info(f"连接到 Mentis Runtime: {runtime_url}")

    # Create an observation queue
    obs_queue = queue.Queue()

    try:
        # Create sandbox and pass the queue
        with MentisSandbox.create(
            base_url=runtime_url, 
            observation_queue=obs_queue, 
            space_id="default" # Specify space_id if needed
        ) as sandbox:
            logger.info(f"Sandbox created: {sandbox.sandbox_id}")

            # --- Action 1 --- 
            code1 = "print('Hello world!')"
            logger.info(f"Executing: {code1}")
            action_id1 = sandbox.run_ipython_cell(code1)
            logger.info(f"Action 1 initiated with ID: {action_id1}")
            
            # Wait for results and print
            stdout1 = wait_for_action_results(action_id1, obs_queue)
            logger.info(f"执行结果1 (stdout):\n{stdout1.strip()}")
            print("-"*20) # Separator

            # --- Action 2 --- 
            code2 = "5 * 8"
            logger.info(f"Executing: {code2}")
            action_id2 = sandbox.run_ipython_cell(code2) 
            logger.info(f"Action 2 initiated with ID: {action_id2}")
            
            # Wait for results and print
            stdout2 = wait_for_action_results(action_id2, obs_queue)
            logger.info(f"执行结果2 (stdout):\n{stdout2.strip()}")
            print("-"*20) # Separator
            
            # --- Action 3 (Example with numpy) ---
            code3 = "import numpy as np\na = np.array([1, 2, 3])\nprint(a)\nprint(np.mean(a))"
            logger.info(f"Executing numpy code:")
            action_id3 = sandbox.run_ipython_cell(code3)
            logger.info(f"Action 3 initiated with ID: {action_id3}")
            
            # Wait for results and print
            stdout3 = wait_for_action_results(action_id3, obs_queue)
            logger.info(f"执行结果3 (stdout):\n{stdout3.strip()}")
            print("-"*20) # Separator

    except Exception as e: # Catch other potential errors
        # Use logger.exception to include traceback
        logger.exception(f"运行 simple.py 时发生意外错误") 
    finally:
        logger.info("Simple example finished.")

if __name__ == "__main__":
    main()