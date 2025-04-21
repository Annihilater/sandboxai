# mentis_client/experimental/__init__.py
"""实验性功能模块，包含尚未稳定的功能和集成。

这些功能可能在未来版本中发生变化或被移除，请谨慎使用。
"""

try:
    from .crewai import MentisIPythonTool, MentisShellTool
except ImportError:
    # 如果crewai未安装，这些类将不可用
    pass

try:
    from .langgraph import MentisPythonTool, MentisShellTool as LangGraphMentisShellTool, MentisToolNode
except ImportError:
    # 如果langgraph未安装，这些类将不可用
    pass