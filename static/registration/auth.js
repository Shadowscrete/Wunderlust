document.querySelectorAll('.password-toggle').forEach((toggle) => {
    toggle.addEventListener('click', () => {
        const input = toggle.parentElement.querySelector('input');
        if (!input) return;

        const showPassword = input.type === 'password';
        input.type = showPassword ? 'text' : 'password';
        toggle.textContent = showPassword ? 'Hide' : 'Show';
        toggle.setAttribute('aria-pressed', String(showPassword));
        toggle.setAttribute('aria-label', showPassword ? 'Hide password' : 'Show password');
    });
});
