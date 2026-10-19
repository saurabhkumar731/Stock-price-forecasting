import json
import re
import datetime

import pandas as pd
import requests

from flask import Blueprint, request, jsonify, g

from backend.auth_utils import login_required
from backend.config import Config
from backend.extensions import chat_history_collection
from backend.ml.model_loader import load_company_models, has_models
from backend.ml.forecasting import (
    forecast_arima_to_date,
    forecast_lstm_to_date,
)
from .predict import COMPANIES, _get_recent_close


chatbot_bp = Blueprint(
    "chatbot",
    __name__,
    url_prefix="/api/chat"
)


# ============================================================
# OLLAMA
# ============================================================

def query_ollama(model: str, messages: list) -> str:
    """
    Send a conversation to Ollama and return the generated text.
    """

    ollama_url = Config.OLLAMA_URL.rstrip("/")

    # Support both:
    # http://127.0.0.1:11434
    # http://127.0.0.1:11434/api/chat
    if not ollama_url.endswith("/api/chat"):
        ollama_url += "/api/chat"

    try:
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
        }

        resp = requests.post(
            ollama_url,
            json=payload,
            stream=True,
            timeout=120,
        )

        if resp.status_code != 200:
            return (
                f"Ollama API error: {resp.status_code}. "
                f"Check that Ollama is running and model "
                f"`{model}` is available."
            )

        full_reply = ""

        for line in resp.iter_lines(decode_unicode=True):

            if not line:
                continue

            try:
                data = json.loads(line)

                if "message" in data:
                    content = data["message"].get(
                        "content",
                        ""
                    )

                    full_reply += content

            except json.JSONDecodeError:
                continue

        return (
            full_reply.strip()
            or "(empty response from model)"
        )

    except requests.exceptions.ConnectionError:

        return (
            f"Can't reach Ollama at {ollama_url} - "
            "is `ollama serve` running?"
        )

    except requests.exceptions.Timeout:

        return (
            "Ollama took too long to respond. "
            "Please try again."
        )

    except Exception as e:

        return f"Ollama error: {str(e)}"


# ============================================================
# COMPANY HELPERS
# ============================================================

def extract_companies(query: str):
    """
    Deterministically find supported companies/tickers
    mentioned in the query.
    """

    query_lower = query.lower()

    found = []

    for name, ticker in COMPANIES.items():

        short_name = (
            name.split("(")[0]
            .strip()
            .lower()
        )

        ticker_clean = (
            ticker.lower()
            .replace(".ns", "")
        )

        if (
            short_name in query_lower
            or ticker_clean in query_lower
        ):
            found.append(name)

    return found


def company_list_for_llm():
    """
    Give Mistral the companies supported by the application.
    """

    companies = []

    for name, ticker in COMPANIES.items():

        companies.append({
            "name": name,
            "ticker": ticker
        })

    return companies


def find_company_by_name_or_ticker(value):
    """
    Validate a company returned by Mistral.
    """

    if not value:
        return None

    value = str(value).strip().lower()

    for name, ticker in COMPANIES.items():

        short_name = (
            name.split("(")[0]
            .strip()
            .lower()
        )

        ticker_clean = (
            ticker.lower()
            .replace(".ns", "")
        )

        if (
            value == name.lower()
            or value == short_name
            or value == ticker.lower()
            or value == ticker_clean
        ):

            return {
                "name": name,
                "ticker": ticker
            }

    return None


# ============================================================
# DATE / PERIOD HELPERS
# ============================================================

def extract_date(query: str):
    """
    Extract explicit dates from the user query.
    """

    from dateparser.search import search_dates

    try:

        results = search_dates(
            query,
            settings={
                "PREFER_DATES_FROM": "future",
                "STRICT_PARSING": True,
            },
        )

        if results:

            digit_matches = [
                (text, dt)
                for text, dt in results
                if any(ch.isdigit() for ch in text)
            ]

            if digit_matches:

                return digit_matches[-1][1].date()

    except Exception:
        pass

    # DD-MM-YYYY
    match = re.search(
        r"(\d{2})-(\d{2})-(\d{4})",
        query
    )

    if match:

        day, month, year = map(
            int,
            match.groups()
        )

        try:

            return datetime.date(
                year,
                month,
                day
            )

        except ValueError:
            return None

    # DD/MM/YYYY
    match = re.search(
        r"(\d{2})/(\d{2})/(\d{4})",
        query
    )

    if match:

        day, month, year = map(
            int,
            match.groups()
        )

        try:

            return datetime.date(
                year,
                month,
                day
            )

        except ValueError:
            return None

    return None


