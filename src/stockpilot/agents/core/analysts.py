"""Core analyst agents — fundamental, technical, sentiment, news.

Each agent is a function that takes AgentState and returns updated state.
Ported from TradingAgents' agents/ module.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from stockpilot.agents.llm.providers import get_analyst_llm

logger = logging.getLogger(__name__)


FUNDAMENTAL_PROMPT = """You are an expert fundamental analyst specializing in financial statement analysis.
Analyze the provided fundamental data and financial metrics for {ticker}.

Consider:
- Valuation ratios (PE, PB, PS)
- Profitability (ROE, profit margins)
- Growth metrics (revenue growth, earnings growth)
- Financial health (debt-to-equity, free cash flow)
- Dividend yield and sustainability

Data:
{fundamental_data}

Provide a clear BUY/HOLD/SELL recommendation with confidence (0-100%) and detailed reasoning."""


TECHNICAL_PROMPT = """You are an expert technical analyst.
Analyze the technical indicators and signals for {ticker}.

Technical Signals:
{technical_signals}

Pattern Analysis:
{pattern_signals}

Recent Price Data:
{price_data}

Consider:
- Trend direction (moving averages, MACD)
- Momentum (RSI, KDJ, ROC)
- Volatility (Bollinger Bands, ATR)
- Volume analysis (OBV, MFI)
- Candlestick patterns

Provide a BUY/HOLD/SELL recommendation with confidence and reasoning."""


SENTIMENT_PROMPT = """You are a market sentiment analyst.
Analyze the current market sentiment for {ticker}.

News Summary:
{news_summary}

Sentiment Data:
{sentiment_data}

Consider:
- Overall market mood
- Recent news impact
- Social media sentiment
- Institutional activity
- Sector trends

Provide a BUY/HOLD/SELL recommendation with confidence and reasoning."""


NEWS_PROMPT = """You are a financial news analyst.
Analyze how recent news events might impact {ticker}.

News Data:
{news_summary}

Consider:
- Material events (earnings, M&A, regulatory)
- Industry trends
- Macroeconomic factors
- Competitive dynamics
- Short-term vs long-term implications

Provide a BUY/HOLD/SELL recommendation with confidence and reasoning."""


def create_analyst_agent(prompt_template: str, agent_name: str):
    """Factory function to create an analyst agent node."""

    def agent_node(state: dict) -> dict:
        llm = get_analyst_llm()
        prompt = prompt_template.format(
            ticker=state.get("ticker", ""),
            fundamental_data=state.get("fundamental_data", "N/A"),
            technical_signals=state.get("technical_signals", "N/A"),
            pattern_signals=state.get("pattern_signals", "N/A"),
            price_data=state.get("price_data", "N/A"),
            news_summary=state.get("news_summary", "N/A"),
            sentiment_data=state.get("sentiment_data", "N/A"),
        )

        try:
            response = llm.invoke([
                SystemMessage(content=f"You are {agent_name}."),
                HumanMessage(content=prompt),
            ])
            return {agent_name.lower().replace(" ", "_"): response.content}
        except Exception as e:
            logger.error("%s failed: %s", agent_name, e)
            return {agent_name.lower().replace(" ", "_"): f"Analysis unavailable: {e}"}

    agent_node.__name__ = agent_name.lower().replace(" ", "_")
    return agent_node


# Pre-built analyst agents
fundamental_analyst = create_analyst_agent(FUNDAMENTAL_PROMPT, "fundamental_analysis")
technical_analyst = create_analyst_agent(TECHNICAL_PROMPT, "technical_analysis")
sentiment_analyst = create_analyst_agent(SENTIMENT_PROMPT, "sentiment_analysis")
news_analyst = create_analyst_agent(NEWS_PROMPT, "news_analysis")


RISK_MANAGER_PROMPT = """You are a risk manager evaluating a potential trade in {ticker}.

Fundamental Analysis: {fundamental_analysis}
Technical Analysis: {technical_analysis}
Sentiment Analysis: {sentiment_analysis}
News Analysis: {news_analysis}

Evaluate:
1. Downside risk and potential loss scenarios
2. Position sizing recommendation (% of portfolio)
3. Stop-loss level suggestion
4. Risk/reward ratio
5. Overall risk rating (LOW/MEDIUM/HIGH/VERY_HIGH)

Provide a structured risk assessment."""


PORTFOLIO_MANAGER_PROMPT = """You are a portfolio manager making the final investment decision for {ticker}.

Fundamental Analysis: {fundamental_analysis}
Technical Analysis: {technical_analysis}
Sentiment Analysis: {sentiment_analysis}
News Analysis: {news_analysis}
Risk Assessment: {risk_assessment}

{persona_context}

Synthesize all analyses and provide:
1. Final recommendation: STRONG_BUY / BUY / HOLD / SELL / STRONG_SELL
2. Confidence level (0-100%)
3. Suggested position size (% of portfolio)
4. Entry price / target price / stop loss
5. Detailed reasoning combining all perspectives"""


def risk_manager_node(state: dict) -> dict:
    """Risk management agent."""
    llm = get_analyst_llm()
    prompt = RISK_MANAGER_PROMPT.format(
        ticker=state.get("ticker", ""),
        fundamental_analysis=state.get("fundamental_analysis", "N/A"),
        technical_analysis=state.get("technical_analysis", "N/A"),
        sentiment_analysis=state.get("sentiment_analysis", "N/A"),
        news_analysis=state.get("news_analysis", "N/A"),
    )
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        return {"risk_assessment": response.content}
    except Exception as e:
        return {"risk_assessment": f"Risk assessment unavailable: {e}"}


def portfolio_manager_node(state: dict) -> dict:
    """Portfolio manager — final decision maker."""
    llm = get_analyst_llm()

    persona_ctx = ""
    persona_analyses = state.get("persona_analyses", {})
    if persona_analyses:
        persona_ctx = "Investor Persona Opinions:\n"
        for name, analysis in persona_analyses.items():
            persona_ctx += f"\n--- {name} ---\n{analysis}\n"

    prompt = PORTFOLIO_MANAGER_PROMPT.format(
        ticker=state.get("ticker", ""),
        fundamental_analysis=state.get("fundamental_analysis", "N/A"),
        technical_analysis=state.get("technical_analysis", "N/A"),
        sentiment_analysis=state.get("sentiment_analysis", "N/A"),
        news_analysis=state.get("news_analysis", "N/A"),
        risk_assessment=state.get("risk_assessment", "N/A"),
        persona_context=persona_ctx,
    )
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        return {"final_decision": response.content}
    except Exception as e:
        return {"final_decision": f"Decision unavailable: {e}"}
