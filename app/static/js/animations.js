(() => {
  'use strict';

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const selector = '.reveal, .reveal-up, .reveal-left, .reveal-right, .reveal-scale, [data-reveal]';
  let observer;

  function prepareElement(element, index = 0) {
    if (element.dataset.revealReady === 'true') return;
    element.dataset.revealReady = 'true';
    if (!element.style.getPropertyValue('--reveal-delay') && element.parentElement?.classList.contains('stagger-grid')) {
      element.style.setProperty('--reveal-index', String(index));
    }
    if (reduceMotion.matches || !('IntersectionObserver' in window)) {
      element.classList.add('is-visible');
      return;
    }
    observer.observe(element);
  }

  function scan(root = document) {
    const elements = root.matches?.(selector) ? [root] : [...root.querySelectorAll(selector)];
    elements.forEach((element, index) => prepareElement(element, index));
  }

  if ('IntersectionObserver' in window) {
    observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -36px' });
  }

  scan();

  const mutationObserver = new MutationObserver(records => {
    records.forEach(record => record.addedNodes.forEach(node => {
      if (node.nodeType === Node.ELEMENT_NODE) scan(node);
    }));
  });
  mutationObserver.observe(document.body, { childList: true, subtree: true });

  function setButtonLoading(button, loading, loadingText = 'Processando…') {
    if (!button) return;
    if (loading) {
      if (button.dataset.loading === 'true') return;
      button.dataset.loading = 'true';
      button.dataset.originalHtml = button.innerHTML;
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      button.innerHTML = `<span class="button-spinner" aria-hidden="true"></span><span>${loadingText}</span>`;
    } else {
      button.disabled = false;
      button.removeAttribute('aria-busy');
      if (button.dataset.originalHtml) button.innerHTML = button.dataset.originalHtml;
      delete button.dataset.originalHtml;
      delete button.dataset.loading;
    }
  }

  window.DivulgaiUI = Object.freeze({ setButtonLoading, scanReveals: scan });
})();