def get_future_trading_date(days: int):
    """
    Convert trading-day horizon into a future weekday date.

    This keeps compatibility with the existing forecasting
    functions.
    """

    days = max(
        1,
        min(int(days), 252)
    )

    today = pd.Timestamp.today().normalize()

    future_dates = pd.bdate_range(
        start=today,
        periods=days + 1
    )

    return future_dates[-1].date()


# ============================================================
# STOCK DATA TOOLS
# ============================================================

def get_stock_price(ticker: str):
    """
    Get the latest available closing price.
    """

    try:

        df = _get_recent_close(ticker)

        if df is None or df.empty:
            return None

        last_row = df.iloc[-1]

        return {
            "ticker": ticker,
            "date": str(
                pd.Timestamp(
                    last_row["Date"]
                ).date()
            ),
            "price": float(
                last_row["Close"]
            ),
        }

    except Exception as e:

        return {
            "ticker": ticker,
            "error": str(e)
        }


def get_stock_trend(ticker: str):
    """
    Calculate recent descriptive stock trend.
    """

    try:

        df = _get_recent_close(ticker)

        if df is None or df.empty:
            return None

        closes = df["Close"].dropna()

        if len(closes) < 2:
            return None

        current = float(
            closes.iloc[-1]
        )

        lookback = min(
            20,
            len(closes) - 1
        )

        previous = float(
            closes.iloc[-lookback - 1]
        )

        change = current - previous

        change_percent = (
            (change / previous) * 100
            if previous != 0
            else 0
        )

        if change_percent > 2:

            trend = "upward"

        elif change_percent < -2:

            trend = "downward"

        else:

            trend = "relatively stable"

        return {
            "ticker": ticker,
            "current_price": current,
            "lookback_observations": lookback,
            "previous_price": previous,
            "change": change,
            "change_percent": change_percent,
            "trend": trend,
        }

    except Exception as e:

        return {
            "ticker": ticker,
            "error": str(e)
        }


# ============================================================
# ARIMA + LSTM
# ============================================================

def get_prediction(
    ticker: str,
    target_date: datetime.date
):
    """
    Use the existing trained ARIMA and LSTM models.
    """

    if not has_models(ticker):

        return {
            "ticker": ticker,
            "error": (
                "No trained model found for this company."
            )
        }

    try:

        df = _get_recent_close(ticker)

        if df is None or df.empty:

            return {
                "ticker": ticker,
                "error": (
                    "No historical stock data available."
                )
            }

        last_date = pd.Timestamp(
            df["Date"].iloc[-1]
        )

        last_close = float(
            df["Close"].iloc[-1]
        )

        target_ts = pd.Timestamp(
            target_date
        )

        # ----------------------------------------------------
        # HISTORICAL
        # ----------------------------------------------------

        if target_ts <= last_date:

            hist = df.loc[
                df["Date"] <= target_ts,
                "Close"
            ]

            historical_price = (
                float(hist.iloc[-1])
                if not hist.empty
                else None
            )

            return {
                "ticker": ticker,
                "type": "historical",
                "target_date": str(
                    target_date
                ),
                "last_close": last_close,
                "historical_price": historical_price,
            }

        # ----------------------------------------------------
        # FUTURE
        # ----------------------------------------------------

        arima_fit, lstm_model, scaler = (
            load_company_models(ticker)
        )

        _, arima_preds = (
            forecast_arima_to_date(
                arima_fit,
                last_date,
                target_ts
            )
        )

        _, lstm_preds = (
            forecast_lstm_to_date(
                lstm_model,
                scaler,
                df["Close"].values,
                last_date,
                target_ts
            )
        )

        arima_price = (
            float(arima_preds[-1])
            if len(arima_preds)
            else None
        )

        lstm_price = (
            float(lstm_preds[-1])
            if len(lstm_preds)
            else None
        )

        result = {
            "ticker": ticker,
            "type": "forecast",
            "last_close": last_close,
            "last_date": str(
                last_date.date()
            ),
            "target_date": str(
                target_date
            ),
            "ARIMA": arima_price,
            "LSTM": lstm_price,
        }

        if arima_price is not None:

            result["ARIMA_change_percent"] = (
                (
                    arima_price - last_close
                )
                / last_close
                * 100
            )

        if lstm_price is not None:

            result["LSTM_change_percent"] = (
                (
                    lstm_price - last_close
                )
                / last_close
                * 100
            )

        return result

    except Exception as e:

        return {
            "ticker": ticker,
            "error": (
                f"Prediction failed: {str(e)}"
            )
        }


