(() => {
  const body = document.body;
  const countBadge = document.getElementById('live-notification-count');
  const endpoint = body.dataset.notificationEndpoint;

  function buildEmpty(compact) {
    const empty = document.createElement('div');
    empty.className = compact ? 'inbox-empty' : 'empty-state';
    const title = document.createElement('strong');
    title.textContent = 'You’re all caught up.';
    const description = document.createElement('p');
    description.textContent = compact
      ? 'No notifications today. Older ones are in Activity.'
      : 'New trip and group updates will appear here throughout the day.';
    empty.append(title, description);
    return empty;
  }

  function buildRow(notification, compact, csrfInput) {
    const row = document.createElement('article');
    row.className = compact ? 'inbox-item' : 'notification-page-row';
    const dot = document.createElement('span');
    dot.className = `notification-dot${notification.is_read ? ' read' : ''}`;
    const copy = document.createElement('div');
    copy.className = compact ? 'inbox-item-copy' : 'notification-page-copy';
    const title = document.createElement('strong');
    title.textContent = notification.title;
    const message = document.createElement('p');
    message.textContent = notification.message || 'There’s a new update for your travel space.';
    const meta = document.createElement('small');
    meta.textContent = [notification.time, notification.trip].filter(Boolean).join(' · ');
    copy.append(title, message, meta);
    row.append(dot, copy);
    if (notification.can_mark_read && csrfInput) {
      const form = document.createElement('form');
      form.method = 'post';
      form.action = notification.mark_url;
      const token = document.createElement('input');
      token.type = 'hidden';
      token.name = 'csrfmiddlewaretoken';
      token.value = csrfInput.value;
      const next = document.createElement('input');
      next.type = 'hidden';
      next.name = 'next';
      next.value = window.location.pathname + window.location.search;
      const button = document.createElement('button');
      button.className = 'text-button';
      button.type = 'submit';
      button.textContent = 'Mark read';
      form.append(token, next, button);
      row.append(form);
    }
    return row;
  }

  function renderNotifications(notifications) {
    const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
    document.querySelectorAll('[data-notification-feed]').forEach((feed) => {
      const compact = feed.hasAttribute('data-compact');
      if (!notifications.length) {
        feed.replaceChildren(buildEmpty(compact));
        return;
      }
      feed.replaceChildren(...notifications.map((n) => buildRow(n, compact, csrfInput)));
    });
  }

  async function refreshNotificationCount() {
    if (!endpoint || !countBadge) return;
    try {
      const response = await fetch(endpoint, {
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        cache: 'no-store',
      });
      if (!response.ok) return;
      const data = await response.json();
      countBadge.textContent = String(data.count);
      countBadge.hidden = data.count === 0;
      renderNotifications(data.notifications || []);
    } catch (_) {
      // Keep the last rendered count when the connection is temporarily unavailable.
    }
  }

  refreshNotificationCount();
  window.setInterval(refreshNotificationCount, 60000);

  document.querySelectorAll('[data-copy-target]').forEach((button) => {
    button.addEventListener('click', async () => {
      const input = document.getElementById(button.dataset.copyTarget);
      if (!input) return;
      try {
        await navigator.clipboard.writeText(input.value);
      } catch (_) {
        input.select();
        document.execCommand('copy');
      }
      const previousText = button.textContent;
      button.textContent = 'Copied';
      window.setTimeout(() => { button.textContent = previousText; }, 1400);
    });
  });
})();

(() => {
  const menus = [...document.querySelectorAll('[data-dropdown]')];
  if (!menus.length) return;
  const parts = (menu) => ({
    trigger: menu.querySelector('[data-dropdown-trigger]'),
    panel: menu.querySelector('[data-dropdown-panel]'),
  });
  const setOpen = (menu, open) => {
    const { trigger, panel } = parts(menu);
    panel.hidden = !open;
    trigger.setAttribute('aria-expanded', String(open));
  };
  menus.forEach((menu) => {
    parts(menu).trigger.addEventListener('click', (event) => {
      event.stopPropagation();
      const willOpen = parts(menu).panel.hidden;
      menus.forEach((other) => setOpen(other, false));
      setOpen(menu, willOpen);
    });
  });
  document.addEventListener('click', (event) => {
    menus.forEach((menu) => { if (!menu.contains(event.target)) setOpen(menu, false); });
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    menus.forEach((menu) => {
      if (!parts(menu).panel.hidden) {
        setOpen(menu, false);
        parts(menu).trigger.focus();
      }
    });
  });
})();

(() => {
  document.querySelectorAll('[data-dialog-open]').forEach((button) => {
    button.addEventListener('click', () => {
      const dialog = document.getElementById(button.dataset.dialogOpen);
      if (dialog && !dialog.open) dialog.showModal();
    });
  });
  document.querySelectorAll('dialog.modal').forEach((dialog) => {
    dialog.querySelectorAll('[data-dialog-close]').forEach((button) => {
      button.addEventListener('click', () => dialog.close());
    });
    // Clicking the dimmed backdrop closes the dialog.
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) dialog.close();
    });
    if (dialog.hasAttribute('data-open-on-load')) dialog.showModal();
  });
})();

