const PDFJS_VERSION = '4.10.38';
const PDFJS_URL = `https://cdn.jsdelivr.net/npm/pdfjs-dist@${PDFJS_VERSION}/build/pdf.mjs`;
const PDFJS_WORKER_URL = `https://cdn.jsdelivr.net/npm/pdfjs-dist@${PDFJS_VERSION}/build/pdf.worker.mjs`;

const dataElement = document.querySelector('[data-pdf-url], [data-metadata-url]');
const args = dataElement ? dataElement.dataset : {};
const pagesElement = document.getElementById('citation-pdf-pages');
const scrollElement = document.getElementById('citation-pdf-scroll');
const statusElement = document.getElementById('citation-pdf-status');

let pdfDocument = null;
let metadata = null;
let renderVersion = 0;
let resizeTimeout = null;

document.body.addEventListener('citations-update', () => {
    window.location.reload();
});

function setStatus(message) {
    statusElement.textContent = message;
}

function numberValue(value) {
    return Number.parseFloat(value);
}

function pageHighlights(pageNumber) {
    return metadata.highlights.filter(
        (highlight) => Number.parseInt(highlight.page, 10) === pageNumber,
    );
}

function evidenceSelector(evidenceType, evidenceIndex) {
    return `.citation-pdf-highlight[data-evidence-type="${evidenceType}"][data-evidence-index="${evidenceIndex}"]`;
}

function evidenceLabel(evidenceType) {
    if (evidenceType === 'table') {
        return tdt('Table');
    }
    if (evidenceType === 'figure') {
        return tdt('Figure');
    }
    return tdt('Sentence');
}

function evidenceHighlights(evidenceType, evidenceIndex) {
    return Array.from(
        pagesElement.querySelectorAll(
            evidenceSelector(evidenceType, evidenceIndex),
        ),
    );
}

function updateEvidenceHighlightState(evidenceType, evidenceIndex) {
    const highlights = evidenceHighlights(evidenceType, evidenceIndex);
    const isActive = highlights.some((highlight) => highlight.matches(':hover, :focus'));

    highlights.forEach((highlight) => {
        highlight.classList.toggle('citation-pdf-highlight-active', isActive);
    });
}

function renderHighlight(highlight, pageInfo, viewport) {
    const box = document.createElement('button');
    const xScale = viewport.width / numberValue(pageInfo.width);
    const yScale = viewport.height / numberValue(pageInfo.height);
    const evidenceType = highlight.evidence_type || 'sentence';
    const evidenceIndex = Number.parseInt(
        highlight.evidence_index ?? highlight.sentence_index,
        10,
    );
    const label = evidenceLabel(evidenceType);

    box.type = 'button';
    box.className = `citation-pdf-highlight citation-pdf-highlight-${evidenceType}`;
    box.dataset.evidenceType = evidenceType;
    box.dataset.evidenceIndex = String(evidenceIndex);
    box.title = `${label} ${evidenceIndex}`;
    box.setAttribute('aria-label', `${label} ${evidenceIndex}`);
    box.style.left = `${numberValue(highlight.x) * xScale}px`;
    box.style.top = `${numberValue(highlight.y) * yScale}px`;
    box.style.width = `${numberValue(highlight.width) * xScale}px`;
    box.style.height = `${numberValue(highlight.height) * yScale}px`;
    ['mouseenter', 'mouseleave', 'focus', 'blur'].forEach((eventName) => {
        box.addEventListener(eventName, () => {
            updateEvidenceHighlightState(evidenceType, evidenceIndex);
        });
    });

    return box;
}

