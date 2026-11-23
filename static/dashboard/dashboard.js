(() => {
  const body = document.body;
  const countBadge = document.getElementById('live-notification-count');
  const endpoint = body.dataset.notificationEndpoint;
  const feed = document.getElementById('live-notification-feed');

  function renderNotifications(notifications) {
    if (!feed) return;
    if (!notifications.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      const title = document.createElement('strong');
      title.textContent = 'You’re all caught up.';
      const description = document.createElement('p');
      description.textContent = 'New trip and group updates will appear here throughout the day.';
      empty.append(title, description);
      feed.replaceChildren(empty);
      return;
    }

    const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
    const rows = notifications.map((notification) => {
      const row = document.createElement('article');
      row.className = 'notification-page-row';
      const dot = document.createElement('span');
      dot.className = `notification-dot${notification.is_read ? ' read' : ''}`;
      const copy = document.createElement('div');
      copy.className = 'notification-page-copy';
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
        const button = document.createElement('button');
        button.className = 'text-button';
        button.type = 'submit';
        button.textContent = 'Mark read';
        form.append(token, button);
        row.append(form);
      }
      return row;
    });
    feed.replaceChildren(...rows);
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
