from ._version import PACKAGE_VERSION as __version__
from .integrations.langgraph_mcp.governed_mcp_call import install
from .integrations.langgraph_mcp.content_governance_builder import install_content_hooks

__all__ = ["__version__", "install", "install_content_hooks"]
