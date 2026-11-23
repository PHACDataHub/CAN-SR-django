# Tasks and workflows 

This is a description of the business/workflow logic, focused on background tasks, their dependencies and their sequence

## Individual tasks

These aren't background tasks in the technical sense, but a vague process that cashes out to running one or many background tasks. Some have dependencies, some can queue the next process automatically. 

### Download Shallow Data
- hypothetical at this point, not implemented yet
- scope: review 
    - note: not citation scoped, run once for the entire review
- dependencies: none
- notes:
    - queries up to 3 distinct APIs (pubmed, europePMC, scopus), maybe with retries (small, constant upper-bound number of requests)
    - populates Dataset, Citations, Columns records from the response
- what can run next automatically?
    - not recommended to run more processes automatically until some manual review/tweaking of imported data


### DOI Recovery
- hypothetical at this point, not implemented yet
- scope
    - citation? (one background task per citation)
    - review? might be runnable in bulk for many citations
- dependencies: none
- description: This process would fill in missing DOI information for citations, by using one or many external APIs
- what can run next? if successful (recovered a DOI), PDF auto-download. Depending on 

### L1 Screening (+critical screening)
- scope: (citation, question) pair
- just requires shallow data (title, abstract, json fields, L1 questions configured), no PDF or anything 
- technically, this isn't one task, it's a chain of two tasks (initial prompt, critical prompt) per question. These are sequential, not concurrent: the critical task requires output from the initial task. 
- there is no code that runs on "completing" the entire process.  To query completeness, we check that all results in the DB are non-pending 
- what can run next?
    - we're bundling critical screening in here, but that's technically a separate step, per question
    - no other tasks should ever be run automatically after this process pair
- entrypoint (queue) : src/my_app/services/l1_screening.py::EnqueueL1ScreeningService 
    - this will queue all the initial screening tasks, and each of those will, on success, queue the critical screening task too

### PDF Auto Download (doi_pdf_task)
- scope: citation
- requires a non-empty DOI field, should fail if not present
- What can run next? PDF processing, through the phase 2 citation workflow (implemented).
- notes:
    - phase 2 skips citations with an attached PDF; otherwise it uses the regular queue service, which rejects pending requests and resets finished/failed/canceled requests
    - can be chained after DOI recovery, logic will depend on DOI recovery is done per citation or in bulk for the review. Can even be chained in parallel w/ DOI recovery, e.g. queue PDF download for citations that have DOIs, queue DOI+PDF download for those missing DOIs
- entrypoint (queue): src/my_app/services/doi_pdf_service.py::QueueDoiPdfService

### PDF processing 
- scope: citation
- dependencies: 
    - requires PDF to exist for this citation
- fans out into two parallel tasks
    - grobid/text
    - docint/images 
- completeness check/logic?
    - phase 2's citation checker waits until both the document's `TextExtractionResult` and `FigureExtractionResult` have settled, then continues only if both completed successfully
    - result records remain document-scoped; newly queued extractions also have a nullable FK to the phase 2 workflow that requested them
    - `QueueProcessDocumentService` is an enqueue-only helper shared by uploads and workflows. It creates missing result rows under a document lock and queues text/figure tasks independently after commit. It does not create a task group or check completion.
    - existing results are reused without resetting status or changing workflow ownership: completed results are accepted, pending results are waited on, and failed results are reported as failures rather than automatically retried. If only one result exists, only the missing extraction is queued.
- What can run next? L2 screening, through the phase 2 citation workflow (implemented). The PDF processing service only extracts text and figures; it accepts no downstream screening or parameter options. Uploading a PDF queues extraction only. Use a phase 2 workflow for L2 chaining and the separate parameter extraction action for parameters.
- entrypoint to queue this process: my_app/services/process_document.py::QueueProcessDocumentService

### L2 screening (+critical screening)
- scope: (citation, question) pair
- Dependencies: 
    - requires PDF to be processed (grobid/text, optionally docint/images/figures, or at least non-pending docint status)
    - L2 questions configured
- can be done immediately, or can be done after L1 screening
- technically, this isn't one task, it's a chain of two tasks (initial prompt, critical prompt) per question
- standalone L2 behavior remains available; phase 2 checks all expected initial and critical results before recording workflow completion
- entrypoint (queue): my_app/services/l2_screening.py::EnqueueL2ScreeningService
    - validates citation prerequisites before deleting any results, loads citation dependencies in one query, bulk-creates results, and dispatches tasks after commit

