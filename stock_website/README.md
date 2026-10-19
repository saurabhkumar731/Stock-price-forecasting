# Ledger — Stock Forecast Website

Full-stack rebuild: Flask backend (auth, MongoDB, ML serving) + vanilla HTML/CSS/JS frontend.

## Project structure
```
stock_website/
├── backend/
│   ├── app.py              Flask app factory, serves frontend + registers API routes
│   ├── config.py           Env-driven settings (Mongo URI, JWT secret, Ollama URL)
│   ├── extensions.py       Mongo client + bcrypt instance
│   ├── auth_utils.py       JWT create/verify + @login_required decorator
│   ├── routes/
│   │   ├── auth.py         /api/auth/signup, /login, /logout, /me
│   │   ├── predict.py      /api/companies, /api/predict, /api/history/<ticker>
│   │   └── chatbot.py      /api/chat, /api/chat/history (proxies to Ollama)
│   └── ml/
│       ├── model_loader.py Loads arima_*.pkl / lstm_*.keras / scaler_*.pkl per ticker
│       └── forecasting.py  Trading-day-correct forecast functions
├── frontend/
│   ├── index.html, login.html, signup.html, predict.html, visualize.html, chatbot.html
│   ├── css/style.css
│   └── js/ (auth.js, nav.js, predict.js, visualize.js, chatbot.js)
└── models/                 Drop your trained arima_*.pkl / lstm_*.keras / scaler_*.pkl here
                             (produced by Stock_Prediction_Rebuilt.ipynb)
```

## Setup

1. **Install MongoDB** locally (or use MongoDB Atlas free tier) and have it running on
   `mongodb://localhost:27017` — or set `MONGO_URI` to your Atlas connection string.

2. **Install Python dependencies:**
   ```
   cd backend
   pip install -r requirements.txt
   ```

3. **Set environment variables** (or just edit the defaults in `config.py` for local dev):
   ```
   set MONGO_URI=mongodb://localhost:27017/stockapp
   set JWT_SECRET=some-long-random-string
   set OLLAMA_URL=http://localhost:11434/api/chat
   ```

4. **Copy your trained model files** from the training notebook's `models/` folder into
   `stock_website/models/`. Filenames must match the pattern `arima_<TICKER>.pkl`,
   `lstm_<TICKER>.keras`, `scaler_<TICKER>.pkl` (e.g. `arima_TCS_NS.pkl`).

5. **(Optional) Start Ollama** for the chatbot page: `ollama serve`, then
   `ollama pull mistral` (or whichever model you set in `chatbot.js`).

6. **Run the server:**
   ```
   python -m backend.app
   ```
   Visit `http://localhost:5000`.

## How auth works
- Passwords are hashed with bcrypt before being stored in MongoDB's `users` collection.
- On login/signup, a JWT is issued and stored in an **httpOnly cookie** (not accessible
  to JavaScript, which protects against XSS token theft).
- Protected API routes (`/api/predict`, `/api/history`, `/api/chat`) use the
  `@login_required` decorator, which reads and validates that cookie.
- Protected pages (`predict.html`, `visualize.html`, `chatbot.html`) call `requireAuth()`
  on load, which pings `/api/auth/me` and redirects to `/login.html` if the session
  is invalid or expired.

## What's already verified
The auth flow (signup → duplicate rejection → login → protected route access →
wrong password rejection → logout → access revoked) was tested end-to-end with a
mock MongoDB. The `/api/predict` route correctly returns a clear 404 with the
expected file paths when a ticker's model files aren't present yet — drop in
your trained models from the notebook and it'll pick them up automatically.

The chatbot now has two paths, both tested:
- **Stock question** ("predict TCS for 25-12-2026", "what about Infosys in 3 months") —
  detected via company-name + date extraction, answered directly from your trained
  ARIMA/LSTM models (no LLM call at all), using the same trading-day-correct
  forecasting as the Predict page.
- **General question** — falls back to your local Ollama model.
- Date extraction uses `dateparser.search.search_dates`, filtered to require a digit
  in the matched text — this avoids a real false-positive bug where the word "no" or
  "are" alone gets misread as a date by the raw library.
- MongoDB connection failures now fail fast (3s) with a clear message instead of a
  30-second hang and a cryptic timeout traceback.

## Still worth doing (not built yet)
- Rate limiting / account lockout on repeated failed logins.
- A "forgot password" flow.
- Real NSE holiday calendar for forecasting (currently uses business days only,
  via `pd.bdate_range` — close enough for a project, but misses public holidays).
- HTTPS/production WSGI server config (this runs Flask's dev server).