(() => {
  const search = document.querySelector('[data-help-search]');
  if (!search) return;
  const topics = [...document.querySelectorAll('[data-help-topic]')];
  const empty = document.querySelector('[data-help-empty]');
  search.addEventListener('input', () => {
    const terms = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    let anyVisible = false;
    topics.forEach((topic) => {
      let topicVisible = false;
      topic.querySelectorAll('.help-item').forEach((item) => {
        const text = item.textContent.toLowerCase();
        const match = terms.every((term) => text.includes(term));
        item.hidden = !match;
        item.open = match && terms.length > 0;
        if (match) topicVisible = true;
      });
      topic.hidden = !topicVisible;
      if (topicVisible) anyVisible = true;
    });
    empty.hidden = anyVisible;
  });
})();


(() => {
  document.querySelectorAll('input[type="date"][data-min-from]').forEach((endInput) => {
    const startInput = document.getElementById(endInput.dataset.minFrom);
    if (!startInput) return;
    const baseMin = endInput.min;
    const sync = () => {
      endInput.min = startInput.value || baseMin;
      // If the return date is now before departure, move it up to the departure date.
      if (startInput.value && endInput.value && endInput.value < startInput.value) {
        endInput.value = startInput.value;
      }
    };
    startInput.addEventListener('change', sync);
    sync();
  });
})();

(() => {
  document.querySelectorAll('[data-avatar-form]').forEach((form) => {
    const input = form.querySelector('input[type="file"]');
    input.addEventListener('change', () => {
      if (!input.files.length) return;
      form.querySelector('.avatar-upload').classList.add('is-uploading');
      form.submit();
    });
  });
})();

(() => {
  // Theme picker: preview instantly, then save.
  document.querySelectorAll('form[data-autosubmit]').forEach((form) => {
    form.addEventListener('change', (event) => {
      if (event.target.name === 'theme') document.documentElement.dataset.theme = event.target.value;
      form.submit();
    });
  });
})();

(() => {
  // Show a page skeleton while the next dashboard page loads (server round-trips can take a second or two).
  const skeleton = document.querySelector('[data-page-skeleton]');
  if (!skeleton) return;
  let timer = null;
  const routes = [
    [/^\/dashboard\/traveler\/$/, 'overview'],
    [/^\/dashboard\/admin\/$/, 'admin'],
    [/^\/dashboard\/trips\/new\/$/, 'trip-form'],
    [/^\/dashboard\/trips\/\d+\/edit\/$/, 'trip-form'],
    [/^\/dashboard\/trips\/\d+\//, 'trip-detail'],
    [/^\/dashboard\/trips\/$/, 'trip-list'],
    [/^\/dashboard\/activities\/$/, 'activity'],
    [/^\/accounts\/profile\//, 'profile'],
    [/^\/accounts\/settings\/$/, 'settings'],
    [/^\/accounts\/support\/$/, 'support'],
  ];
  const skeletonFor = (pathname) => (routes.find(([pattern]) => pattern.test(pathname)) || [null, 'list'])[1];
  const render = (pathname) => {
    const template = document.querySelector(`template[data-skeleton="${skeletonFor(pathname)}"]`)
      || document.querySelector('template[data-skeleton="list"]');
    skeleton.replaceChildren(template.content.cloneNode(true));
  };
  const show = (pathname) => {
    // Small delay so fast loads don't flash the skeleton.
    timer = window.setTimeout(() => {
      render(pathname);
      skeleton.hidden = false;
      document.body.classList.add('is-navigating');
      window.scrollTo(0, 0);
    }, 150);
  };
  const reset = () => {
    window.clearTimeout(timer);
    skeleton.hidden = true;
    skeleton.replaceChildren();
    document.body.classList.remove('is-navigating');
  };

  document.addEventListener('click', (event) => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (link.target && link.target !== '_self') return;
    if (link.hasAttribute('download')) return;
    const url = new URL(link.href, window.location.href);
    if (url.origin !== window.location.origin) return;
    // Same-page anchors (#section) don't load a new page.
    if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) return;
    if (url.pathname.startsWith('/media/') || url.pathname.startsWith('/static/')) return;
    show(url.pathname);
  });

  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (event.defaultPrevented || form.target === '_blank') return;
    show(new URL(form.action || window.location.href, window.location.href).pathname);
  });

  // Coming back with the browser's Back button can restore this page from cache; clear the skeleton.
  window.addEventListener('pageshow', reset);
})();

