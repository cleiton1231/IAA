"use strict";

document.querySelectorAll("[data-copy-run-id]").forEach((button) => {
  button.addEventListener("click", async () => {
    const status = document.querySelector(".copy-status");
    try {
      await navigator.clipboard.writeText(button.dataset.copyRunId);
      if (status) status.textContent = "ID copiado.";
    } catch (_error) {
      if (status) status.textContent = "Não foi possível copiar automaticamente; selecione o ID acima.";
    }
  });
});
