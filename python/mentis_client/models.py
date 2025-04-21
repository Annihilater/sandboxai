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
    observation_type: Literal["IPythonStartObservation", "start"]
    code: str
    execution_count: Optional[int] = None # May arrive later

class IPythonOutputObservationPart(BaseObservation):
    observation_type: Literal["IPythonOutputObservationPart", "stream"] # 添加服务器实际发送的'stream'类型
    # Based on Jupyter spec, stream can be stdout, stderr
    # display_data, execute_result, update_display_data have 'data' dict
    stream: Literal["stdout", "stderr", "display_data", "execute_result", "update_display_data"] # Add others if needed
    data: Any # Can be str for stdout/err, Dict[str, Any] for rich outputs
    line: Optional[str] = None # 服务器发送的'stream'类型使用'line'字段而不是'data'字段

class IPythonResultObservation(BaseObservation):
    observation_type: Literal["IPythonResultObservation", "result", "end"]
    status: Literal["ok", "error"] = "ok"  # 默认为ok
    execution_count: Optional[int] = None  # 设为可选
    # 添加服务器可能发送的字段
    exit_code: Optional[int] = None
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
    
    # 记录原始action_id，用于调试
    original_action_id = data.get("action_id")
    if original_action_id:
        logger.debug(f"Processing observation with original action_id: {original_action_id}")
    
    # 创建数据副本，确保不修改原始数据
    data_copy = data.copy()
    
    # 处理服务器发送的特殊类型观察数据
    if obs_type == "stream":
        # 将'line'字段复制到'data'字段，以便与IPythonOutputObservationPart兼容
        if "line" in data_copy and "data" not in data_copy:
            data_copy["data"] = data_copy["line"]
        # 确保保留原始action_id
        logger.debug(f"Converting 'stream' observation with action_id: {original_action_id}")
        return IPythonOutputObservationPart(**data_copy)
    
    # 处理服务器发送的'start'类型观察数据
    if obs_type == "start":
        # 确保数据包含必要的字段
        if "code" not in data_copy:
            # 如果没有code字段，添加一个空字符串
            data_copy["code"] = ""
        # 确保保留原始action_id
        logger.debug(f"Converting 'start' observation with action_id: {original_action_id}")
        return IPythonStartObservation(**data_copy)
        
    # 处理服务器发送的'end'类型观察数据
    if obs_type == "end":
        # 如果没有status字段，根据exit_code设置status
        if "status" not in data_copy:
            data_copy["status"] = "ok" if data_copy.get("exit_code", 0) == 0 else "error"
        # 确保保留原始action_id
        logger.debug(f"Converting 'end' observation with action_id: {original_action_id}")
        return IPythonResultObservation(**data_copy)
    
    # 处理服务器发送的'result'类型观察数据
    if obs_type == "result":
        # 如果没有status字段，根据exit_code设置status
        if "status" not in data_copy:
            data_copy["status"] = "ok" if data_copy.get("exit_code", 0) == 0 else "error"
        # 确保保留原始action_id
        logger.debug(f"Converting 'result' observation with action_id: {original_action_id}")
        return IPythonResultObservation(**data_copy)
    
    # 处理标准观察类型
    if obs_type == "CmdStartObservation":
        logger.debug(f"Processing CmdStartObservation with action_id: {original_action_id}")
        return CmdStartObservation(**data_copy)
    elif obs_type == "CmdOutputObservationPart":
        logger.debug(f"Processing CmdOutputObservationPart with action_id: {original_action_id}")
        return CmdOutputObservationPart(**data_copy)
    elif obs_type == "CmdEndObservation":
        logger.debug(f"Processing CmdEndObservation with action_id: {original_action_id}")
        return CmdEndObservation(**data_copy)
    elif obs_type == "IPythonStartObservation":
        logger.debug(f"Processing IPythonStartObservation with action_id: {original_action_id}")
        return IPythonStartObservation(**data_copy)
    elif obs_type == "IPythonOutputObservationPart":
        logger.debug(f"Processing IPythonOutputObservationPart with action_id: {original_action_id}")
        return IPythonOutputObservationPart(**data_copy)
    elif obs_type == "IPythonResultObservation":
        logger.debug(f"Processing IPythonResultObservation with action_id: {original_action_id}")
        return IPythonResultObservation(**data_copy)
    elif obs_type == "ErrorObservation":
        logger.debug(f"Processing ErrorObservation with action_id: {original_action_id}")
        return ErrorObservation(**data_copy)
    elif obs_type == "AgentStateObservation":
        logger.debug(f"Processing AgentStateObservation with action_id: {original_action_id}")
        return AgentStateObservation(**data_copy)
    else:
        # Fallback or raise error for unknown types
        logger.warning(f"Received unknown observation type: {obs_type} with action_id: {original_action_id}")
        # Return BaseObservation or a custom UnknownObservation type
        # This might fail if fields don't match base, consider a dedicated UnknownObservation model
        try:
            return BaseObservation(**data_copy)
        except Exception:
             logger.error(f"Failed to parse unknown observation type {obs_type} with action_id: {original_action_id} as BaseObservation.", exc_info=True)
             # Return a minimal representation or raise an error
             return BaseObservation(observation_type=obs_type or "Unknown", action_id=original_action_id, timestamp=datetime.now()) # Example fallback
