# mentis_client/__init__.py
"""
Mentis沙箱客户端库

这个库提供了与Mentis Runtime服务交互的客户端接口，允许创建和管理沙箱环境，
以及在这些环境中执行代码和命令。
"""

__version__ = "0.1.0"

# 导出核心组件
from .client import MentisSandbox
from .exceptions import MentisSandboxError, ConnectionError, APIError, WebSocketError
from .models import BaseObservation, parse_observation

# 导出API模型
from .api import (
    SandboxSpec,
    SandboxStatus,
    RunIPythonCellRequest,
    RunShellCommandRequest,
    CreateSandboxRequest,
    Sandbox,
    Space,
    CreateSpaceRequest,
    UpdateSpaceRequest,
)

# 导出空间管理器
from .spaces import SpaceManager

# 导出嵌入式服务器组件
from .embedded import (
    start_server,
    stop_server,
    is_running,
    get_base_url,
    EmbeddedMentisSandbox,
)

__all__ = [
    # 核心组件
    "MentisSandbox",
    "MentisSandboxError",
    "ConnectionError",
    "APIError",
    "WebSocketError",
    "BaseObservation",
    "parse_observation",
    
    # API模型
    "SandboxSpec",
    "SandboxStatus",
    "RunIPythonCellRequest",
    "RunShellCommandRequest",
    "CreateSandboxRequest",
    "Sandbox",
    "Space",
    "CreateSpaceRequest",
    "UpdateSpaceRequest",
    
    # 空间管理器
    "SpaceManager",
    
    # 嵌入式服务器组件
    "start_server",
    "stop_server",
    "is_running",
    "get_base_url",
    "EmbeddedMentisSandbox",
]

# 注意：实验性功能需要显式导入
# from mentis_client.experimental import MentisIPythonTool, MentisShellTool