### Parameter extraction
- scope: (citation, parameter) pair
- dependencies: 
    - requires PDF to be processed (grobid/text, optionally docint/images/figures, or at least non-pending docint status)
    - parameter definitions configured
- can be done immediately, or after L2 screening
- technically, this isn't one task, it's one task per parameter
- there is no code that runs on "completing" the entire process. To query completeness, we check that all results in the DB are non-pending 
- entrypoint (queue): my_app/services/parameter_extraction.py::EnqueueParameterExtractionService


## Overall flow and bulk-chaining of tasks

Finally, there are the functions that scope out which citations should be run through these flows. This is best understood as more of a user-story,

1. Users create a systematic review
    - (not implemented) optionally running `DownloadShallowData` then manually cleaning out downloaded citation rows that don't apply, and adding a few manually
    - alternatively or supplementarily, users can manually add citation rows via,
        - CSV/RIS input (implemented)
        - web forms (not implemented)
2. Users run the L1 screening in bulk
    - This is just queuing a bunch of L1 screening initial tasks
        - not implemented yet
        - doesn't _need_ to run in the background, it can run in a request handler provided we refactor for bulk-friendliness to avoid N+1 issues, as the user may be queuing hundreds of citations at once. Right now, the entrypoint to L1 screening is NOT bulk-friendly
    - This is considered complete when all citations are either complete or failed 
3. Users do more manual stuff, looking over screened records, marking citations as included/excluded
4. L1 screened-in citations (using overall status annotation) are then put through a bulk processing flow
    - implemented for PDF download, PDF processing, and L2 screening; DOI recovery remains hypothetical
    - request records are created in bulk; each citation advances independently through its selected processes
    - This is a complex chain of compound processes. Implemented naïvely, a single queue will approximate a breadth-first traversal. We may want to tweak this later. 
    - the sub-processes here, in order, are: 
        1. (hypothetically maybe) DOI recovery supplementation (only rows with empty DOIs, citations can be skipped and move onto the next task otherwise)
        2. PDF downloads (only rows with DOIs and without PDFs, citations can be skipped and move onto the next task otherwise) 
        3. PDF Processing (both grobid/text and docint/images)
        4. L2 screening (one task per question)
    - However, users may start this at any point, opt-out of any step, so we want to remain flexible
5. Users do more manual stuff, marking more inclusions/exclusions
6. The final-list of doubly-screened citations are each put through the Parameter process
    - need another bulk-friendly way to queue all the tasks for every (citation,parameter) pair

### Accordingly, there are 3 bulk-tasks here:

1. Bulk phase 1 processes (L1)
    - not implemented yet
    - queue up (ideally in a bulk-friendly way) all the L1 screening tasks
2. Bulk phase 2 processes
    - implemented: scope in citations with L1 overall status `In`, across the review (independent of list filters)
    - create a `BulkWorkflowRequest` and one `Phase2CitationWorkflowRequest` per selected citation, with boolean PDF download / PDF processing / L2 options
    - citation checker tasks advance each citation independently; a separate bulk checker records completion after every child is terminal
    - DOI recovery remains unimplemented
3. Bulk phase 3 processes (Parameter extraction)
    - not implemented yet
    - scope in appropriate citations, based on L2 overall status
    - queue up all the initial tasks for Parameter extraction, and commit necessary information to the DB so that successful tasks can queue up the next tasks in the chain


## Canceling tasks (not implemented)

There is a review-wide cancel button that will cancel all tasks associated with the review. Every task functions are expected to check for cancellation and terminate early, this can be a simple before-ware type function. Tasks that are already running and have cleared the initial cancellation check don't need to check it again before completion. 


## Implemented phase 2 workflow requests

### Request records and entrypoints

- `my_app.models.Phase2CitationWorkflowRequest` records one invocation for one citation: requester, request/finish timestamps, pending/completed/failed status, error, optional bulk parent, and boolean `should_download_pdf`, `should_process_pdf`, `should_run_l2` options.
- `current_process` records execution position in the fixed order: PDF download → PDF processing → L2. Options describe intent and are not cleared as work progresses. At least one option must be selected.
- `QueueCitationWorkflowService(citation, requested_by=..., should_download_pdf=..., should_process_pdf=..., should_run_l2=...).perform()` creates a request and queues its checker after commit.
- `QueueBulkWorkflowService(review, ...same options...).perform()` selects all citations whose L1 overall status is `In`, creates all citation requests in bulk, then queues their checkers and a bulk checker after commit.
- The bulk parent stores review, requester, timestamps, status and error. Effective options are stored on its citation children.
- Only one pending phase 2 workflow per citation is permitted, enforced by a database constraint. A bulk submission containing an already-pending citation is rejected atomically; completed or failed workflows may be requested again.
- L2 uses the review's current active, enabled questions when screening starts. Questions/options must be configured when requesting L2. No question snapshot or expected count is stored; changing questions during a workflow is not accommodated.
- L2 results created by a workflow reference that request. Existing answers are replaced when the L2 process starts; this does not retain historical answers.
- Launch/status pages are linked from the L2 list: a bulk launch above the list and a citation launch on each row. Pages use the existing review access permission. Status pages have a manual refresh link.

