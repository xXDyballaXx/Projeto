(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const page = document.body.dataset.page;
  const ui = window.DivulgaiUI || {};
  let dashboardChart = null;
  let profilePromise = null;
  let refreshPromise = null;

  function setButtonLoading(button, loading, text = 'Processando…') {
    if (ui.setButtonLoading) ui.setButtonLoading(button, loading, text);
    else if (button) button.disabled = loading;
  }

  function showToast(message, type = 'success') {
    const element = $('#appToast');
    if (!element) return;
    if (typeof type === 'boolean') type = type ? 'error' : 'success';
    if (!['success', 'error', 'warning', 'info'].includes(type)) type = 'info';

    const meta = {
      success: ['Tudo certo', 'bi-check2-circle'],
      error: ['Algo deu errado', 'bi-exclamation-circle'],
      warning: ['Atenção', 'bi-exclamation-triangle'],
      info: ['Informação', 'bi-info-circle']
    }[type];

    element.classList.remove('toast-success', 'toast-error', 'toast-warning', 'toast-info');
    element.classList.add(`toast-${type}`);
    $('.toast-title', element).textContent = meta[0];
    $('.toast-body', element).textContent = message;
    const icon = $('.toast-icon i', element);
    icon.className = `bi ${meta[1]}`;
    element.setAttribute('role', type === 'error' ? 'alert' : 'status');
    bootstrap.Toast.getOrCreateInstance(element, { delay: type === 'error' ? 6200 : 4400 }).show();
  }

  async function refreshSession() {
    if (!refreshPromise) {
      refreshPromise = (async () => {
        try {
          const response = await fetch('/api/auth/refresh', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: '{}'
          });
          return response.ok;
        } catch {
          return false;
        } finally {
          refreshPromise = null;
        }
      })();
    }
    return refreshPromise;
  }

  async function api(url, options = {}, allowRefresh = true) {
    const config = { credentials: 'same-origin', ...options };
    if (config.body && !(config.body instanceof FormData)) {
      config.headers = { 'Content-Type': 'application/json', ...(config.headers || {}) };
    }
    const response = await fetch(url, config);
    if (
      response.status === 401
      && allowRefresh
      && !url.startsWith('/api/auth/')
      && !['/login', '/cadastro'].includes(location.pathname)
      && await refreshSession()
    ) {
      return api(url, options, false);
    }
    if (response.status === 401 && !['/login', '/cadastro'].includes(location.pathname)) {
      location.href = '/login';
      throw new Error('Sua sessão expirou. Entre novamente.');
    }
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? data.detail.map(item => item.msg).join(' ') : data.detail;
      throw new Error(detail || 'Não foi possível concluir a operação.');
    }
    return data;
  }

  function getProfile(force = false) {
    if (!profilePromise || force) profilePromise = api('/api/settings/profile');
    return profilePromise;
  }

  async function initUserContext() {
    if (!page || page === 'public') return;
    try {
      const profile = await getProfile();
      const copy = $('.profile-copy');
      if (copy) {
        $('strong', copy).textContent = profile.name;
        $('small', copy).textContent = profile.company;
      }
    } catch {
      // The page-specific request will surface authentication or connectivity errors.
    }
  }

  function formObject(form) {
    return Object.fromEntries(new FormData(form).entries());
  }

  function beginSubmit(event, text) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.checkValidity()) {
      form.classList.add('was-validated');
      showFormValidation(form);
      form.querySelector(':invalid')?.focus();
      return null;
    }
    form.classList.remove('was-validated');
    const button = event.submitter || $('button[type="submit"]', form) || $('button:not([type])', form);
    setButtonLoading(button, true, text);
    return button;
  }

  function validationMessage(field) {
    const label = field.id ? document.querySelector(`label[for="${CSS.escape(field.id)}"]`)?.textContent.trim() : '';
    const name = label ? ` o campo ${label.replace(/\s*\(opcional\)\s*/i, '').toLowerCase()}` : ' este campo';
    if (field.validity.valueMissing) return field.type === 'checkbox' ? 'Confirme esta opção para continuar.' : `Preencha${name}.`;
    if (field.validity.typeMismatch) return field.type === 'email' ? 'Informe um e-mail válido.' : 'Informe um valor no formato esperado.';
    if (field.validity.tooShort) return `Use pelo menos ${field.minLength} caracteres.`;
    if (field.validity.tooLong) return `Use no máximo ${field.maxLength} caracteres.`;
    if (field.validity.rangeUnderflow) return `O valor mínimo é ${field.min}.`;
    if (field.validity.rangeOverflow) return `O valor máximo é ${field.max}.`;
    if (field.validity.stepMismatch || field.validity.badInput) return 'Informe um valor válido.';
    if (field.validity.patternMismatch) return 'Revise o formato informado.';
    return field.validationMessage || 'Revise este campo.';
  }

  function renderFieldValidation(field) {
    if (!field.willValidate) return;
    const feedbackId = `${field.id || field.name}-feedback`;
    let feedback = document.getElementById(feedbackId);
    const describedBy = new Set((field.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean));
    if (field.validity.valid) {
      field.removeAttribute('aria-invalid');
      feedback?.remove();
      describedBy.delete(feedbackId);
      if (describedBy.size) field.setAttribute('aria-describedby', [...describedBy].join(' '));
      else field.removeAttribute('aria-describedby');
      return;
    }
    field.setAttribute('aria-invalid', 'true');
    if (!feedback) {
      feedback = document.createElement('div');
      feedback.id = feedbackId;
      feedback.className = 'invalid-feedback';
      feedback.setAttribute('role', 'alert');
      if (field.type === 'checkbox') field.parentElement.append(feedback);
      else field.insertAdjacentElement('afterend', feedback);
    }
    feedback.textContent = validationMessage(field);
    describedBy.add(feedbackId);
    field.setAttribute('aria-describedby', [...describedBy].join(' '));
  }

  function showFormValidation(form) {
    [...form.elements].forEach(field => {
      if (field instanceof HTMLInputElement || field instanceof HTMLSelectElement || field instanceof HTMLTextAreaElement) renderFieldValidation(field);
    });
  }

  function initFormValidation() {
    $$('form[novalidate]').forEach(form => {
      form.addEventListener('input', event => {
        if (form.classList.contains('was-validated')) renderFieldValidation(event.target);
      });
      form.addEventListener('change', event => {
        if (form.classList.contains('was-validated')) renderFieldValidation(event.target);
      });
      form.addEventListener('reset', () => window.setTimeout(() => {
        form.classList.remove('was-validated');
        $$('.invalid-feedback', form).forEach(item => item.remove());
        $$('[aria-invalid="true"]', form).forEach(field => field.removeAttribute('aria-invalid'));
        $$('[aria-describedby]', form).forEach(field => {
          const ids = field.getAttribute('aria-describedby').split(/\s+/).filter(id => id && !id.endsWith('-feedback'));
          if (ids.length) field.setAttribute('aria-describedby', ids.join(' '));
          else field.removeAttribute('aria-describedby');
        });
      }));
    });
  }

  function confirmAction(message, options = {}) {
    const modalElement = $('#confirmModal');
    const acceptButton = $('#confirmModalAccept');
    if (!modalElement || !acceptButton) return Promise.resolve(window.confirm(message));

    const { title = 'Confirmar ação', confirmText = 'Confirmar', danger = false } = options;
    $('#confirmModalTitle').textContent = title;
    $('#confirmModalMessage').textContent = message;
    acceptButton.textContent = confirmText;
    acceptButton.className = `btn ${danger ? 'btn-danger' : 'btn-primary'}`;
    const icon = $('#confirmModalIcon i');
    icon.className = `bi ${danger ? 'bi-exclamation-triangle' : 'bi-question-lg'}`;
    const modal = bootstrap.Modal.getOrCreateInstance(modalElement);

    return new Promise(resolve => {
      let accepted = false;
      const onAccept = () => {
        accepted = true;
        modal.hide();
      };
      const onHidden = () => {
        acceptButton.removeEventListener('click', onAccept);
        resolve(accepted);
      };
      acceptButton.addEventListener('click', onAccept);
      modalElement.addEventListener('hidden.bs.modal', onHidden, { once: true });
      modal.show();
    });
  }

  const statusLabels = {
    draft: 'Rascunho', review: 'Em revisão', scheduled: 'Agendada', sending: 'Enviando', sent: 'Concluída',
    simulated: 'Simulada', cancelled: 'Cancelada', failed: 'Falhou', pending: 'Pendente', queued: 'Na fila', running: 'Processando', completed: 'Concluída', ignored: 'Ignorada',
    approved: 'Aprovado', rejected: 'Rejeitado',
    delivered: 'Entregue', read: 'Lida', published: 'Publicada', blocked: 'Bloqueado', active: 'Ativo', inactive: 'Inativo',
    whatsapp: 'WhatsApp', facebook: 'Facebook', instagram: 'Instagram', ai: 'IA'
  };

  function badge(value, type = 'status-badge') {
    const normalized = String(value ?? '').toLowerCase();
    const success = ['sent', 'delivered', 'read', 'published', 'active'];
    const danger = ['failed', 'cancelled', 'blocked'];
    const warning = ['scheduled', 'review', 'simulated', 'pending', 'queued', 'sending'];
    const element = document.createElement('span');
    element.className = type;
    if (success.includes(normalized)) element.classList.add('success');
    if (danger.includes(normalized)) element.classList.add('danger');
    if (warning.includes(normalized)) element.classList.add('warning');
    element.textContent = statusLabels[normalized] || value || '—';
    return element;
  }

  function cell(row, value, className = '') {
    const td = document.createElement('td');
    if (className) td.className = className;
    if (value instanceof Node) td.append(value);
    else td.textContent = value ?? '—';
    row.append(td);
    return td;
  }

  function formatDate(value) {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Data inválida';
    return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(date);
  }

  function localDateTimeInZone(value, timeZone) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const parts = new Intl.DateTimeFormat('sv-SE', {
      timeZone,
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
    }).formatToParts(date).reduce((result, item) => ({ ...result, [item.type]: item.value }), {});
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
  }

  function zonedDateTimeToISOString(value, timeZone) {
    if (!value) return null;
    const [datePart, timePart] = value.split('T');
    const [year, month, day] = datePart.split('-').map(Number);
    const [hour, minute] = timePart.split(':').map(Number);
    const desiredUtc = Date.UTC(year, month - 1, day, hour, minute);
    let candidate = desiredUtc;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const rendered = localDateTimeInZone(new Date(candidate).toISOString(), timeZone);
      const [renderedDate, renderedTime] = rendered.split('T');
      const [renderedYear, renderedMonth, renderedDay] = renderedDate.split('-').map(Number);
      const [renderedHour, renderedMinute] = renderedTime.split(':').map(Number);
      const renderedUtc = Date.UTC(renderedYear, renderedMonth - 1, renderedDay, renderedHour, renderedMinute);
      candidate += desiredUtc - renderedUtc;
    }
    return new Date(candidate).toISOString();
  }

  function emptyState(icon, title, description, compact = false) {
    const root = document.createElement('div');
    root.className = `empty-state${compact ? ' compact' : ''}`;
    const visual = document.createElement('span');
    visual.className = 'empty-state-icon';
    visual.setAttribute('aria-hidden', 'true');
    visual.innerHTML = `<i class="bi ${icon}"></i>`;
    const heading = document.createElement('h3');
    heading.textContent = title;
    const text = document.createElement('p');
    text.textContent = description;
    root.append(visual, heading, text);
    return root;
  }

  function emptyTable(tableBody, columns, icon, title, description) {
    const row = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = columns;
    td.append(emptyState(icon, title, description, true));
    row.append(td);
    tableBody.replaceChildren(row);
  }

  async function initLogout() {
    const button = $('#logout');
    if (!button) return;
    button.addEventListener('click', async () => {
      setButtonLoading(button, true, 'Saindo…');
      try {
        await api('/api/auth/logout', { method: 'POST' });
        location.href = '/';
      } catch (error) {
        showToast(error.message, 'error');
        setButtonLoading(button, false);
      }
    });
  }

  function initAuth() {
    $('#loginForm')?.addEventListener('submit', async event => {
      const button = beginSubmit(event, 'Entrando…');
      if (!button) return;
      try {
        await api('/api/auth/login', { method: 'POST', body: JSON.stringify(formObject(event.currentTarget)) });
        location.href = '/dashboard';
      } catch (error) {
        showToast(error.message, 'error');
        setButtonLoading(button, false);
      }
    });

    $('#forgotPassword')?.addEventListener('click', async event => {
      const button = event.currentTarget;
      setButtonLoading(button, true, 'Solicitando…');
      try {
        const data = await api('/api/auth/forgot-password', { method: 'POST' });
        showToast(data.message, 'info');
      } catch (error) {
        showToast(error.message, 'error');
      } finally {
        setButtonLoading(button, false);
      }
    });

    $('#registerForm')?.addEventListener('submit', async event => {
      const button = beginSubmit(event, 'Criando conta…');
      if (!button) return;
      const data = formObject(event.currentTarget);
      if (data.password !== data.password_confirmation) {
        showToast('As senhas informadas não coincidem.', 'warning');
        $('#registerPasswordConfirmation')?.focus();
        setButtonLoading(button, false);
        return;
      }
      data.accept_terms = data.accept_terms === 'on';
      try {
        await api('/api/auth/register', { method: 'POST', body: JSON.stringify(data) });
        location.href = '/dashboard';
      } catch (error) {
        showToast(error.message, 'error');
        setButtonLoading(button, false);
      }
    });
  }

  async function initDashboard() {
    const stats = $('#stats');
    if (!stats) return;
    const labels = {
      contacts: ['bi-people', 'Contatos'], campaigns: ['bi-megaphone', 'Campanhas'], scheduled: ['bi-calendar-check', 'Agendadas'],
      sent_campaigns: ['bi-send-check', 'Enviadas'], delivered: ['bi-check2-circle', 'Entregues'], errors: ['bi-exclamation-triangle', 'Erros'],
      publications: ['bi-share', 'Publicações'], clicks: ['bi-cursor', 'Cliques']
    };
    try {
      const data = await api('/api/dashboard');
      const cards = Object.entries(data.totals || {}).map(([key, value], index) => {
        const meta = labels[key] || ['bi-activity', key.replaceAll('_', ' ')];
        const col = document.createElement('div');
        col.className = 'col-6 col-md-4 col-xl-3';
        col.dataset.reveal = 'up';
        col.style.setProperty('--reveal-delay', `${index * 45}ms`);
        const card = document.createElement('article');
        card.className = 'stat-card';
        const icon = document.createElement('i');
        icon.className = `bi ${meta[0]}`;
        icon.setAttribute('aria-hidden', 'true');
        const strong = document.createElement('strong');
        strong.textContent = value;
        const label = document.createElement('span');
        label.textContent = meta[1];
        const context = document.createElement('small');
        context.textContent = 'Visão atual';
        card.append(icon, strong, label, context);
        col.append(card);
        return col;
      });
      stats.replaceChildren(...cards);
      stats.setAttribute('aria-busy', 'false');

      const activities = $('#activities');
      activities.replaceChildren();
      (data.activities || []).forEach(item => {
        const entry = document.createElement('div');
        entry.className = 'activity-item';
        const title = document.createElement('div');
        title.textContent = String(item.action || 'Atividade').replaceAll('.', ' · ');
        const date = document.createElement('small');
        date.textContent = formatDate(item.date);
        entry.append(title, date);
        activities.append(entry);
      });
      if (!data.activities?.length) activities.append(emptyState('bi-activity', 'Nenhuma atividade recente', 'As próximas ações registradas aparecerão aqui.', true));
      activities.setAttribute('aria-busy', 'false');

      const canvas = $('#performanceChart');
      if (canvas && window.Chart) {
        dashboardChart?.destroy();
        dashboardChart = new Chart(canvas, {
          type: 'bar',
          data: {
            labels: data.chart?.labels || [],
            datasets: [{ data: data.chart?.values || [], backgroundColor: ['#5b6cff', '#8b5cf6', '#22d3ee', '#22c55e'], borderColor: 'transparent', borderRadius: 8, borderSkipped: false, maxBarThickness: 64 }]
          },
          options: {
            responsive: true, maintainAspectRatio: false,
            animation: { duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 550 },
            plugins: { legend: { display: false }, tooltip: { backgroundColor: '#1b2338', titleColor: '#f8fafc', bodyColor: '#aab2c5', borderColor: 'rgba(255,255,255,.12)', borderWidth: 1, padding: 12 } },
            scales: {
              y: { beginAtZero: true, ticks: { color: '#7e879e', precision: 0 }, grid: { color: 'rgba(255,255,255,.055)' }, border: { display: false } },
              x: { ticks: { color: '#aab2c5' }, grid: { display: false }, border: { color: 'rgba(255,255,255,.08)' } }
            }
          }
        });
      }
    } catch (error) {
      stats.setAttribute('aria-busy', 'false');
      stats.replaceChildren(emptyState('bi-exclamation-triangle', 'Não foi possível carregar os indicadores', error.message));
      const activities = $('#activities');
      activities?.setAttribute('aria-busy', 'false');
      activities?.replaceChildren(emptyState('bi-exclamation-triangle', 'Atividades indisponíveis', 'Tente atualizar a página em instantes.', true));
      showToast(error.message, 'error');
    }
  }

  function initContacts() {
    const table = $('#contactsTable');
    if (!table) return;
    let currentQuery = '';
    let searchTimer;
    let contactRequest;
    let contactsById = new Map();
    const consentChannels = ['whatsapp', 'facebook', 'instagram'];

    function activeConsentChannels(contact) {
      return new Set((contact?.consents || []).filter(item => item.is_granted && !item.revoked_at).map(item => item.channel));
    }

    function openContactEditor(contact = null) {
      const form = $('#contactForm');
      form.reset();
      form.classList.remove('was-validated');
      form.elements.contact_id.value = contact?.id || '';
      $('#contactModalTitle').textContent = contact ? 'Editar contato' : 'Novo contato';
      const submit = $('button[type="submit"]', form);
      submit.innerHTML = contact ? '<i class="bi bi-check2" aria-hidden="true"></i> Salvar alterações' : '<i class="bi bi-check2" aria-hidden="true"></i> Salvar contato';
      if (contact) {
        form.elements.name.value = contact.name || '';
        form.elements.phone.value = contact.phone || '';
        form.elements.email.value = contact.email || '';
        form.elements.source.value = contact.source || 'manual';
        form.elements.tags.value = (contact.tags || []).join(', ');
        const active = activeConsentChannels(contact);
        consentChannels.forEach(channel => {
          form.elements[channel].checked = active.has(channel);
          form.elements[channel].disabled = contact.permanently_blocked;
        });
      } else {
        consentChannels.forEach(channel => { form.elements[channel].disabled = false; });
      }
      bootstrap.Modal.getOrCreateInstance($('#contactModal')).show();
    }

    $('#newContactButton')?.addEventListener('click', () => openContactEditor());

    async function loadContacts(query = currentQuery) {
      currentQuery = query;
      contactRequest?.abort();
      contactRequest = new AbortController();
      try {
        const contacts = await api(`/api/contacts?q=${encodeURIComponent(query)}&limit=500`, { signal: contactRequest.signal });
        contactsById = new Map(contacts.map(contact => [contact.id, contact]));
        table.replaceChildren();
        contacts.forEach(contact => {
          const row = document.createElement('tr');
          const check = document.createElement('input');
          check.type = 'checkbox';
          check.className = 'form-check-input contact-select';
          check.value = contact.id;
          check.setAttribute('aria-label', `Selecionar ${contact.name}`);
          cell(row, check);

          const identity = document.createElement('div');
          const strong = document.createElement('strong');
          strong.textContent = contact.name;
          const email = document.createElement('small');
          email.className = 'd-block text-muted';
          email.textContent = contact.email || 'Sem e-mail';
          identity.append(strong, email);
          cell(row, identity);
          cell(row, contact.phone);

          const consents = document.createElement('div');
          contact.consents.filter(item => item.is_granted && !item.revoked_at).forEach(item => consents.append(badge(item.channel, 'channel-badge me-1')));
          if (!consents.children.length) consents.textContent = 'Sem consentimento';
          cell(row, consents);

          const contactStatus = contact.permanently_blocked ? 'blocked' : contact.is_active ? 'active' : 'inactive';
          cell(row, badge(contactStatus));

          const actions = document.createElement('div');
          actions.className = 'table-actions';
          const edit = document.createElement('button');
          edit.type = 'button';
          edit.className = 'btn btn-sm btn-outline-primary';
          edit.innerHTML = '<i class="bi bi-pencil" aria-hidden="true"></i><span class="visually-hidden"> Editar</span>';
          edit.title = `Editar ${contact.name}`;
          edit.setAttribute('aria-label', `Editar ${contact.name}`);
          edit.addEventListener('click', () => openContactEditor(contact));

          const exportData = document.createElement('a');
          exportData.className = 'btn btn-sm btn-light';
          exportData.href = `/api/contacts/${contact.id}/export`;
          exportData.download = '';
          exportData.innerHTML = '<i class="bi bi-download" aria-hidden="true"></i><span class="visually-hidden"> Exportar dados</span>';
          exportData.title = `Exportar dados de ${contact.name}`;
          exportData.setAttribute('aria-label', `Exportar dados de ${contact.name}`);

          const toggle = document.createElement('button');
          toggle.type = 'button';
          toggle.className = 'btn btn-sm btn-light';
          toggle.textContent = contact.is_active ? 'Inativar' : 'Ativar';
          toggle.disabled = contact.permanently_blocked;
          toggle.setAttribute('aria-label', `${contact.is_active ? 'Inativar' : 'Ativar'} ${contact.name}`);
          toggle.addEventListener('click', async () => {
            setButtonLoading(toggle, true, contact.is_active ? 'Inativando…' : 'Ativando…');
            try {
              await api(`/api/contacts/${contact.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: !contact.is_active }) });
              showToast(`Contato ${contact.is_active ? 'inativado' : 'ativado'}.`);
              await loadContacts();
            } catch (error) {
              showToast(error.message, 'error');
              setButtonLoading(toggle, false);
            }
          });
          const block = document.createElement('button');
          block.type = 'button';
          block.className = 'btn btn-sm btn-outline-warning';
          block.innerHTML = '<i class="bi bi-slash-circle" aria-hidden="true"></i><span class="visually-hidden"> Bloquear permanentemente</span>';
          block.title = contact.permanently_blocked ? 'Contato já bloqueado permanentemente' : `Bloquear permanentemente ${contact.name}`;
          block.setAttribute('aria-label', block.title);
          block.disabled = contact.permanently_blocked;
          block.addEventListener('click', async () => {
            const confirmed = await confirmAction(`Bloquear permanentemente ${contact.name} e revogar todos os consentimentos? Esta ação não pode ser desfeita pela interface.`, { title: 'Bloquear contato', confirmText: 'Bloquear', danger: true });
            if (!confirmed) return;
            setButtonLoading(block, true, '');
            try {
              await api(`/api/contacts/${contact.id}`, { method: 'PATCH', body: JSON.stringify({ permanently_blocked: true }) });
              showToast('Contato bloqueado e consentimentos revogados.', 'warning');
              await loadContacts();
            } catch (error) {
              showToast(error.message, 'error');
              setButtonLoading(block, false);
            }
          });
          const remove = document.createElement('button');
          remove.type = 'button';
          remove.className = 'btn btn-sm btn-outline-danger';
          remove.innerHTML = '<i class="bi bi-trash" aria-hidden="true"></i><span class="visually-hidden">Excluir</span>';
          remove.title = 'Excluir contato';
          remove.addEventListener('click', async () => {
            const confirmed = await confirmAction(`Excluir ${contact.name} e todos os consentimentos associados?`, { title: 'Excluir contato', confirmText: 'Excluir', danger: true });
            if (!confirmed) return;
            setButtonLoading(remove, true, '');
            try {
              await api(`/api/contacts/${contact.id}`, { method: 'DELETE' });
              showToast('Contato excluído.');
              await Promise.all([loadContacts(), loadContactLists()]);
            } catch (error) {
              showToast(error.message, 'error');
              setButtonLoading(remove, false);
            }
          });
          actions.append(edit, exportData, toggle, block, remove);
          cell(row, actions, 'text-end');
          table.append(row);
        });
        if (!contacts.length) emptyTable(table, 6, 'bi-people', query ? 'Nenhum contato encontrado' : 'Nenhum contato cadastrado', query ? 'Tente buscar por outro nome, telefone ou e-mail.' : 'Cadastre seu primeiro contato para começar a organizar a base.');
        const selectAll = $('#selectAllContacts');
        if (selectAll) { selectAll.checked = false; selectAll.indeterminate = false; }
      } catch (error) {
        if (error.name !== 'AbortError') {
          emptyTable(table, 6, 'bi-exclamation-triangle', 'Não foi possível carregar os contatos', error.message);
          showToast(error.message, 'error');
        }
      }
    }

    $('#contactSearch')?.addEventListener('input', event => {
      clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => loadContacts(event.target.value.trim()), 300);
    });

    $('#contactForm')?.addEventListener('submit', async event => {
      const form = event.currentTarget;
      const button = beginSubmit(event, 'Salvando…');
      if (!button) return;
      const data = formObject(form);
      const contactId = Number(data.contact_id) || null;
      const selectedConsents = new Set(consentChannels.filter(channel => form.elements[channel].checked));
      const tags = String(data.tags || '').split(',').map(item => item.trim()).filter(Boolean);
      const payload = { name: data.name, phone: data.phone, email: data.email || null, source: data.source, tags };
      if (!contactId) payload.consents = [...selectedConsents].map(channel => ({ channel, is_granted: true, source: data.source }));
      try {
        if (contactId) {
          const original = contactsById.get(contactId);
          await api(`/api/contacts/${contactId}`, { method: 'PATCH', body: JSON.stringify(payload) });
          const previous = activeConsentChannels(original);
          const changes = consentChannels.filter(channel => previous.has(channel) !== selectedConsents.has(channel));
          await Promise.all(changes.map(channel => api(`/api/contacts/${contactId}/consents`, {
            method: 'POST',
            body: JSON.stringify({ channel, is_granted: selectedConsents.has(channel), source: data.source })
          })));
        } else {
          await api('/api/contacts', { method: 'POST', body: JSON.stringify(payload) });
        }
        bootstrap.Modal.getInstance($('#contactModal'))?.hide();
        form.reset();
        showToast(contactId ? 'Contato e consentimentos atualizados.' : 'Contato salvo com sucesso.');
        await loadContacts(currentQuery);
      } catch (error) {
        showToast(error.message, 'error');
      } finally {
        setButtonLoading(button, false);
      }
    });

    $('#csvFile')?.addEventListener('change', async event => {
      const file = event.target.files?.[0];
      if (!file) return;
      event.target.disabled = true;
      const form = new FormData();
      form.append('file', file);
      showToast('Importando o arquivo…', 'info');
      try {
        const data = await api('/api/contacts/import/csv', { method: 'POST', body: form });
        const failed = data.error_rows?.length || 0;
        const message = `${data.created} contatos importados; ${data.skipped} duplicados ignorados${failed ? `; ${failed} linhas com erro (${data.error_rows.join(', ')})` : ''}.`;
        showToast(message, failed ? 'warning' : 'success');
        await loadContacts('');
      } catch (error) {
        showToast(error.message, 'error');
      } finally {
        event.target.disabled = false;
        event.target.value = '';
      }
    });

    $('#csvFileButton')?.addEventListener('click', () => $('#csvFile')?.click());

    $('#selectAllContacts')?.addEventListener('change', event => $$('.contact-select').forEach(item => { item.checked = event.target.checked; }));

    async function renderListContactOptions(preselectedIds = null) {
      const root = $('#listContactOptions');
      if (!root) return;
      root.replaceChildren();
      try {
        const contacts = await api('/api/contacts?limit=500');
        const preselected = new Set(preselectedIds || $$('.contact-select:checked').map(item => Number(item.value)));
        if (!contacts.length) {
          root.append(emptyState('bi-person-plus', 'Nenhum contato disponível', 'Cadastre ao menos um contato antes de criar uma lista.', true));
          return;
        }
        contacts.forEach(contact => {
          const label = document.createElement('label');
          label.className = 'list-contact-option';
          const input = document.createElement('input');
          input.type = 'checkbox';
          input.className = 'form-check-input list-contact-select';
          input.value = contact.id;
          input.checked = preselected.has(contact.id);
          const copy = document.createElement('span');
          const name = document.createElement('strong');
          name.textContent = contact.name;
          const phone = document.createElement('small');
          phone.className = 'd-block text-muted';
          phone.textContent = contact.phone;
          copy.append(name, phone);
          label.append(input, copy);
          root.append(label);
        });
      } catch (error) {
        root.append(emptyState('bi-exclamation-triangle', 'Não foi possível carregar os contatos', error.message, true));
      }
    }

    $('#openListModal')?.addEventListener('click', async () => {
      const form = $('#listForm');
      form.reset();
      form.elements.list_id.value = '';
      $('#listModalTitle').textContent = 'Criar lista de contatos';
      $('button[type="submit"]', form).innerHTML = '<i class="bi bi-check2" aria-hidden="true"></i> Criar lista';
      const feedback = $('#listFormFeedback');
      feedback?.classList.add('d-none');
      if (feedback) feedback.textContent = '';
      bootstrap.Modal.getOrCreateInstance($('#listModal')).show();
      await renderListContactOptions();
    });

    $('#toggleListContacts')?.addEventListener('click', event => {
      const checks = $$('.list-contact-select');
      const selectAll = checks.some(item => !item.checked);
      checks.forEach(item => { item.checked = selectAll; });
      event.currentTarget.textContent = selectAll ? 'Desmarcar todos' : 'Selecionar todos';
    });

    $('#listForm')?.addEventListener('submit', async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const feedback = $('#listFormFeedback');
      feedback.classList.add('d-none');
      if (!form.checkValidity()) {
        form.classList.add('was-validated');
        form.querySelector(':invalid')?.focus();
        return;
      }
      const ids = $$('.list-contact-select:checked').map(item => Number(item.value));
      if (!ids.length) {
        feedback.textContent = 'Selecione ao menos um contato para a lista.';
        feedback.classList.remove('d-none');
        return;
      }
      const button = event.submitter;
      setButtonLoading(button, true, 'Criando…');
      const data = formObject(form);
      const listId = Number(data.list_id) || null;
      try {
        await api(listId ? `/api/contacts/lists/${listId}` : '/api/contacts/lists', { method: listId ? 'PATCH' : 'POST', body: JSON.stringify({ name: data.name, description: data.description || null, contact_ids: ids }) });
        bootstrap.Modal.getInstance($('#listModal'))?.hide();
        form.reset();
        showToast(listId ? 'Lista atualizada com sucesso.' : 'Lista criada com sucesso.');
        await loadContactLists();
      } catch (error) {
        feedback.textContent = error.message;
        feedback.classList.remove('d-none');
      } finally {
        setButtonLoading(button, false);
      }
    });

    async function loadContactLists() {
      const root = $('#contactLists');
      if (!root) return;
      try {
        const lists = await api('/api/contacts/lists/all');
        root.replaceChildren();
        $('#contactListsCount').textContent = `${lists.length} ${lists.length === 1 ? 'lista' : 'listas'}`;
        lists.forEach((item, index) => {
          const col = document.createElement('div');
          col.className = 'col-md-6 col-xl-4';
          col.dataset.reveal = 'up';
          col.style.setProperty('--reveal-delay', `${index * 50}ms`);
          const card = document.createElement('article');
          card.className = 'list-card';
          const name = document.createElement('strong');
          name.textContent = item.name;
          const count = document.createElement('small');
          count.textContent = `${item.contacts} ${item.contacts === 1 ? 'contato' : 'contatos'}`;
          const description = document.createElement('p');
          description.className = 'small mb-0 mt-2 text-muted';
          description.textContent = item.description || 'Sem descrição';
          const actions = document.createElement('div');
          actions.className = 'table-actions mt-3';
          const edit = document.createElement('button');
          edit.type = 'button';
          edit.className = 'btn btn-sm btn-outline-primary';
          edit.innerHTML = '<i class="bi bi-pencil" aria-hidden="true"></i> Editar';
          edit.setAttribute('aria-label', `Editar lista ${item.name}`);
          edit.addEventListener('click', async () => {
            setButtonLoading(edit, true, 'Abrindo…');
            try {
              const detail = await api(`/api/contacts/lists/${item.id}`);
              const form = $('#listForm');
              form.reset();
              form.elements.list_id.value = detail.id;
              form.elements.name.value = detail.name;
              form.elements.description.value = detail.description || '';
              $('#listModalTitle').textContent = 'Editar lista de contatos';
              $('button[type="submit"]', form).innerHTML = '<i class="bi bi-check2" aria-hidden="true"></i> Salvar lista';
              bootstrap.Modal.getOrCreateInstance($('#listModal')).show();
              await renderListContactOptions(detail.contact_ids);
            } catch (error) {
              showToast(error.message, 'error');
            } finally {
              setButtonLoading(edit, false);
            }
          });
          const remove = document.createElement('button');
          remove.type = 'button';
          remove.className = 'btn btn-sm btn-outline-danger';
          remove.innerHTML = '<i class="bi bi-trash" aria-hidden="true"></i><span class="visually-hidden"> Excluir</span>';
          remove.setAttribute('aria-label', `Excluir lista ${item.name}`);
          remove.addEventListener('click', async () => {
            const confirmed = await confirmAction(`Excluir a lista "${item.name}"? Os contatos não serão apagados.`, { title: 'Excluir lista', confirmText: 'Excluir', danger: true });
            if (!confirmed) return;
            setButtonLoading(remove, true, '');
            try {
              await api(`/api/contacts/lists/${item.id}`, { method: 'DELETE' });
              showToast('Lista excluída.');
              await loadContactLists();
            } catch (error) {
              showToast(error.message, 'error');
              setButtonLoading(remove, false);
            }
          });
          actions.append(edit, remove);
          card.append(name, count, description, actions);
          col.append(card);
          root.append(col);
        });
        if (!lists.length) {
          const col = document.createElement('div');
          col.className = 'col-12';
          col.append(emptyState('bi-collection', 'Nenhuma lista criada', 'Selecione contatos e crie uma lista para usar nas campanhas.'));
          root.append(col);
        }
      } catch (error) {
        root.replaceChildren(emptyState('bi-exclamation-triangle', 'Não foi possível carregar as listas', error.message));
      }
    }

    loadContacts();
    loadContactLists();
  }

  function initCampaigns() {
    const table = $('#campaignsTable');
    if (!table) return;
    let listsPromise = null;
    let templatesPromise = null;
    let campaignsById = new Map();
    const timezonePromise = getProfile().then(profile => profile.timezone || 'America/Sao_Paulo').catch(() => 'America/Sao_Paulo');

    function showCampaignPreview(campaign) {
      $('#campaignPreviewTitle').textContent = `Prévia · ${campaign.internal_name}`;
      $('#campaignPreviewChannel').textContent = statusLabels[campaign.channel] || campaign.channel;
      $('#campaignPreviewHeading').textContent = campaign.title;
      $('#campaignPreviewBody').textContent = campaign.body;
      $('#campaignPreviewCta').textContent = campaign.call_to_action || '';
      const link = $('#campaignPreviewLink');
      link.textContent = campaign.link_url || '';
      link.href = campaign.link_url || '#';
      link.classList.toggle('d-none', !campaign.link_url);
      const media = $('#campaignPreviewMedia');
      media.replaceChildren();
      if (campaign.image_path) {
        const image = document.createElement('img');
        image.src = campaign.image_path;
        image.alt = `Imagem da campanha ${campaign.internal_name}`;
        image.className = 'img-fluid rounded-3';
        media.append(image);
      } else if (campaign.video_path) {
        const video = document.createElement('video');
        video.src = campaign.video_path;
        video.controls = true;
        video.className = 'w-100 rounded-3';
        video.setAttribute('aria-label', `Vídeo da campanha ${campaign.internal_name}`);
        media.append(video);
      }
      bootstrap.Modal.getOrCreateInstance($('#campaignPreviewModal')).show();
    }

    async function loadTasks() {
      const tasksTable = $('#campaignTasksTable');
      if (!tasksTable) return;
      try {
        const tasks = await api('/api/campaigns/tasks/all');
        tasksTable.replaceChildren();
        tasks.forEach(item => {
          const row = document.createElement('tr');
          const campaign = campaignsById.get(item.campaign_id);
          cell(row, campaign?.internal_name || `Campanha #${item.campaign_id || '—'}`);
          cell(row, formatDate(item.execute_at));
          cell(row, badge(item.status));
          cell(row, item.attempts);
          const result = item.result?.reason || item.result?.message || (item.result?.status ? statusLabels[item.result.status] || item.result.status : item.error ? 'Falha registrada' : '—');
          cell(row, result);
          tasksTable.append(row);
        });
        if (!tasks.length) emptyTable(tasksTable, 5, 'bi-calendar2-check', 'Nenhum agendamento registrado', 'Ao agendar ou enviar uma campanha, a tarefa aparecerá aqui.');
      } catch (error) {
        emptyTable(tasksTable, 5, 'bi-exclamation-triangle', 'Não foi possível carregar as tarefas', error.message);
      }
    }

    async function loadLists(force = false) {
      const select = $('#campaignList');
      if (!select) return [];
      if (listsPromise && !force) return listsPromise;
      listsPromise = (async () => {
        const lists = await api('/api/contacts/lists/all');
        const empty = document.createElement('option');
        empty.value = '';
        empty.textContent = 'Nenhuma';
        select.replaceChildren(empty);
        lists.forEach(item => {
          const option = document.createElement('option');
          option.value = item.id;
          option.textContent = `${item.name} (${item.contacts})`;
          select.append(option);
        });
        return lists;
      })().catch(error => {
        listsPromise = null;
        showToast(error.message, 'error');
        return [];
      });
      return listsPromise;
    }

    async function loadTemplates(force = false) {
      const select = $('#campaignTemplate');
      if (!select) return [];
      if (templatesPromise && !force) return templatesPromise;
      templatesPromise = (async () => {
        const templates = await api('/api/integrations/whatsapp/message-templates');
        const empty = document.createElement('option');
        empty.value = '';
        empty.textContent = 'Selecione um template aprovado';
        select.replaceChildren(empty);
        templates.forEach(template => {
          const option = document.createElement('option');
          option.value = template.id;
          option.disabled = template.status !== 'approved';
          option.textContent = `${template.name} · ${template.language} (${statusLabels[template.status] || template.status})`;
          select.append(option);
        });
        return templates;
      })().catch(error => {
        templatesPromise = null;
        showToast(`Não foi possível carregar os templates: ${error.message}`, 'error');
        return [];
      });
      return templatesPromise;
    }

    function updateCampaignChannelFields() {
      const whatsapp = $('#campaignChannel')?.value === 'whatsapp';
      $('#campaignTemplateField')?.classList.toggle('d-none', !whatsapp);
      if (!whatsapp && $('#campaignTemplate')) $('#campaignTemplate').value = '';
    }

    function campaignDateTimeLocal(value, timeZone = 'America/Sao_Paulo') {
      return localDateTimeInZone(value, timeZone);
    }

    async function openCampaignEditor(campaign = null) {
      const form = $('#campaignEditorForm');
      if (!form) return;
      await Promise.all([loadLists(), loadTemplates()]);
      form.reset();
      form.classList.remove('was-validated');
      form.elements.campaign_id.value = campaign?.id || '';
      $('#campaignModalTitle').textContent = campaign ? 'Editar campanha' : 'Nova campanha';
      $('#campaignSubmitButton').innerHTML = campaign ? '<i class="bi bi-check2" aria-hidden="true"></i> Salvar alterações' : '<i class="bi bi-check2" aria-hidden="true"></i> Salvar campanha';
      if (campaign) {
        form.elements.internal_name.value = campaign.internal_name || '';
        form.elements.title.value = campaign.title || '';
        form.elements.body.value = campaign.body || '';
        form.elements.channel.value = campaign.channel;
        form.elements.contact_list_id.value = campaign.contact_list_id || '';
        form.elements.message_template_id.value = campaign.message_template_id || '';
        form.elements.scheduled_at.value = campaignDateTimeLocal(campaign.scheduled_at, campaign.timezone || 'America/Sao_Paulo');
        form.elements.call_to_action.value = campaign.call_to_action || '';
        form.elements.link_url.value = campaign.link_url || '';
      }
      updateCampaignChannelFields();
      bootstrap.Modal.getOrCreateInstance($('#campaignModal')).show();
    }

    $('#newCampaignButton')?.addEventListener('click', () => openCampaignEditor());
    $('#campaignChannel')?.addEventListener('change', updateCampaignChannelFields);

    $('#campaignEditorForm')?.addEventListener('submit', async event => {
      const button = beginSubmit(event, 'Salvando…');
      if (!button) return;
      const form = event.currentTarget;
      const data = formObject(form);
      const companyTimezone = await timezonePromise;
      const campaignId = data.campaign_id;
      const media = form.elements.media.files?.[0];
      const payload = {
        internal_name: data.internal_name, title: data.title, body: data.body, channel: data.channel,
        timezone: companyTimezone, contact_list_id: data.contact_list_id ? Number(data.contact_list_id) : null,
        message_template_id: data.message_template_id ? Number(data.message_template_id) : null,
        scheduled_at: data.scheduled_at ? zonedDateTimeToISOString(data.scheduled_at, companyTimezone) : null,
        call_to_action: data.call_to_action || null, link_url: data.link_url || null
      };
      try {
        const campaign = await api(campaignId ? `/api/campaigns/${campaignId}` : '/api/campaigns', { method: campaignId ? 'PATCH' : 'POST', body: JSON.stringify(payload) });
        form.elements.campaign_id.value = campaign.id;
        if (media) {
          const upload = new FormData();
          upload.append('file', media);
          try {
            await api(`/api/campaigns/${campaign.id}/upload`, { method: 'POST', body: upload });
          } catch (uploadError) {
            showToast(`A campanha foi salva, mas a mídia não foi enviada: ${uploadError.message}`, 'warning');
            await loadCampaigns();
            return;
          }
        }
        bootstrap.Modal.getInstance($('#campaignModal'))?.hide();
        form.reset();
        showToast(campaignId ? 'Campanha atualizada com sucesso.' : 'Campanha criada com sucesso.');
        await loadCampaigns();
      } catch (error) {
        showToast(error.message, 'error');
      } finally {
        setButtonLoading(button, false);
      }
    });

    async function loadCampaigns() {
      try {
        const campaigns = await api('/api/campaigns');
        campaignsById = new Map(campaigns.map(campaign => [campaign.id, campaign]));
        table.replaceChildren();
        campaigns.forEach(campaign => {
          const row = document.createElement('tr');
          const title = document.createElement('div');
          const strong = document.createElement('strong');
          strong.textContent = campaign.internal_name;
          const small = document.createElement('small');
          small.className = 'd-block text-muted';
          small.textContent = campaign.title;
          title.append(strong, small);
          cell(row, title);
          cell(row, badge(campaign.channel, 'channel-badge'));
          cell(row, formatDate(campaign.scheduled_at));
          cell(row, badge(campaign.status));

          const actions = document.createElement('div');
          actions.className = 'table-actions';
          const preview = document.createElement('button');
          preview.type = 'button';
          preview.className = 'btn btn-sm btn-light';
          preview.innerHTML = '<i class="bi bi-eye" aria-hidden="true"></i> Prévia';
          preview.setAttribute('aria-label', `Visualizar prévia de ${campaign.internal_name}`);
          preview.addEventListener('click', () => showCampaignPreview(campaign));
          const edit = document.createElement('button');
          edit.type = 'button';
          edit.className = 'btn btn-sm btn-outline-primary';
          edit.innerHTML = '<i class="bi bi-pencil" aria-hidden="true"></i> Editar';
          edit.disabled = ['sending', 'sent', 'simulated', 'failed'].includes(campaign.status);
          edit.title = campaign.status === 'sent' ? 'Duplique uma campanha enviada para criar uma nova versão.' : '';
          edit.setAttribute('aria-label', `Editar ${campaign.internal_name}`);
          edit.addEventListener('click', () => openCampaignEditor(campaign));

          const duplicate = document.createElement('button');
          duplicate.type = 'button';
          duplicate.className = 'btn btn-sm btn-light';
          duplicate.innerHTML = '<i class="bi bi-copy" aria-hidden="true"></i> Duplicar';
          duplicate.setAttribute('aria-label', `Duplicar ${campaign.internal_name}`);
          duplicate.addEventListener('click', async () => {
            setButtonLoading(duplicate, true, 'Duplicando…');
            try {
              await api(`/api/campaigns/${campaign.id}/duplicate`, { method: 'POST' });
              showToast('Campanha duplicada.');
              await loadCampaigns();
            } catch (error) {
              showToast(error.message, 'error');
              setButtonLoading(duplicate, false);
            }
          });

          const remove = document.createElement('button');
          remove.type = 'button';
          remove.className = 'btn btn-sm btn-outline-danger';
          remove.innerHTML = '<i class="bi bi-trash" aria-hidden="true"></i><span class="visually-hidden">Apagar</span>';
          remove.title = 'Apagar campanha';
          remove.setAttribute('aria-label', `Apagar ${campaign.internal_name}`);
          remove.disabled = ['sending', 'sent', 'simulated', 'failed'].includes(campaign.status);
          remove.addEventListener('click', async () => {
            const confirmed = await confirmAction(`Apagar definitivamente a campanha "${campaign.internal_name}"?`, { title: 'Apagar campanha', confirmText: 'Apagar', danger: true });
            if (!confirmed) return;
            setButtonLoading(remove, true, '');
            try {
              await api(`/api/campaigns/${campaign.id}`, { method: 'DELETE' });
              showToast('Campanha apagada.');
              await loadCampaigns();
            } catch (error) {
              showToast(error.message, 'error');
              setButtonLoading(remove, false);
            }
          });

          const cancel = document.createElement('button');
          cancel.type = 'button';
          cancel.className = 'btn btn-sm btn-outline-warning';
          cancel.innerHTML = '<i class="bi bi-calendar-x" aria-hidden="true"></i> Cancelar';
          cancel.setAttribute('aria-label', `Cancelar ${campaign.internal_name}`);
          cancel.disabled = !['draft', 'review', 'scheduled'].includes(campaign.status);
          cancel.addEventListener('click', async () => {
            const confirmed = await confirmAction(`Cancelar a campanha "${campaign.internal_name}" e qualquer tarefa pendente?`, { title: 'Cancelar campanha', confirmText: 'Cancelar campanha', danger: true });
            if (!confirmed) return;
            setButtonLoading(cancel, true, 'Cancelando…');
            try {
              const response = await api(`/api/campaigns/${campaign.id}/cancel`, { method: 'POST' });
              showToast(response.message, 'warning');
              await loadCampaigns();
            } catch (error) {
              showToast(error.message, 'error');
              setButtonLoading(cancel, false);
            }
          });

          const send = document.createElement('button');
          send.type = 'button';
          send.className = 'btn btn-sm btn-primary';
          send.innerHTML = '<i class="bi bi-send" aria-hidden="true"></i> Enviar';
          send.setAttribute('aria-label', `Enviar ${campaign.internal_name}`);
          send.disabled = ['sent', 'simulated', 'sending', 'cancelled'].includes(campaign.status);
          send.addEventListener('click', async () => {
            const message = campaign.requires_confirmation ? 'Esta campanha é grande. Confirme que a base e os consentimentos foram revisados.' : 'Confirma o envio? Somente destinatários consentidos serão processados.';
            const confirmed = await confirmAction(message, { title: 'Confirmar envio', confirmText: 'Confirmar envio' });
            if (!confirmed) return;
            setButtonLoading(send, true, 'Enviando…');
            try {
              const response = await api(`/api/campaigns/${campaign.id}/send?confirm=${campaign.requires_confirmation}`, { method: 'POST' });
              showToast(response.message);
              await loadCampaigns();
            } catch (error) {
              showToast(error.message, 'error');
              setButtonLoading(send, false);
            }
          });
          actions.append(preview, edit, duplicate, cancel, remove, send);
          cell(row, actions, 'text-end');
          table.append(row);
        });
        if (!campaigns.length) emptyTable(table, 5, 'bi-megaphone', 'Nenhuma campanha criada', 'Crie sua primeira campanha para começar o planejamento.');
        await loadTasks();
      } catch (error) {
        emptyTable(table, 5, 'bi-exclamation-triangle', 'Não foi possível carregar as campanhas', error.message);
        showToast(error.message, 'error');
      }
    }

    loadLists();
    loadTemplates();
    loadCampaigns();
  }

  function initContent() {
    const form = $('#contentForm');
    if (!form) return;
    let generatedId = null;

    form.addEventListener('submit', async event => {
      const button = beginSubmit(event, 'Gerando…');
      if (!button) return;
      try {
        const data = await api('/api/content/generate', { method: 'POST', body: JSON.stringify(formObject(form)) });
        generatedId = data.id;
        $('#generatedContent').value = data.content;
        const provider = $('#aiProvider');
        provider.textContent = data.provider === 'simulation' ? 'SIMULAÇÃO' : 'API oficial';
        provider.className = `badge ${data.provider === 'simulation' ? 'text-bg-warning' : 'text-bg-success'}`;
        $('#approveContent').disabled = false;
        showToast('Sugestão criada. Revise antes de aprovar.');
      } catch (error) {
        showToast(error.message, 'error');
      } finally {
        setButtonLoading(button, false);
      }
    });

    $('#copyContent')?.addEventListener('click', async event => {
      const content = $('#generatedContent').value;
      if (!content.trim()) { showToast('Gere ou escreva um conteúdo antes de copiar.', 'warning'); return; }
      const button = event.currentTarget;
      setButtonLoading(button, true, 'Copiando…');
      try {
        await navigator.clipboard.writeText(content);
        showToast('Texto copiado.');
      } catch {
        $('#generatedContent').select();
        const copied = document.execCommand('copy');
        showToast(copied ? 'Texto copiado.' : 'Não foi possível copiar automaticamente.', copied ? 'success' : 'error');
      } finally {
        setButtonLoading(button, false);
      }
    });

    $('#approveContent')?.addEventListener('click', async event => {
      if (!generatedId) return;
      const button = event.currentTarget;
      setButtonLoading(button, true, 'Aprovando…');
      try {
        const content = $('#generatedContent').value.trim();
        if (!content) {
          showToast('Revise e mantenha algum conteúdo antes de aprovar.', 'warning');
          return;
        }
        await api(`/api/content/${generatedId}/approve`, { method: 'POST', body: JSON.stringify({ content }) });
        showToast('Conteúdo aprovado. Copie-o para uma campanha.');
      } catch (error) {
        showToast(error.message, 'error');
      } finally {
        setButtonLoading(button, false);
      }
    });
  }

  function initIntegrations() {
    if (!$('#integrationCards')) return;

    async function loadIntegrations() {
      try {
        const integrations = await api('/api/integrations');
        $$('.integration-card').forEach(card => {
          delete card.dataset.id;
          card.dataset.account = '';
          card.dataset.businessAccount = '';
          const status = $('.integration-status', card);
          status.textContent = 'Não configurada';
          status.className = 'badge integration-status text-bg-secondary';
          $('.testIntegration', card)?.classList.add('d-none');
          $('.removeIntegration', card)?.classList.add('d-none');
          $('.syncTemplates', card)?.classList.add('d-none');
        });
        integrations.forEach(integration => {
          const card = $(`.integration-card[data-provider="${integration.provider}"]`);
          if (!card) return;
          const status = $('.integration-status', card);
          status.textContent = integration.active ? 'Conectada' : integration.credential_hints.length ? `Salva ${integration.credential_hints.join(', ')}` : 'Não configurada';
          status.className = `badge integration-status ${integration.active ? 'text-bg-success' : 'text-bg-secondary'}`;
          status.title = integration.last_error || '';
          card.dataset.id = integration.id;
          card.dataset.account = integration.account || '';
          card.dataset.businessAccount = integration.metadata?.business_account_id || '';
          $('.testIntegration', card)?.classList.remove('d-none');
          $('.removeIntegration', card)?.classList.remove('d-none');
          if (integration.provider === 'whatsapp') $('.syncTemplates', card)?.classList.remove('d-none');
        });
      } catch (error) {
        $$('.integration-status').forEach(status => {
          status.textContent = 'Não foi possível verificar';
          status.className = 'badge integration-status text-bg-danger';
        });
        showToast(error.message, 'error');
      }
    }

    $$('.configureIntegration').forEach(button => button.addEventListener('click', () => {
      const card = button.closest('.integration-card');
      const form = $('#integrationForm');
      form.reset();
      form.classList.remove('was-validated');
      form.elements.provider.value = card.dataset.provider;
      form.elements.external_account_id.value = card.dataset.account || '';
      form.elements.business_account_id.value = card.dataset.businessAccount || '';
      $('#integrationBusinessAccountField')?.classList.toggle('d-none', card.dataset.provider !== 'whatsapp');
      const title = $('h2', card)?.textContent;
      $('#integrationModalTitle').textContent = `Configurar ${title || 'integração'}`;
      bootstrap.Modal.getOrCreateInstance($('#integrationModal')).show();
    }));

    $$('.testIntegration').forEach(button => button.addEventListener('click', async () => {
      const card = button.closest('.integration-card');
      if (!card.dataset.id) return;
      setButtonLoading(button, true, 'Testando…');
      try {
        const result = await api(`/api/integrations/${card.dataset.id}/test`, { method: 'POST' });
        showToast(result.message, result.connected ? 'success' : result.simulation ? 'warning' : 'error');
        (result.warnings || []).forEach(message => showToast(message, 'warning'));
        await loadIntegrations();
      } catch (error) {
        showToast(error.message, 'error');
      } finally {
        setButtonLoading(button, false);
      }
    }));

    $$('.removeIntegration').forEach(button => button.addEventListener('click', async () => {
      const card = button.closest('.integration-card');
      if (!card.dataset.id) return;
      const provider = $('h2', card)?.textContent || 'esta integração';
      const confirmed = await confirmAction(`Remover ${provider} e as credenciais armazenadas?`, { title: 'Remover integração', confirmText: 'Remover', danger: true });
      if (!confirmed) return;
      setButtonLoading(button, true, '');
      try {
        await api(`/api/integrations/${card.dataset.id}`, { method: 'DELETE' });
        showToast('Integração removida.');
        await loadIntegrations();
      } catch (error) {
        showToast(error.message, 'error');
      } finally {
        setButtonLoading(button, false);
      }
    }));

    $$('.syncTemplates').forEach(button => button.addEventListener('click', async () => {
      const card = button.closest('.integration-card');
      if (!card.dataset.id || card.dataset.provider !== 'whatsapp') return;
      setButtonLoading(button, true, 'Sincronizando…');
      try {
        const result = await api(`/api/integrations/${card.dataset.id}/whatsapp/templates/sync`, { method: 'POST' });
        showToast(result.message, result.synchronized ? 'success' : 'warning');
      } catch (error) {
        showToast(error.message, 'error');
      } finally {
        setButtonLoading(button, false);
      }
    }));

    $('#integrationForm')?.addEventListener('submit', async event => {
      const button = beginSubmit(event, 'Salvando…');
      if (!button) return;
      const form = event.currentTarget;
      const data = formObject(form);
      const keyNames = { whatsapp: 'access_token', facebook: 'page_access_token', instagram: 'page_access_token', ai: 'api_key' };
      const credentials = {};
      if (data.token) credentials[keyNames[data.provider]] = data.token;
      const metadata = data.provider === 'whatsapp' && data.business_account_id ? { business_account_id: data.business_account_id } : {};
      try {
        const result = await api('/api/integrations', { method: 'POST', body: JSON.stringify({ provider: data.provider, external_account_id: data.external_account_id || null, credentials, metadata }) });
        bootstrap.Modal.getInstance($('#integrationModal'))?.hide();
        form.reset();
        showToast(result.message);
        await loadIntegrations();
      } catch (error) {
        showToast(error.message, 'error');
      } finally {
        setButtonLoading(button, false);
      }
    });

    loadIntegrations();
  }

  async function initHistory() {
    const table = $('#historyTable');
    if (!table) return;
    const pageSize = 25;
    let currentPage = 0;

    const showDetail = async item => {
      const modalElement = $('#historyDetailModal');
      const body = $('#historyDetailBody');
      $('#historyDetailTitle').textContent = item.campaign;
      body.replaceChildren(Object.assign(document.createElement('div'), { className: 'loading-card', textContent: 'Carregando detalhes…' }));
      bootstrap.Modal.getOrCreateInstance(modalElement).show();
      try {
        const detail = await api(`/api/campaigns/history/${item.id}`);
        const summary = document.createElement('div');
        summary.className = 'row g-3 mb-4';
        [
          ['Canal', statusLabels[detail.channel] || detail.channel],
          ['Status', statusLabels[detail.status] || detail.status],
          ['Criada em', formatDate(detail.created_at)],
          ['Agendada para', formatDate(detail.scheduled_at)]
        ].forEach(([label, value]) => {
          const col = document.createElement('div');
          col.className = 'col-6';
          const labelNode = document.createElement('small');
          labelNode.className = 'text-secondary d-block';
          labelNode.textContent = label;
          const valueNode = document.createElement('strong');
          valueNode.textContent = value;
          col.append(labelNode, valueNode);
          summary.append(col);
        });
        const title = document.createElement('h3');
        title.className = 'h6';
        title.textContent = detail.title;
        const message = document.createElement('p');
        message.className = 'history-message';
        message.textContent = detail.body;
        const recipientTitle = document.createElement('h3');
        recipientTitle.className = 'h6 mt-4';
        recipientTitle.textContent = `Destinatários (${detail.recipients.length})`;
        const statusCounts = detail.recipients.reduce((result, recipient) => {
          result[recipient.status] = (result[recipient.status] || 0) + 1;
          return result;
        }, {});
        const statusList = document.createElement('div');
        statusList.className = 'd-flex flex-wrap gap-2';
        Object.entries(statusCounts).forEach(([status, count]) => {
          const itemBadge = badge(status);
          itemBadge.textContent = `${statusLabels[status] || status}: ${count}`;
          statusList.append(itemBadge);
        });
        const eventTitle = document.createElement('h3');
        eventTitle.className = 'h6 mt-4';
        eventTitle.textContent = `Eventos recentes (${detail.events.length})`;
        const events = document.createElement('ul');
        events.className = 'list-unstyled mb-0';
        detail.events.forEach(event => {
          const line = document.createElement('li');
          line.className = 'py-2 border-bottom border-secondary-subtle';
          line.textContent = `${statusLabels[event.type] || event.type} · ${formatDate(event.date)}`;
          events.append(line);
        });
        if (!detail.events.length) {
          const line = document.createElement('li');
          line.className = 'text-secondary';
          line.textContent = 'Nenhum evento adicional registrado.';
          events.append(line);
        }
        body.replaceChildren(summary, title, message, recipientTitle, statusList, eventTitle, events);
      } catch (error) {
        body.replaceChildren(emptyState('bi-exclamation-triangle', 'Detalhes indisponíveis', error.message, true));
      }
    };

    const loadHistory = async (focusPage = false) => {
      const form = $('#historyFilters');
      const query = new URLSearchParams();
      const values = formObject(form);
      Object.entries(values).forEach(([key, value]) => { if (value) query.set(key, value); });
      // Busca um registro adicional para saber se existe uma próxima página,
      // inclusive quando o total é um múltiplo exato do tamanho da página.
      query.set('limit', String(pageSize + 1));
      query.set('offset', String(currentPage * pageSize));
      table.replaceChildren();
      emptyTable(table, 8, 'bi-hourglass-split', 'Carregando histórico', 'Aguarde enquanto os registros são consultados.');
      try {
        const result = await api(`/api/campaigns/history/all?${query}`);
        const hasNextPage = result.length > pageSize;
        const items = result.slice(0, pageSize);
        table.replaceChildren();
        items.forEach(item => {
          const row = document.createElement('tr');
          [item.campaign, badge(item.channel, 'channel-badge'), formatDate(item.date), item.recipients, item.sent, item.failures, badge(item.status)].forEach(value => cell(row, value));
          const detail = document.createElement('button');
          detail.type = 'button';
          detail.className = 'btn btn-sm btn-outline-primary';
          detail.textContent = 'Ver';
          detail.setAttribute('aria-label', `Ver detalhes da campanha ${item.campaign}`);
          detail.addEventListener('click', () => showDetail(item));
          cell(row, detail);
          table.append(row);
        });
        if (!items.length) emptyTable(table, 8, 'bi-clock-history', 'Nenhum histórico disponível', 'Campanhas processadas aparecerão aqui com seus resultados.');
        $('#historyPrevious').disabled = currentPage === 0;
        $('#historyNext').disabled = !hasNextPage;
        $('#historyPage').textContent = `Página ${currentPage + 1}`;
      } catch (error) {
        emptyTable(table, 8, 'bi-exclamation-triangle', 'Não foi possível carregar o histórico', error.message);
        showToast(error.message, 'error');
      }
      if (focusPage) {
        const pageLabel = $('#historyPage');
        pageLabel.tabIndex = -1;
        window.requestAnimationFrame(() => pageLabel.focus({ preventScroll: true }));
      }
    };

    $('#historyFilters')?.addEventListener('submit', event => {
      event.preventDefault();
      currentPage = 0;
      loadHistory();
    });
    $('#historyPrevious')?.addEventListener('click', () => { if (currentPage > 0) { currentPage -= 1; loadHistory(true); } });
    $('#historyNext')?.addEventListener('click', () => { currentPage += 1; loadHistory(true); });
    await loadHistory();
  }

  async function initSettings() {
    const settingsForm = $('#settingsForm');
    if (settingsForm) {
      settingsForm.setAttribute('aria-busy', 'true');
      try {
        const profile = await getProfile();
        Object.entries({
          name: profile.name,
          company: profile.company,
          email: profile.email,
          timezone: profile.timezone,
          daily_limit: profile.daily_limit,
          unsubscribe_policy: profile.unsubscribe_policy
        }).forEach(([name, value]) => {
          if (settingsForm.elements[name]) settingsForm.elements[name].value = value ?? '';
        });
        const passwordUsername = $('#passwordUsername');
        if (passwordUsername) passwordUsername.value = profile.email || '';
      } catch (error) {
        showToast(`Não foi possível carregar as configurações: ${error.message}`, 'error');
      } finally {
        settingsForm.setAttribute('aria-busy', 'false');
      }
    }
    $('#settingsForm')?.addEventListener('submit', async event => {
      const button = beginSubmit(event, 'Salvando…');
      if (!button) return;
      const form = event.currentTarget;
      const raw = formObject(form);
      const data = Object.fromEntries(Object.entries(raw).filter(([, value]) => value !== ''));
      if (data.daily_limit) data.daily_limit = Number(data.daily_limit);
      try {
        const result = await api('/api/settings/profile', { method: 'PATCH', body: JSON.stringify(data) });
        profilePromise = null;
        await initUserContext();
        showToast(result.message);
      } catch (error) {
        showToast(error.message, 'error');
      } finally {
        setButtonLoading(button, false);
      }
    });

    $('#passwordForm')?.addEventListener('submit', async event => {
      const button = beginSubmit(event, 'Atualizando…');
      if (!button) return;
      const form = event.currentTarget;
      try {
        const result = await api('/api/settings/password', { method: 'POST', body: JSON.stringify(formObject(form)) });
        showToast(result.message);
        form.reset();
        if (result.reauthenticate) window.setTimeout(() => { location.href = '/login'; }, 900);
      } catch (error) {
        showToast(error.message, 'error');
      } finally {
        setButtonLoading(button, false);
      }
    });
  }

  async function initAdmin() {
    const overview = $('#adminOverview');
    if (!overview) return;
    const pageSize = 25;
    const pages = { logs: 0, users: 0, companies: 0, campaigns: 0, errors: 0 };
    let currentQuery = '';
    let pendingPaginationFocus = null;
    const renderTable = (target, headers, rows, buildRow, emptyTitle, emptyDescription) => {
      const table = document.createElement('table');
      table.className = 'table';
      const head = document.createElement('thead');
      const headRow = document.createElement('tr');
      headers.forEach(label => {
        const th = document.createElement('th');
        th.scope = 'col';
        th.textContent = label;
        headRow.append(th);
      });
      head.append(headRow);
      const body = document.createElement('tbody');
      rows.forEach(item => body.append(buildRow(item)));
      if (!rows.length) emptyTable(body, headers.length, 'bi-inbox', emptyTitle, emptyDescription);
      table.append(head, body);
      target.replaceChildren(table);
    };

    const adminUrl = (path, key, values = {}) => {
      const query = new URLSearchParams({
        limit: String(pageSize + 1),
        offset: String(pages[key] * pageSize),
        ...values
      });
      return `${path}?${query}`;
    };

    const renderPagination = (target, key, hasNextPage) => {
      if (!target) return;
      const previous = document.createElement('button');
      previous.type = 'button';
      previous.className = 'btn btn-sm btn-outline-secondary';
      previous.textContent = 'Anterior';
      previous.disabled = pages[key] === 0;
      previous.addEventListener('click', () => {
        if (pages[key] === 0) return;
        pendingPaginationFocus = key;
        pages[key] -= 1;
        loadAdminData(currentQuery);
      });
      const label = document.createElement('span');
      label.textContent = `Página ${pages[key] + 1}`;
      label.setAttribute('aria-live', 'polite');
      const next = document.createElement('button');
      next.type = 'button';
      next.className = 'btn btn-sm btn-outline-secondary';
      next.textContent = 'Próxima';
      next.disabled = !hasNextPage;
      next.addEventListener('click', () => {
        pendingPaginationFocus = key;
        pages[key] += 1;
        loadAdminData(currentQuery);
      });
      target.replaceChildren(previous, label, next);
      if (pendingPaginationFocus === key) {
        pendingPaginationFocus = null;
        label.tabIndex = -1;
        window.requestAnimationFrame(() => label.focus({ preventScroll: true }));
      }
    };

    const loadAdminData = async (query = '') => {
      currentQuery = query;
      overview.setAttribute('aria-busy', 'true');
      try {
        const [data, logResult, userResult, companyResult, campaignResult, errorResult] = await Promise.all([
          api('/api/admin/overview'),
          api(adminUrl('/api/admin/logs', 'logs')),
          api(adminUrl('/api/admin/users', 'users', query ? { q: query } : {})),
          api(adminUrl('/api/admin/companies', 'companies')),
          api(adminUrl('/api/admin/campaigns', 'campaigns')),
          api(adminUrl('/api/admin/integration-errors', 'errors'))
        ]);
        const logs = logResult.slice(0, pageSize);
        const users = userResult.slice(0, pageSize);
        const companies = companyResult.slice(0, pageSize);
        const campaigns = campaignResult.slice(0, pageSize);
        const errors = errorResult.slice(0, pageSize);
        const totals = { users: ['bi-people', 'Usuários'], companies: ['bi-buildings', 'Empresas'], campaigns: ['bi-megaphone', 'Campanhas'], blocked_contacts: ['bi-person-x', 'Contatos bloqueados'], integrations: ['bi-plug', 'Integrações'] };
        overview.replaceChildren(...Object.entries(totals).map(([key, meta], index) => {
          const col = document.createElement('div');
          col.className = 'col-6 col-md-4 col-xl';
          col.style.setProperty('--reveal-delay', `${index * 45}ms`);
          const card = document.createElement('article');
          card.className = 'stat-card';
          const icon = document.createElement('i');
          icon.className = `bi ${meta[0]}`;
          icon.setAttribute('aria-hidden', 'true');
          const value = document.createElement('strong');
          value.textContent = data[key];
          const label = document.createElement('span');
          label.textContent = meta[1];
          card.append(icon, value, label);
          col.append(card);
          return col;
        }));
        overview.setAttribute('aria-busy', 'false');

        renderTable($('#adminLogs'), ['Ação', 'Empresa', 'Data'], logs, log => {
          const row = document.createElement('tr');
          cell(row, log.action); cell(row, log.company_id); cell(row, formatDate(log.date));
          return row;
        }, 'Nenhum registro recente', 'As próximas ações administrativas aparecerão aqui.');
        renderPagination($('#adminLogsPagination'), 'logs', logResult.length > pageSize);

        renderTable($('#adminUsers'), ['Usuário', 'Empresa', 'Perfil', 'Status', 'Ação'], users, user => {
          const row = document.createElement('tr');
          const identity = document.createElement('span');
          identity.className = 'd-grid';
          const name = document.createElement('strong');
          name.textContent = user.name;
          const email = document.createElement('small');
          email.className = 'text-secondary';
          email.textContent = user.email;
          identity.append(name, email);
          cell(row, identity); cell(row, user.company); cell(row, user.role === 'admin' ? 'Administrador' : 'Usuário'); cell(row, badge(user.active ? 'active' : 'inactive'));
          const action = document.createElement('button');
          action.type = 'button';
          action.className = `btn btn-sm ${user.active ? 'btn-outline-danger' : 'btn-outline-primary'}`;
          const isCurrentAdmin = user.id === data.current_admin_id;
          action.textContent = isCurrentAdmin ? 'Conta atual' : user.active ? 'Bloquear' : 'Desbloquear';
          action.disabled = isCurrentAdmin;
          action.setAttribute('aria-label', isCurrentAdmin ? `${user.name} é a conta administrativa atual e não pode ser bloqueada` : `${action.textContent} acesso de ${user.name}`);
          if (!isCurrentAdmin) action.addEventListener('click', async () => {
            const desired = !user.active;
            const confirmed = await confirmAction(`${desired ? 'Desbloquear' : 'Bloquear'} o acesso de ${user.name}?`, { title: 'Alterar acesso', confirmText: desired ? 'Desbloquear' : 'Bloquear', danger: !desired });
            if (!confirmed) return;
            setButtonLoading(action, true);
            try {
              await api(`/api/admin/users/${user.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: desired }) });
              showToast(`Acesso de ${user.name} atualizado.`);
              await loadAdminData($('#adminUserSearch')?.value || '');
            } catch (error) { showToast(error.message, 'error'); setButtonLoading(action, false); }
          });
          cell(row, action);
          return row;
        }, 'Nenhum usuário encontrado', 'A busca não retornou usuários.');
        renderPagination($('#adminUsersPagination'), 'users', userResult.length > pageSize);

        renderTable($('#adminCompanies'), ['Empresa', 'Uso', 'Limite diário', 'Ação'], companies, company => {
          const row = document.createElement('tr');
          cell(row, company.name); cell(row, `${company.users} usuário(s) · ${company.campaigns} campanha(s)`);
          const input = document.createElement('input');
          input.type = 'number'; input.min = '1'; input.max = '100000'; input.value = company.daily_limit;
          input.className = 'form-control form-control-sm admin-limit-input';
          input.setAttribute('aria-label', `Limite diário de ${company.name}`);
          cell(row, input);
          const save = document.createElement('button');
          save.type = 'button'; save.className = 'btn btn-sm btn-outline-primary'; save.textContent = 'Salvar';
          save.setAttribute('aria-label', `Salvar limite diário de ${company.name}`);
          save.addEventListener('click', async () => {
            const value = Number(input.value);
            if (!Number.isInteger(value) || value < 1 || value > 100000) { showToast('Informe um limite entre 1 e 100.000.', 'warning'); input.focus(); return; }
            setButtonLoading(save, true);
            try {
              await api(`/api/admin/companies/${company.id}/limits`, { method: 'PATCH', body: JSON.stringify({ daily_limit: value }) });
              showToast(`Limite de ${company.name} atualizado.`);
            } catch (error) { showToast(error.message, 'error'); }
            finally { setButtonLoading(save, false); }
          });
          cell(row, save);
          return row;
        }, 'Nenhuma empresa', 'As empresas cadastradas aparecerão aqui.');
        renderPagination($('#adminCompaniesPagination'), 'companies', companyResult.length > pageSize);

        renderTable($('#adminCampaigns'), ['Campanha', 'Empresa', 'Canal', 'Status', 'Data'], campaigns, campaign => {
          const row = document.createElement('tr');
          cell(row, campaign.name); cell(row, campaign.company); cell(row, badge(campaign.channel, 'channel-badge')); cell(row, badge(campaign.status)); cell(row, formatDate(campaign.scheduled_at || campaign.created_at));
          return row;
        }, 'Nenhuma campanha', 'Ainda não existem campanhas cadastradas.');
        renderPagination($('#adminCampaignsPagination'), 'campaigns', campaignResult.length > pageSize);

        renderTable($('#adminErrors'), ['Empresa', 'Canal', 'Erro', 'Teste'], errors, item => {
          const row = document.createElement('tr');
          cell(row, item.company); cell(row, badge(item.provider, 'channel-badge')); cell(row, item.error); cell(row, formatDate(item.last_tested_at));
          return row;
        }, 'Nenhum erro de integração', 'Não há falhas de integração registradas.');
        renderPagination($('#adminErrorsPagination'), 'errors', errorResult.length > pageSize);
      } catch (error) {
        overview.setAttribute('aria-busy', 'false');
        overview.replaceChildren(emptyState('bi-shield-exclamation', 'Acesso indisponível', error.message));
        ['#adminLogs', '#adminUsers', '#adminCompanies', '#adminCampaigns', '#adminErrors'].forEach(selector => {
          $(selector)?.replaceChildren(emptyState('bi-lock', 'Conteúdo protegido', 'Os dados exigem permissão administrativa.'));
        });
        ['#adminLogsPagination', '#adminUsersPagination', '#adminCompaniesPagination', '#adminCampaignsPagination', '#adminErrorsPagination'].forEach(selector => $(selector)?.replaceChildren());
        showToast(error.message, 'error');
      }
    };

    let searchTimer;
    $('#adminUserSearch')?.addEventListener('input', event => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        pages.users = 0;
        loadAdminData(event.target.value.trim());
      }, 300);
    });
    await loadAdminData();
  }

  initLogout();
  initFormValidation();
  initAuth();
  initUserContext();

  const initializers = {
    dashboard: initDashboard,
    contacts: initContacts,
    campaigns: initCampaigns,
    content: initContent,
    integrations: initIntegrations,
    history: initHistory,
    settings: initSettings,
    admin: initAdmin
  };
  initializers[page]?.();
})();