# ============================================================
# COMPARISON
# ============================================================

def compare_stocks(companies):
    """
    Compare supported companies using latest price and trend.
    """

    results = []

    for company in companies:

        info = find_company_by_name_or_ticker(
            company
        )

        if not info:
            continue

        name = info["name"]
        ticker = info["ticker"]

        price_data = get_stock_price(
            ticker
        )

        trend_data = get_stock_trend(
            ticker
        )

        results.append({
            "company": name,
            "ticker": ticker,
            "price": price_data,
            "trend": trend_data,
        })

    return results


# ============================================================
# ROUTER
# ============================================================

def understand_query(
    model: str,
    message: str,
    conversation
):
    """
    Mistral determines the intent of the CURRENT message.

    Conversation history is used only for references such as
    "it", "its", "that company", etc.
    """

    supported_companies = (
        company_list_for_llm()
    )

    router_prompt = f"""
You are the intent classifier for a stock-analysis chatbot.

Your ONLY job is to classify the CURRENT user message.

DO NOT answer the user.
DO NOT calculate anything.
DO NOT invent prices.
DO NOT invent predictions.
DO NOT invent companies.

Supported companies:

{json.dumps(
    supported_companies,
    indent=2
)}

==================================================
AVAILABLE INTENTS
==================================================

1. stock_price

Use ONLY when the CURRENT message explicitly asks for:

- current price
- latest price
- stock price
- closing price
- price of a company

Examples:

"What is the price of TCS?"
"How much is TCS trading at?"
"What is the latest price of Infosys?"

==================================================

2. trend

Use ONLY when the CURRENT message explicitly asks about:

- trend
- movement
- rising/falling
- going up/down
- recent stock movement
- recent performance

Examples:

"What is the trend of TCS?"
"Is TCS going up?"
"How has TCS been moving recently?"

==================================================

3. prediction

Use ONLY when the CURRENT message explicitly asks for:

- prediction
- forecast
- future price
- expected future price
- tomorrow's price
- next days
- next week
- next month

Examples:

"Predict TCS."
"Forecast TCS for 7 days."
"What will TCS price be tomorrow?"

==================================================

4. model_analysis

Use ONLY when the CURRENT message explicitly mentions:

- LSTM
- ARIMA
- machine learning model
- model prediction
- which model is higher/lower
- model performance

Examples:

"What does LSTM predict for TCS?"
"What does ARIMA predict for TCS?"
"Which model predicts higher for TCS?"

==================================================

5. comparison

Use when the CURRENT message explicitly asks to compare
two or more companies.

Examples:

"Compare TCS and Infosys."
"Which is better, TCS or Infosys?"
"Compare TCS, Infosys and Reliance."

==================================================

6. investment_analysis

Use when the CURRENT message asks about:

- buy
- sell
- hold
- invest
- investment
- whether a stock is attractive

Examples:

"Should I buy TCS?"
"Should I sell Infosys?"
"Is TCS a good investment?"

==================================================

7. general_stock

Use for GENERAL INFORMATION about a company, stock,
or stock-market concept.

Examples:

"What is TCS?"
"Tell me about TCS."
"What does TCS do?"
"Who is the CEO of TCS?"
"What industry is TCS in?"
"Give me an overview of TCS."
"What is P/E ratio?"
"What is an IPO?"
"What is market capitalization?"

IMPORTANT:

"What is TCS?" MUST be general_stock.

"What is TCS?" MUST NOT be:

- stock_price
- prediction
- trend
- model_analysis
- investment_analysis

==================================================

8. general

Use for normal conversation unrelated to stocks.

Examples:

"Hello"
"How are you?"
"Thank you"
"Tell me a joke"

==================================================
CRITICAL RULES
==================================================

RULE 1:

The CURRENT user message determines the intent.

RULE 2:

Previous conversation can ONLY help resolve references such as:

- it
- its
- that stock
- that company
- the first one
- the second one

RULE 3:

Previous conversation must NOT change the intent of the
CURRENT message.

Example:

Previous:
"What does LSTM predict for TCS?"

Current:
"What is TCS?"

Correct:

general_stock

Incorrect:

prediction
model_analysis

RULE 4:

If the user says:

"What is TCS?"

they want information ABOUT TCS.

They do NOT automatically want:

- TCS price
- TCS trend
- ARIMA prediction
- LSTM prediction
- investment advice

RULE 5:

Only use prediction when the CURRENT message asks for
prediction or future price.

RULE 6:

Only use model_analysis when the CURRENT message mentions
ARIMA, LSTM, or model analysis.

RULE 7:

Only use stock_price when the CURRENT message asks about
price.

RULE 8:

Only use trend when the CURRENT message asks about trend
or movement.

RULE 9:

If the CURRENT message does not mention a forecast period,
set "days" to null.

RULE 10:

Do NOT assume that the user requested 7 days.

RULE 11:

Use exact company names from the supported list.

RULE 12:

Return ONLY valid JSON.

==================================================
JSON FORMAT
==================================================

{{
    "intent": "general_stock",
    "companies": [],
    "days": null,
    "date": null
}}

Current user message:

{message}

Previous conversation:

{json.dumps(
    conversation,
    indent=2
)}
"""

    messages = [
        {
            "role": "system",
            "content": router_prompt
        },
        {
            "role": "user",
            "content": message
        }
    ]

    response = query_ollama(
        model,
        messages
    )

    try:

        cleaned = response.strip()

        # Remove markdown code fences
        cleaned = re.sub(
            r"^```json\s*",
            "",
            cleaned,
            flags=re.IGNORECASE
        )

        cleaned = re.sub(
            r"^```\s*",
            "",
            cleaned
        )

        cleaned = re.sub(
            r"\s*```$",
            "",
            cleaned
        )

        parsed = json.loads(
            cleaned
        )

        if not isinstance(
            parsed,
            dict
        ):
            raise ValueError(
                "Router response is not an object"
            )

        return parsed

    except Exception:

        # ====================================================
        # DETERMINISTIC FALLBACK
        # ====================================================

        message_lower = message.lower()

        companies = extract_companies(
            message
        )

        # ----------------------------------------------------
        # MODEL
        # ----------------------------------------------------

        if re.search(
            r"\blstm\b|"
            r"\barima\b|"
            r"machine learning model|"
            r"model prediction|"
            r"which model",
            message_lower
        ):

            intent = "model_analysis"

        # ----------------------------------------------------
        # PREDICTION
        # ----------------------------------------------------

        elif re.search(
            r"\bpredict\b|"
            r"\bprediction\b|"
            r"\bforecast\b|"
            r"\bfuture price\b|"
            r"\btomorrow\b|"
            r"\bnext\s+\d+\s+days?\b|"
            r"\bnext week\b|"
            r"\bnext month\b",
            message_lower
        ):

            intent = "prediction"

        # ----------------------------------------------------
        # COMPARISON
        # ----------------------------------------------------

        elif re.search(
            r"\bcompare\b|"
            r"\bversus\b|"
            r"\bvs\b|"
            r"which is better",
            message_lower
        ):

            intent = "comparison"

        # ----------------------------------------------------
        # INVESTMENT
        # ----------------------------------------------------

        elif re.search(
            r"\bbuy\b|"
            r"\bsell\b|"
            r"\bhold\b|"
            r"\binvest\b|"
            r"\binvestment\b",
            message_lower
        ):

            intent = "investment_analysis"

        # ----------------------------------------------------
        # TREND
        # ----------------------------------------------------

        elif re.search(
            r"\btrend\b|"
            r"\bgoing up\b|"
            r"\bgoing down\b|"
            r"\brising\b|"
            r"\bfalling\b|"
            r"\bmovement\b",
            message_lower
        ):

            intent = "trend"

        # ----------------------------------------------------
        # PRICE
        # ----------------------------------------------------

        elif re.search(
            r"\bprice\b|"
            r"\btrading at\b|"
            r"\bclosing price\b",
            message_lower
        ):

            intent = "stock_price"

        # ----------------------------------------------------
        # GENERAL STOCK
        # ----------------------------------------------------

        elif companies:

            intent = "general_stock"

        elif re.search(
            r"\bwhat is\b|"
            r"\btell me about\b|"
            r"\bwhat does\b|"
            r"\bwho is\b|"
            r"\bindustry\b|"
            r"\bcompany\b|"
            r"\bceo\b|"
            r"\bipo\b|"
            r"\bp\/e\b|"
            r"\bmarket cap\b",
            message_lower
        ):

            intent = "general_stock"

        else:

            intent = "general"

        return {
            "intent": intent,
            "companies": companies,
            "days": None,
            "date": None,
        }


