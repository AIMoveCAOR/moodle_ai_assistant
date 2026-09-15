"""Infomaniak Cohere-compatible remote reranker."""

import logging
from typing import List, Tuple

import httpx
from langchain_core.documents.base import Document

logger = logging.getLogger(__name__)


class InfomaniakReranker:
    """Calls Infomaniak's /cohere/v2/rerank endpoint to score and filter documents.

    Scores returned are calibrated probabilities in [0, 1].  Documents below
    `threshold` are dropped; survivors are returned sorted by score descending.
    """

    _ENDPOINT = "https://api.infomaniak.com/2/ai/{product_id}/cohere/v2/rerank"

    def __init__(self, api_key: str, product_id: str, model: str, threshold: float):
        self._api_key = api_key
        self._url = self._ENDPOINT.format(product_id=product_id)
        self._model = model
        self._threshold = threshold

    def rerank(self, query: str, documents: List[Document]) -> List[Document]:
        """Return documents filtered by threshold and sorted by relevance score (desc)."""
        return [doc for score, doc in self.score(query, documents) if score >= self._threshold]

    def score(self, query: str, documents: List[Document]) -> List[Tuple[float, Document]]:
        """Return every document with its relevance score, sorted by score (desc).

        No threshold is applied: callers that select relative to the top score
        (RAGService.retrieve_ranked) need the full distribution.
        """
        if not documents:
            return []

        payload = {
            "model": self._model,
            "query": query,
            "documents": [doc.page_content for doc in documents],
            "return_documents": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(self._url, json=payload, headers=headers)

        if response.status_code != 200:
            raise RuntimeError(
                f"Infomaniak reranker API error {response.status_code}: {response.text}"
            )

        results = response.json().get("results", [])
        scored = sorted(
            ((float(r["relevance_score"]), documents[r["index"]]) for r in results),
            key=lambda x: x[0],
            reverse=True,
        )

        # Per-document scores, so it is possible to tell WHICH document earned
        # which score — without this, a wrong video card is indistinguishable
        # from a wrong ranking. Only the head: the pool can be 50+ documents.
        for score, doc in scored[:12]:
            logger.info(
                "  rerank %.4f  %-16s %s",
                score,
                doc.metadata.get("type", "?"),
                doc.metadata.get("source", "?")[:80],
            )
        logger.info(f"remote rerank: scored {len(documents)} candidates")
        return scored
