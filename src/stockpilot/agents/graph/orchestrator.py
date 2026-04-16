"""LangGraph orchestrator — the main analysis workflow.

Builds a LangGraph that coordinates data fetching, analyst agents,
optional persona analysis, bull/bear debate, and final decision.
Ported from TradingAgents' graph/trading_graph.py.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from langgraph.graph import END, StateGraph

from stockpilot.agents.graph.state import AgentState
from stockpilot.agents.core.analysts import (
    fundamental_analyst,
    technical_analyst,
    sentiment_analyst,
    news_analyst,
    risk_manager_node,
    portfolio_manager_node,
)
from stockpilot.agents.personas.investors import PERSONAS, create_persona_agent

logger = logging.getLogger(__name__)


def data_collection_node(state: dict) -> dict:
    """Collect all required data for analysis."""
    from stockpilot.agents.tools.agent_tools import (
        get_stock_price_history,
        get_stock_fundamentals,
        run_technical_analysis,
        get_pattern_analysis,
    )

    ticker = state.get("ticker", "")
    market = state.get("market", "a_share")

    results = {}
    try:
        results["price_data"] = get_stock_price_history.invoke(
            {"symbol": ticker, "market": market, "days": 120}
        )
    except Exception as e:
        results["price_data"] = f"Price data unavailable: {e}"

    try:
        results["fundamental_data"] = get_stock_fundamentals.invoke(
            {"symbol": ticker, "market": market}
        )
    except Exception as e:
        results["fundamental_data"] = f"Fundamental data unavailable: {e}"

    try:
        results["technical_signals"] = run_technical_analysis.invoke(
            {"symbol": ticker, "days": 120}
        )
    except Exception as e:
        results["technical_signals"] = f"Technical analysis unavailable: {e}"

    try:
        results["pattern_signals"] = get_pattern_analysis.invoke({"symbol": ticker})
    except Exception as e:
        results["pattern_signals"] = f"Pattern analysis unavailable: {e}"

    return results


def debate_node(state: dict) -> dict:
    """Bull vs bear debate based on analyst outputs."""
    from stockpilot.agents.llm.providers import get_debate_llm

    llm = get_debate_llm()
    ticker = state.get("ticker", "")
    history = state.get("debate_history", [])
    round_num = state.get("debate_rounds", 0) + 1

    context = f"""Stock: {ticker}
