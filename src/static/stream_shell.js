// this script is run several times
let data = document.currentScript.dataset;
let { done, stream_closed } = JSON.parse(data.translations);

(function () {
    const shell = document.getElementById("llm-demo-stream-shell");
    if (!shell) {
        return;
    }

    const output = shell.querySelector("[data-stream-output]");
    const status = shell.querySelector("[data-stream-status]");
    const streamUrl = shell.dataset.streamUrl;
    let finished = false;
    const source = new EventSource(streamUrl);

    source.onmessage = function (event) {
        if (event.data === "[DONE]") {
            finished = true;
            status.textContent = done;
            source.close();
            return;
        }

        output.textContent += event.data;
    }

    source.onerror = function () {
        if (finished) {
            return;
        }
        status.textContent = stream_closed;
        source.close();
    }
})();