### Fixed process order and skips

1. Download a missing PDF if requested. An attached PDF skips downloading. The workflow calls `QueueDoiPdfService` directly: an already-pending download is rejected without queuing a duplicate, and the workflow fails. Previously finished/failed/canceled download requests are reset and queued using the same behavior as a standalone request. Missing/invalid DOI fails rather than attempting DOI recovery. No PDF download run ID is stored on the workflow.
2. Process the PDF if requested. An attached document is required. `QueueProcessDocumentService` creates and queues only missing text/figure extractions in parallel; existing document results are reused. The citation checker reads both result statuses directly from the document and waits for both to settle before reporting failures or advancing. A shared PDF is not processed again for each citation. The workflow has no task-group FK and uses no `gather_tasks()` call. The document is always obtained from the citation; document replacement during a workflow is not accommodated.
3. Run L2 if requested. If PDF processing was omitted, existing text and figure extraction must already be completed. Both extractions remain required, matching current L2 prerequisites; optional/failed figure extraction is not implemented. One initial task is dispatched per current active, enabled question, and each successful initial task dispatches its critical task as before.

L1 and parameter workflows, their bulk flows, DOI recovery, and review-wide cancellation are outside this implementation.

### Two checker levels

Checker tasks are background tasks that repeatedly check the status of ongoing processes. They reschedule themselves until the process they monitor reaches a terminal state, ensuring that workflows progress without blocking worker threads.

- New `my_app.tasks.phase2_workflow.check_citation_workflow`: checks the current citation process, advances one process at a time, and reschedules after five seconds while the workflow remains pending. It loads the request and citation through cached properties using `select_for_update()` inside its transaction, and terminal/missing requests are no-ops. Separate helpers check completion and start each process (PDF download, PDF processing, and L2); `advance()` only selects the next process or marks the workflow completed.
- New `my_app.tasks.phase2_workflow.check_bulk_workflow`: checks child workflow statuses and reschedules after five seconds while any child is pending. A failed child does not stop other citations. After all settle, the parent is failed if any child failed, otherwise completed. An empty batch completes successfully.

All checks are short background tasks; no worker sleeps while waiting. New phase 2 workflows require a backend supporting deferred tasks (the configured database backend); the immediate backend is rejected.

### Completion and failures

- PDF completion means the document's text and figure results both settled successfully. `current_process` remains `process_pdf` until both settle; the workflow checker owns completion and advancement. Existing result ownership does not affect reuse, so a workflow can wait for work originally queued by an upload or another citation workflow.
- L2 completion checks the result rows linked to the workflow: all must be completed/abandoned. Every completed initial result must also have a completed/abandoned critical result. Missing critical rows remain incomplete; abandoned initial results do not require a critical row.
- L2 waits for every pair to settle even if another pair is abandoned. Any abandoned initial or critical result makes the citation workflow fail after settlement. This is execution success, independent of whether answers screen the citation in or out.
- Figure extraction records `FAILED` outside its rolled-back extraction transaction, allowing later retries while preserving previous extracted data.
- An initial L2 dispatch failure abandons that result and logs the error while allowing dispatch of the other results to continue. Critical dispatch failures also abandon the pending critical result.
- Unexpected initial/critical task errors mark workflow-owned pending results abandoned and re-raise, so a failed task cannot leave the workflow waiting forever. Standalone task error behavior remains unchanged. Existing prompt-output retries still run inside the processing services.
- Preparation/dispatch errors mark the workflow failed; unexpected exceptions are also re-raised for task error reporting. Failures stop further processes for that citation.
- Citation `finished_at` is set when its checker recognizes a terminal outcome, not after every subprocess. Bulk `finished_at` similarly records when the bulk checker observes all children terminal. These timestamps are not rewritten by repeated checks.
- No generic checker framework or task afterware is introduced. Processing tasks update results; checkers own advancement and workflow completion.
