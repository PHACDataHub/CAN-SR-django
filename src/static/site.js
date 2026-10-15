const data = document.currentScript.dataset;

const {
    featureFlag,
    debug,
    csrfToken,
} = data;

window.DEBUG = JSON.parse(debug);
window.FEATURE_FLAG = JSON.parse(featureFlag);

/* site-wide initialization scripts can go here */

function tdt(str) {
    // This is a placeholder for a translation function
    // In a real app, keep client-side translations to a minimum
    // send exceptional bits through <script> tag data-* attributes 
    return str;
}


document.addEventListener("DOMContentLoaded", function (event) {
    configureMorph();
    configureHtmx();
});


function configureMorph() {
    // ensure that morph-swapped detail tags retain their open/closed state

    const morph = Idiomorph.morph;
    Idiomorph.morph = function (target, content, options = {}) {
        const beforeNodeMorphed = options.callbacks?.beforeNodeMorphed;
        return morph(target, content, {
            ...options,
            callbacks: {
                ...options.callbacks,
                beforeNodeMorphed(current, incoming) {
                    const result = beforeNodeMorphed?.(current, incoming);
                    if (current instanceof HTMLDetailsElement && incoming instanceof HTMLDetailsElement) {
                        // Keep disclosure state while allowing the contents to refresh.
                        incoming.open = current.open;
                    }
                    return result;
                },
            },
        });
    };
}



function getFocusSelector(evt) {
    // checks data-focus-after and HX-Refocus response header for a selector
    // data-focus-after takes precedence
    const trigger = evt.detail.requestConfig?.elt;
    const triggerSelector = trigger?.dataset.focusAfter;

    if (triggerSelector) {
        return triggerSelector;
    }

    const xhr = evt.detail.xhr;
    const responseSelector = xhr.getResponseHeader('HX-Refocus');
    if (responseSelector) {
        return responseSelector;
    }

    return null;

}

function configureHtmx() {

    document.body.addEventListener('htmx:configRequest', (event) => {
        event.detail.headers['X-CSRFToken'] = csrfToken;
    });

    htmx.logger = function (elt, event, data) {
        if (event.toLowerCase().includes("error")) {
            console.error(elt, event, data);
        }
    };

    document.addEventListener("htmx:afterSettle", function (evt) {
        const focusSelector = getFocusSelector(evt);
        if (focusSelector) {
            const element = document.querySelector(focusSelector);
            if (element) {
                setTimeout(() => {
                    element.focus();
                }, 50);
            } else {
                console.warn(`Hx-refocus: element with selector ${focusSelector} not found.`);
            }
        }
    });

}

function announceMessagesToScreenReaders() {
    // Screen readers with aria-live only announce changes to the region, not initial content
    // So we re-insert the messages to trigger an announcement
    const messageBar = document.getElementById('message-bar');
    if (messageBar && messageBar.children.length > 0) {
        const messages = Array.from(messageBar.children);
        messages.forEach(msg => {
            const clone = msg.cloneNode(true);
            messageBar.removeChild(msg);
            // Small delay to ensure screen readers detect the change
            setTimeout(() => {
                messageBar.appendChild(clone);
            }, 100);
        });
    }
}
