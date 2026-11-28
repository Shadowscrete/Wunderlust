(() => {
  const form = document.querySelector('[data-profile-setup]');
  if (!form) return;

  const row = form.querySelector('.field-row');
  const control = row.querySelector('input, select, textarea');
  const popup = row.querySelector('[data-setup-error]');

  const shake = () => {
    control.classList.remove('setup-field-shake');
    void control.offsetWidth;
    control.classList.add('setup-field-shake');
  };

  const showError = (message) => {
    if (message) popup.textContent = message;
    popup.hidden = false;
    row.classList.add('has-error');
    control.setAttribute('aria-invalid', 'true');
    control.setAttribute('aria-describedby', popup.id);
    control.focus();
    shake();
  };

  control.addEventListener('invalid', (event) => {
    event.preventDefault();
    if (control.type === 'date') {
      if (control.validity.rangeOverflow) {
        showError('You must be at least 13 years old to continue.');
        return;
      }
      showError('Enter a valid date of birth.');
      return;
    }
    showError(control.validationMessage);
  });

  const dismissError = () => {
    if (popup.hidden || !control.validity.valid) return;
    popup.hidden = true;
    row.classList.remove('has-error');
    control.classList.remove('setup-field-shake');
    control.removeAttribute('aria-invalid');
    control.removeAttribute('aria-describedby');
  };

  control.addEventListener('input', dismissError);
  control.addEventListener('change', dismissError);
  if (!popup.hidden) showError();
})();
