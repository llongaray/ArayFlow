"use strict";
(function () {
  const search = document.getElementById("post-search");
  const filter = document.getElementById("post-filter");
  const rows = [...document.querySelectorAll("tr.post-row")];
  const count = document.getElementById("visible-count");
  const empty = document.querySelector(".filter-empty");
  function applyFilters() {
    const query = (search?.value || "").trim().toLocaleLowerCase("pt-BR");
    const status = filter?.value || "all";
    let visible = 0;
    for (const row of rows) {
      const matchText = !query || (row.dataset.text || "").includes(query);
      const matchStatus =
        status === "all" ||
        (status === "approved" && row.dataset.approved === "yes") ||
        (status === "review" && row.dataset.approved !== "yes") ||
        (status === "suite" && row.dataset.suite === "scheduled") ||
        (status === "published" && row.dataset.meta === "published");
      const show = matchText && matchStatus;
      row.hidden = !show;
      if (show) visible++;
    }
    if (count) count.textContent = String(visible);
    if (empty) empty.hidden = rows.length === 0 || visible > 0;
  }
  search?.addEventListener("input", applyFilters);
  filter?.addEventListener("change", applyFilters);
  document.querySelectorAll("button[data-copy-target]").forEach((button) => {
    button.addEventListener("click", async () => {
      const target = document.getElementById(button.dataset.copyTarget);
      if (!target) return;
      try {
        await navigator.clipboard.writeText(target.textContent.trim());
        const previous = button.textContent;
        button.textContent = "Copiado!";
        window.setTimeout(() => { button.textContent = previous; }, 1500);
      } catch (_) {
        button.textContent = "Selecione e copie";
      }
    });
  });
})();
