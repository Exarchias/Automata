"""Finds issues from the associated leetcode solutions store"""
import logging
from typing import Optional

import numpy as np
import pandas as pd
import tiktoken
from constants import (
    DIFFICULTIES,
    FETCHER_INSTRUCTIONS,
    MAX_TOKENS,
    RETRIEVER_SYSTEM_PROMPT,
)

from automata.agent import OpenAIAutomataAgent
from automata.config import OpenAIAutomataAgentConfigBuilder

logger = logging.getLogger(__name__)


class LeetCodeSolutionsFinder:
    """A class to find example solutions using OpenAI."""

    def __init__(
        self,
        embedding_provider,
        max_entry_id,
        max_num_examples,
        num_examples_to_screen,
        solutions_data_path,
        lowest_difficulty,
    ) -> None:  # sourcery skip: docstrings-for-functions
        self.embedding_provider = embedding_provider
        self.max_num_examples = max_num_examples
        self.num_examples_to_screen = num_examples_to_screen
        self.available_difficulties = DIFFICULTIES
        self.allowed_difficulties = self.available_difficulties[
            self.available_difficulties.index(lowest_difficulty) :
        ]
        self.load_data(solutions_data_path, max_entry_id)

    def load_data(self, solutions_data_path: str, max_entry_id: int) -> None:
        """Load the data and solutions from provided path."""
        self.solutions_data = pd.read_json(solutions_data_path)
        self.solutions_data = self.solutions_data[
            self.solutions_data["id"] < max_entry_id
        ]

        # Extract the difficulties for each provided problem
        difficulty = []
        for entry in self.solutions_data["code_with_data"].values:
            split_entry = entry.split("\n")
            found_match = False
            for line in split_entry:
                if any(
                    f"# {entry}" in line
                    for entry in self.available_difficulties
                ):
                    difficulty.append(line.split("# ")[1])
                    found_match = True
                    break
            if not found_match:
                difficulty.append("Easy")

        # Check that allowed_difficulties are in the 'code_with_data' column
        # for each entry
        self.solutions_data["difficulty"] = difficulty
        self.solutions_data = self.solutions_data[
            self.solutions_data["difficulty"].isin(self.allowed_difficulties)
        ]

    def get_embedding(self, document: str) -> np.ndarray:
        """Get the embedding for a given row."""
        return self.embedding_provider.build_embedding_vector(document)

    @staticmethod
    def calculate_similarity(
        embedding_a: np.ndarray, embedding_b: np.ndarray
    ) -> np.ndarray:
        """Calculate the similarity between two embeddings."""

        dot_product = np.dot(embedding_a, embedding_b)
        magnitude_a = np.sqrt(np.dot(embedding_a, embedding_a))
        magnitude_b = np.sqrt(np.dot(embedding_b, embedding_b))
        return dot_product / (magnitude_a * magnitude_b)

    def find_best_match_and_explanation(self, query: str) -> str:
        """Find the best matching solution."""
        context_embedding = self.get_embedding(query)

        # Calculate similarities between solution embeddings and latest problem
        # and store in a new column
        self.solutions_data["similarity"] = self.solutions_data[
            "embedding"
        ].apply(
            lambda x: self.calculate_similarity(x, context_embedding)  # type: ignore
        )

        # Sort solutions by similarity
        solutions_data_sorted = self.solutions_data.sort_values(
            by="similarity", ascending=False
        )

        solutions, counter = [], 0
        for code_with_problem in solutions_data_sorted[
            "code_with_problem"
        ].values:
            statement, solution = code_with_problem.split("```python")
            solution = f"```python\\n{solution}"
            statement, _ = statement.split("**Example 1:**")

            solutions.append(
                f"Related Solution {counter}:\nStatement:\n{statement}\nSolution:\n{solution}\n{'-'*50}\n"
            )

            counter += 1
            if counter >= self.num_examples_to_screen:
                break

        encoding = tiktoken.encoding_for_model("gpt-4")
        examples_formatted = "\n".join(solutions)
        examples_tokens_consumed = len(encoding.encode(examples_formatted))

        # truncate the solutions if they are exceeding our available context
        examples_formatted = examples_formatted[
            : min(
                int(
                    MAX_TOKENS
                    / examples_tokens_consumed
                    * 0.8
                    * len(examples_formatted)
                ),
                len(examples_formatted),
            )
        ]

        logging.info(
            f"Tokens consumed (after reduction) = {examples_tokens_consumed}"
        )

        formatted_instructions = FETCHER_INSTRUCTIONS.format(
            QUERY=query,
            MAX_NUM_EXAMPLES=str(self.max_num_examples),
            FORMATTED_EXAMPLES=examples_formatted,
        )

        config = (
            OpenAIAutomataAgentConfigBuilder()
            .with_stream(True)
            .with_verbose(False)
            .with_tools([])
            .with_system_template(RETRIEVER_SYSTEM_PROMPT)
            .build()
        )

        selected: Optional[int] = None
        try:
            logging.info("Attempting to fetch the best solutions now...")
            agent = OpenAIAutomataAgent(formatted_instructions, config)
            result = agent.run()
            selected_input = (
                result.split("Solution:")[1].split("\n")[0].strip()
            )
            selected = (
                None if selected_input == "None" else int(selected_input)
            )
            explanation = str(result.split("Explanation:")[1].strip())
        except Exception as e:
            logger.error(
                f"An error {e} occurred while selecting the best solutions"
            )
            selected = 0
            explanation = "Agentified fetching failed, so we defaulted to the most semantically similar solution."

        selected_solution = solutions[selected] if selected else "None"
        final_result = (
            "To assist you with solving the given problem, you have been",
            f" provdied the following solution:\n{selected_solution}.\n",
            f"\nThis problem was deemed useful because:\n{explanation}",
        )
        return "".join(final_result)
