(() => {
  'use strict';

  const body = document.body;
  const sidebar = document.querySelector('#sidebar');
  const menuToggle = document.querySelector('#menuToggle');
  const sidebarBackdrop = document.querySelector('#sidebarBackdrop');
  const sidebarCollapse = document.querySelector('#sidebarCollapse');
  const publicNavbar = document.querySelector('#publicNavbar');
  const publicMenuToggle = document.querySelector('#publicMenuToggle');
  const publicNavLinks = document.querySelector('#publicNavLinks');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let menuReturnFocus = null;
  let publicMenuReturnFocus = null;

  function readCollapsedPreference() {
    try { return localStorage.getItem('divulgai-sidebar-collapsed') === 'true'; }
    catch { return false; }
  }

  function saveCollapsedPreference(collapsed) {
    try { localStorage.setItem('divulgai-sidebar-collapsed', String(collapsed)); }
    catch { /* O layout continua funcional quando o armazenamento está bloqueado. */ }
  }

  function isMobileSidebar() {
    return window.matchMedia('(max-width: 991.98px)').matches;
  }

  function setMobileSidebar(open, restoreFocus = false) {
    if (!sidebar || !menuToggle) return;
    if (!isMobileSidebar()) {
      sidebar.classList.remove('open');
      sidebar.removeAttribute('inert');
      sidebar.removeAttribute('aria-hidden');
      body.classList.remove('sidebar-open');
      menuToggle.setAttribute('aria-expanded', 'false');
      return;
    }
    sidebar.classList.toggle('open', open);
    body.classList.toggle('sidebar-open', open);
    menuToggle.setAttribute('aria-expanded', String(open));
    menuToggle.setAttribute('aria-label', open ? 'Fechar menu' : 'Abrir menu');
    sidebarBackdrop?.setAttribute('aria-hidden', String(!open));
    if (open) {
      sidebar.removeAttribute('inert');
      sidebar.setAttribute('aria-hidden', 'false');
      menuReturnFocus = document.activeElement;
      window.setTimeout(() => sidebar.querySelector('a, button')?.focus(), 220);
    } else {
      sidebar.setAttribute('inert', '');
      sidebar.setAttribute('aria-hidden', 'true');
      if (restoreFocus && menuReturnFocus instanceof HTMLElement) menuReturnFocus.focus();
    }
  }

  menuToggle?.addEventListener('click', () => setMobileSidebar(!sidebar.classList.contains('open')));
  sidebarBackdrop?.addEventListener('click', () => setMobileSidebar(false, true));
  sidebar?.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
    if (isMobileSidebar()) setMobileSidebar(false);
  }));

  function applyCollapsedState(collapsed) {
    if (!sidebarCollapse) return;
    const active = collapsed && !isMobileSidebar();
    body.classList.toggle('sidebar-is-collapsed', active);
    sidebarCollapse.setAttribute('aria-expanded', String(!active));
    sidebarCollapse.setAttribute('aria-label', active ? 'Expandir menu' : 'Recolher menu');
    sidebarCollapse.querySelector('i')?.classList.toggle('bi-layout-sidebar-inset-reverse', active);
    sidebarCollapse.querySelector('i')?.classList.toggle('bi-layout-sidebar-inset', !active);
  }

  if (sidebarCollapse) {
    applyCollapsedState(readCollapsedPreference());
    sidebarCollapse.addEventListener('click', () => {
      const collapsed = !body.classList.contains('sidebar-is-collapsed');
      applyCollapsedState(collapsed);
      saveCollapsedPreference(collapsed);
    });
  }

  function isPublicMenuMobile() {
    return window.matchMedia('(max-width: 991.98px)').matches;
  }

  function setPublicMenu(open, restoreFocus = false) {
    if (!publicNavbar || !publicMenuToggle || !publicNavLinks) return;
    const active = open && isPublicMenuMobile();
    publicNavbar.classList.toggle('menu-open', active);
    publicMenuToggle.setAttribute('aria-expanded', String(active));
    publicMenuToggle.setAttribute('aria-label', active ? 'Fechar menu' : 'Abrir menu');
    const icon = publicMenuToggle.querySelector('i');
    icon?.classList.toggle('bi-list', !active);
    icon?.classList.toggle('bi-x-lg', active);

    if (active) {
      publicMenuReturnFocus = document.activeElement;
      publicNavLinks.removeAttribute('inert');
      publicNavLinks.setAttribute('aria-hidden', 'false');
      window.requestAnimationFrame(() => publicNavLinks.querySelector('a[href], button:not([disabled])')?.focus());
    } else {
      if (isPublicMenuMobile()) {
        publicNavLinks.setAttribute('inert', '');
        publicNavLinks.setAttribute('aria-hidden', 'true');
      } else {
        publicNavLinks.removeAttribute('inert');
        publicNavLinks.removeAttribute('aria-hidden');
      }
      if (restoreFocus && publicMenuReturnFocus instanceof HTMLElement) publicMenuReturnFocus.focus();
      publicMenuReturnFocus = null;
    }
  }

  publicMenuToggle?.addEventListener('click', event => {
    event.stopPropagation();
    setPublicMenu(!publicNavbar.classList.contains('menu-open'));
  });
  publicNavLinks?.querySelectorAll('a').forEach(link => link.addEventListener('click', () => setPublicMenu(false, true)));
  document.addEventListener('click', event => {
    if (publicNavbar?.classList.contains('menu-open') && !publicNavbar.contains(event.target)) setPublicMenu(false, true);
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      if (sidebar?.classList.contains('open')) setMobileSidebar(false, true);
      if (publicNavbar?.classList.contains('menu-open')) {
        setPublicMenu(false, true);
      }
    }
    if (event.key === 'Tab' && isPublicMenuMobile() && publicNavbar?.classList.contains('menu-open')) {
      const links = [...publicNavLinks.querySelectorAll('a[href], button:not([disabled])')];
      if (!links.length) return;
      const first = links[0];
      const last = links[links.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        publicMenuToggle.focus();
      } else if (event.shiftKey && document.activeElement === publicMenuToggle) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        publicMenuToggle.focus();
      } else if (!event.shiftKey && document.activeElement === publicMenuToggle) {
        event.preventDefault();
        first.focus();
      }
    }
    if (event.key === 'Tab' && isMobileSidebar() && sidebar?.classList.contains('open')) {
      const focusable = [...sidebar.querySelectorAll('a[href], button:not([disabled])')].filter(element => !element.hasAttribute('inert'));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });

  window.addEventListener('resize', () => {
    const restorePublicFocus = isPublicMenuMobile() && publicNavbar?.classList.contains('menu-open');
    if (isMobileSidebar()) {
      body.classList.remove('sidebar-is-collapsed');
      setMobileSidebar(sidebar?.classList.contains('open'));
    } else {
      setMobileSidebar(false);
      applyCollapsedState(readCollapsedPreference());
    }
    setPublicMenu(false, restorePublicFocus);
  });

  if (isMobileSidebar()) setMobileSidebar(false);
  setPublicMenu(false);

  const modalFocusOrigins = new WeakMap();
  document.querySelectorAll('.modal').forEach(modal => {
    modal.addEventListener('show.bs.modal', event => {
      const origin = event.relatedTarget || document.activeElement;
      if (origin instanceof HTMLElement && !modal.contains(origin)) modalFocusOrigins.set(modal, origin);
    });
    modal.addEventListener('shown.bs.modal', () => {
      const field = modal.querySelector('[autofocus], input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled])');
      const fallback = modal.querySelector('.modal-footer button:not([disabled])')
        || modal.querySelector('.modal-header button:not([disabled])')
        || modal.querySelector('a[href]');
      window.requestAnimationFrame(() => (field || fallback)?.focus());
    });
    modal.addEventListener('hidden.bs.modal', () => {
      const origin = modalFocusOrigins.get(modal);
      modalFocusOrigins.delete(modal);
      if (origin?.isConnected) window.requestAnimationFrame(() => origin.focus());
    });
  });

  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (link.target && link.target !== '_self') return;
    if (link.hasAttribute('download') || link.hasAttribute('data-bs-toggle')) return;

    const rawHref = link.getAttribute('href');
    if (!rawHref || rawHref.startsWith('#') || rawHref.startsWith('mailto:') || rawHref.startsWith('tel:')) return;

    let destination;
    try { destination = new URL(link.href, window.location.href); } catch { return; }
    if (destination.origin !== window.location.origin || destination.pathname.startsWith('/api/')) return;
    if (destination.pathname === window.location.pathname && destination.search === window.location.search && destination.hash) return;
    if (reduceMotion.matches) return;

    event.preventDefault();
    body.classList.add('page-leaving');
    window.setTimeout(() => { window.location.href = destination.href; }, 180);
  });

  window.addEventListener('pageshow', () => body.classList.remove('page-leaving'));
})();
