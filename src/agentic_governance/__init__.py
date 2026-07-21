from ._version import PACKAGE_VERSION as __version__
from .integrations.langgraph_mcp.governed_mcp_call import install

__all__ = ["__version__", "install"]
