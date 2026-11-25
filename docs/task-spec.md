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
- phase 1 bulk requests are completed by the shared bulk checker after all linked initial and required critical results settle
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
    - existing results are reused without resetting status or changing workflow ownership: completed results are accepted, pending results are waited on, and failed results are reported as failures. Canceled extractions can be queued again. If only one result exists, only the missing extraction is queued.
- What can run next? L2 screening, through the phase 2 citation workflow (implemented). The PDF processing service only extracts text and figures; it accepts no downstream screening or parameter options. Uploading a PDF queues extraction only. Use a phase 2 workflow for L2 chaining and the separate parameter extraction action for parameters.
- entrypoint to queue this process: my_app/services/process_document.py::QueueProcessDocumentService

### L2 screening (+critical screening)
- scope: (citation, question) pair
- Dependencies: 
    - requires PDF to be processed (grobid/text, optionally docint/images/figures, or at least non-pending docint status)
    - L2 questions configured
- can be done immediately, or can be done after L1 screening
- technically, this isn't one task, it's a chain of two tasks (initial prompt, critical prompt) per question
- standalone L2 behavior remains available; phase 2 checks linked initial and required critical results before recording workflow completion
- entrypoint (queue): my_app/services/l2_screening.py::EnqueueL2ScreeningService
    - validates citation prerequisites before deleting any results, loads citation dependencies in one query, bulk-creates results, and dispatches tasks after commit

### Parameter extraction
- scope: (citation, parameter) pair
- dependencies: 
    - requires PDF to be processed (grobid/text, optionally docint/images/figures, or at least non-pending docint status)
    - parameter definitions configured
- can be done immediately, or after L2 screening
- technically, this isn't one task, it's one task per parameter
- phase 3 bulk requests are completed by the shared bulk checker after all linked parameter results settle
- entrypoint (queue): my_app/services/parameter_extraction.py::EnqueueParameterExtractionService


## Checker tasks

Checker tasks monitor workflows made up of multiple background tasks and persist their completion status in the DB. Processing tasks update result records; checkers decide whether the workflow is still pending, has completed, or has failed.

| Checker | Monitors | Updates |
| --- | --- | --- |
| `tasks.bulk_workflow.check_bulk_workflow` | Phase 1 initial/critical results, phase 2 citation workflows, or phase 3 parameter results | `BulkWorkflowRequest.status` and `finished_at` |
| `tasks.phase2_workflow.check_citation_workflow` | The current process for one phase 2 citation | Advances `current_process`, starts the next selected process, or sets request `status`, `finished_at`, and `error` |

The citation checker launches at normal priority. Once it starts a stage, it schedules a check above normal priority using `run_after`. The initial delay is configured by `WORKFLOW_CHECK_INITIAL_SECONDS` (default 5). For L2 screening, this value is the estimated duration of one initial or critical task. The checker delay is that duration multiplied by the larger of 2 and twice the question count divided by `WORKFLOW_EFFECTIVE_SCREENING_WORKERS` (default 1). Use the estimated worker capacity available to one citation. If work is still pending, the checker retries after `WORKFLOW_CHECK_FOLLOWUP_SECONDS` (default 2).

On the shared queue, workflow critical screening and phase 2 stages that follow an earlier stage have the highest priority. Active citation checks come next, followed by launches and first-stage work. Workers can start more citations whenever higher-priority work is unavailable. Running tasks continue uninterrupted, and strict priority does not guarantee fairness across reviews. Bulk completion checks for phases 1 and 2 run below normal priority. Bulk completion checks retain their five-second polling interval, and phase 3 keeps its existing priority.

Each check uses a short transaction and releases the worker between polls. Request locking prevents simultaneous checks from advancing or finishing the same request twice. Checks of terminal requests do nothing.

`finished_at` records when a checker observes a terminal outcome. It is set once for the whole request, not after each subprocess. Execution success is independent of whether screening includes/excludes a citation or a parameter is found.

## Bulk workflows: phases 1, 2, and 3

All three use `BulkWorkflowRequest`. Its fields are `id`, `review`, `phase` (1/2/3, default 2), `requested_by`, `requested_at`, `status`, `finished_at`, `error`, and `cancellation_generation_id`. Status is `pending`, `completed`, `failed`, or `canceled`; requester and finish time can be null, and error defaults to blank.

| Phase | Citation selection | Work and tracking | Complete when |
| --- | --- | --- | --- |
| **1 — L1 screening** | All citations in the review | One initial → critical chain per active, enabled L1 question. Initial results link to the bulk request through `bulk_request`; critical results link to their initial result. | All initial results and required critical results have settled. |
| **2 — PDF/L2 workflow** | Citations whose L1 overall status is `In` | One `Phase2CitationWorkflowRequest` per citation, linked through `bulk_request`. Each independently runs its selected processes, described below. | All citation workflows are terminal. |
| **3 — Parameter extraction** | Citations whose L2 overall status is `In` | One extraction task per active parameter, with results linked through `bulk_request`. No critical screening step. | All extraction results have settled. |

Bulk-layer behavior:

