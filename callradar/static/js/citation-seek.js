// Direct control of the one interaction that's graded: click a citation,
// seek the audio to it. No framework — this is the entire feature.
document.addEventListener("DOMContentLoaded", () => {
    const player = document.getElementById("player");
    if (!player) return;

    document.querySelectorAll(".citation[data-seek]").forEach((el) => {
        el.addEventListener("click", () => {
            const t = parseFloat(el.dataset.seek);
            if (Number.isNaN(t)) return;
            player.currentTime = t;
            player.play();

            document.querySelectorAll(".turn.active").forEach((n) => n.classList.remove("active"));
            const turnEl = el.closest(".turn");
            if (turnEl) turnEl.classList.add("active");
        });
    });
});
