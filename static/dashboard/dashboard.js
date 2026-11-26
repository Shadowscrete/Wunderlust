// ---- Error feedback for background saves -------------------------------
// A small toast so a failed save is never silent. err.message holds the HTTP status when there is one.
const FAILURE_TEXT = {
  '403': 'Your session expired or you don’t have access. Reload the page and try again.',
  '404': 'That item no longer exists. Reload the page to see the latest.',
  '503': 'We can’t reach the server right now. Please try again in a minute.',
};
function showErrorToast(err, fallback) {
  const text = !navigator.onLine
    ? 'You’re offline. Your change wasn’t saved.'
    : FAILURE_TEXT[err && err.message] || fallback || 'Something went wrong and your change wasn’t saved. Please try again.';
  let toast = document.getElementById('error-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'error-toast';
    toast.className = 'error-toast';
    toast.setAttribute('role', 'alert');
    document.body.append(toast);
  }
  toast.textContent = text;
  toast.hidden = false;
  window.clearTimeout(showErrorToast.timer);
  showErrorToast.timer = window.setTimeout(() => { toast.hidden = true; }, 5000);
}

// A redirect to the login page (session expired) comes back as HTML with status 200; treat it as a 403.
function assertJson(response) {
  if (!response.ok) throw new Error(String(response.status));
  if (response.redirected && /\/accounts\/login\//.test(response.url)) throw new Error('403');
  return response.json().catch(() => { throw new Error('500'); });
}

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

  function buildRow(notification, compact) {
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
    return row;
  }

  function renderNotifications(notifications) {
    document.querySelectorAll('[data-notification-feed]').forEach((feed) => {
      feed.setAttribute('aria-busy', 'false');
      const compact = feed.hasAttribute('data-compact');
      if (!notifications.length) {
        feed.replaceChildren(buildEmpty(compact));
        return;
      }
      feed.replaceChildren(...notifications.map((n) => buildRow(n, compact)));
    });
  }

  let latestRequest = 0;
  async function refreshNotificationCount() {
    if (!endpoint || !countBadge) return;
    const requestId = ++latestRequest;
    const opened = !document.hidden && !document.getElementById('inbox-dropdown').hidden;
    try {
      const response = await fetch(endpoint, {
        credentials: 'same-origin',
        method: opened ? 'POST' : 'GET',
        headers: opened ? { 'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value } : {},
        cache: 'no-store',
      });
      const data = await assertJson(response);
      if (requestId !== latestRequest) return;
      countBadge.textContent = String(data.count);
      countBadge.hidden = data.count === 0;
      renderNotifications(data.notifications || []);
    } catch (err) {
      if (opened && requestId === latestRequest) showErrorToast(err, 'Could not refresh the inbox. Please reopen it to retry.');
    }
  }

  document.getElementById('inbox-dropdown')?.addEventListener('inbox-open', refreshNotificationCount);
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
    if (open && panel.id === 'inbox-dropdown') panel.dispatchEvent(new Event('inbox-open'));
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
    [/^\/accounts\/friends\/$/, 'list'],
    [/^\/accounts\/u\/[^/]+\/$/, 'profile'],
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

  // My row in the Travelers panel (shown on more than one tab) plus the "x/y ready" badge.
  const updateMyProgress = ({ my_percent, my_done, my_total, my_ready, group_ready_count, group_size }) => {
    if (typeof my_percent !== 'number') return;
    document.querySelectorAll('[data-traveler-me]').forEach((row) => {
      const meter = row.querySelector('[data-my-progress]');
      const bar = row.querySelector('[data-bar]');
      const caption = row.querySelector('[data-caption]');
      if (meter) meter.setAttribute('aria-valuenow', String(my_percent));
      if (bar) { bar.style.width = `${my_percent}%`; bar.classList.toggle('is-ready', !!my_ready); }
      if (caption) caption.textContent = my_ready ? 'Ready to go' : `${my_done} of ${my_total} items · ${my_percent}%`;
    });
    document.querySelectorAll('[data-group-ready]').forEach((badge) => { badge.textContent = `${group_ready_count}/${group_size} ready`; });
  };

  const updateTripStatus = ({ trip_status, trip_status_label }) => {
    const pill = $('[data-trip-status]');
    if (!pill || !trip_status) return;
    pill.className = `status-pill status-${trip_status.toLowerCase()}`;
    pill.textContent = trip_status_label;
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
        const data = await assertJson(response);
        paint(form, data.is_complete);      // trust the server's answer
        updateTotals(data);
        updateTripStatus(data);
        updateMyProgress(data);
      } catch (err) {
        showErrorToast(err);
        paint(form, was);                   // revert if it didn't save
        button.classList.add('check-failed');
        window.setTimeout(() => button.classList.remove('check-failed'), 900);
      } finally {
        delete form.dataset.busy;
      }
    }, true);
  });
})();

