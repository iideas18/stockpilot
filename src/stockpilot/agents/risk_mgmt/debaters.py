"""Risk management debate system.

Three debaters (aggressive, conservative, neutral) challenge a trading
decision from different risk perspectives, then a judge synthesizes
the final risk-adjusted recommendation.
Ported from TradingAgents' risk_mgmt/ module.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from stockpilot.agents.llm.providers import get_debate_llm

logger = logging.getLogger(__name__)


AGGRESSIVE_SYSTEM = """You are the Aggressive Risk Analyst. Champion high-reward opportunities, 
emphasize bold strategies and growth potential. Challenge conservative views with data-driven 
rebuttals. Focus on upside, market timing advantages, and competitive positioning."""

CONSERVATIVE_SYSTEM = """You are the Conservative Risk Analyst. Your primary objective is to 
protect assets, minimize volatility, and ensure steady growth. Critically examine high-risk 
elements, point out potential losses, and advocate for cautious alternatives that secure 
long-term gains."""

NEUTRAL_SYSTEM = """You are the Neutral Risk Analyst. Provide a balanced perspective weighing 
both potential benefits and risks. Challenge both aggressive and conservative views where they 
are extreme. Advocate for a moderate, sustainable strategy."""

JUDGE_SYSTEM = """You are the Risk Management Judge. After reviewing the debate between 
aggressive, conservative, and neutral risk analysts, synthesize a final risk assessment.
Output a structured recommendation with:
1. Risk Level: LOW / MEDIUM / HIGH / VERY_HIGH
2. Position Size Recommendation: percentage of portfolio (0-100%)
3. Stop-Loss Level: suggested stop-loss percentage
4. Key Risk Factors: top 3 risks identified
5. Final Verdict: concise risk-adjusted recommendation"""


def _build_debate_prompt(
    role: str,
    trader_decision: str,
    analysis_data: dict[str, str],
    history: str,
    other_responses: dict[str, str],
) -> str:
    """Build a debate prompt for a risk analyst."""
    others = "\n".join(
        f"- {name}: {resp}" for name, resp in other_responses.items() if resp
    )
    return f"""The trader proposes: {trader_decision}

Available analysis data:
- Technical: {analysis_data.get('technical', 'N/A')}
- Fundamental: {analysis_data.get('fundamental', 'N/A')}
- Sentiment: {analysis_data.get('sentiment', 'N/A')}
- News: {analysis_data.get('news', 'N/A')}

Debate history:
{history or '(Opening arguments)'}

Other analysts' positions:
{others or '(No responses yet — present your opening argument)'}

Present your {role} risk analysis. Be specific, reference the data, and directly 
counter other analysts' arguments where you disagree. Keep it concise (2-3 paragraphs)."""


def run_risk_debate(
    trader_decision: str,
    analysis_data: dict[str, str],
    rounds: int = 2,
) -> dict[str, Any]:
    """Run a multi-round risk management debate.

    Args:
        trader_decision: The proposed trading action to evaluate
        analysis_data: Dict with keys like 'technical', 'fundamental', 'sentiment', 'news'
        rounds: Number of debate rounds

    Returns:
        Dict with debate_history, final_assessment, risk_level, position_recommendation
    """
    llm = get_debate_llm()

    history = ""
    aggressive_response = ""
    conservative_response = ""
    neutral_response = ""

    debate_log: list[dict] = []

    for round_num in range(1, rounds + 1):
        logger.info("Risk debate round %d/%d", round_num, rounds)

        # Aggressive
        prompt = _build_debate_prompt(
            "aggressive", trader_decision, analysis_data, history,
            {"Conservative": conservative_response, "Neutral": neutral_response},
        )
        try:
            resp = llm.invoke([
                SystemMessage(content=AGGRESSIVE_SYSTEM),
                HumanMessage(content=prompt),
            ])
            aggressive_response = resp.content
        except Exception as e:
            aggressive_response = f"[Error: {e}]"

        # Conservative
        prompt = _build_debate_prompt(
            "conservative", trader_decision, analysis_data, history,
            {"Aggressive": aggressive_response, "Neutral": neutral_response},
        )
        try:
            resp = llm.invoke([
                SystemMessage(content=CONSERVATIVE_SYSTEM),
                HumanMessage(content=prompt),
            ])
            conservative_response = resp.content
        except Exception as e:
            conservative_response = f"[Error: {e}]"

        # Neutral
        prompt = _build_debate_prompt(
            "neutral", trader_decision, analysis_data, history,
            {"Aggressive": aggressive_response, "Conservative": conservative_response},
        )
        try:
            resp = llm.invoke([
                SystemMessage(content=NEUTRAL_SYSTEM),
                HumanMessage(content=prompt),
            ])
            neutral_response = resp.content
        except Exception as e:
            neutral_response = f"[Error: {e}]"

        round_entry = {
            "round": round_num,
            "aggressive": aggressive_response,
            "conservative": conservative_response,
            "neutral": neutral_response,
        }
        debate_log.append(round_entry)
        history += (
            f"\n--- Round {round_num} ---\n"
            f"Aggressive: {aggressive_response}\n"
            f"Conservative: {conservative_response}\n"
            f"Neutral: {neutral_response}\n"
        )

    # Judge synthesizes
    judge_prompt = f"""Review this risk debate about the trader's decision:

Decision: {trader_decision}

Full debate transcript:
{history}

Synthesize the three perspectives into a final risk assessment."""

    try:
        judge_resp = llm.invoke([
            SystemMessage(content=JUDGE_SYSTEM),
            HumanMessage(content=judge_prompt),
        ])
        final_assessment = judge_resp.content
    except Exception as e:
        final_assessment = f"Risk assessment unavailable: {e}"

    return {
        "debate_rounds": debate_log,
        "final_assessment": final_assessment,
        "debate_transcript": history,
    }