(() => {
  // Trip page tabs: Overview / Preparation / Travel information. The URL hash keeps the tab across reloads and redirects.
  const bar = document.querySelector('[data-tabs]');
  if (!bar) return;
  const tabs = [...bar.querySelectorAll('[data-tab]')];
  const panels = [...document.querySelectorAll('[data-panel]')];
  const names = tabs.map((tab) => tab.dataset.tab);

  const select = (name, { focus = false, updateHash = true } = {}) => {
    if (!names.includes(name)) name = names[0];
    tabs.forEach((tab) => {
      const active = tab.dataset.tab === name;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      tab.classList.toggle('active', active);
      if (active && focus) tab.focus();
    });
    panels.forEach((panel) => { panel.hidden = panel.dataset.panel !== name; });
    if (updateHash) history.replaceState(null, '', name === names[0] ? window.location.pathname + window.location.search : `#${name}`);
  };

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => select(tab.dataset.tab));
    tab.addEventListener('keydown', (event) => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      if (step) {
        event.preventDefault();
        select(names[(index + step + names.length) % names.length], { focus: true });
      } else if (event.key === 'Home' || event.key === 'End') {
        event.preventDefault();
        select(event.key === 'Home' ? names[0] : names[names.length - 1], { focus: true });
      }
    });
  });

  const fromHash = window.location.hash.slice(1);
  const fromServer = bar.dataset.activeTab;
  select(names.includes(fromHash) ? fromHash : (names.includes(fromServer) ? fromServer : names[0]), { updateHash: false });
  window.addEventListener('hashchange', () => select(window.location.hash.slice(1), { updateHash: false }));
})();


(() => {
  // "Other (type it in)" choices: show the matching text box only when Other is selected.
  document.querySelectorAll('input[data-other-for]').forEach((input) => {
    const select = document.getElementById(input.dataset.otherFor);
    const field = input.closest('.form-field');
    if (!select || !field) return;
    const sync = (focus) => {
      const isOther = select.value === '__other__';
      field.hidden = !isOther;
      input.required = isOther;
      if (!isOther) input.value = '';
      else if (focus) input.focus();
    };
    select.addEventListener('change', () => sync(true));
    sync(false);
  });
})();

(() => {
  // A profile picture that fails to load (missing file, private bucket) is removed so the initials underneath show.
  const drop = (img) => img.remove();
  document.querySelectorAll('img[data-avatar-img]').forEach((img) => {
    if (img.complete && img.naturalWidth === 0) drop(img);
    else img.addEventListener('error', () => drop(img), { once: true });
  });
})();

(() => {
  // Checklist: tick/untick instantly and save in the background (no page reload).
  const forms = document.querySelectorAll('form[data-checklist-toggle]');
  if (!forms.length) return;
  const CHECK = '<svg class="check-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
  const $ = (sel) => document.querySelector(sel);

  const paint = (form, done) => {
    const button = form.querySelector('.check-state');
    const title = form.querySelector('.checklist-title');
    const name = title ? title.textContent.trim() : 'item';
    button.classList.toggle('is-complete', done);
    button.innerHTML = done ? CHECK : '';
    button.setAttribute('aria-label', `${done ? 'Mark' : 'Mark'} ${name} ${done ? 'incomplete' : 'complete'}`);
    button.setAttribute('aria-pressed', String(done));
    if (title) title.classList.toggle('completed-text', done);
  };

  const updateTotals = ({ all_done, all_count, document_done, document_count }) => {
    const percent = all_count ? Math.round((all_done * 100) / all_count) : 0;
    const set = (sel, text) => { const el = $(sel); if (el) el.textContent = text; };
    set('[data-prep-summary]', `${all_done} of ${all_count} items ready`);
    set('[data-prep-docs]', `${document_done} of ${document_count} required documents complete`);
    set('[data-prep-percent]', `${percent}%`);
    set('[data-prep-tab]', `${all_done}/${all_count}`);
    set('[data-doc-badge]', `${document_done}/${document_count}`);
    const bar = $('[data-prep-bar]');
    if (bar) bar.style.width = `${percent}%`;
  };

  forms.forEach((form) => {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();   // don't trigger the page-loading skeleton
      if (form.dataset.busy) return;       // ignore double-clicks while saving
      const button = form.querySelector('.check-state');
      const was = button.classList.contains('is-complete');
      paint(form, !was);                    // optimistic: show the change right away
      form.dataset.busy = '1';
      try {
        const response = await fetch(form.action, {
          method: 'POST',
          body: new FormData(form),
          credentials: 'same-origin',
          headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' },
        });
        if (!response.ok) throw new Error(String(response.status));
        const data = await response.json();
        paint(form, data.is_complete);      // trust the server's answer
        updateTotals(data);
      } catch (_) {
        paint(form, was);                   // revert if it didn't save
        button.classList.add('check-failed');
        window.setTimeout(() => button.classList.remove('check-failed'), 900);
      } finally {
        delete form.dataset.busy;
      }
    }, true);
  });
})();
