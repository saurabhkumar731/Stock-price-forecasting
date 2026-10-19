requireAuth();

let charts = {};

let currentHistory = [];
let currentTicker = null;


/*
====================================================
MODEL PERFORMANCE DATA
====================================================
*/

const MODEL_RESULTS = {

    "TCS.NS": {
        arimaRMSE: 702.95,
        arimaMAPE: 24.79,
        lstmRMSE: 100.33,
        lstmMAPE: 3.35
    },

    "INFY.NS": {
        arimaRMSE: 281.08,
        arimaMAPE: 19.01,
        lstmRMSE: 40.21,
        lstmMAPE: 2.41
    },

    "RELIANCE.NS": {
        arimaRMSE: 144.06,
        arimaMAPE: 9.37,
        lstmRMSE: 21.06,
        lstmMAPE: 1.17
    },

    "HDFCBANK.NS": {
        arimaRMSE: 121.08,
        arimaMAPE: 10.92,
        lstmRMSE: 11.75,
        lstmMAPE: 0.93
    },

    "ICICIBANK.NS": {
        arimaRMSE: 79.15,
        arimaMAPE: 4.44,
        lstmRMSE: 33.87,
        lstmMAPE: 1.98
    },

    "SBIN.NS": {
        arimaRMSE: 190.08,
        arimaMAPE: 15.97,
        lstmRMSE: 54.63,
        lstmMAPE: 4.59
    },

    "BHARTIARTL.NS": {
        arimaRMSE: 106.17,
        arimaMAPE: 4.83,
        lstmRMSE: 45.09,
        lstmMAPE: 1.85
    },

    "ITC.NS": {
        arimaRMSE: 79.02,
        arimaMAPE: 21.29,
        lstmRMSE: 11.09,
        lstmMAPE: 2.61
    },

    "HINDUNILVR.NS": {
        arimaRMSE: 173.24,
        arimaMAPE: 6.40,
        lstmRMSE: 37.24,
        lstmMAPE: 1.20
    },

    "MARUTI.NS": {
        arimaRMSE: 2420.84,
        arimaMAPE: 13.22,
        lstmRMSE: 746.25,
        lstmMAPE: 4.01
    }

};


/*
====================================================
COLORS
====================================================
*/

const COLORS = {

    gold: "#C9A227",

    green: "#2FA36B",

    red: "#D14343",

    grid: "#23324A",

    text: "#8B97AC"

};


/*
====================================================
LOAD COMPANIES
====================================================
*/

async function loadCompanies() {

    try {

        const res = await fetch(
            "/api/companies",
            {
                credentials: "include"
            }
        );


        if (!res.ok) {

            throw new Error(
                "Could not load companies."
            );

        }


        const companies =
            await res.json();


        const select =
            document.getElementById("company");


        select.innerHTML =
            companies.map(company => {

                return `
                    <option value="${company.ticker}">
                        ${company.name}
                    </option>
                `;

            }).join("");


        if (companies.length > 0) {

            currentTicker =
                companies[0].ticker;

            await loadHistory(
                currentTicker
            );

        }

    }

    catch (error) {

        showError(error.message);

        console.error(error);

    }

}


/*
====================================================
LOAD HISTORY
====================================================
*/

async function loadHistory(ticker) {

    clearError();

    try {

        const res = await fetch(

            `/api/history/${encodeURIComponent(ticker)}`,

            {
                credentials: "include"
            }

        );


        if (!res.ok) {

            let message =
                `Request failed (${res.status})`;


            try {

                const data =
                    await res.json();


                if (data.error) {

                    message =
                        data.error;

                }

            }

            catch (e) {}


            throw new Error(message);

        }


        const rows =
            await res.json();


        if (
            !Array.isArray(rows) ||
            rows.length === 0
        ) {

            throw new Error(
                "No historical data returned for this company."
            );

        }


        currentHistory = rows;

        currentTicker = ticker;


        showDashboard();


        renderHistoricalChart();

        updateStatistics();

        updateModelPerformance();

    }

    catch (error) {

        showError(error.message);

        console.error(error);

    }

}


