const PDFJS_VERSION = '4.10.38';
const PDFJS_URL = `https://cdn.jsdelivr.net/npm/pdfjs-dist@${PDFJS_VERSION}/build/pdf.mjs`;
const PDFJS_WORKER_URL = `https://cdn.jsdelivr.net/npm/pdfjs-dist@${PDFJS_VERSION}/build/pdf.worker.mjs`;

const args = document.getElementById('l2-citation-data').dataset;
const pagesElement = document.getElementById('l2-pdf-pages');
const scrollElement = document.getElementById('l2-pdf-scroll');
const statusElement = document.getElementById('l2-pdf-status');

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

function sentenceHighlights(sentenceIndex) {
    return Array.from(
        pagesElement.querySelectorAll(
            `.l2-pdf-highlight[data-sentence-index="${sentenceIndex}"]`,
        ),
    );
}

function updateSentenceHighlightState(sentenceIndex) {
    const highlights = sentenceHighlights(sentenceIndex);
    const isActive = highlights.some((highlight) => highlight.matches(':hover, :focus'));

    highlights.forEach((highlight) => {
        highlight.classList.toggle('l2-pdf-highlight-active', isActive);
    });
}

function renderHighlight(highlight, pageInfo, viewport) {
    const box = document.createElement('button');
    const xScale = viewport.width / numberValue(pageInfo.width);
    const yScale = viewport.height / numberValue(pageInfo.height);
    const sentenceIndex = Number.parseInt(highlight.sentence_index, 10);

    box.type = 'button';
    box.className = 'l2-pdf-highlight';
    box.dataset.sentenceIndex = String(sentenceIndex);
    box.title = `${tdt('Sentence')} ${sentenceIndex}`;
    box.setAttribute('aria-label', `${tdt('Sentence')} ${sentenceIndex}`);
    box.style.left = `${numberValue(highlight.x) * xScale}px`;
    box.style.top = `${numberValue(highlight.y) * yScale}px`;
    box.style.width = `${numberValue(highlight.width) * xScale}px`;
    box.style.height = `${numberValue(highlight.height) * yScale}px`;
    ['mouseenter', 'mouseleave', 'focus', 'blur'].forEach((eventName) => {
        box.addEventListener(eventName, () => {
            updateSentenceHighlightState(sentenceIndex);
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

    pageElement.className = 'l2-pdf-page';
    pageElement.dataset.pageNumber = String(pageNumber);
    pageElement.style.width = `${viewport.width}px`;
    pageElement.style.height = `${viewport.height}px`;
    canvas.width = Math.floor(viewport.width * outputScale);
    canvas.height = Math.floor(viewport.height * outputScale);
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;
    overlayElement.className = 'l2-pdf-overlay';
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

function scrollToSentenceIndex(sentenceIndex) {
    const highlight = pagesElement.querySelector(
        `.l2-pdf-highlight[data-sentence-index="${sentenceIndex}"]`,
    );
    if (!highlight) {
        setStatus(
            `${tdt('Sentence')} ${sentenceIndex} ${tdt('could not be located in the PDF.')}`,
        );
        return;
    }

    highlight.scrollIntoView({behavior: 'smooth', block: 'center'});
    highlight.focus({preventScroll: true});
}

function bindEvidenceChips() {
    document.querySelectorAll('.l2-evidence-chip').forEach((chip) => {
        chip.addEventListener('click', () => {
            scrollToSentenceIndex(chip.dataset.sentenceIndex);
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

initializePdfViewer();
