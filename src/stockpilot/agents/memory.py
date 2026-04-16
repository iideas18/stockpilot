"""Financial situation memory with BM25 semantic retrieval.

Stores past analyses and recommendations, retrieves relevant context
for new analyses using BM25 lexical similarity. Persists to SQLite.
Ported from TradingAgents' FinancialSituationMemory.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FinancialSituationMemory:
    """Memory system for storing and retrieving financial analysis context."""

    def __init__(self, name: str = "default", db_path: str | None = None):
        self.name = name
        self._db_path = db_path or str(
            Path(__file__).resolve().parent.parent.parent.parent / "data" / "memory.db"
        )
        self.documents: list[str] = []
        self.recommendations: list[str] = []
        self.metadata: list[dict] = []
        self.bm25 = None
        self._ensure_db()
        self._load_from_db()

    def _ensure_db(self):
        """Create SQLite tables if they don't exist."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_name TEXT NOT NULL,
                    situation TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_name
                ON memories(memory_name)
            """)

    def _load_from_db(self):
        """Load existing memories from SQLite."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT situation, recommendation, metadata FROM memories WHERE memory_name = ? ORDER BY id",
                    (self.name,),
                ).fetchall()
            for situation, recommendation, meta_json in rows:
                self.documents.append(situation)
                self.recommendations.append(recommendation)
                self.metadata.append(json.loads(meta_json) if meta_json else {})
            if self.documents:
                self._rebuild_index()
                logger.info("Loaded %d memories for '%s'", len(self.documents), self.name)
        except Exception as e:
            logger.warning("Failed to load memories: %s", e)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenize text for BM25 indexing."""
        return re.findall(r"\b\w+\b", text.lower())

    def _rebuild_index(self):
        """Rebuild BM25 index after adding documents."""
        try:
            from rank_bm25 import BM25Okapi
            tokenized = [self._tokenize(doc) for doc in self.documents]
            self.bm25 = BM25Okapi(tokenized)
        except ImportError:
            logger.warning("rank-bm25 not installed; memory search disabled")
            self.bm25 = None

    def add(
        self,
        situation: str,
        recommendation: str,
        meta: dict | None = None,
    ):
        """Add a single situation-recommendation pair."""
        self.documents.append(situation)
        self.recommendations.append(recommendation)
        self.metadata.append(meta or {})
        self._rebuild_index()

        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO memories (memory_name, situation, recommendation, metadata) VALUES (?, ?, ?, ?)",
                    (self.name, situation, recommendation, json.dumps(meta or {})),
                )
        except Exception as e:
            logger.warning("Failed to persist memory: %s", e)

    def add_analysis(
        self,
        ticker: str,
        market: str,
        analysis_summary: str,
        recommendation: str,
        signal: str = "",
        score: float = 0.0,
    ):
        """Add a stock analysis result to memory."""
        situation = (
            f"Analysis of {ticker} ({market}) on {datetime.now().strftime('%Y-%m-%d')}: "
            f"{analysis_summary}"
        )
        meta = {
            "ticker": ticker,
            "market": market,
            "signal": signal,
            "score": score,
            "date": datetime.now().isoformat(),
        }
        self.add(situation, recommendation, meta)

    def add_situations(self, situations_and_advice: list[tuple[str, str]]):
        """Add multiple situation-recommendation pairs (batch)."""
        for situation, recommendation in situations_and_advice:
            self.add(situation, recommendation)

    def recall(self, query: str, n_matches: int = 3) -> list[dict]:
        """Find relevant past memories using BM25 similarity.

        Falls back to substring matching when BM25 yields no positive scores
        (common with very few documents where IDF is degenerate).
        """
        if not self.documents:
            return []

        results = []

        # Try BM25 first
        if self.bm25 is not None:
            tokens = self._tokenize(query)
            scores = self.bm25.get_scores(tokens)

            top_indices = sorted(
                range(len(scores)), key=lambda i: scores[i], reverse=True
            )[:n_matches]

            max_score = max(scores) if len(scores) > 0 and max(scores) > 0 else 1.0

            for idx in top_indices:
                if scores[idx] > 0:
                    results.append({
                        "situation": self.documents[idx],
                        "recommendation": self.recommendations[idx],
                        "score": round(scores[idx] / max_score, 4),
                        "metadata": self.metadata[idx],
                    })

        # Fallback: simple keyword overlap when BM25 returns nothing
        if not results:
            query_tokens = set(self._tokenize(query))
            scored = []
            for i, doc in enumerate(self.documents):
                doc_tokens = set(self._tokenize(doc))
                overlap = len(query_tokens & doc_tokens)
                if overlap > 0:
                    scored.append((i, overlap / max(len(query_tokens), 1)))
            scored.sort(key=lambda x: x[1], reverse=True)
            for idx, score in scored[:n_matches]:
                results.append({
                    "situation": self.documents[idx],
                    "recommendation": self.recommendations[idx],
                    "score": round(score, 4),
                    "metadata": self.metadata[idx],
                })

        return results

    def recall_for_ticker(self, ticker: str, n_matches: int = 5) -> list[dict]:
        """Get past memories specifically about a ticker."""
        query = f"Analysis of {ticker} stock market investment"
        all_results = self.recall(query, n_matches=n_matches * 2)
        # Filter to only results about this ticker
        ticker_results = [
            r for r in all_results
            if r.get("metadata", {}).get("ticker") == ticker
        ]
        return ticker_results[:n_matches] or all_results[:n_matches]

    def clear(self):
        """Clear all memories for this instance."""
        self.documents.clear()
        self.recommendations.clear()
        self.metadata.clear()
        self.bm25 = None
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("DELETE FROM memories WHERE memory_name = ?", (self.name,))
        except Exception as e:
            logger.warning("Failed to clear memories: %s", e)

    def count(self) -> int:
        return len(self.documents)

    def __repr__(self) -> str:
        return f"FinancialSituationMemory(name='{self.name}', memories={self.count()})"


# Global memory instances
_memories: dict[str, FinancialSituationMemory] = {}


def get_memory(name: str = "default") -> FinancialSituationMemory:
    """Get or create a named memory instance (singleton per name)."""
    if name not in _memories:
        _memories[name] = FinancialSituationMemory(name=name)
    return _memories[name]