/*
====================================================
ANALYZE
====================================================
*/

async function analyze() {

    clearError();


    const ticker =
        document.getElementById("company").value;


    const targetDate =
        document.getElementById("forecast-date").value;


    if (!ticker) {

        showError(
            "Please select a company."
        );

        return;

    }


    if (!targetDate) {

        showError(
            "Please select a forecast date."
        );

        return;

    }


    const button =
        document.getElementById("analyze-btn");


    button.disabled = true;

    button.textContent =
        "Analyzing...";


    try {

        /*
        Get latest historical data
        */

        await loadHistory(ticker);


        /*
        Request forecast
        */

        const response =
            await fetch(
                "/api/predict",
                {
                    method: "POST",

                    credentials: "include",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({

                        ticker: ticker,

                        target_date:
                            targetDate,

                        mode:
                            "comparison"

                    })

                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            throw new Error(
                data.error ||
                "Prediction request failed."
            );

        }


        /*
        Render forecast
        */

        renderForecastComparison(data);

        renderForecastSummary(data);

        renderForecastInsight(data);


    }

    catch (error) {

        showError(error.message);

        console.error(error);

    }

    finally {

        button.disabled = false;

        button.textContent =
            "Analyze";

    }

}


/*
====================================================
HISTORICAL PRICE CHART
====================================================
*/

function renderHistoricalChart() {

    destroyChart("history");


    const rows =
        getFilteredHistory();


    const labels =
        rows.map(row => row.date);


    const close =
        rows.map(
            row => Number(row.close)
        );


    const sma10 =
        rows.map(
            row => Number(row.sma10)
        );


    const sma50 =
        rows.map(
            row => Number(row.sma50)
        );


    const canvas =
        document.getElementById(
            "history-chart"
        );


    const ctx =
        canvas.getContext("2d");


    charts.history =
        new Chart(ctx, {

            type: "line",

            data: {

                labels: labels,

                datasets: [

                    {
                        label: "Closing Price",

                        data: close,

                        borderColor:
                            COLORS.gold,

                        borderWidth: 2,

                        pointRadius: 0,

                        tension: 0.2
                    },


                    {
                        label: "SMA 10",

                        data: sma10,

                        borderColor:
                            COLORS.green,

                        borderWidth: 1.5,

                        pointRadius: 0,

                        tension: 0.2
                    },


                    {
                        label: "SMA 50",

                        data: sma50,

                        borderColor:
                            COLORS.red,

                        borderWidth: 1.5,

                        pointRadius: 0,

                        tension: 0.2
                    }

                ]

            },

            options:
                chartOptions("Price (₹)")

        });

}


/*
====================================================
ARIMA VS LSTM FORECAST
====================================================
*/

function renderForecastComparison(data) {

    destroyChart("comparison");


    if (
        !data.arima ||
        !data.lstm
    ) {

        return;

    }


    const historical =
        getFilteredHistory();


    const historyLabels =
        historical.map(
            row => row.date
        );


    const historyValues =
        historical.map(
            row => Number(row.close)
        );


    const arimaSeries =
        data.arima.series || [];


    const lstmSeries =
        data.lstm.series || [];


    const arimaLabels =
        arimaSeries.map(
            row => row.date
        );


    const arimaValues =
        arimaSeries.map(
            row => Number(row.value)
        );


    const lstmValues =
        lstmSeries.map(
            row => Number(row.value)
        );


    /*
    Use historical + forecast dates
    */

    const labels = [
        ...historyLabels,
        ...arimaLabels
    ];


    /*
    Historical line
    */

    const historicalData = [

        ...historyValues,

        ...new Array(
            arimaValues.length
        ).fill(null)

    ];


    /*
    ARIMA line starts at
    last historical value
    */

    const arimaData = [

        ...new Array(
            historyValues.length - 1
        ).fill(null),

        historyValues[
            historyValues.length - 1
        ],

        ...arimaValues

    ];


    /*
    LSTM line
    */

    const lstmData = [

        ...new Array(
            historyValues.length - 1
        ).fill(null),

        historyValues[
            historyValues.length - 1
        ],

        ...lstmValues

    ];


    const ctx =
        document
            .getElementById(
                "comparison-chart"
            )
            .getContext("2d");


    charts.comparison =
        new Chart(ctx, {

            type: "line",

            data: {

                labels: labels,

                datasets: [

                    {
                        label:
                            "Historical Price",

                        data:
                            historicalData,

                        borderColor:
                            COLORS.gold,

                        borderWidth: 2,

                        pointRadius: 0,

                        tension: 0.2
                    },


                    {
                        label:
                            "ARIMA Forecast",

                        data:
                            arimaData,

                        borderColor:
                            COLORS.red,

                        borderWidth: 2,

                        borderDash:
                            [7, 5],

                        pointRadius: 2,

                        tension: 0.2
                    },


                    {
                        label:
                            "LSTM Forecast",

                        data:
                            lstmData,

                        borderColor:
                            COLORS.green,

                        borderWidth: 2,

                        borderDash:
                            [7, 5],

                        pointRadius: 2,

                        tension: 0.2
                    }

                ]

            },

            options:
                forecastChartOptions()

        });

}


/*
====================================================
FORECAST SUMMARY
====================================================
*/

function renderForecastSummary(data) {

    if (data.arima) {

        const prediction =
            document.getElementById(
                "arima-prediction"
            );


        prediction.textContent =
            formatPrice(
                data.arima.predicted_close
            );


        const change =
            document.getElementById(
                "arima-change"
            );


        change.textContent =
            `${formatChange(
                data.arima.change_pct
            )}`;


        const trend =
            document.getElementById(
                "arima-trend"
            );


        trend.textContent =
            formatTrend(
                data.arima.trend
            );


        applyTrendClass(
            change,
            data.arima.change_pct
        );


        applyTrendClass(
            trend,
            data.arima.change_pct
        );

    }


    if (data.lstm) {

        const prediction =
            document.getElementById(
                "lstm-prediction"
            );


        prediction.textContent =
            formatPrice(
                data.lstm.predicted_close
            );


        const change =
            document.getElementById(
                "lstm-change"
            );


        change.textContent =
            `${formatChange(
                data.lstm.change_pct
            )}`;


        const trend =
            document.getElementById(
                "lstm-trend"
            );


        trend.textContent =
            formatTrend(
                data.lstm.trend
            );


        applyTrendClass(
            change,
            data.lstm.change_pct
        );


        applyTrendClass(
            trend,
            data.lstm.change_pct
        );

    }

}


/*
====================================================
FORECAST INSIGHT
====================================================
*/

function renderForecastInsight(data) {

    const box =
        document.getElementById(
            "forecast-insight"
        );


    if (
        !data.arima ||
        !data.lstm
    ) {

        box.textContent =
            "Forecast data is not available.";

        return;

    }


    const arimaChange =
        Number(
            data.arima.change_pct
        );


    const lstmChange =
        Number(
            data.lstm.change_pct
        );


    let message = "";


    if (
        arimaChange < 0 &&
        lstmChange < 0
    ) {

        message =
            "Both models estimate a lower price than the current price for the selected forecast date.";

    }

    else if (
        arimaChange > 0 &&
        lstmChange > 0
    ) {

        message =
            "Both models estimate a higher price than the current price for the selected forecast date.";

    }

    else {

        message =
            "The two models give different directions for the selected forecast date.";

    }


    box.innerHTML =
        `<strong>Forecast summary:</strong> ${message}`;

}


/*
====================================================
MODEL PERFORMANCE
====================================================
*/

function updateModelPerformance() {

    const result =
        MODEL_RESULTS[currentTicker];


    if (!result) {

        return;

    }


    document.getElementById(
        "arima-rmse"
    ).textContent =
        result.arimaRMSE.toFixed(2);


    document.getElementById(
        "arima-mape"
    ).textContent =
        `${result.arimaMAPE.toFixed(2)}%`;


    document.getElementById(
        "lstm-rmse"
    ).textContent =
        result.lstmRMSE.toFixed(2);


    document.getElementById(
        "lstm-mape"
    ).textContent =
        `${result.lstmMAPE.toFixed(2)}%`;


    /*
    Find lower historical MAPE
    */

    const lstmBetter =
        result.lstmMAPE <
        result.arimaMAPE;


    const lowerErrorModel =
        lstmBetter
            ? "LSTM"
            : "ARIMA";


    document.getElementById(
        "best-model"
    ).textContent =
        lowerErrorModel;


    document.getElementById(
        "best-model-mape"
    ).textContent =
        `${lstmBetter
            ? result.lstmMAPE
            : result.arimaMAPE}% historical MAPE`;


    renderPerformanceChart(result);

}


/*
====================================================
PERFORMANCE CHART
====================================================
*/

function renderPerformanceChart(result) {

    destroyChart("performance");


    const ctx =
        document
            .getElementById(
                "performance-chart"
            )
            .getContext("2d");


    charts.performance =
        new Chart(ctx, {

            type: "bar",

            data: {

                labels: [
                    "RMSE",
                    "MAPE (%)"
                ],

                datasets: [

                    {
                        label: "ARIMA",

                        data: [
                            result.arimaRMSE,
                            result.arimaMAPE
                        ],

                        backgroundColor:
                            COLORS.red

                    },


                    {
                        label: "LSTM",

                        data: [
                            result.lstmRMSE,
                            result.lstmMAPE
                        ],

                        backgroundColor:
                            COLORS.green

                    }

                ]

            },

            options:
                chartOptions("Error")

        });

}


/*
====================================================
STATISTICS
====================================================
*/

function updateStatistics() {

    const rows =
        getFilteredHistory();


    const prices =
        rows.map(
            row => Number(row.close)
        );


    if (!prices.length) {

        return;

    }


    const current =
        prices[prices.length - 1];


    const highest =
        Math.max(...prices);


    const lowest =
        Math.min(...prices);


    document.getElementById(
        "current-price"
    ).textContent =
        formatPrice(current);


    document.getElementById(
        "current-date"
    ).textContent =
        rows[
            rows.length - 1
        ].date;


    document.getElementById(
        "highest-price"
    ).textContent =
        formatPrice(highest);


    document.getElementById(
        "lowest-price"
    ).textContent =
        formatPrice(lowest);

}


/*
====================================================
FILTER HISTORY
====================================================
*/

function getFilteredHistory() {

    const period =
        Number(
            document.getElementById(
                "period"
            ).value
        );


    if (!currentHistory.length) {

        return [];

    }


    return currentHistory.slice(
        -period
    );

}


/*
====================================================
NORMAL CHART OPTIONS
====================================================
*/

function chartOptions(yTitle) {

    return {

        responsive: true,

        maintainAspectRatio: false,

        interaction: {

            mode: "index",

            intersect: false

        },

        plugins: {

            legend: {

                labels: {

                    color:
                        COLORS.text

                }

            },

            tooltip: {

                callbacks: {

                    label: function(context) {

                        return `${context.dataset.label}: ${formatPrice(context.raw)}`;

                    }

                }

            }

        },

        scales: {

            x: {

                ticks: {

                    color:
                        COLORS.text,

                    maxTicksLimit:
                        10

                },

                grid: {

                    color:
                        COLORS.grid

                }

            },

            y: {

                title: {

                    display: true,

                    text: yTitle,

                    color:
                        COLORS.text

                },

                ticks: {

                    color:
                        COLORS.text

                },

                grid: {

                    color:
                        COLORS.grid

                }

            }

        }

    };

}


/*
====================================================
FORECAST CHART OPTIONS
====================================================
*/

function forecastChartOptions() {

    return {

        responsive: true,

        maintainAspectRatio: false,

        interaction: {

            mode: "index",

            intersect: false

        },

        plugins: {

            legend: {

                labels: {

                    color:
                        COLORS.text

                }

            },

            tooltip: {

                callbacks: {

                    label: function(context) {

                        if (
                            context.raw === null ||
                            context.raw === undefined
                        ) {

                            return "";

                        }

                        return `${context.dataset.label}: ${formatPrice(context.raw)}`;

                    }

                }

            }

        },

        scales: {

            x: {

                ticks: {

                    color:
                        COLORS.text,

                    maxTicksLimit:
                        10

                },

                grid: {

                    color:
                        COLORS.grid

                }

            },

            y: {

                title: {

                    display: true,

                    text:
                        "Price (₹)",

                    color:
                        COLORS.text

                },

                ticks: {

                    color:
                        COLORS.text

                },

                grid: {

                    color:
                        COLORS.grid

                }

            }

        }

    };

}


/*
====================================================
DESTROY CHART
====================================================
*/

function destroyChart(name) {

    if (charts[name]) {

        charts[name].destroy();

        charts[name] = null;

    }

}


/*
====================================================
SHOW DASHBOARD
====================================================
*/

function showDashboard() {

    document.getElementById(
        "empty-state"
    ).style.display =
        "none";


    document.getElementById(
        "dashboard"
    ).style.display =
        "block";

}


/*
====================================================
ERROR
====================================================
*/

function showError(message) {

    const error =
        document.getElementById(
            "viz-error"
        );


    error.className =
        "error-text";


    error.textContent =
        message;

}


function clearError() {

    const error =
        document.getElementById(
            "viz-error"
        );


    error.textContent = "";

    error.className = "";

}


/*
====================================================
PRICE FORMAT
====================================================
*/

function formatPrice(value) {

    if (
        value === null ||
        value === undefined ||
        Number.isNaN(Number(value))
    ) {

        return "—";

    }


    return "₹" +
        Number(value).toLocaleString(
            "en-IN",
            {
                minimumFractionDigits: 2,

                maximumFractionDigits: 2
            }
        );

}


/*
====================================================
CHANGE FORMAT
====================================================
*/

function formatChange(value) {

    const number =
        Number(value);


    if (Number.isNaN(number)) {

        return "—";

    }


    const arrow =
        number > 0
            ? "▲"
            : number < 0
                ? "▼"
                : "—";


    return `${arrow} ${Math.abs(number).toFixed(2)}%`;

}


/*
====================================================
TREND FORMAT
====================================================
*/

function formatTrend(trend) {

    if (!trend) {

        return "—";

    }


    const value =
        String(trend).toLowerCase();


    if (value === "up") {

        return "UP";

    }


    if (value === "down") {

        return "DOWN";

    }


    return value.toUpperCase();

}


/*
====================================================
TREND CLASS
====================================================
*/

function applyTrendClass(element, change) {

    element.classList.remove(
        "up",
        "down"
    );


    const number =
        Number(change);


    if (number > 0) {

        element.classList.add("up");

    }

    else if (number < 0) {

        element.classList.add("down");

    }

}


/*
====================================================
EVENTS
====================================================
*/

document.addEventListener(
    "DOMContentLoaded",
    () => {

        loadCompanies();


        document
            .getElementById(
                "analyze-btn"
            )
            .addEventListener(
                "click",
                analyze
            );


        document
            .getElementById(
                "company"
            )
            .addEventListener(
                "change",
                async event => {

                    await loadHistory(
                        event.target.value
                    );

                }
            );


        document
            .getElementById(
                "period"
            )
            .addEventListener(
                "change",
                () => {

                    if (
                        !currentHistory.length
                    ) {

                        return;

                    }


                    renderHistoricalChart();

                    updateStatistics();

                }
            );

    }
);