# mentis_client/client.py
import httpx
import websockets
import asyncio
import threading
import json
import uuid
import logging
import time
import random # Added for jitter
from typing import Callable, Dict, Any, Optional, Union, List
from queue import Queue, Empty

from .exceptions import MentisSandboxError, ConnectionError, APIError, WebSocketError
# Import Observation models and parsing function
from .models import BaseObservation, parse_observation

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:8080" # Default Runtime service URL
DEFAULT_WEBSOCKET_RECV_TIMEOUT = 5.0 # Timeout for reading from WebSocket
DEFAULT_WEBSOCKET_CONNECT_TIMEOUT = 10.0 # Timeout for establishing WebSocket connection
DEFAULT_WEBSOCKET_PING_INTERVAL = 20.0
DEFAULT_WEBSOCKET_PING_TIMEOUT = 20.0
DEFAULT_RECONNECT_DELAY = 1.0 # Initial delay before attempting WebSocket reconnect
DEFAULT_MAX_RECONNECT_DELAY = 60.0 # Maximum delay between reconnect attempts
DEFAULT_API_TIMEOUT = 30.0 # Default timeout for standard API calls
DEFAULT_CREATE_API_TIMEOUT = 60.0 # Default timeout for the create call

class MentisSandbox:
    """
    Client for interacting with the MentisSandbox Runtime.

    Provides methods for managing sandbox lifecycle, executing commands/code,
    and receiving real-time observations via WebSocket.
    """
    def __init__(
        self,
        sandbox_id: str,
        base_url: str = DEFAULT_BASE_URL,
        api_timeout: float = DEFAULT_API_TIMEOUT,
        # WebSocket configuration options
        ws_recv_timeout: float = DEFAULT_WEBSOCKET_RECV_TIMEOUT,
        ws_connect_timeout: float = DEFAULT_WEBSOCKET_CONNECT_TIMEOUT,
        ws_ping_interval: float = DEFAULT_WEBSOCKET_PING_INTERVAL,
        ws_ping_timeout: float = DEFAULT_WEBSOCKET_PING_TIMEOUT,
        ws_reconnect_delay: float = DEFAULT_RECONNECT_DELAY,
        ws_max_reconnect_delay: float = DEFAULT_MAX_RECONNECT_DELAY,
        # Observation handling
        observation_queue: Optional[Queue] = None,
        on_observation_callback: Optional[Callable[[BaseObservation], None]] = None, # Callback receives Pydantic model
        on_error_callback: Optional[Callable[[Exception], None]] = None,
        on_disconnect_callback: Optional[Callable[[], None]] = None,
        on_connect_callback: Optional[Callable[[], None]] = None,
    ):
        """
        Initializes the client for an existing sandbox.

        Args:
            sandbox_id: The ID of the sandbox to connect to.
            base_url: The base URL of the MentisRuntime service.
            api_timeout: Timeout in seconds for standard REST API calls.
            ws_recv_timeout: Timeout for receiving a message over WebSocket.
            ws_connect_timeout: Timeout for establishing the WebSocket connection.
            ws_ping_interval: Interval for sending WebSocket pings.
            ws_ping_timeout: Timeout for receiving pong after sending a ping.
            ws_reconnect_delay: Initial delay before attempting WebSocket reconnect.
            ws_max_reconnect_delay: Maximum delay between WebSocket reconnect attempts.
            observation_queue: A queue.Queue instance to put received Pydantic Observation models into.
                                If provided, callback is ignored.
            on_observation_callback: A function to call when an observation is received.
                                     Called from the listener thread. Signature: callback(observation: BaseObservation).
            on_error_callback: A function to call when an error occurs in the listener thread.
                               Signature: callback(error: Exception).
            on_disconnect_callback: A function to call when the WebSocket disconnects unexpectedly.
                                    Called from the listener thread.
            on_connect_callback: A function to call when the WebSocket connects successfully.
                                 Called from the listener thread.
        """
        if not sandbox_id:
            raise ValueError("sandbox_id cannot be empty")
        if not (observation_queue or on_observation_callback):
            logger.warning("No observation_queue or on_observation_callback provided. Observations will be logged only.")

        self.sandbox_id = sandbox_id
        self.base_url = base_url.rstrip('/')
        self.api_url = f"{self.base_url}/v1"
        # Construct WebSocket URL carefully
        try:
            http_proto, host_part = self.base_url.split("://", 1)
            ws_proto = "ws" if http_proto == "http" else "wss"
            self.stream_url = f"{ws_proto}://{host_part}/v1/sandboxes/{self.sandbox_id}/stream"
        except ValueError:
             raise ValueError(f"Invalid base_url format: {self.base_url}. Expected format like 'http://host:port'")

        self._client = httpx.Client(base_url=self.api_url, timeout=api_timeout)

        # Store WebSocket config
        self._ws_recv_timeout = ws_recv_timeout
        self._ws_connect_timeout = ws_connect_timeout
        self._ws_ping_interval = ws_ping_interval
        self._ws_ping_timeout = ws_ping_timeout
        self._ws_reconnect_delay = ws_reconnect_delay
        self._ws_max_reconnect_delay = ws_max_reconnect_delay

        # Store callbacks and queue
        self._observation_queue = observation_queue
        self._on_observation_callback = on_observation_callback
        self._on_error_callback = on_error_callback
        self._on_disconnect_callback = on_disconnect_callback
        self._on_connect_callback = on_connect_callback

        self._listener_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_connected = threading.Event() # To signal successful connection

    @classmethod
    def create(
        cls,
        settings: Optional[Dict[str, Any]] = None,
        base_url: str = DEFAULT_BASE_URL,
        api_timeout: float = DEFAULT_CREATE_API_TIMEOUT, # Use specific timeout for creation
        **kwargs # Pass other init args like callbacks/queue/ws_config
    ) -> 'MentisSandbox':
        """
        Creates a new sandbox instance via the API and returns a client for it.
        """
        url = f"{base_url.rstrip('/')}/v1/sandboxes"
        logger.info(f"Creating sandbox via {url}...")
        try:
            # Use a temporary client for creation to respect specific timeout
            with httpx.Client(timeout=api_timeout) as create_client:
                response = create_client.post(url, json=settings or {})
                if response.status_code == 201:
                    data = response.json()
                    sandbox_id = data['sandbox_id']
                    logger.info(f"Sandbox created successfully with ID: {sandbox_id}")
                    # Initialize client with the new ID and other kwargs
                    # Pass the original api_timeout from kwargs if provided, else use default
                    if 'api_timeout' not in kwargs:
                        kwargs['api_timeout'] = DEFAULT_API_TIMEOUT # Use standard timeout for the instance
                    return cls(sandbox_id=sandbox_id, base_url=base_url, **kwargs)
                else:
                    # Try to parse error details from response
                    try:
                        error_detail = response.json().get('detail', response.text)
                    except Exception:
                        error_detail = response.text
                    raise APIError(f"Failed to create sandbox (HTTP {response.status_code}): {error_detail}", status_code=response.status_code)
        except httpx.RequestError as e:
            raise ConnectionError(f"Failed to connect to MentisRuntime at {url}: {e}") from e
        except Exception as e:
            # Catch potential JSON decoding errors or other issues
             raise MentisSandboxError(f"An unexpected error occurred during sandbox creation: {e}") from e

    def _post_action(self, endpoint: str, payload: Dict[str, Any]) -> str:
        """Helper to POST an action and return action_id."""
        # 不再生成客户端action_id，让服务器生成
        url = f"/sandboxes/{self.sandbox_id}/{endpoint}"
        logger.debug(f"Posting action to {url}: {payload}")
        try:
            response = self._client.post(url, json=payload)

            if response.status_code == 202:
                data = response.json()
                server_action_id = data.get("action_id")
                if not server_action_id:
                    logger.warning(f"服务器未返回action_id，这可能导致观察结果无法正确匹配")
                    server_action_id = str(uuid.uuid4())  # 仅在服务器未返回ID时生成一个备用ID
                logger.info(f"Action accepted by server. Type: {endpoint}, ActionID: {server_action_id}")
                return server_action_id
            else:
                 try:
                     error_detail = response.json().get('detail', response.text)
                 except Exception:
                     error_detail = response.text
                 raise APIError(f"Action failed (HTTP {response.status_code}): {error_detail}", status_code=response.status_code)
        except httpx.RequestError as e:
            raise ConnectionError(f"API request failed for action {endpoint}: {e}") from e
        except Exception as e:
             raise MentisSandboxError(f"Unexpected error posting action: {e}") from e

    # --- Action Methods (Phase 1) ---

    def run_shell_command(self, command: str, work_dir: Optional[str]=None, env: Optional[Dict[str,str]]=None, timeout: Optional[int]=None) -> str:
        """
        Initiates a shell command execution. Returns an action_id.
        Results are received via the connected observation stream/callback.
        """
        payload = {"command": command}
        if work_dir: payload["work_dir"] = work_dir
        if env: payload["env"] = env
        if timeout: payload["timeout"] = timeout
        return self._post_action("shell", payload)

    def run_ipython_cell(self, code: str, timeout: Optional[int]=None) -> str:
        """
        Initiates an IPython cell execution. Returns an action_id.
        Results are received via the connected observation stream/callback.
        
        Args:
            code: The Python code to execute
            timeout: Maximum time to wait for execution to complete (seconds)
            
        Returns:
            The action_id for tracking the execution
            
        Raises:
            MentisSandboxError: If execution fails
        """
        payload = {"code": code}
        if timeout: payload["timeout"] = timeout
        return self._post_action("ipython", payload)

    # --- Streaming Connection Methods ---

    def connect_stream(self, timeout: Optional[float] = None):
        """
        Connects to the WebSocket observation stream in a background thread.
        Observations will be delivered to the configured queue or callback.

        Args:
            timeout: Time in seconds to wait for the initial connection.
                     Defaults to the configured ws_connect_timeout.

        Raises:
            ConnectionError: If the connection fails within the timeout.
            RuntimeError: If the stream is already connected.
        """
        if self._listener_thread and self._listener_thread.is_alive():
            logger.warning("Stream listener thread is already running.")
            raise RuntimeError("Stream is already connected or connecting.")

        connect_timeout = timeout if timeout is not None else self._ws_connect_timeout

        self._stop_event.clear()
        self._is_connected.clear() # Clear connection status flag

        self._listener_thread = threading.Thread(target=self._websocket_listener_sync_wrapper, daemon=True)
        self._listener_thread.start()

        # Wait for the connection to be established or timeout
        logger.info(f"Waiting up to {connect_timeout}s for WebSocket connection...")
        connected = self._is_connected.wait(timeout=connect_timeout)
        if not connected:
            # Ensure cleanup if connection timed out
            # Signal stop event first
            self._stop_event.set()
            # Wait briefly for thread to potentially react
            if self._listener_thread:
                self._listener_thread.join(timeout=1.0)
            # Reset thread variable if it didn't exit cleanly (though it might still be running)
            if self._listener_thread and self._listener_thread.is_alive():
                 logger.warning("Listener thread still alive after connection timeout and stop signal.")
            self._listener_thread = None
            self._stop_event.clear() # Reset stop event

            raise ConnectionError(f"Failed to connect to WebSocket stream at {self.stream_url} within {connect_timeout} seconds.")
        logger.info("WebSocket stream connected successfully.")


    def _websocket_listener_sync_wrapper(self):
        """Runs the async listener function in a way compatible with threading."""
        try:
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._websocket_listener_async())
        except Exception as e:
            logger.exception("WebSocket listener thread encountered an unhandled exception.")
            if self._on_error_callback:
                try:
                    self._on_error_callback(e)
                except Exception as cb_e:
                     logger.error(f"Error calling on_error_callback: {cb_e}", exc_info=True)
        finally:
            loop.close()
            logger.info("Event loop closed for WebSocket listener thread.")


    async def _websocket_listener_async(self):
        """Async function to handle WebSocket connection and message receiving with robust reconnect."""
        reconnect_delay = self._ws_reconnect_delay # Initial reconnect delay from config
        while not self._stop_event.is_set():
            try:
                logger.info(f"Attempting to connect to WebSocket: {self.stream_url}")
                # Configure connect options using instance attributes
                async with websockets.connect(
                    self.stream_url,
                    ping_interval=self._ws_ping_interval,
                    ping_timeout=self._ws_ping_timeout,
                    open_timeout=self._ws_connect_timeout # Use configured connect timeout
                ) as websocket:
                    self._is_connected.set() # Signal successful connection
                    logger.info(f"WebSocket connected to {self.stream_url}")
                    reconnect_delay = self._ws_reconnect_delay # Reset delay on successful connection
                    if self._on_connect_callback:
                        try: self._on_connect_callback()
                        except Exception as e: logger.error(f"Error in on_connect_callback: {e}", exc_info=True)

                    # --- Receive loop ---
                    while not self._stop_event.is_set():
                        try:
                            # Wait for message with a timeout to allow checking stop_event
                            message = await asyncio.wait_for(websocket.recv(), timeout=self._ws_recv_timeout)
                            if self._stop_event.is_set(): break # Check again after recv

                            # --- Observation Processing ---
                            try:
                                raw_observation = json.loads(message)
                                # --- Use Pydantic Parsing ---
                                try:
                                    # parsed_obs will be specific type like CmdStartObservation etc. or BaseObservation/Unknown
                                    parsed_obs: BaseObservation = parse_observation(raw_observation)
                                    observation_to_deliver = parsed_obs # Deliver the model instance
                                except Exception as parse_err:
                                     logger.error(f"Pydantic parsing error for observation: {raw_observation}", exc_info=True)
                                     # Decide how to handle parsing errors - maybe push an ErrorObservation?
                                     # For now, log and maybe push the raw dict or skip
                                     if self._on_error_callback:
                                         try: self._on_error_callback(parse_err)
                                         except Exception as cb_e: logger.error(f"Error calling on_error_callback for parsing error: {cb_e}", exc_info=True)
                                     continue # Skip this malformed message

                                # --- Deliver Observation ---
                                if self._observation_queue:
                                    self._observation_queue.put(observation_to_deliver)
                                elif self._on_observation_callback:
                                    try:
                                        # Callback now receives a Pydantic model instance
                                        self._on_observation_callback(observation_to_deliver)
                                    except Exception as cb_e:
                                         logger.error(f"Error in on_observation_callback: {cb_e}", exc_info=True)
                                else:
                                    # Default logging if no handler provided
                                    logger.debug(f"Received observation model: {observation_to_deliver}")

                            except json.JSONDecodeError:
                                logger.warning(f"Received non-JSON WebSocket message: {message[:100]}...")
                            except Exception as e: # Catch errors during parsing or callback
                                logger.exception(f"Error processing WebSocket message or callback")
                                if self._on_error_callback:
                                    try: self._on_error_callback(e)
                                    except Exception as cb_e: logger.error(f"Error calling on_error_callback: {cb_e}", exc_info=True)
                            # --- End Observation Processing ---

                        except asyncio.TimeoutError:
                            # No message received, just loop and check stop_event
                            # Check connection health, maybe send ping? websockets handles auto-ping.
                            # logger.debug("WebSocket recv timeout, checking status...")
                            try:
                                # Explicitly send a ping to check liveness if needed, though library handles it
                                await asyncio.wait_for(websocket.ping(), timeout=self._ws_ping_timeout)
                            except asyncio.TimeoutError:
                                logger.warning("WebSocket ping timed out, connection likely lost.")
                                break # Exit inner loop to trigger reconnect logic
                            except websockets.exceptions.ConnectionClosed:
                                logger.warning("WebSocket connection closed during ping check.")
                                break # Exit inner loop to trigger reconnect logic
                            except Exception as ping_err:
                                 logger.error(f"Error during explicit ping: {ping_err}", exc_info=True)
                                 # Assume connection might be broken
                                 break
                            continue # Continue waiting for messages if ping was ok or not sent
                        except websockets.exceptions.ConnectionClosedOK:
                            logger.info("WebSocket connection closed normally by server.")
                            break # Exit inner loop
                        except websockets.exceptions.ConnectionClosedError as e:
                            logger.warning(f"WebSocket connection closed with error: {e}")
                            break # Exit inner loop
                        except websockets.exceptions.ConnectionClosed as e: # Catch base class for any closure
                            logger.warning(f"WebSocket connection closed unexpectedly: {e}")
                            break # Exit inner loop
                        except Exception as e: # Catch other potential recv errors
                             logger.exception("Unexpected error during websocket recv")
                             if self._on_error_callback:
                                 try: self._on_error_callback(e)
                                 except Exception as cb_e: logger.error(f"Error calling on_error_callback for recv error: {cb_e}", exc_info=True)
                             break # Assume connection is broken

                    # --- End Receive loop ---

            except websockets.exceptions.InvalidURI as e:
                 logger.error(f"Invalid WebSocket URI: {self.stream_url} - {e}. Stopping listener.", exc_info=True)
                 if self._on_error_callback:
                     try: self._on_error_callback(WebSocketError(f"Invalid WebSocket URI: {e}"))
                     except Exception as cb_e: logger.error(f"Error calling on_error_callback for InvalidURI: {cb_e}", exc_info=True)
                 self._is_connected.clear() # Ensure flag is clear
                 break # Exit outer loop - non-recoverable URI error
            except (websockets.exceptions.WebSocketException, OSError, asyncio.TimeoutError) as e:
                 # Catch connection errors (WebSocketException, network errors, connect timeout)
                 logger.error(f"WebSocket connection failed: {e}")
                 # Potentially recoverable, will retry after delay
                 # Ensure flag is clear before potentially calling disconnect callback
                 self._is_connected.clear()
                 if self._on_disconnect_callback: # Treat connection failure as a disconnect
                     try: self._on_disconnect_callback()
                     except Exception as cb_e: logger.error(f"Error in on_disconnect_callback after connection failure: {cb_e}", exc_info=True)
                 if self._on_error_callback:
                     try: self._on_error_callback(ConnectionError(f"WebSocket connection failed: {e}"))
                     except Exception as cb_e: logger.error(f"Error calling on_error_callback for connection failure: {cb_e}", exc_info=True)
            except Exception as e:
                 # Catch-all for unexpected errors during connection attempt
                 logger.exception(f"Unexpected error in WebSocket listener connection phase")
                 self._is_connected.clear() # Ensure flag is clear
                 if self._on_error_callback:
                     try: self._on_error_callback(e)
                     except Exception as cb_e: logger.error(f"Error calling on_error_callback for unexpected connection error: {cb_e}", exc_info=True)
                 # Decide whether to break or retry based on error type, retry for now

            finally:
                 # Ensure connection status is cleared on any exit from the connect block
                 # Only call disconnect callback if it *was* connected and we are not stopping
                 was_connected = self._is_connected.is_set()
                 self._is_connected.clear()
                 if was_connected and not self._stop_event.is_set():
                     logger.info("WebSocket disconnected.")
                     if self._on_disconnect_callback:
                         try: self._on_disconnect_callback()
                         except Exception as e: logger.error(f"Error in on_disconnect_callback: {e}", exc_info=True)


            # --- Reconnect Logic ---
            if not self._stop_event.is_set():
                # Add jitter: random component between 0% and 10% of the current delay
                wait_time = reconnect_delay + random.uniform(0, 0.1 * reconnect_delay)
                logger.info(f"Waiting {wait_time:.2f}s before attempting WebSocket reconnect...")
                # Use stop_event.wait for interruptible sleep
                stopped = self._stop_event.wait(timeout=wait_time)
                if stopped:
                    logger.info("Stop event received during reconnect delay.")
                    break # Exit outer loop if stop requested

                # Exponential backoff
                reconnect_delay = min(reconnect_delay * 2, self._ws_max_reconnect_delay)


        logger.info("WebSocket listener async function finished.")
        self._is_connected.clear() # Ensure flag is clear on final exit


    def disconnect_stream(self):
        """Signals the listener thread to stop and attempts cleanup."""
        if not self._listener_thread or not self._listener_thread.is_alive():
            # logger.debug("Stream listener is not running.") # Can be noisy
            return

        logger.info("Disconnecting WebSocket stream...")
        self._stop_event.set()

        # Give the thread some time to shut down gracefully
        # Timeout should consider potential waits inside the loop (e.g., recv timeout)
        join_timeout = self._ws_recv_timeout + 2.0 # Add a buffer
        self._listener_thread.join(timeout=join_timeout)

        if self._listener_thread.is_alive():
            logger.warning(f"Stream listener thread did not exit cleanly after {join_timeout}s.")
            # Application might need to decide if this is critical

        self._listener_thread = None
        # No need to explicitly close websocket here, the listener thread should handle it on exit/stop
        self._is_connected.clear() # Ensure status is updated
        self._stop_event.clear() # Reset stop event for potential future connections
        logger.info("Stream listener stopped.")


    def delete(self):
        """Deletes the sandbox instance via the API after stopping the stream."""
        self.disconnect_stream() # Ensure stream is stopped first
        url = f"/sandboxes/{self.sandbox_id}"
        logger.info(f"Deleting sandbox {self.sandbox_id} via {self.api_url}{url}...")
        try:
            # Use the instance client
            response = self._client.delete(url)
            if response.status_code == 204:
                logger.info(f"Sandbox {self.sandbox_id} deleted successfully.")
            elif response.status_code == 404:
                 logger.warning(f"Sandbox {self.sandbox_id} not found during deletion (already deleted?).")
            else:
                try:
                    error_detail = response.json().get('detail', response.text)
                except Exception:
                    error_detail = response.text
                # Raise APIError but still ensure client is closed in finally
                raise APIError(f"Failed to delete sandbox {self.sandbox_id} (HTTP {response.status_code}): {error_detail}", status_code=response.status_code)
        except httpx.RequestError as e:
            # Log error but might proceed to close client anyway
            logger.error(f"API request failed during sandbox deletion: {e}", exc_info=True)
            # Re-raise as ConnectionError, client closing happens in finally
            raise ConnectionError(f"Failed to connect to MentisRuntime to delete sandbox: {e}") from e
        except Exception as e:
             logger.error(f"Unexpected error during sandbox deletion: {e}", exc_info=True)
             # Re-raise, client closing happens in finally
             raise MentisSandboxError(f"Unexpected error during sandbox deletion: {e}") from e
        finally:
            # --- Ensure client is closed ---
            if not self._client.is_closed:
                logger.debug("Closing HTTP client.")
                self._client.close()

    def close(self):
        """Disconnects stream and closes HTTP client without deleting the sandbox."""
        logger.info(f"Closing client connection for sandbox {self.sandbox_id}...")
        self.disconnect_stream()
        if not self._client.is_closed:
            logger.debug("Closing HTTP client.")
            self._client.close()
        logger.info("Client connection closed.")

    def is_stream_connected(self) -> bool:
        """Checks if the WebSocket connection is currently believed to be active."""
        return self._is_connected.is_set()


    # --- Context Manager ---
    def __enter__(self):
        # Keep explicit connect_stream call outside context manager entry
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Default behavior: Close connections, do not delete sandbox
        logger.info("Exiting MentisSandbox context, closing client connections...")
        self.close()
        # If auto-deletion is desired, uncomment the line below and comment out self.close()
        # self.delete()

    # Note: Removed the previous close() alias for delete() to have distinct behaviors.
    # If delete() is the desired primary cleanup, rename delete() to close()
    # or adjust __exit__ accordingly. Current setup: close() cleans connections, delete() removes sandbox.

def collect_observations(queue: Queue, action_id: str, timeout: float = 10.0) -> List[Any]:
    """从队列中收集与特定action_id相关的所有观察结果"""
    observations = []
    end_time = time.time() + timeout
    end_received = False
    
    logger.debug(f"开始收集观察结果，action_id: {action_id}")
    
    while time.time() < end_time and not end_received:
        try:
            obs = queue.get(timeout=0.5)
            logger.debug(f"收到观察结果: 类型={obs.observation_type}, action_id={obs.action_id}")
            
            if obs.action_id != action_id:
                logger.debug(f"忽略不匹配的action_id: {obs.action_id}，期望: {action_id}")
                continue
                
            observations.append(obs)
            
            if obs.observation_type == "end":
                end_received = True
                logger.debug("收到结束观察结果")
                
        except Empty:
            continue
            
    if not end_received:
        logger.warning(f"在超时时间内未收到结束观察结果，action_id: {action_id}")
        
    return observations
