import numpy as np
import pandas as pd


def future_trading_dates(
    last_date: pd.Timestamp,
    target_date: pd.Timestamp
) -> pd.DatetimeIndex:
    """
    Return future business days between last_date and target_date.

    This excludes Saturdays and Sundays. It does not yet exclude NSE
    exchange holidays. If exact NSE holidays are required later, this
    function can be replaced with an NSE market calendar.
    """
    last_date = pd.Timestamp(last_date).normalize()
    target_date = pd.Timestamp(target_date).normalize()

    return pd.bdate_range(
        start=last_date + pd.Timedelta(days=1),
        end=target_date
    )


def _get_last_arima_value(arima_fit):
    """
    Return the last actual observation used when the saved ARIMA model
    was fitted.

    Your saved model has an integer index (0 ... 1495), so we cannot use
    the ARIMA row label as a date. Instead, we use the last observed value
    to locate the corresponding date in fresh Yahoo Finance data.
    """
    try:
        endog = np.asarray(arima_fit.model.endog, dtype=float).reshape(-1)

        if len(endog) == 0:
            return None

        return float(endog[-1])
    except Exception:
        return None


def _find_arima_training_end(
    arima_fit,
    fresh_df: pd.DataFrame,
    tolerance: float = 1e-5
):
    """
    Find the date of the last observation contained in the saved ARIMA
    model by matching its last fitted observation against fresh Yahoo
    Finance closing prices.

    Example:
        Saved ARIMA last value = 2204.10009766
        Yahoo:
            2026-09-10 = 2204.10
            2026-09-11 = 2200.80

        Result:
            training end = 2026-09-10

    A relative tolerance is used because floating-point representations
    may differ slightly between the saved model and Yahoo Finance.
    """
    if fresh_df is None or fresh_df.empty:
        return None

    last_arima_value = _get_last_arima_value(arima_fit)

    if last_arima_value is None:
        return None

    work = fresh_df.copy()

    if "Date" not in work.columns or "Close" not in work.columns:
        return None

    work["Date"] = pd.to_datetime(
        work["Date"], errors="coerce"
    ).dt.normalize()

    work["Close"] = pd.to_numeric(
        work["Close"], errors="coerce"
    )

    work = (
        work.dropna(subset=["Date", "Close"])
            .sort_values("Date")
            .drop_duplicates(subset=["Date"])
            .reset_index(drop=True)
    )

    if work.empty:
        return None

    values = work["Close"].to_numpy(dtype=float)

    # Use np.isclose rather than exact equality because the saved ARIMA
    # value may contain more floating-point precision.
    matches = np.isclose(
        values,
        last_arima_value,
        rtol=tolerance,
        atol=0.01
    )

    matching_rows = work.loc[matches]

    if matching_rows.empty:
        return None

    # If the same closing price occurred more than once, the last matching
    # date is the safest candidate for the model's final observation.
    return pd.Timestamp(
        matching_rows["Date"].iloc[-1]
    ).normalize()


def _prepare_fresh_data(fresh_df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize fresh Yahoo Finance data before using it for ARIMA updates.
    """
    if fresh_df is None or fresh_df.empty:
        return pd.DataFrame()

    work = fresh_df.copy()

    if "Date" not in work.columns or "Close" not in work.columns:
        return pd.DataFrame()

    work["Date"] = pd.to_datetime(
        work["Date"], errors="coerce"
    ).dt.normalize()

    work["Close"] = pd.to_numeric(
        work["Close"], errors="coerce"
    )

    work = (
        work.dropna(subset=["Date", "Close"])
            .sort_values("Date")
            .drop_duplicates(subset=["Date"])
            .reset_index(drop=True)
    )

    return work


def forecast_arima_to_date(
    arima_fit,
    fresh_df,
    last_date,
    target_date
):
    """
    Forecast with the saved ARIMA model while incorporating new Yahoo
    Finance observations without retraining the complete 5-year model.

    Process:
        1. Load the already-trained ARIMA model.
        2. Find the model's last training observation by matching its last
           value against fresh Yahoo Finance data.
        3. Identify observations after that training endpoint.
        4. Append only those new observations with refit=False.
        5. Forecast from the latest actual market date.

    The original .pkl file is NEVER modified or overwritten.
    """
    dates = future_trading_dates(last_date, target_date)

    if len(dates) == 0:
        return dates, np.array([])

    work = _prepare_fresh_data(fresh_df)

    # Start with the original saved model.
    updated_fit = arima_fit

    if not work.empty:
        training_end = _find_arima_training_end(
            arima_fit,
            work
        )

        if training_end is not None:
            # Only observations that were not present during the original
            # ARIMA training are appended.
            new_rows = work[
                work["Date"] > training_end
            ]

            if not new_rows.empty:
                new_values = new_rows["Close"].astype(
                    float
                ).to_numpy()

                try:
                    # Efficient update: do NOT refit the ARIMA parameters.
                    updated_fit = arima_fit.append(
                        new_values,
                        refit=False
                    )
                except TypeError:
                    # Compatibility with older statsmodels versions.
                    updated_fit = arima_fit.append(
                        new_values
                    )

        else:
            # Do not blindly append data if we cannot reliably determine
            # where the saved ARIMA training data ended.
            #
            # This is safer than accidentally appending the entire 5-year
            # Yahoo dataset to an already-fitted model.
            updated_fit = arima_fit

    forecast = updated_fit.get_forecast(
        steps=len(dates)
    )

    predicted = np.asarray(
        forecast.predicted_mean,
        dtype=float
    ).reshape(-1)

    return dates, predicted


def forecast_lstm_to_date(
    lstm_model,
    scaler,
    last_close_values,
    last_date,
    target_date,
    time_step=60
):
    """
    Make an LSTM forecast using the latest actual Yahoo Finance data.

    The saved LSTM weights and saved scaler are reused.
    No LSTM training or scaler refitting occurs during prediction.
    """
    dates = future_trading_dates(last_date, target_date)

    if len(dates) == 0:
        return dates, np.array([])

    values = np.asarray(
        last_close_values,
        dtype=float
    ).reshape(-1)

    if len(values) < time_step:
        raise ValueError(
            f"LSTM requires at least {time_step} close prices, "
            f"but only {len(values)} were provided."
        )

    # Use the existing scaler from training.
    seq = scaler.transform(
        values[-time_step:].reshape(-1, 1)
    )

    preds = []

    for _ in range(len(dates)):
        x = seq[-time_step:].reshape(
            1,
            time_step,
            1
        )

        p = float(
            lstm_model.predict(
                x,
                verbose=0
            )[0, 0]
        )

        preds.append(p)

        # Recursive multi-step forecasting:
        # the predicted scaled value becomes the next input.
        seq = np.append(
            seq,
            [[p]],
            axis=0
        )

    # Convert predictions back to the original price scale.
    preds = scaler.inverse_transform(
        np.asarray(preds).reshape(-1, 1)
    ).flatten()

    return dates, preds
