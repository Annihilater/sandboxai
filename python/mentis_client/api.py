# mentis_client/api.py
from __future__ import annotations

from typing import Dict, Optional, List, Any, Union
from pydantic import BaseModel, Field, validator
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

    @validator('image')
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