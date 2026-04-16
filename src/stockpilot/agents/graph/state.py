"""LangGraph agent state definitions."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph import add_messages


class AgentState(TypedDict):
    """State shared across all agents in the graph."""
    messages: Annotated[list, add_messages]
    ticker: str
    market: str
    analysis_date: str

    # Data gathered by analysts
    price_data: str
    fundamental_data: str
    technical_signals: str
    pattern_signals: str
    news_summary: str
    sentiment_data: str

    # Agent outputs
    fundamental_analysis: str
    technical_analysis: str
    sentiment_analysis: str
    news_analysis: str

    # Debate
    bullish_argument: str
    bearish_argument: str
    debate_rounds: int
    debate_history: list[dict[str, str]]

    # Persona analyses
    persona_analyses: dict[str, str]

    # Final decision
    risk_assessment: str
    portfolio_recommendation: str
    final_decision: str
    confidence: float
