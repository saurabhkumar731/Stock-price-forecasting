import pandas as pd
from flask import Blueprint, request, jsonify
from backend.auth_utils import login_required
from backend.ml.model_loader import load_company_models, has_models
from backend.ml.forecasting import (
    forecast_arima_to_date,
    forecast_lstm_to_date,
)

predict_bp = Blueprint("predict", __name__, url_prefix="/api")

COMPANIES = {
    "Tata Consultancy Services (TCS)": "TCS.NS",
    "Infosys": "INFY.NS",
    "Reliance Industries": "RELIANCE.NS",
    "HDFC Bank": "HDFCBANK.NS",
    "ICICI Bank": "ICICIBANK.NS",
    "Maruti Suzuki": "MARUTI.NS",
    "State Bank of India": "SBIN.NS",
    "Bharti Airtel": "BHARTIARTL.NS",
    "ITC Limited": "ITC.NS",
    "Hindustan Unilever": "HINDUNILVR.NS",
}


@predict_bp.get("/companies")
def companies():
    return jsonify([
        {
            "name": name,
            "ticker": ticker,
            "trained": has_models(ticker)
        }
        for name, ticker in COMPANIES.items()
    ])


def _get_recent_close(ticker: str):
    """
    Fetch fresh daily market data from Yahoo Finance.

    IMPORTANT:
    During NSE market hours Yahoo Finance can return today's unfinished
    daily candle. Its "Close" value is then the latest/current traded
    price, NOT a completed closing price.

    Therefore:
      - Before the NSE close, today's row is removed.
      - After the NSE close, today's completed row is kept.
      - The returned dataframe contains only completed daily observations.

    This is important because ARIMA and LSTM should not treat an
    intraday price as today's final closing price.
    """
    import yfinance as yf
    from datetime import datetime
    from zoneinfo import ZoneInfo

    df = yf.download(
        ticker,
        period="5y",
        auto_adjust=True,
        progress=False
    )

    if df is None or df.empty:
        return pd.DataFrame()

    # Flatten MultiIndex returned by some yfinance versions.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    df = df.reset_index()

    if "Date" not in df.columns or "Close" not in df.columns:
        return pd.DataFrame()

    df["Date"] = pd.to_datetime(
        df["Date"],
        errors="coerce"
    )

    df["Close"] = pd.to_numeric(
        df["Close"],
        errors="coerce"
    )

    df = (
        df.dropna(subset=["Date", "Close"])
          .sort_values("Date")
          .drop_duplicates(subset=["Date"])
          .reset_index(drop=True)
    )

    if df.empty:
        return df

    # ---------------------------------------------------------
    # NSE daily close handling
    # ---------------------------------------------------------
    #
    # NSE normal continuous trading ends at 15:30 IST.
    # If it is currently before 15:30 on a weekday and Yahoo has
    # already returned today's row, that row is still INTRADAY.
    #
    # We remove it so:
    #   last_date  = last completed trading day
    #   last_close = last completed closing price
    #
    # On weekends/holidays Yahoo normally won't have a current row,
    # so this operation does nothing.
    # ---------------------------------------------------------

    india_now = datetime.now(
        ZoneInfo("Asia/Kolkata")
    )

    today = pd.Timestamp(
        india_now.date()
    ).normalize()

    market_close_hour = 15
    market_close_minute = 30

    market_closed_today = (
        india_now.hour > market_close_hour
        or (
            india_now.hour == market_close_hour
            and india_now.minute >= market_close_minute
        )
    )

    is_weekday = india_now.weekday() < 5

    has_today_row = (
        df["Date"].dt.normalize() == today
    ).any()

    # If today's market session is still running, remove today's
    # unfinished daily candle.
    if is_weekday and not market_closed_today and has_today_row:
        df = df[
            df["Date"].dt.normalize() < today
        ].reset_index(drop=True)

    return df


