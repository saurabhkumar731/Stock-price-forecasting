requireAuth();

const modeSelect = document.getElementById('mode');
const modelField = document.getElementById('model-field');
modeSelect.addEventListener('change', () => {
  modelField.style.display = modeSelect.value === 'single' ? 'block' : 'none';
});

async function loadCompanies() {
  const res = await fetch('/api/companies');
  const companies = await res.json();
  const select = document.getElementById('company');
  select.innerHTML = companies.map(c =>
    `<option value="${c.ticker}">${c.name}${c.trained ? '' : '  (not trained yet)'}</option>`
  ).join('');
}
loadCompanies();

function trendArrow(trend) {
  return trend === 'up' ? '▲' : '▼';
}

function resultBlock(title, result) {
  if (!result) return `<div class="panel"><h3>${title}</h3><p class="muted">No forecast available.</p></div>`;
  const cls = result.trend === 'up' ? 'up' : 'down';
  return `
    <div class="panel">
      <h3>${title}</h3>
      <div class="result-row">
        <span class="result-label">Predicted close</span>
        <span class="result-value ticker-num">₹${result.predicted_close}</span>
      </div>
      <div class="result-row">
        <span class="result-label">Trend</span>
        <span class="result-value ${cls}">${trendArrow(result.trend)} ${result.change_pct}%</span>
      </div>
    </div>`;
}

document.getElementById('predict-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const errorEl = document.getElementById('error');
  errorEl.textContent = '';
  const resultsEl = document.getElementById('results');
  resultsEl.innerHTML = '<p class="muted">Running forecast…</p>';

  const payload = {
    ticker: document.getElementById('company').value,
    target_date: document.getElementById('target-date').value,
    mode: modeSelect.value,
    model: document.getElementById('model').value,
  };

  try {
    const res = await fetch('/api/predict', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      resultsEl.innerHTML = '';
      errorEl.textContent = data.error || 'Prediction failed';
      return;
    }

    let html = `<div class="panel" style="margin-bottom:20px;">
      <div class="result-row">
        <span class="result-label">Last close (${data.last_date})</span>
        <span class="result-value ticker-num">₹${data.last_close}</span>
      </div>
    </div>`;

    if (payload.mode === 'single') {
      html += resultBlock(payload.model, data.result);
    } else {
      html += `<div class="compare-cols">${resultBlock('ARIMA', data.arima)}${resultBlock('LSTM', data.lstm)}</div>`;
    }
    resultsEl.innerHTML = html;
  } catch (err) {
    resultsEl.innerHTML = '';
    errorEl.textContent = 'Could not reach the server.';
  }
});
