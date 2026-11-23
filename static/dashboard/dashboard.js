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
