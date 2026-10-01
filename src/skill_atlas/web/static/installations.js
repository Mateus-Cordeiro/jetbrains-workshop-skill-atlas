(() => {
  const feedback = document.getElementById("installation-feedback");
  try {
    const saved = sessionStorage.getItem("atlas-installation-message");
    if (saved) {
      feedback.textContent = saved;
      sessionStorage.removeItem("atlas-installation-message");
    }
  } catch (_) { /* Storage is optional. */ }
  document.querySelector('.installation-form[method="get"]').addEventListener("input", () => {
    document.querySelectorAll('[data-installation-action="install"] button, [data-installation-action="update"] button')
      .forEach(button => { button.disabled = true; });
  });
  let pending = false;
  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("form[data-installation-action]");
    if (!form) return;
    event.preventDefault();
    if (pending) return;
    pending = true;
    const buttons = [...document.querySelectorAll("form[data-installation-action] button")];
    const states = buttons.map(button => button.disabled);
    buttons.forEach(button => { button.disabled = true; });
    feedback.textContent = "Working…";
    try {
      const body = new URLSearchParams(new FormData(form));
      const response = await fetch(`/installations/${form.dataset.installationAction}`, {
        method: "POST", headers: {"X-Atlas-Request": "1"}, body,
      });
      const result = await response.json();
      feedback.textContent = result.message;
      if (response.ok) {
        try { sessionStorage.setItem("atlas-installation-message", result.message); } catch (_) { /* Optional notice. */ }
        window.location.reload();
      } else {
        feedback.focus();
      }
    } catch (_) {
      feedback.textContent = "The request could not finish. Refresh status before retrying; it may have completed.";
      feedback.focus();
    } finally {
      pending = false;
      buttons.forEach((button, index) => { button.disabled = states[index]; });
    }
  });
})();
