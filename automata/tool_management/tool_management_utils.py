import importlib
import logging
from typing import Dict, List

from automata.core.base.tool import Tool, Toolkit, ToolkitType
from automata.core.utils import root_py_path
from automata.tool_management.base_tool_manager import BaseToolManager
from automata.tools.python_tools.python_indexer import PythonIndexer
from automata.tools.python_tools.python_writer import PythonWriter

logger = logging.getLogger(__name__)


class ToolManagerFactory:
    """
    A class for creating tool managers.
    """

    @staticmethod
    def create_tool_manager(toolkit_type: ToolkitType) -> BaseToolManager:
        """
        Creates a tool manager of the given type.

        Args:
        - toolkit_type (ToolkitType): The type of toolkit to create.

        Returns:
        - BaseToolManager: A tool manager of the given type.

        Raises:
        - ValueError: If the toolkit type is unknown.
        """
        if toolkit_type == ToolkitType.PYTHON_INDEXER:
            python_indexer = PythonIndexer(root_py_path())
            PythonIndexerToolManager = importlib.import_module(
                "automata.tool_management.python_indexer_tool_manager"
            ).PythonIndexerToolManager
            return PythonIndexerToolManager(python_indexer=python_indexer)
        elif toolkit_type == ToolkitType.PYTHON_WRITER:
            python_indexer = PythonIndexer(root_py_path())
            PythonWriterToolManager = importlib.import_module(
                "automata.tool_management.python_writer_tool_manager"
            ).PythonWriterToolManager
            return PythonWriterToolManager(python_writer=PythonWriter(python_indexer))
        elif toolkit_type == ToolkitType.COVERAGE_PROCESSOR:
            CoverageToolManager = importlib.import_module(
                "automata.tool_management.coverage_tool_manager"
            ).CoverageToolManager
            return CoverageToolManager()
        else:
            raise ValueError("Unknown toolkit type: %s" % toolkit_type)


class ToolkitBuilder:
    def __init__(self, **kwargs):
        """Initializes a ToolkitBuilder object with the given inputs."""

        self._tool_management: Dict[ToolkitType, BaseToolManager] = {}

    def _build_toolkit(self, toolkit_type: ToolkitType) -> Toolkit:
        """Builds a toolkit of the given type."""
        tool_manager = ToolManagerFactory.create_tool_manager(toolkit_type)

        if not tool_manager:
            raise ValueError("Unknown toolkit type: %s" % toolkit_type)
        tools = ToolkitBuilder.build_tools(tool_manager)
        return Toolkit(tools)

    @staticmethod
    def build_tools(tool_manager: BaseToolManager) -> List[Tool]:
        """Build tools from a tool manager."""
        return tool_manager.build_tools()


def build_llm_toolkits(tool_list: List[str], **kwargs) -> Dict[ToolkitType, Toolkit]:
    """
    Loads the tools specified in the tool_list and returns a dictionary of the loaded tools.

    Args:
        tool_list: A list of tool names to load.
        kwargs: A dictionary of inputs to pass to the tools.

    Returns:
        A dictionary of loaded tools.

    Raises:
        ValueError: If an unknown tool is specified.
    """

    toolkits: Dict[ToolkitType, Toolkit] = {}
    toolkit_builder = ToolkitBuilder(**kwargs)
    for tool_name in tool_list:
        tool_name = tool_name.strip()
        toolkit_type = None
        if tool_name == "python_indexer":
            toolkit_type = ToolkitType.PYTHON_INDEXER
        elif tool_name == "python_writer":
            toolkit_type = ToolkitType.PYTHON_WRITER
        elif tool_name == "coverage_processor":
            toolkit_type = ToolkitType.COVERAGE_PROCESSOR
        else:
            logger.warning("Unknown tool: %s", tool_name)
            raise ValueError(f"Unknown tool: {tool_name}")
        if not toolkit_type:
            raise ValueError(f"Unknown tool: {tool_name}")

        toolkit = toolkit_builder._build_toolkit(toolkit_type)  # type: ignore
        toolkits[toolkit_type] = toolkit

    return toolkits