@predict_bp.post("/predict")
@login_required
def predict():
    data = request.get_json(silent=True) or {}

    ticker = data.get("ticker")
    target_date_str = data.get("target_date")
    mode = data.get("mode", "comparison")
    model_choice = data.get("model", "ARIMA")

    if not ticker or ticker not in COMPANIES.values():
        return jsonify({
            "error": "Unknown or missing ticker"
        }), 400

    if not target_date_str:
        return jsonify({
            "error": "target_date is required (YYYY-MM-DD)"
        }), 400

    try:
        target_date = pd.Timestamp(
            target_date_str
        ).normalize()
    except Exception:
        return jsonify({
            "error": "target_date must be a valid date (YYYY-MM-DD)"
        }), 400

    if mode not in ("single", "comparison"):
        return jsonify({
            "error": "mode must be single or comparison"
        }), 400

    try:
        arima_fit, lstm_model, scaler = load_company_models(ticker)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404

    try:
        df = _get_recent_close(ticker)
    except Exception as e:
        return jsonify({
            "error": f"Could not fetch price data for {ticker}: {e}"
        }), 502

    if df.empty:
        return jsonify({
            "error": f"No completed price data returned for {ticker}"
        }), 502

    # IMPORTANT:
    # _get_recent_close() removes today's unfinished candle while the
    # NSE market is open. Therefore these are completed market values.
    last_date = pd.Timestamp(
        df["Date"].iloc[-1]
    ).normalize()

    last_close = float(
        df["Close"].iloc[-1]
    )

    if target_date <= last_date:
        return jsonify({
            "error": (
                f"target_date must be after the latest completed "
                f"market date {last_date.date()}"
            )
        }), 400

    response = {
        "ticker": ticker,
        "last_close": round(last_close, 2),
        "last_date": str(last_date.date()),
    }

    def package(dates, preds):
        if len(preds) == 0:
            return None

        pred_close = float(preds[-1])
        change_pct = (
            (pred_close - last_close) / last_close
        ) * 100

        return {
            "predicted_close": round(pred_close, 2),
            "trend": (
                "up"
                if pred_close > last_close
                else "down"
            ),
            "change_pct": round(change_pct, 2),
            "series": [
                {
                    "date": str(
                        pd.Timestamp(d).date()
                    ),
                    "value": round(float(v), 2)
                }
                for d, v in zip(dates, preds)
            ],
        }

    # ---------------------------------------------------------
    # Prediction
    # ---------------------------------------------------------
    #
    # ARIMA:
    # forecasting.py receives the fresh completed daily data and
    # appends only observations that were not in the saved model.
    #
    # LSTM:
    # forecasting.py receives the latest completed daily closes
    # and uses the existing scaler + saved LSTM model.
    # Neither model is retrained here.
    # ---------------------------------------------------------

    if mode == "single":

        if model_choice == "ARIMA":

            dates, preds = forecast_arima_to_date(
                arima_fit,
                df,
                last_date,
                target_date
            )

        elif model_choice == "LSTM":

            dates, preds = forecast_lstm_to_date(
                lstm_model,
                scaler,
                df["Close"].values,
                last_date,
                target_date
            )

        else:
            return jsonify({
                "error": "model must be ARIMA or LSTM"
            }), 400

        response["result"] = package(
            dates,
            preds
        )

    else:

        a_dates, a_preds = forecast_arima_to_date(
            arima_fit,
            df,
            last_date,
            target_date
        )

        l_dates, l_preds = forecast_lstm_to_date(
            lstm_model,
            scaler,
            df["Close"].values,
            last_date,
            target_date
        )

        response["arima"] = package(
            a_dates,
            a_preds
        )

        response["lstm"] = package(
            l_dates,
            l_preds
        )

    return jsonify(response), 200


@predict_bp.get("/history/<ticker>")
@login_required
def history(ticker):

    if ticker not in COMPANIES.values():
        return jsonify({
            "error": "Unknown ticker"
        }), 400

    try:
        df = _get_recent_close(ticker)
    except Exception as e:
        return jsonify({
            "error": (
                f"Could not fetch price data for "
                f"{ticker}: {e}"
            )
        }), 502

    if df.empty:
        return jsonify({
            "error": f"No completed price data returned for {ticker}"
        }), 502

    df["SMA_10"] = (
        df["Close"]
        .rolling(10)
        .mean()
    )

    df["SMA_50"] = (
        df["Close"]
        .rolling(50)
        .mean()
    )

    records = df[
        ["Date", "Close", "SMA_10", "SMA_50"]
    ].fillna(0).to_dict(
        orient="records"
    )

    return jsonify([
        {
            "date": str(
                pd.Timestamp(r["Date"]).date()
            ),
            "close": round(
                float(r["Close"]), 2
            ),
            "sma10": round(
                float(r["SMA_10"]), 2
            ),
            "sma50": round(
                float(r["SMA_50"]), 2
            ),
        }
        for r in records
    ])
