"""Symbol documentation embedding builder."""
import logging
from copy import copy
from typing import Any, Dict, List

from jinja2 import Template

from automata.config import DOC_GENERATION_TEMPLATE
from automata.core import get_docstring_from_node
from automata.embedding import EmbeddingBuilder, EmbeddingVectorProvider
from automata.experimental.code_parsers import (
    ContextComponent,
    PyContextHandler,
)
from automata.experimental.search import SymbolSearch
from automata.llm import LLMChatCompletionProvider
from automata.symbol import Symbol, convert_to_ast_object
from automata.symbol_embedding import SymbolDocEmbedding

logger = logging.getLogger(__name__)


class SymbolDocEmbeddingBuilder(EmbeddingBuilder):
    """Builds `Symbol` documentation embeddings."""

    # TODO - Make this class more modular and consider it's structure
    def __init__(
        self,
        embedding_provider: EmbeddingVectorProvider,
        completion_provider: LLMChatCompletionProvider,
        symbol_search: SymbolSearch,
        handler: PyContextHandler,
        class_cut_size: int = 500,
    ) -> None:
        super().__init__(embedding_provider)
        self.completion_provider = completion_provider
        self.symbol_search = symbol_search
        self.handler = handler
        self.class_cut_size = class_cut_size

    def build(self, source_code: str, symbol: Symbol) -> SymbolDocEmbedding:
        """
        Build the embedding for a symbol's documentation.
        Example Document Output:
        ===========
        AgentConfig
        ===========
        ``AgentConfig`` is an abstract base class that provides a template for
        configurations related to providers. It contains abstract methods like
        ``setup()`` and ``load()`` that need to be implemented by subclasses.
        This class also handles the configuration of arbitrary types during the
        initialization.
        Overview
        --------
        ``AgentConfig`` is designed for ensuring configurability of providers.
        Subclasses need to provide implementations for the ``setup()`` and
        ``load()`` methods in order to properly define the behavior during the
        agent setup and configuration loading processes. This class follows the
        BaseModel design, making it easy to extend and customize according to
        specific agent requirements.
        Related Symbols
        ---------------
        -  ``automata.agent.instances.OpenAIAutomataAgentInstance.Config``
        -  ``automata.tests.unit.test_automata_agent_builder.test_builder_default_config``
        -  ``automata.tests.unit.test_task_environment.TestURL``
        -  ``automata.agent.agent.AgentInstance.Config``
        Example
        -------
        The following example demonstrates how to create a custom agent
        configuration by extending the ``AgentConfig`` class:
        .. code:: python
        from config.config_types import AgentConfig
        class CustomAgentConfig(AgentConfig):
            def setup(self):
                # Define your custom agent setup process
                pass
            @classmethod
            def load(cls, config_name: AgentConfigName) -> "CustomAgentConfig":
                # Load the config for your custom agent
                pass
        Limitations
        -----------
        ``AgentConfig`` itself is an abstract class and cannot directly be
        instantiated. It must be subclassed, and its methods need to be
        implemented by the extending class according to the specific agent
        requirements. Additionally, the current implementation allows for
        arbitrary types, which may lead to code that is not type-safe.
        Follow-up Questions:
        --------------------
        -  How can we ensure type safety while maintaining the flexibility and
        customizability provided by ``AgentConfig``?
        """

        if len(source_code) < self.class_cut_size:
            logger.info(
                f"Skipping {symbol} with source code {source_code} because of it's small length {len(source_code)})"
            )
            return self.build_non_class(source_code, symbol)

        prompt = self._build_prompt(symbol)
        document = self._build_class_document(copy(prompt))
        summary = self._build_class_document_summary(copy(document))
        embedding = self.embedding_provider.build_embedding_vector(
            copy(document)
        )
        return SymbolDocEmbedding(
            symbol,
            vector=embedding,
            source_code=source_code,
            document=document,
            summary=summary,
            context=prompt,
        )

    def build_non_class(
        self, source_code: str, symbol: Symbol
    ) -> SymbolDocEmbedding:
        """Build the embedding for a non-class type symbol's documentation."""

        if len(source_code) < self.class_cut_size:
            logger.info(
                f"Returning {symbol} with source code {source_code} embedding because of it's small length {len(source_code)})"
            )
            embedding = self.embedding_provider.build_embedding_vector(
                copy(source_code)
            )

            return SymbolDocEmbedding(
                symbol,
                vector=embedding,
                source_code=source_code,
                document=source_code,
                summary=source_code,
                context="",
            )

        ast_object = convert_to_ast_object(symbol)
        raw_doctring = get_docstring_from_node(ast_object)
        document = f"Symbol: {symbol.dotpath}\n{raw_doctring}"

        embedding = self.embedding_provider.build_embedding_vector(document)

        return SymbolDocEmbedding(
            symbol,
            vector=embedding,
            source_code=source_code,
            document=document,
            summary=document,
            context="",
        )

    def _build_class_document_summary(self, document: str) -> str:
        """Build the summary for a class document."""
        return self.completion_provider.standalone_call(
            f"Condense the documentation below down to one to two concise paragraphs:\n {document}\nIf there is an example, include that in full in the output."
        )

    def _build_class_document(self, prompt: str) -> str:
        """Build the document for a class symbol."""
        return self.completion_provider.standalone_call(prompt)

    def _build_prompt(self, symbol: Symbol) -> str:
        """Build the prompt for a symbol doc generation."""

        abbreviated_selected_symbol = symbol.uri.split("/")[1].split("#")[0]
        primary_active_components: Dict[ContextComponent, Any] = {
            ContextComponent.HEADLINE: {},
            ContextComponent.SOURCE_CODE: {},
        }
        tertiary_active_components: Dict[ContextComponent, Any] = {
            ContextComponent.HEADLINE: {},
            ContextComponent.INTERFACE: {},
        }
        context = self.handler.construct_symbol_context(
            symbol,
            primary_active_components=primary_active_components,
            tertiary_active_components=tertiary_active_components,
        )

        return Template(DOC_GENERATION_TEMPLATE).render(
            symbol_dotpath=abbreviated_selected_symbol,
            symbol_context=context,
        )

    def _generate_search_list(
        self, abbreviated_selected_symbol: str
    ) -> List[Symbol]:
        """Generate a search list by splicing the search results on the symbol with the search results biased on automata.tests."""

        search_results = self.symbol_search.get_symbol_rank_results(
            f"{abbreviated_selected_symbol}"
        )
        search_results_with_tests = [
            ele for ele in search_results if "test" in ele[0].uri
        ]
        search_results_without_tests = [
            ele for ele in search_results if "test" not in ele[0].uri
        ]
        search_list: List[Symbol] = []
        for i in range(
            max(
                len(search_results_with_tests),
                len(search_results_without_tests),
            )
        ):
            set_list = set(search_list)
            if (
                i < len(search_results_with_tests)
                and search_results_with_tests[i] not in set_list
            ):
                search_list.append(search_results_with_tests[i][0])
            if (
                i < len(search_results_without_tests)
                and search_results_without_tests[i] not in set_list
            ):
                search_list.append(search_results_without_tests[i][0])
        return search_list

    def batch_build(self, source_text: List[str], symbol: List[Symbol]) -> Any:
        raise NotImplementedError(
            "Batch building not yet implemented for document embeddings."
        )
