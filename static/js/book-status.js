(() => {
  const root = document.getElementById('ocr-status');
  const labels = JSON.parse(document.getElementById('status-labels').textContent);
  const el = id => document.getElementById(id);
  let timer, busy = false, failures = 0;
  async function poll() {
    if (busy) return;
    clearTimeout(timer); busy = true;
    let interval = 3000;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(root.dataset.url, {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('status');
      const data = await response.json(), counts = data.counts;
      for (const key of ['completed', 'processing', 'pending', 'failed']) el(key).textContent = counts[key] || 0;
      el('progress').value = counts.completed || 0;
      el('progress-text').textContent = `${counts.completed || 0} / ${data.total}`;
      el('worker-text').textContent = labels[data.state] || data.state;
      el('start-form').querySelector('button').disabled = data.active || !counts.pending;
      el('pause-form').querySelector('button').disabled = !data.active || data.state === 'pausing';
      el('retry-form').querySelector('button').disabled = data.active || !data.retryable_failed;
      root.querySelector('.single-page-form button').disabled = data.active || !counts.pending;
      el('exports').hidden = !data.complete;
      el('poll-error').textContent = ''; failures = 0;
      interval = data.active ? 3000 : 15000;
    } catch (_) {
      el('poll-error').textContent = labels.connection_error;
      interval = Math.min(30000, 3000 * 2 ** Math.min(++failures, 3));
    } finally {
      clearTimeout(timeout); busy = false;
      timer = setTimeout(poll, document.hidden ? Math.max(interval, 15000) : interval);
    }
  }
  for (const form of root.querySelectorAll('form')) form.addEventListener('submit', async event => {
    event.preventDefault();
    for (const button of form.querySelectorAll('button')) button.disabled = true;
    try {
      const response = await fetch(form.action, {method:'POST', body:new FormData(form)});
      if (!response.ok) throw new Error('action');
    } catch (_) { el('poll-error').textContent = labels.connection_error; }
    await poll();
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  poll();
})();
