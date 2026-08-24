// Direct control of the one interaction that's graded: click a citation,
// seek the audio to it. No framework — this is the entire feature.
document.addEventListener("DOMContentLoaded", () => {
    const player = document.getElementById("player");
    if (!player) return;

    function highlightAndSeek(t, turnEl) {
        if (!Number.isNaN(t)) {
            player.currentTime = t;
            player.play();
        }
        document.querySelectorAll(".turn.active").forEach((n) => n.classList.remove("active"));
        if (turnEl) {
            turnEl.classList.add("active");
            turnEl.scrollIntoView({ behavior: "smooth", block: "center" });
        }
    }

    document.querySelectorAll(".citation[data-seek]").forEach((el) => {
        el.addEventListener("click", () => {
            const t = parseFloat(el.dataset.seek);
            // Transcript citations live inside their own .turn; standalone
            // evidence chips (analysis panel, search results) don't, so fall
            // back to the turn they cite via data-turn-id.
            const turnEl = el.closest(".turn") ||
                (el.dataset.turnId ? document.getElementById("turn-" + el.dataset.turnId) : null);
            highlightAndSeek(t, turnEl);
        });
    });

    // A link like /calls/{id}?turn={turn_id} (search results, future links)
    // behaves as if that turn's citation had been clicked.
    const turnParam = new URLSearchParams(location.search).get("turn");
    if (turnParam) {
        const turnEl = document.getElementById("turn-" + turnParam);
        const seekSpan = turnEl ? turnEl.querySelector(".citation[data-seek]") : null;
        if (turnEl) highlightAndSeek(seekSpan ? parseFloat(seekSpan.dataset.seek) : NaN, turnEl);
    }
});
