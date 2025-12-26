"""
Tool Executor for Civic Commons

Centralized execution layer for all tools with:
- Argument validation and sanitization
- Execution timing and performance metrics
- Structured logging to activity_log
- Error handling and recovery
- Result truncation for database storage
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Optional

from .tool_registry import TOOLS, AccessLevel

logger = logging.getLogger("tool_executor")


class ToolExecutionResult:
    """Result of a tool execution."""
    
    def __init__(
        self,
        name: str,
        success: bool,
        result: Any = None,
        error: Optional[str] = None,
        execution_time_ms: float = 0,
        args: Optional[dict] = None,
        source: Optional[str] = None,
    ):
        self.name = name
        self.success = success
        self.result = result
        self.error = error
        self.execution_time_ms = execution_time_ms
        self.args = args or {}
        self.source = source  # "chat", "rest", "mcp"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "source": self.source,
        }
    
    def to_activity_log_details(self) -> dict[str, Any]:
        """Convert to activity_log details format."""
        return {
            "tool_name": self.name,
            "tool_args": self._sanitize_for_storage(self.args),
            "tool_result": self._sanitize_for_storage(self.result),
            "execution_time_ms": round(self.execution_time_ms, 2),
            "source": self.source,
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    @staticmethod
    def _sanitize_for_storage(data: Any, max_length: int = 1000) -> Any:
        """
        Sanitize data for storage in activity_log.
        Truncates large strings, removes sensitive nested objects.
        """
        if isinstance(data, str):
            if len(data) > max_length:
                return f"{data[:max_length]}... [truncated {len(data) - max_length} chars]"
            return data
        elif isinstance(data, dict):
            return {k: ToolExecutionResult._sanitize_for_storage(v, max_length) for k, v in data.items()}
        elif isinstance(data, list):
            return [ToolExecutionResult._sanitize_for_storage(item, max_length) for item in data[:10]]
        return data


class ToolExecutor:
    """
    Executes tools with proper logging, error handling, and timing.
    """
    
    def __init__(self, activity_logger=None):
        """
        Initialize executor.
        
        Args:
            activity_logger: ActivityLogger instance for logging tool calls
        """
        self.activity_logger = activity_logger
        self.tool_cache = {}  # Cache for loaded tool functions
    
    async def execute_tool(
        self,
        name: str,
        args: dict[str, Any],
        source: str = "unknown",
        city_id: Optional[str] = None,
        access_level: AccessLevel = "read_only",
    ) -> ToolExecutionResult:
        """
        Execute a tool with logging and error handling.
        
        Args:
            name: Tool name
            args: Tool arguments
            source: Source of call (chat, rest, mcp)
            city_id: City context for logging
            access_level: Required access level for authorization
            
        Returns:
            ToolExecutionResult with execution details
        """
        start_time = time.time()
        
        # Validate tool exists
        if name not in TOOLS:
            error_msg = f"Tool '{name}' not found"
            logger.error(error_msg)
            return ToolExecutionResult(
                name=name,
                success=False,
                error=error_msg,
                execution_time_ms=0,
                args=args,
                source=source,
            )
        
        tool_def = TOOLS[name]
        
        # Check access level
        if tool_def.access_level != access_level:
            error_msg = f"Tool '{name}' requires {tool_def.access_level} access, got {access_level}"
            logger.warning(error_msg)
            return ToolExecutionResult(
                name=name,
                success=False,
                error=error_msg,
                execution_time_ms=0,
                args=args,
                source=source,
            )
        
        # Log tool started
        if self.activity_logger:
            try:
                await self.activity_logger.log_tool_started(
                    name,
                    args=args,
                    source=source,
                    city_id=city_id,
                )
            except Exception as e:
                logger.warning(f"Failed to log tool start for {name}: {e}")
        
        try:
            # Validate and sanitize args
            validated_args = self._validate_arguments(name, args)
            
            # Load and execute tool
            logger.debug(f"Executing tool: {name} with source: {source}")
            tool_func = await self._get_tool_function(tool_def.handler_path)
            
            # Execute with timeout
            result = await asyncio.wait_for(
                tool_func(**validated_args),
                timeout=30.0,  # 30 second timeout
            )
            
            execution_time = (time.time() - start_time) * 1000  # Convert to ms
            
            # Log tool completed
            if self.activity_logger:
                try:
                    await self.activity_logger.log_tool_completed(
                        name,
                        args=validated_args,
                        result=result,
                        execution_time_ms=execution_time,
                        source=source,
                        city_id=city_id,
                    )
                except Exception as e:
                    logger.warning(f"Failed to log tool completion for {name}: {e}")
            
            logger.info(f"Tool {name} executed successfully in {execution_time:.2f}ms")
            
            return ToolExecutionResult(
                name=name,
                success=True,
                result=result,
                execution_time_ms=execution_time,
                args=validated_args,
                source=source,
            )
        
        except asyncio.TimeoutError:
            execution_time = (time.time() - start_time) * 1000
            error_msg = f"Tool execution timed out after 30 seconds"
            logger.error(error_msg)
            
            if self.activity_logger:
                try:
                    await self.activity_logger.log_tool_failed(
                        name,
                        error=error_msg,
                        execution_time_ms=execution_time,
                        source=source,
                        city_id=city_id,
                    )
                except Exception as e:
                    logger.warning(f"Failed to log tool failure for {name}: {e}")
            
            return ToolExecutionResult(
                name=name,
                success=False,
                error=error_msg,
                execution_time_ms=execution_time,
                args=args,
                source=source,
            )
        
        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            error_msg = f"Tool execution failed: {str(e)}"
            logger.exception(f"Error executing tool {name}")
            
            if self.activity_logger:
                try:
                    await self.activity_logger.log_tool_failed(
                        name,
                        error=error_msg,
                        execution_time_ms=execution_time,
                        source=source,
                        city_id=city_id,
                    )
                except Exception as log_e:
                    logger.warning(f"Failed to log tool failure for {name}: {log_e}")
            
            return ToolExecutionResult(
                name=name,
                success=False,
                error=error_msg,
                execution_time_ms=execution_time,
                args=args,
                source=source,
            )
    
    def _validate_arguments(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """
        Validate and sanitize tool arguments.
        
        Args:
            tool_name: Name of tool
            args: Arguments to validate
            
        Returns:
            Validated arguments
        """
        tool_def = TOOLS.get(tool_name)
        if not tool_def:
            return args
        
        # Check required parameters
        required = tool_def.parameters.get("required", [])
        for param in required:
            if param not in args:
                raise ValueError(f"Missing required parameter: {param}")
        
        # Sanitize string values
        sanitized = {}
        for key, value in args.items():
            if isinstance(value, str) and len(value) > 5000:
                sanitized[key] = f"{value[:5000]}... [truncated]"
            else:
                sanitized[key] = value
        
        return sanitized
    
    async def _get_tool_function(self, handler_path: str):
        """
        Load a tool function from handler path.
        Uses caching to avoid repeated imports.
        Handles both "server.module.func" and "module.func" paths for Docker compatibility.
        
        Args:
            handler_path: Module path to function (e.g., "server.tools.get_events" or "tools.get_events")
            
        Returns:
            Callable tool function
        """
        if handler_path in self.tool_cache:
            return self.tool_cache[handler_path]
        
        try:
            parts = handler_path.rsplit(".", 1)
            if len(parts) != 2:
                raise ImportError(f"Invalid handler path: {handler_path}")
            
            module_path, func_name = parts
            
            # Try original path first
            try:
                module = __import__(module_path, fromlist=[func_name])
                tool_func = getattr(module, func_name)
            except (ImportError, AttributeError):
                # For Docker, try removing "server." prefix
                if module_path.startswith("server."):
                    alt_module_path = module_path[7:]  # Remove "server."
                    module = __import__(alt_module_path, fromlist=[func_name])
                    tool_func = getattr(module, func_name)
                # For scraper paths, also try removing "scraper." prefix
                elif module_path.startswith("scraper."):
                    alt_module_path = module_path[8:]  # Remove "scraper."
                    module = __import__(alt_module_path, fromlist=[func_name])
                    tool_func = getattr(module, func_name)
                else:
                    raise
            
            self.tool_cache[handler_path] = tool_func
            return tool_func
        
        except (ImportError, AttributeError) as e:
            raise ImportError(f"Failed to load tool function {handler_path}: {e}")
    
    async def batch_execute(
        self,
        tools: list[tuple[str, dict[str, Any]]],
        source: str = "unknown",
        city_id: Optional[str] = None,
        stop_on_error: bool = False,
    ) -> list[ToolExecutionResult]:
        """
        Execute multiple tools in parallel.
        
        Args:
            tools: List of (tool_name, args) tuples
            source: Source of calls
            city_id: City context
            stop_on_error: Stop on first error
            
        Returns:
            List of ToolExecutionResult
        """
        tasks = [
            self.execute_tool(name, args, source=source, city_id=city_id)
            for name, args in tools
        ]
        
        if stop_on_error:
            results = []
            for task in tasks:
                result = await task
                results.append(result)
                if not result.success:
                    break
            return results
        else:
            return await asyncio.gather(*tasks)


async def create_executor(activity_logger=None) -> ToolExecutor:
    """
    Factory function to create a ToolExecutor.
    
    Args:
        activity_logger: ActivityLogger instance
        
    Returns:
        Initialized ToolExecutor
    """
    return ToolExecutor(activity_logger=activity_logger)

