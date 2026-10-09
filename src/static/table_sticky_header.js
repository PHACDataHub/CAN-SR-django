/*
    This helps the sticky header be less annoyingly tall
    without JS, the header is a bit taller, and won't re-adjust after resizing
*/
(() => {
    function initializeStickyHeaders() {
        document.querySelectorAll(".stickyheader-table-container thead").forEach((header) => {
            const tableContainer = header.closest(".stickyheader-table-container");
            if (header.dataset.stickyHeaderInitialized) return;
            const cell = header.querySelector("th");
            if (!cell) return;
            header.dataset.stickyHeaderInitialized = "true";

            function updateHeaderHeight() {
                const style = getComputedStyle(cell);
                const bottomInset = parseFloat(style.paddingBottom) + parseFloat(style.borderBottomWidth);
                tableContainer.style.setProperty("--table-header-height", `${header.getBoundingClientRect().height}px`);
                tableContainer.style.setProperty("--table-header-bottom-inset", `${bottomInset}px`);
            }

            updateHeaderHeight();
            const observer = new ResizeObserver(updateHeaderHeight);
            observer.observe(header);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initializeStickyHeaders, { once: true });
    } else {
        initializeStickyHeaders();
    }
})();