# ============================================================
# CONVERSATION HISTORY
# ============================================================

def get_recent_conversation(
    username,
    limit=10
):
    """
    Retrieve recent conversations.
    """

    try:

        docs = (
            chat_history_collection
            .find({
                "username": username
            })
            .sort(
                "_id",
                -1
            )
            .limit(limit)
        )

        docs = list(docs)

        docs.reverse()

        conversation = []

        for doc in docs:

            conversation.append({
                "role": "user",
                "content": doc.get(
                    "message",
                    ""
                )
            })

            conversation.append({
                "role": "assistant",
                "content": doc.get(
                    "reply",
                    ""
                )
            })

        return conversation

    except Exception:

        return []


# ============================================================
# FOLLOW-UP COMPANY RESOLUTION
# ============================================================

def resolve_previous_companies(
    conversation,
    current_message
):
    """
    Resolve companies from previous user messages when the
    current query uses references like:

    "it"
    "its"
    "that company"
    "the stock"
    """

    current_lower = current_message.lower()

    reference_words = [
        "it",
        "its",
        "that stock",
        "that company",
        "this stock",
        "this company",
        "the stock",
        "the company",
        "the first one",
        "the second one",
    ]

    has_reference = any(
        word in current_lower
        for word in reference_words
    )

    if not has_reference:
        return []

    previous_text = " ".join(
        item["content"]
        for item in conversation
        if item["role"] == "user"
    )

    return extract_companies(
        previous_text
    )


