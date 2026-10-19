// Include on every protected page (predict, visualize, chatbot).
// Checks the session cookie via /api/auth/me; redirects to login if invalid.
async function requireAuth() {
  try {
    const res = await fetch('/api/auth/me', { credentials: 'include' });
    if (!res.ok) {
      window.location.href = '/login.html';
      return null;
    }
    const data = await res.json();
    const el = document.getElementById('nav-username');
    if (el) el.textContent = data.username;
    return data.username;
  } catch (e) {
    window.location.href = '/login.html';
    return null;
  }
}

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
  window.location.href = '/index.html';
}

document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('logout-btn');
  if (btn) btn.addEventListener('click', logout);
});