async function renderPage(pageNumber, version) {
    const page = await pdfDocument.getPage(pageNumber);
    if (version !== renderVersion) {
        return null;
    }

    const baseViewport = page.getViewport({scale: 1});
    const availableWidth = Math.max(pagesElement.clientWidth - 32, 240);
    const scale = Math.min(availableWidth / baseViewport.width, 1.75);
    const viewport = page.getViewport({scale});
    const outputScale = window.devicePixelRatio || 1;
    const canvas = document.createElement('canvas');
    const canvasContext = canvas.getContext('2d');
    const pageElement = document.createElement('div');
    const overlayElement = document.createElement('div');

    pageElement.className = 'citation-pdf-page';
    pageElement.dataset.pageNumber = String(pageNumber);
    pageElement.style.width = `${viewport.width}px`;
    pageElement.style.height = `${viewport.height}px`;
    canvas.width = Math.floor(viewport.width * outputScale);
    canvas.height = Math.floor(viewport.height * outputScale);
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;
    overlayElement.className = 'citation-pdf-overlay';
    overlayElement.style.width = `${viewport.width}px`;
    overlayElement.style.height = `${viewport.height}px`;

    pageElement.append(canvas, overlayElement);
    pagesElement.append(pageElement);

    const pageInfo = metadata.pages[pageNumber - 1];
    if (pageInfo) {
        overlayElement.append(
            ...pageHighlights(pageNumber).map(
                (highlight) => renderHighlight(highlight, pageInfo, viewport),
            ),
        );
    }

    await page.render({
        canvasContext,
        transform: outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0],
        viewport,
    }).promise;

    return pageElement;
}

async function renderDocument() {
    const version = ++renderVersion;
    pagesElement.replaceChildren();
    setStatus(tdt('Rendering PDF...'));

    for (let pageNumber = 1; pageNumber <= pdfDocument.numPages; pageNumber += 1) {
        await renderPage(pageNumber, version);
        if (version !== renderVersion) {
            return;
        }
    }

    if (pdfDocument.numPages === 1) {
        setStatus(`1 ${tdt('page')}`);
    } else {
        setStatus(`${pdfDocument.numPages} ${tdt('pages')}`);
    }
}

function scrollToEvidence(evidenceType, evidenceIndex) {
    const label = evidenceLabel(evidenceType);
    const highlight = pagesElement.querySelector(evidenceSelector(evidenceType, evidenceIndex));
    if (!highlight) {
        setStatus(
            `${label} ${evidenceIndex} ${tdt('could not be located in the PDF.')}`,
        );
        return;
    }

    highlight.scrollIntoView({behavior: 'smooth', block: 'center'});
    highlight.focus({preventScroll: true});
}

function bindEvidenceChips() {
    document.querySelectorAll('.evidence-chip').forEach((chip) => {
        chip.addEventListener('click', () => {
            const evidenceType = chip.dataset.evidenceType || 'sentence';
            const evidenceIndex = chip.dataset.evidenceIndex ?? chip.dataset.sentenceIndex;
            scrollToEvidence(evidenceType, evidenceIndex);
        });
    });
}

function bindResizeHandler() {
    const observer = new ResizeObserver(() => {
        window.clearTimeout(resizeTimeout);
        resizeTimeout = window.setTimeout(() => {
            renderDocument();
        }, 150);
    });
    observer.observe(scrollElement);
}

async function initializePdfViewer() {
    bindEvidenceChips();

    if (!args.pdfUrl || !args.metadataUrl) {
        return;
    }

    try {
        const [pdfjsLib, metadataResponse] = await Promise.all([
            import(PDFJS_URL),
            fetch(args.metadataUrl),
        ]);
        if (!metadataResponse.ok) {
            throw new Error(`Metadata request failed with status ${metadataResponse.status}`);
        }

        metadata = await metadataResponse.json();
        pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL;
        pdfDocument = await pdfjsLib.getDocument(args.pdfUrl).promise;
        await renderDocument();
        bindResizeHandler();
    } catch (error) {
        console.error(error);
        setStatus(tdt('The PDF could not be loaded.'));
    }
}

if (pagesElement && scrollElement && statusElement) {
    initializePdfViewer();
}
