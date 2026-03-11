"""
Semantic Tool Filter for Aruba Central + SSH MCP Servers

Uses sentence-transformers and FAISS for semantic similarity search to filter
148 tools down to the most relevant 5-10 tools based on user query.

Supports both Phase 1 (Aruba Central REST API) and Phase 2 (SSH/CLI) tools.
"""

import numpy as np
from typing import List, Tuple
from sentence_transformers import SentenceTransformer
import faiss

from tool_registry import TOOL_REGISTRY

# Try to import SSH tool registry (Phase 2)
try:
    from ssh_tool_registry import SSH_TOOL_REGISTRY
    HAS_SSH_TOOLS = True
except ImportError:
    SSH_TOOL_REGISTRY = {}
    HAS_SSH_TOOLS = False


class SemanticToolFilter:
    """
    Semantic filter that uses embeddings and cosine similarity to find
    the most relevant tools for a given query.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", min_relevance: float = 0.15):
        """
        Initialize the semantic tool filter.

        Args:
            model_name: Sentence transformer model to use (runs 100% locally)
            min_relevance: Minimum cosine similarity threshold for relevance
        """
        self.model_name = model_name
        self.min_relevance = min_relevance

        # Merge Phase 1 + Phase 2 registries
        self.combined_registry = {}
        self.combined_registry.update(TOOL_REGISTRY)
        if HAS_SSH_TOOLS:
            self.combined_registry.update(SSH_TOOL_REGISTRY)

        # Load the sentence transformer model
        print(f"Loading sentence transformer model: {model_name}...")
        self.model = SentenceTransformer(model_name)

        # Build the tool index
        self._build_index()

        phase_info = f"Phase 1: {len(TOOL_REGISTRY)} API tools"
        if HAS_SSH_TOOLS:
            phase_info += f" + Phase 2: {len(SSH_TOOL_REGISTRY)} SSH tools"
        print(f"Tool filter initialized with {len(self.tool_names)} tools ({phase_info})")

    def _build_index(self):
        """Build FAISS index from tool descriptions."""
        self.tool_names = list(self.combined_registry.keys())

        # Create rich text descriptions for better semantic matching
        tool_texts = []
        for tool_name in self.tool_names:
            metadata = self.combined_registry[tool_name]
            text = f"{metadata['description']} Keywords: {', '.join(metadata['keywords'])}"
            tool_texts.append(text)

        # Generate embeddings
        print("Generating embeddings for all tools...")
        self.tool_embeddings = self.model.encode(tool_texts, convert_to_numpy=True)

        # Normalize embeddings for cosine similarity
        faiss.normalize_L2(self.tool_embeddings)

        # Create FAISS index
        dimension = self.tool_embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dimension)
        self.index.add(self.tool_embeddings)

    def filter(self, query: str, top_k: int = 8) -> List[str]:
        """
        Filter tools to find the most relevant ones for a query.

        Args:
            query: User query to search for relevant tools
            top_k: Number of top tools to return

        Returns:
            List of tool names, ordered by relevance
        """
        query_embedding = self.model.encode([query], convert_to_numpy=True)
        faiss.normalize_L2(query_embedding)

        scores, indices = self.index.search(query_embedding, top_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if score >= self.min_relevance:
                results.append(self.tool_names[idx])

        return results

    def filter_with_scores(self, query: str, top_k: int = 8) -> List[Tuple[str, float]]:
        """
        Filter tools and return with relevance scores for debugging.

        Args:
            query: User query
            top_k: Number of top tools

        Returns:
            List of (tool_name, score) tuples
        """
        query_embedding = self.model.encode([query], convert_to_numpy=True)
        faiss.normalize_L2(query_embedding)

        scores, indices = self.index.search(query_embedding, top_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if score >= self.min_relevance:
                results.append((self.tool_names[idx], float(score)))

        return results