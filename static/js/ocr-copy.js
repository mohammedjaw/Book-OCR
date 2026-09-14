(function () {
  'use strict';
  const area = document.getElementById('ocr-area');
  const text = document.getElementById('ocr');
  const full = document.getElementById('copy-page');
  const selectionButton = document.getElementById('copy-selection');
  const status = document.getElementById('copy-status');
  if (!area || !text || !full || !selectionButton) return;
  let timer;
  function fallback(value) {
    const input = document.createElement('textarea');
    input.value = value; input.setAttribute('readonly', ''); input.style.position = 'fixed'; input.style.opacity = '0';
    document.body.appendChild(input); input.select();
    let ok = false; try { ok = document.execCommand('copy'); } finally { input.remove(); }
    return ok;
  }
  function copy(value) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(value).then(() => true, () => fallback(value));
    return Promise.resolve(fallback(value));
  }
  function feedback(ok) {
    status.textContent = ok ? full.title : '';
    clearTimeout(timer); timer = setTimeout(() => { status.textContent = ''; }, 1800);
  }
  full.addEventListener('click', () => copy(text.innerText).then(feedback));
  function updateSelection() {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.toString().trim() || !selection.anchorNode || !text.contains(selection.anchorNode) || !text.contains(selection.focusNode)) {
      selectionButton.hidden = true; return;
    }
    const rect = selection.getRangeAt(0).getBoundingClientRect();
    const parent = area.getBoundingClientRect();
    selectionButton.style.left = Math.max(4, rect.left - parent.left + rect.width / 2 - 30) + 'px';
    selectionButton.style.top = Math.max(4, rect.top - parent.top - 42) + 'px';
    selectionButton.hidden = false;
  }
  document.addEventListener('selectionchange', updateSelection);
  document.addEventListener('mousedown', (event) => { if (!area.contains(event.target)) selectionButton.hidden = true; });
  selectionButton.addEventListener('mousedown', (event) => event.preventDefault());
  selectionButton.addEventListener('click', () => {
    const selection = window.getSelection(); const value = selection ? selection.toString() : '';
    if (value.trim()) copy(value).then(() => { selectionButton.hidden = true; feedback(true); });
  });
  selectionButton.hidden = true;
}());
