"""
MCP SSE Server Entry Point

This module provides an entry point for the MCP SSE server that properly
sets up the Python path before importing the actual server.
"""

import sys
from pathlib import Path

# Ensure /app is in the Python path so we can import shared, services, etc.
app_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(app_root))

# Now import the actual app
from services.mcp.sse_server import app

__all__ = ['app']
