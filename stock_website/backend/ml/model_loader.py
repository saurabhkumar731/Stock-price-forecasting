import os
import pickle
from backend.config import Config

# Cache loaded models in memory so we don't hit disk on every request
_cache = {}


def _paths(ticker: str):
    safe = ticker.replace(".", "_")
    return {
        "arima": os.path.join(Config.MODELS_DIR, f"arima_{safe}.pkl"),
        "lstm": os.path.join(Config.MODELS_DIR, f"lstm_{safe}.keras"),
        "scaler": os.path.join(Config.MODELS_DIR, f"scaler_{safe}.pkl"),
    }


def has_models(ticker: str) -> bool:
    p = _paths(ticker)
    return os.path.exists(p["arima"]) and os.path.exists(p["lstm"]) and os.path.exists(p["scaler"])


def load_company_models(ticker: str):
    """Returns (arima_fit, lstm_model, scaler) for a ticker, loading from disk
    once and caching in memory afterwards. Raises FileNotFoundError if the
    trained files for this ticker don't exist yet (run the training notebook)."""
    if ticker in _cache:
        return _cache[ticker]

    p = _paths(ticker)
    if not has_models(ticker):
        raise FileNotFoundError(
            f"No trained models found for {ticker}. Expected files: "
            f"{p['arima']}, {p['lstm']}, {p['scaler']}. Run the training notebook first."
        )

    # Imported lazily so the app can start even if tensorflow isn't installed
    # yet (e.g. while you're still wiring up auth/DB before ML is ready).
    from tensorflow.keras.models import load_model as keras_load_model

    arima_fit = pickle.load(open(p["arima"], "rb"))
    lstm_model = keras_load_model(p["lstm"])
    scaler = pickle.load(open(p["scaler"], "rb"))

    _cache[ticker] = (arima_fit, lstm_model, scaler)
    return _cache[ticker]