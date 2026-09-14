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
    status.textContent = ok ? status.dataset.success : '';
    clearTimeout(timer); timer = setTimeout(() => { status.textContent = ''; }, 1800);
  }
  full.addEventListener('click', () => copy(text.textContent).then(feedback));
  function hideSelectionButton() { selectionButton.hidden = true; }
  function updateSelection() {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.toString().trim() || !selection.anchorNode || !text.contains(selection.anchorNode) || !text.contains(selection.focusNode)) {
      hideSelectionButton(); return;
    }
    const rect = selection.getRangeAt(0).getBoundingClientRect();
    selectionButton.hidden = false;
    const gap = 8; const buttonRect = selectionButton.getBoundingClientRect();
    let left = rect.left + rect.width / 2 - buttonRect.width / 2;
    let top = rect.top - buttonRect.height - gap;
    if (top < gap) top = Math.min(window.innerHeight - buttonRect.height - gap, rect.bottom + gap);
    left = Math.max(gap, Math.min(left, window.innerWidth - buttonRect.width - gap));
    top = Math.max(gap, Math.min(top, window.innerHeight - buttonRect.height - gap));
    selectionButton.style.left = left + 'px'; selectionButton.style.top = top + 'px';
  }
  document.addEventListener('selectionchange', updateSelection);
  document.addEventListener('mousedown', (event) => { if (!area.contains(event.target)) hideSelectionButton(); });
  window.addEventListener('scroll', hideSelectionButton, true);
  window.addEventListener('resize', hideSelectionButton);
  selectionButton.addEventListener('mousedown', (event) => event.preventDefault());
  selectionButton.addEventListener('click', () => {
    const selection = window.getSelection(); const value = selection ? selection.toString() : '';
    if (value.trim()) copy(value).then(() => { hideSelectionButton(); feedback(true); });
  });
  selectionButton.hidden = true;
}());
