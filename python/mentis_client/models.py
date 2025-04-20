# mentis_client/models.py
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any, Literal, Union
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# --- Base Model ---
class BaseObservation(BaseModel):
    observation_type: str
    action_id: Optional[str] = None # UUID as string
    timestamp: datetime # Pydantic handles ISO string parsing

# --- Specific Observation Models (Phase 1) ---

class CmdStartObservation(BaseObservation):
    observation_type: Literal["CmdStartObservation"]
    command: str
    pid: int

class CmdOutputObservationPart(BaseObservation):
    observation_type: Literal["CmdOutputObservationPart"]
    pid: int
    stream: Literal["stdout", "stderr"]
    data: str

class CmdEndObservation(BaseObservation):
    observation_type: Literal["CmdEndObservation"]
    pid: int
    command: str
    exit_code: int

class IPythonStartObservation(BaseObservation):
    observation_type: Literal["IPythonStartObservation"]
    code: str
    execution_count: Optional[int] = None # May arrive later

class IPythonOutputObservationPart(BaseObservation):
    observation_type: Literal["IPythonOutputObservationPart"]
    # Based on Jupyter spec, stream can be stdout, stderr
    # display_data, execute_result, update_display_data have 'data' dict
    stream: Literal["stdout", "stderr", "display_data", "execute_result", "update_display_data"] # Add others if needed
    data: Any # Can be str for stdout/err, Dict[str, Any] for rich outputs

class IPythonResultObservation(BaseObservation):
    observation_type: Literal["IPythonResultObservation"]
    status: Literal["ok", "error"]
    execution_count: int
    # Fields present on error:
    error_name: Optional[str] = None
    error_value: Optional[str] = None
    traceback: Optional[List[str]] = None

class ErrorObservation(BaseObservation):
    observation_type: Literal["ErrorObservation"]
    message: str
    details: Optional[str] = None

class AgentStateObservation(BaseObservation):
    # Basic placeholder for async server-pushed events not tied to an action
    observation_type: Literal["AgentStateObservation"]
    message: str
    state_details: Optional[Dict[str, Any]] = None


# --- Discriminated Union for Parsing ---
# Use Field(discriminator='observation_type') with Pydantic v2 for robust parsing
StreamMessage = Union[
    CmdStartObservation,
    CmdOutputObservationPart,
    CmdEndObservation,
    IPythonStartObservation,
    IPythonOutputObservationPart,
    IPythonResultObservation,
    ErrorObservation,
    AgentStateObservation,
    # Add future Observation types here
]

# Example parsing function (could be used in the callback)
def parse_observation(data: Dict[str, Any]) -> BaseObservation:
    """Parses raw dict into specific Pydantic Observation model."""
    # Pydantic v2 with discriminated unions handles this automatically if StreamMessage is annotated
    # Manual way for Pydantic v1 or without unions:
    obs_type = data.get("observation_type")
    if obs_type == "CmdStartObservation":
        return CmdStartObservation(**data)
    elif obs_type == "CmdOutputObservationPart":
        return CmdOutputObservationPart(**data)
    elif obs_type == "CmdEndObservation":
        return CmdEndObservation(**data)
    elif obs_type == "IPythonStartObservation":
        return IPythonStartObservation(**data)
    elif obs_type == "IPythonOutputObservationPart":
        return IPythonOutputObservationPart(**data)
    elif obs_type == "IPythonResultObservation":
        return IPythonResultObservation(**data)
    elif obs_type == "ErrorObservation":
        return ErrorObservation(**data)
    elif obs_type == "AgentStateObservation":
        return AgentStateObservation(**data)
    else:
        # Fallback or raise error for unknown types
        logger.warning(f"Received unknown observation type: {obs_type}")
        # Return BaseObservation or a custom UnknownObservation type
        # This might fail if fields don't match base, consider a dedicated UnknownObservation model
        try:
            return BaseObservation(**data)
        except Exception:
             logger.error(f"Failed to parse unknown observation type {obs_type} as BaseObservation.", exc_info=True)
             # Return a minimal representation or raise an error
             return BaseObservation(observation_type=obs_type or "Unknown", timestamp=datetime.now()) # Example fallback