- Selection covers the review and ignores frontend list filters. Users review results and make inclusion/exclusion decisions between phases; finishing one bulk phase does not automatically start another.
- Only one pending bulk request per review/phase is allowed. Different phases may run independently. Phase 2 also permits only one pending workflow per citation, including requests started individually; a conflicting bulk submission is rejected atomically.
- Selected screening/extraction steps require their questions/options or parameters to be configured. Phase 3 also validates completed text and figure extraction for every selected citation before replacing any results.
- Request/result rows are prepared in batches and tasks are dispatched after commit. Phase 2 citations advance independently; a slow citation does not hold up other citations' next steps.
- The checker waits for all work to settle, even if some has failed. The bulk request then fails if any work failed, otherwise completes. An empty batch completes successfully.
- L1/L2 initial results marked `abandoned` need no critical result. A completed initial result requires a completed/abandoned critical result; a missing or pending critical result keeps the workflow pending. Any abandoned result makes the request fail after all work settles.
- Screening and parameter runs replace previous results for the selected citation/question or citation/parameter pairs. Request records preserve request/status information, not historical answers. Question changes and deleted results during a run are not specially accommodated; no question snapshot or expected count is stored.

Queue entrypoints: `services.bulk_workflow.QueueBulkResultsService` handles phases 1/3; `services.phase2_workflow.QueueBulkWorkflowService` handles phase 2. Review-authorized launch/status endpoints exist for each phase, plus a citation-scoped phase 2 endpoint.

## Phase 2 citation workflow

`Phase2CitationWorkflowRequest` records one invocation for one citation. It can run on its own or belong to a phase 2 bulk request.

### Request fields

| Field | Meaning |
| --- | --- |
| `id` | Request identifier. |
| `citation` | Required citation FK. Its current document supplies the PDF and extraction results. |
| `bulk_request` | Optional parent `BulkWorkflowRequest` FK; null for an individual request. |
| `should_download_pdf` | Whether to download a missing PDF; defaults to true. |
| `should_process_pdf` | Whether to queue missing text/figure extraction; defaults to true. |
| `should_run_l2` | Whether to run L2 initial/critical screening; defaults to true. |
| `current_process` | Most recently started process: `not_started` (default), `download_pdf`, `process_pdf`, or `l2`. Terminal outcome is stored in `status`, not this field. |
| `status` | `pending` (default), `completed`, `failed`, or `canceled`. |
| `requested_by` | Optional user FK. |
| `requested_at` | Automatically recorded request creation time. |
| `cancellation_generation_id` | Cancellation boundary captured at launch or inherited from the bulk request. |
| `finished_at` | Null until the checker records completion/failure. |
| `error` | Failure explanation; blank by default. |

At least one process flag must be true. Flags record the requested work and are not cleared as it progresses. There is no document FK or task-group FK on the request.

### Process order and completion

Selected processes always run in this order. Users can omit steps, but downstream prerequisites still apply.

1. **PDF download.** Skip if a PDF is already attached. Otherwise, call `QueueDoiPdfService` and wait for its request to be fulfilled. A missing/invalid DOI or a failed/canceled download fails the citation workflow. An already-pending download is rejected without duplication or reuse. A previously finished download request can be reset and queued again when the PDF is missing.
2. **PDF processing.** Require an attached document. Queue missing text and figure extraction as independent, parallel tasks. Reuse completed or pending results. Failed results cause the workflow to fail after both extractions settle. Queue each missing or canceled extraction.
3. **L2 screening.** Use the current active, enabled L2 questions. Replace previous screening results and queue an initial → critical chain per question. Wait for every linked initial/required critical result to settle. Abandoned results fail the workflow; screening inclusion/exclusion does not affect execution status.

After the last selected process succeeds, the checker marks the citation request completed. A failure stops later processes for that citation; other citation workflows continue.

Text/figure results remain document-scoped, with an optional FK to the workflow that created them. Reuse does not change ownership, so citations sharing a PDF can use results queued by an upload or another workflow. The checker reads the document's results directly; no `gather_tasks()` is used. `QueueProcessDocumentService` only prepares and queues missing extractions. L2 results instead link directly to their citation workflow through `workflow_request`.

Queue entrypoint: `services.phase2_workflow.QueueCitationWorkflowService`. The request does not pin a document or snapshot questions; changing these during execution is not accommodated.

## Failure handling and remaining limits

- Dispatch failures mark the affected workflow-owned result failed/abandoned and allow other independent dispatches to continue. Unexpected processing exceptions also record terminal result states and re-raise for task reporting. Existing prompt-output retries remain unchanged; parameter extraction has no critical follow-up.
- Current L2 and parameter prerequisites require **both** completed text and figure extraction. Optional/failed figure extraction is not supported yet. Skipping PDF processing therefore requires existing successful extraction results.
- Workflows require a backend supporting deferred tasks, such as the configured database backend. The immediate backend is rejected for workflows, though individual processing tasks can still use it.
- DOI recovery and shallow-data download remain unimplemented.


## Task cancellation

Users with access to a review can request cancellation from its detail page. Admins can request cancellation across all reviews from the account dropdown. Each request inserts one timestamped `CancellationGeneration` record. A null review means the record applies globally. Generation refers to an ordinal cancellation boundary.

A new workflow or standalone queue operation snapshots the latest committed cancellation ID, or zero when no cancellation record exists. Bulk and citation workflows store it as `cancellation_generation_id`. All downstream work inherits the original value, including citation workflows within a bulk request, PDF work and L2 screening started by phase 2, and critical screening dispatched by initial screening. Tasks queued before this feature was introduced start at zero.

At entry, tasks check for a higher cancellation ID that applies globally or to their review. A task that clears this check runs to completion, including any follow-up dispatch. Those follow-up tasks check the inherited ID when they start. Workflow checkers record a canceled terminal outcome at their next entry. Skipped screening and parameter results become abandoned, and skipped DOI downloads and document extractions become canceled. A document extraction started for a specific review uses that review's scope even if the document is shared. Older extraction jobs without an originating review use the document's linked reviews.
