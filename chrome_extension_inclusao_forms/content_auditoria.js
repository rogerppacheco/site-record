/**
 * Ponte Auditoria ↔ extensão: sinaliza presença e encaminha o clique "Abrir no Forms".
 */
(function () {
  window.__RECORD_INCLUSAO_EXT__ = true;
  window.dispatchEvent(new CustomEvent("record-inclusao-ext-ready"));

  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin) return;
    const data = event.data;
    if (!data || data.source !== "record-pap-auditoria") return;
    if (data.type !== "RECORD_INCLUSAO_ABRIR_FORMS") return;

    chrome.runtime.sendMessage(
      {
        type: "INCLUSAO_START",
        demandaId: data.demandaId,
        apiBase: data.apiBase,
        accessToken: data.accessToken,
      },
      (resp) => {
        if (chrome.runtime.lastError) {
          alert("Extensão: " + chrome.runtime.lastError.message);
          return;
        }
        if (!resp?.ok) {
          alert("Não foi possível abrir o Forms: " + (resp?.error || "erro desconhecido"));
          return;
        }
        console.info("[Record Inclusão] Forms aberto", resp);
      }
    );
  });
})();
