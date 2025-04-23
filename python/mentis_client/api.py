# mentis_client/api.py
from __future__ import annotations

from typing import Dict, Optional, List, Any, Union
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


class Error(BaseModel):
    """Error response model"""
    message: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Detailed error information")
    code: Optional[str] = Field(None, description="Error code for programmatic handling")


class SandboxSpec(BaseModel):
    """Sandbox specification model"""
    image: Optional[str] = Field(
        None,
        description="Container image for the sandbox",
        min_length=1
    )
    env: Optional[Dict[str, str]] = Field(
        None,
        description="Environment variables for the sandbox"
    )
    resources: Optional[Dict[str, Any]] = Field(
        None,
        description="Resource limits configuration"
    )

    @field_validator('image')
    def validate_image(cls, v):
        if v is not None and ':' not in v:
            raise ValueError("Image must include a tag (e.g., 'python:3.9')")
        return v


class SandboxStatus(BaseModel):
    """Sandbox status information"""
    state: Optional[str] = Field(
        None,
        description="Current state of the sandbox",
        pattern="^(running|stopped|error|unknown)$"
    )
    start_time: Optional[datetime] = Field(
        None,
        description="Sandbox start time"
    )
    ready: Optional[bool] = Field(
        None,
        description="Whether the sandbox is ready"
    )


class RunIPythonCellRequest(BaseModel):
    """Request model for executing IPython cell"""
    code: str = Field(
        ...,
        description="Code to execute in IPython kernel",
        min_length=1
    )
    timeout: Optional[int] = Field(
        None,
        description="Execution timeout in seconds",
        ge=1
    )
    work_dir: Optional[str] = Field(
        None,
        description="Working directory for execution"
    )
    env: Optional[Dict[str, str]] = Field(
        None,
        description="Execution environment variables"
    )
    # --- Added Fields ---
    action_id: Optional[str] = Field(
        None,
        description="Action ID provided by runtime for observation tracking (Used internally between runtime and agent)"
    )
    split_output: Optional[bool] = Field(
        False,
        description="Whether to split stdout and stderr in observations/results (Currently ignored by executor)"
    )
    # --- End Added Fields ---


class RunShellCommandRequest(BaseModel):
    """Request model for executing shell command"""
    command: str = Field(
        ...,
        description="Command to execute",
        min_length=1
    )
    timeout: Optional[int] = Field(
        None,
        description="Execution timeout in seconds",
        ge=1
    )
    work_dir: Optional[str] = Field(
        None,
        description="Working directory for execution"
    )
    env: Optional[Dict[str, str]] = Field(
        None,
        description="Execution environment variables"
    )
    # --- Added Fields ---
    action_id: Optional[str] = Field(
        None,
        description="Action ID provided by runtime for observation tracking (Used internally between runtime and agent)"
    )
    split_output: Optional[bool] = Field(
        False,
        description="Whether to split stdout and stderr in observations/results (Currently ignored by executor)"
    )
    # --- End Added Fields ---


class ActionResult(BaseModel):
    """Result of an action execution, typically sent as an observation"""
    action_id: str = Field(..., description="Identifier of the action this result belongs to")
    exit_code: int = Field(..., description="Exit code of the executed command or cell")
    error: Optional[str] = Field(None, description="Error message if execution failed")
    # Depending on your observation structure, you might add stdout/stderr here too
    # stdout: Optional[str] = Field(None, description="Standard output if not streamed")
    # stderr: Optional[str] = Field(None, description="Standard error if not streamed")


class Observation(BaseModel):
    """Model for observations pushed from agent to runtime or streamed via WebSocket"""
    observation_type: str = Field(..., description="Type of observation (e.g., start, stream, result, error, end)", pattern="^(start|stream|result|error|end)$")
    action_id: str = Field(..., description="Identifier of the action this observation relates to")
    timestamp: datetime = Field(..., description="Timestamp when the observation was generated (UTC)")
    stream: Optional[str] = Field(None, description="Stream type if observation_type is 'stream'", pattern="^(stdout|stderr)$")
    line: Optional[str] = Field(None, description="Content of the stream line if observation_type is 'stream'")
    exit_code: Optional[int] = Field(None, description="Exit code if observation_type is 'result' or 'end'")
    error: Optional[str] = Field(None, description="Error message if observation_type is 'error', 'result' or 'end'")
    # You might nest ActionResult here for 'result' type if preferred


class CreateSandboxRequest(BaseModel):
    """Request model for creating a sandbox"""
    name: Optional[str] = Field(
        None,
        description="Name of the sandbox. If not specified, will be auto-generated",
        min_length=1,
        max_length=63,
        pattern="^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"
    )
    spec: Optional[SandboxSpec] = Field(
        None,
        description="Sandbox specification"
    )
    space: Optional[str] = Field(
        "default",
        description="Space the sandbox belongs to",
        min_length=1,
        max_length=63,
        pattern="^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"
    )


class Sandbox(BaseModel):
    """Sandbox resource model"""
    sandbox_id: str = Field(
        ...,
        description="Unique identifier for the sandbox",
        min_length=1
    )
    name: Optional[str] = Field(
        None,
        description="Name of the sandbox"
    )
    spec: Optional[SandboxSpec] = Field(
        None,
        description="Sandbox specification"
    )
    status: Optional[SandboxStatus] = Field(
        None,
        description="Sandbox status"
    )
    space: Optional[str] = Field(
        "default",
        description="Space the sandbox belongs to"
    )
    created_at: Optional[datetime] = Field(
        None,
        description="Sandbox creation time"
    )
    # --- Added Field (Based on runtime logs/v1.yaml) ---
    agent_url: Optional[str] = Field(None, description="URL to access the agent inside the sandbox")
    # --- End Added Field ---


class Space(BaseModel):
    """Space resource model"""
    space_id: str = Field(
        ...,
        description="Unique identifier for the space",
        min_length=1
    )
    name: str = Field(
        ...,
        description="Name of the space",
        min_length=1,
        max_length=63,
        pattern="^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"
    )
    description: Optional[str] = Field(
        None,
        description="Description of the space"
    )
    created_at: Optional[datetime] = Field(
        None,
        description="Space creation time"
    )
    updated_at: Optional[datetime] = Field(
        None,
        description="Space last update time"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Space metadata"
    )


class CreateSpaceRequest(BaseModel):
    """Request model for creating a space"""
    name: str = Field(
        ...,
        description="Name of the space",
        min_length=1,
        max_length=63,
        pattern="^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"
    )
    description: Optional[str] = Field(
        None,
        description="Description of the space"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Space metadata"
    )


class UpdateSpaceRequest(BaseModel):
    """Request model for updating a space"""
    description: Optional[str] = Field(
        None,
        description="New description for the space"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="New metadata for the space"
    )