# ============================================================
# FINAL ANSWER
# ============================================================

def generate_final_answer(
    model,
    message,
    intent,
    tool_results,
    conversation,
    default_forecast_used=False
):
    """
    Ask Mistral to explain backend results naturally.
    """

    system_prompt = """
You are Ledger, a stock-analysis assistant.

You answer the user's CURRENT question.

The backend has already performed stock calculations.

Your job is to explain the supplied results clearly.

IMPORTANT RULES:

1. Never invent stock prices.

2. Never invent ARIMA predictions.

3. Never invent LSTM predictions.

4. Never invent dates.

5. Never claim that a prediction is guaranteed.

6. Clearly distinguish historical/current data from forecasts.

7. For price questions, call it the "latest available
   closing price" when appropriate.

8. Do not pretend the data is real-time unless the backend
   explicitly says it is real-time.

9. Answer the CURRENT question directly.

10. Do not include unrelated information just because it
    appears in the conversation history.

11. If the user asks "What is TCS?", explain TCS as a company.
    Do NOT provide predictions unless the user asks for them.

12. If the user asks about LSTM, explain the LSTM result.

13. If the user asks about ARIMA, explain the ARIMA result.

14. If the user asks for a prediction, explain the prediction.

15. If the user asks about investment, provide analysis and
    uncertainty rather than a guaranteed buy/sell command.

16. Never say that the user requested a specific date or
    forecast period unless they actually did.

17. If a default forecast period was used by the backend,
    clearly say that it was a default forecast horizon.

18. Keep answers concise and easy to understand.
"""

    user_prompt = f"""
CURRENT USER QUESTION:

{message}

CURRENT INTENT:

{intent}

BACKEND RESULTS:

{json.dumps(
    tool_results,
    indent=2,
    default=str
)}

RECENT CONVERSATION:

{json.dumps(
    conversation,
    indent=2
)}

DEFAULT FORECAST USED:

{default_forecast_used}

Answer ONLY the current user question.

Use backend numerical results when discussing stock-specific
numbers.

Do not bring unrelated predictions or investment advice into
a general company-information question.
"""

    messages = [
        {
            "role": "system",
            "content": system_prompt
        },
        {
            "role": "user",
            "content": user_prompt
        }
    ]

    return query_ollama(
        model,
        messages
    )


