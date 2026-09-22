document.querySelectorAll('[data-column-mapping-row]').forEach((row) => {
    const existing = row.querySelector('[data-column-existing]');
    const name = row.querySelector('[data-column-name]');
    const include = row.querySelector('[data-column-include]');

    function updateState() {
        name.disabled = Boolean(existing.value);
        row.classList.toggle('citation-column-mapping-omitted', !include.checked);
    }

    existing.addEventListener('change', updateState);
    include.addEventListener('change', updateState);
    updateState();
});