(() => {
  // Essentials amounts: save in the background (auto-save after a short pause, or Enter / Update).
  document.querySelectorAll('form[data-quantity-form]').forEach((form) => {
    const input = form.querySelector('input[name="quantity"]');
    const status = form.querySelector('[data-quantity-status]');
    if (!input) return;
    let saved = input.value;
    let timer = null;
    let controller = null;
    let statusTimer = null;

    const show = (text, kind) => {
      if (!status) return;
      window.clearTimeout(statusTimer);
      status.textContent = text;
      status.dataset.kind = kind || '';
      if (kind === 'ok') statusTimer = window.setTimeout(() => { status.textContent = ''; }, 1600);
    };

    const save = async () => {
      window.clearTimeout(timer);
      const value = input.value.trim();
      if (value === saved) return;
      const n = Number(value);
      if (!Number.isInteger(n) || n < 1 || n > 999) {
        show('Use 1–999', 'error');
        return;
      }
      if (controller) controller.abort();          // only the latest value matters
      controller = new AbortController();
      show('Saving…', 'busy');
      try {
        const response = await fetch(form.action, {
          method: 'POST',
          body: new FormData(form),
          credentials: 'same-origin',
          headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' },
          signal: controller.signal,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || 'Couldn’t save');
        saved = String(data.quantity);
        if (input.value.trim() === value) input.value = saved;
        show('Saved', 'ok');
      } catch (error) {
        if (error.name === 'AbortError') return;
        input.value = saved;                         // put back the last saved amount
        show(error.message === 'Failed to fetch' ? 'Offline — not saved' : error.message, 'error');
      }
    };

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();             // no page-loading skeleton
      save();
    }, true);
    input.addEventListener('input', () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(save, 700);          // auto-save once typing/stepping pauses
    });
    input.addEventListener('blur', save);
  });
})();