# ============================================================
# MAIN CHAT ROUTE
# ============================================================

@chatbot_bp.post("")
@login_required
def chat():

    data = request.get_json(
        silent=True
    ) or {}

    message = (
        data.get("message")
        or ""
    ).strip()

    model = data.get(
        "model",
        "mistral"
    )

    if not message:

        return jsonify({
            "error": "message is required"
        }), 400

    username = g.user["username"]

    # --------------------------------------------------------
    # Conversation
    # --------------------------------------------------------

    conversation = get_recent_conversation(
        username,
        limit=10
    )

    # --------------------------------------------------------
    # Understand CURRENT query
    # --------------------------------------------------------

    route = understand_query(
        model,
        message,
        conversation
    )

    intent = route.get(
        "intent",
        "general"
    )

    raw_companies = route.get(
        "companies",
        []
    )

    # --------------------------------------------------------
    # Validate companies
    # --------------------------------------------------------

    validated_companies = []

    for company in raw_companies:

        info = find_company_by_name_or_ticker(
            company
        )

        if (
            info
            and info not in validated_companies
        ):

            validated_companies.append(
                info
            )

    # --------------------------------------------------------
    # Deterministic company extraction
    # --------------------------------------------------------

    explicit_companies = extract_companies(
        message
    )

    for company in explicit_companies:

        info = find_company_by_name_or_ticker(
            company
        )

        if (
            info
            and info not in validated_companies
        ):

            validated_companies.append(
                info
            )

    # --------------------------------------------------------
    # Follow-up resolution
    # --------------------------------------------------------

    if not validated_companies:

        previous_companies = (
            resolve_previous_companies(
                conversation,
                message
            )
        )

        for company in previous_companies:

            info = find_company_by_name_or_ticker(
                company
            )

            if (
                info
                and info not in validated_companies
            ):

                validated_companies.append(
                    info
                )

    # --------------------------------------------------------
    # Backend results
    # --------------------------------------------------------

    tool_results = {}

    default_forecast_used = False

    # ========================================================
    # STOCK PRICE
    # ========================================================

    if intent == "stock_price":

        if validated_companies:

            tool_results["stock_prices"] = []

            for company in validated_companies:

                result = get_stock_price(
                    company["ticker"]
                )

                tool_results[
                    "stock_prices"
                ].append({

                    "company": company["name"],

                    **(
                        result or {}
                    )
                })

        else:

            tool_results["message"] = (
                "No supported company was identified."
            )

    # ========================================================
    # TREND
    # ========================================================

    elif intent == "trend":

        if validated_companies:

            tool_results["trends"] = []

            for company in validated_companies:

                result = get_stock_trend(
                    company["ticker"]
                )

                tool_results[
                    "trends"
                ].append({

                    "company": company["name"],

                    **(
                        result or {}
                    )
                })

        else:

            tool_results["message"] = (
                "No supported company was identified."
            )

    # ========================================================
    # PREDICTION / MODEL ANALYSIS
    # ========================================================

    elif intent in {
        "prediction",
        "model_analysis"
    }:

        if validated_companies:

            days = route.get(
                "days"
            )

            try:

                days = (
                    int(days)
                    if days is not None
                    else None
                )

            except (
                TypeError,
                ValueError
            ):

                days = None

            # ------------------------------------------------
            # Explicit date
            # ------------------------------------------------

            explicit_date = route.get(
                "date"
            )

            target_date = None

            if explicit_date:

                try:

                    target_date = (
                        datetime.datetime
                        .strptime(
                            explicit_date,
                            "%Y-%m-%d"
                        )
                        .date()
                    )

                except ValueError:

                    target_date = None

            # ------------------------------------------------
            # Date directly in message
            # ------------------------------------------------

            if target_date is None:

                target_date = extract_date(
                    message
                )

            # ------------------------------------------------
            # Explicit days
            # ------------------------------------------------

            if (
                target_date is None
                and days is not None
            ):

                days = max(
                    1,
                    min(days, 252)
                )

                target_date = (
                    get_future_trading_date(
                        days
                    )
                )

            # ------------------------------------------------
            # DEFAULT HORIZON
            # ------------------------------------------------

            if target_date is None:

                # We still need a forecast horizon for
                # prediction/model queries.
                #
                # IMPORTANT:
                # This was NOT requested by the user.

                days = 7

                target_date = (
                    get_future_trading_date(
                        days
                    )
                )

                default_forecast_used = True

            tool_results["predictions"] = []

            for company in validated_companies:

                result = get_prediction(
                    company["ticker"],
                    target_date
                )

                tool_results[
                    "predictions"
                ].append({

                    "company": company["name"],

                    **result
                })

        else:

            tool_results["message"] = (
                "No supported company was identified."
            )

    # ========================================================
    # COMPARISON
    # ========================================================

    elif intent == "comparison":

        if len(validated_companies) >= 2:

            tool_results["comparison"] = (
                compare_stocks(
                    [
                        company["name"]
                        for company
                        in validated_companies
                    ]
                )
            )

        elif len(validated_companies) == 1:

            tool_results["message"] = (
                "Please mention at least two supported "
                "companies for a comparison."
            )

        else:

            tool_results["message"] = (
                "I could not identify the companies "
                "you want to compare."
            )

    # ========================================================
    # INVESTMENT ANALYSIS
    # ========================================================

    elif intent == "investment_analysis":

        if validated_companies:

            tool_results[
                "investment_analysis"
            ] = []

            target_date = (
                get_future_trading_date(7)
            )

            for company in validated_companies:

                ticker = company["ticker"]

                price = get_stock_price(
                    ticker
                )

                trend = get_stock_trend(
                    ticker
                )

                prediction = get_prediction(
                    ticker,
                    target_date
                )

                tool_results[
                    "investment_analysis"
                ].append({

                    "company": company["name"],

                    "current_price": price,

                    "recent_trend": trend,

                    "7_trading_day_forecast": prediction,
                })

        else:

            tool_results["message"] = (
                "No supported company was identified."
            )

    # ========================================================
    # GENERAL STOCK
    # ========================================================

    elif intent == "general_stock":

        tool_results = {
            "message": (
                "This is a general stock/company "
                "information question. No stock "
                "calculation is required."
            )
        }

    # ========================================================
    # GENERAL
    # ========================================================

    elif intent == "general":

        tool_results = {
            "message": (
                "This is a general conversation question. "
                "No stock-specific tool is required."
            )
        }

    # ========================================================
    # UNKNOWN
    # ========================================================

    else:

        tool_results = {
            "message": (
                "The request could not be classified clearly."
            )
        }

    # --------------------------------------------------------
    # Final answer
    # --------------------------------------------------------

    reply = generate_final_answer(
        model=model,
        message=message,
        intent=intent,
        tool_results=tool_results,
        conversation=conversation,
        default_forecast_used=default_forecast_used
    )

    # --------------------------------------------------------
    # Save history
    # --------------------------------------------------------

    chat_history_collection.insert_one({

        "username": username,

        "message": message,

        "reply": reply,

    })

    return jsonify({
        "reply": reply
    }), 200


# ============================================================
# CHAT HISTORY
# ============================================================

@chatbot_bp.get("/history")
@login_required
def history():

    docs = (
        chat_history_collection
        .find({
            "username": g.user["username"]
        })
        .sort(
            "_id",
            -1
        )
        .limit(50)
    )

    docs = list(docs)

    docs.reverse()

    return jsonify([
        {
            "message": d.get(
                "message",
                ""
            ),
            "reply": d.get(
                "reply",
                ""
            )
        }
        for d in docs
    ])