Fundamental Analysis: {state.get('fundamental_analysis', 'N/A')}
Technical Analysis: {state.get('technical_analysis', 'N/A')}
Sentiment Analysis: {state.get('sentiment_analysis', 'N/A')}
News Analysis: {state.get('news_analysis', 'N/A')}"""

    prev_debate = ""
    if history:
        prev_debate = "\n\nPrevious debate:\n" + "\n".join(
            f"- {h['side']}: {h['argument']}" for h in history[-4:]
        )

    from langchain_core.messages import HumanMessage

    # Bullish argument
    bull_prompt = f"""You are a BULLISH analyst arguing FOR investing in {ticker}. Round {round_num}.
{context}{prev_debate}
Make your strongest case for buying this stock. Address any bearish concerns raised."""
    bull_response = llm.invoke([HumanMessage(content=bull_prompt)])

    # Bearish argument
    bear_prompt = f"""You are a BEARISH analyst arguing AGAINST investing in {ticker}. Round {round_num}.
{context}{prev_debate}
Bull's latest argument: {bull_response.content[:500]}
Make your strongest case against buying this stock. Address the bullish arguments."""
    bear_response = llm.invoke([HumanMessage(content=bear_prompt)])

    history.append({"side": "BULL", "argument": bull_response.content, "round": round_num})
    history.append({"side": "BEAR", "argument": bear_response.content, "round": round_num})

    return {
        "bullish_argument": bull_response.content,
        "bearish_argument": bear_response.content,
        "debate_rounds": round_num,
        "debate_history": history,
    }


def should_continue_debate(state: dict) -> str:
    """Decide whether to continue the debate or proceed to decision."""
    max_rounds = 3
    if state.get("debate_rounds", 0) >= max_rounds:
        return "decide"
    return "debate"


class StockPilotGraph:
    """Main analysis graph orchestrator.

    Usage:
        graph = StockPilotGraph(enable_personas=True, enable_debate=True)
        result = graph.analyze("000001", market="a_share")
    """

    def __init__(
        self,
        enable_personas: bool = True,
        persona_keys: list[str] | None = None,
        enable_debate: bool = True,
        max_debate_rounds: int = 3,
    ):
        self.enable_personas = enable_personas
        self.persona_keys = persona_keys or [
            "warren_buffett", "charlie_munger", "cathie_wood",
            "michael_burry", "peter_lynch", "ben_graham",
        ]
        self.enable_debate = enable_debate
        self.max_debate_rounds = max_debate_rounds
        self._graph = self._build_graph()

    def _build_graph(self) -> Any:
        """Build the LangGraph workflow."""
        workflow = StateGraph(AgentState)

        # Add nodes
        workflow.add_node("data_collection", data_collection_node)
        workflow.add_node("fundamental_analyst", fundamental_analyst)
        workflow.add_node("technical_analyst", technical_analyst)
        workflow.add_node("sentiment_analyst", sentiment_analyst)
        workflow.add_node("news_analyst", news_analyst)

        if self.enable_debate:
            workflow.add_node("debate", debate_node)

        if self.enable_personas:
            for key in self.persona_keys:
                if key in PERSONAS:
                    workflow.add_node(f"persona_{key}", create_persona_agent(key))

        workflow.add_node("risk_manager", risk_manager_node)
        workflow.add_node("portfolio_manager", portfolio_manager_node)

        # Define edges
        workflow.set_entry_point("data_collection")

        # Data → parallel analysts
        workflow.add_edge("data_collection", "fundamental_analyst")
        workflow.add_edge("data_collection", "technical_analyst")
        workflow.add_edge("data_collection", "sentiment_analyst")
        workflow.add_edge("data_collection", "news_analyst")

        # Analysts → debate or personas or risk manager
        analyst_outputs = [
            "fundamental_analyst", "technical_analyst",
            "sentiment_analyst", "news_analyst",
        ]

        if self.enable_debate:
            for node in analyst_outputs:
                workflow.add_edge(node, "debate")
            workflow.add_conditional_edges(
                "debate",
                should_continue_debate,
                {"debate": "debate", "decide": "risk_manager"},
            )
        elif self.enable_personas:
            for node in analyst_outputs:
                for key in self.persona_keys:
                    if key in PERSONAS:
                        workflow.add_edge(node, f"persona_{key}")
            for key in self.persona_keys:
                if key in PERSONAS:
                    workflow.add_edge(f"persona_{key}", "risk_manager")
        else:
            for node in analyst_outputs:
                workflow.add_edge(node, "risk_manager")

        workflow.add_edge("risk_manager", "portfolio_manager")
        workflow.add_edge("portfolio_manager", END)

        return workflow.compile()

    def analyze(
        self,
        ticker: str,
        market: str = "a_share",
        analysis_date: str | None = None,
    ) -> dict[str, Any]:
        """Run full analysis pipeline for a stock."""
        initial_state: AgentState = {
            "messages": [],
            "ticker": ticker,
            "market": market,
            "analysis_date": analysis_date or str(date.today()),
            "price_data": "",
            "fundamental_data": "",
            "technical_signals": "",
            "pattern_signals": "",
            "news_summary": "",
            "sentiment_data": "",
            "fundamental_analysis": "",
            "technical_analysis": "",
            "sentiment_analysis": "",
            "news_analysis": "",
            "bullish_argument": "",
            "bearish_argument": "",
            "debate_rounds": 0,
            "debate_history": [],
            "persona_analyses": {},
            "risk_assessment": "",
            "portfolio_recommendation": "",
            "final_decision": "",
            "confidence": 0.0,
        }

        logger.info("Starting analysis for %s (%s)", ticker, market)
        result = self._graph.invoke(initial_state)
        logger.info("Analysis complete for %s", ticker)
        return result