(() => {
  // Header search: live results while typing.
  const input = document.querySelector('[data-user-search]');
  if (!input) return;
  const results = document.querySelector('[data-user-search-results]');
  const menu = input.closest('[data-search-menu]');
  const trigger = menu.querySelector('[data-dropdown-trigger]');
  let timer = null, controller = null, active = -1;

  const hint = (text) => { results.innerHTML = ''; const p = document.createElement('p'); p.className = 'search-hint'; p.textContent = text; results.append(p); };
  const items = () => [...results.querySelectorAll('.search-result')];
  const highlight = (i) => { items().forEach((el, n) => el.classList.toggle('is-active', n === i)); active = i; };

  const render = (people) => {
    results.innerHTML = '';
    if (!people.length) { hint('No travelers found.'); return; }
    people.forEach((p) => {
      const a = document.createElement('a'); a.className = 'search-result'; a.href = p.url; a.setAttribute('role', 'option');
      const av = document.createElement('span'); av.className = 'person-avatar';
      const ini = document.createElement('span'); ini.textContent = p.initials; av.append(ini);
      if (p.avatar_url) { const img = document.createElement('img'); img.src = p.avatar_url; img.alt = ''; img.addEventListener('error', () => img.remove(), { once: true }); av.append(img); }
      const copy = document.createElement('span'); copy.className = 'person-copy';
      const name = document.createElement('strong'); name.textContent = p.name || p.username;
      const handle = document.createElement('small'); handle.textContent = `@${p.username}`;
      copy.append(name, handle); a.append(av, copy);
      if (p.is_friend || p.follows_you) { const b = document.createElement('span'); b.className = `person-badge${p.is_friend ? ' friend' : ''}`; b.textContent = p.is_friend ? 'Friends' : 'Follows you'; a.append(b); }
      results.append(a);
    });
    active = -1;
  };

  const search = async () => {
    const q = input.value.trim();
    if (q.length < 2) { hint('Type at least 2 characters.'); return; }
    if (controller) controller.abort();
    controller = new AbortController();
    hint('Searching…');
    try {
      const r = await fetch(`${input.dataset.endpoint}?q=${encodeURIComponent(q)}`, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' }, signal: controller.signal });
      if (!r.ok) throw new Error();
      render((await r.json()).results || []);
    } catch (e) { if (e.name !== 'AbortError') hint('Search isn’t available right now.'); }
  };

  input.addEventListener('input', () => { window.clearTimeout(timer); timer = window.setTimeout(search, 250); });
  input.addEventListener('keydown', (e) => {
    const list = items();
    if (e.key === 'ArrowDown' && list.length) { e.preventDefault(); highlight((active + 1) % list.length); }
    else if (e.key === 'ArrowUp' && list.length) { e.preventDefault(); highlight((active - 1 + list.length) % list.length); }
    else if (e.key === 'Enter') { const target = list[active] || list[0]; if (target) { e.preventDefault(); target.click(); } }
  });
  trigger.addEventListener('click', () => window.setTimeout(() => { if (trigger.getAttribute('aria-expanded') === 'true') input.focus(); }, 0));
  document.querySelectorAll('[data-open-search]').forEach((b) => b.addEventListener('click', (e) => { e.stopPropagation(); trigger.click(); }));
})();

(() => {
  // Follow / unfollow without reloading. Same form works without JavaScript (falls back to a page load).
  const label = (following, followsMe) => (following && followsMe ? 'Friends' : following ? 'Following' : followsMe ? 'Follow back' : 'Follow');
  const paint = (button, following, followsMe) => {
    button.dataset.following = String(following);
    button.dataset.followsMe = String(followsMe);
    button.classList.toggle('is-following', following);
    button.classList.toggle('button-primary', !following);
    button.textContent = label(following, followsMe);
  };
  document.querySelectorAll('form[data-follow-form]').forEach((form) => {
    const button = form.querySelector('.follow-button');
    // Hovering a "Following"/"Friends" button previews the action.
    button.addEventListener('mouseenter', () => { if (button.dataset.following === 'true') button.textContent = 'Unfollow'; });
    button.addEventListener('mouseleave', () => paint(button, button.dataset.following === 'true', button.dataset.followsMe === 'true'));
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (form.dataset.busy) return;
      const was = button.dataset.following === 'true';
      const followsMe = button.dataset.followsMe === 'true';
      paint(button, !was, followsMe);
      form.dataset.busy = '1';
      try {
        const r = await fetch(form.action, { method: 'POST', body: new FormData(form), credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' } });
        const data = await assertJson(r);
        paint(button, data.i_follow, data.follows_me);
        const count = document.querySelector('[data-followers-count]');
        if (count && typeof data.followers_count === 'number') count.textContent = data.followers_count;
      } catch (err) {
        showErrorToast(err, 'Couldn’t update that follow. Please try again.');
        paint(button, was, followsMe);
      } finally { delete form.dataset.busy; }
    }, true);
  });
})();

(() => {
  // Phone bottom nav: hide while scrolling down, show again on any scroll up.
  const nav = document.querySelector('.sidebar');
  if (!nav) return;
  const phone = window.matchMedia('(max-width: 560px)');
  const body = document.body;
  let lastY = window.scrollY;
  let ticking = false;

  const update = () => {
    ticking = false;
    const y = Math.max(window.scrollY, 0);
    const delta = y - lastY;
    if (!phone.matches || y < 24) {
      body.classList.remove('nav-hidden');       // always visible near the top
    } else if (delta > 6) {
      body.classList.add('nav-hidden');          // scrolling down
    } else if (delta < -6) {
      body.classList.remove('nav-hidden');       // scrolling up
    }
    if (Math.abs(delta) > 6) lastY = y;
  };

  window.addEventListener('scroll', () => {
    if (!ticking) { ticking = true; window.requestAnimationFrame(update); }
  }, { passive: true });
  phone.addEventListener('change', () => body.classList.remove('nav-hidden'));
  // Keyboard users: bring it back when focus moves into it.
  nav.addEventListener('focusin', () => body.classList.remove('nav-hidden'));
})();

// Admin: ask before destructive form submissions (forms marked data-confirm).
document.addEventListener('submit', (event) => {
  const form = event.target;
  if (form instanceof HTMLFormElement && form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
}, true);

// Admin notices: only show the username field when sending to one traveler.
document.querySelectorAll('[data-notice-form]').forEach((form) => {
  const field = form.querySelector('[data-recipient-field]');
  const sync = () => {
    const choice = form.querySelector('input[name$="audience"]:checked');
    if (field) field.hidden = !choice || choice.value !== 'one';
  };
  form.addEventListener('change', sync);
  sync();
});
