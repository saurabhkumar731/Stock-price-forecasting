requireAuth();

const chatWindow = document.getElementById('chat-window');

function appendMessage(text, role) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.textContent = text;
  chatWindow.appendChild(div);
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

async function loadHistory() {
  const res = await fetch('/api/chat/history', { credentials: 'include' });
  if (!res.ok) return;
  const items = await res.json();
  items.forEach(item => {
    appendMessage(item.message, 'user');
    appendMessage(item.reply, 'bot');
  });
}
loadHistory();

document.getElementById('chat-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = document.getElementById('chat-input');
  const message = input.value.trim();
  if (!message) return;
  appendMessage(message, 'user');
  input.value = '';

  const thinking = document.createElement('div');
  thinking.className = 'msg bot';
  thinking.textContent = '…';
  chatWindow.appendChild(thinking);
  chatWindow.scrollTop = chatWindow.scrollHeight;

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ message, model: 'mistral' }),
    });
    const data = await res.json();
    thinking.textContent = res.ok ? data.reply : (data.error || 'Something went wrong.');
  } catch (err) {
    thinking.textContent = 'Could not reach the server.';
  }
});
