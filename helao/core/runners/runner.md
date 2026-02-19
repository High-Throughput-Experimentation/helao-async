# action/experiment/sequence library runners

Runners are an alternative to the Orchestrator scheduling and queuing framework. They behave as "micro-orchestrators" which provide short-lived API endpoints for starting, stopping, resuming, checking status, and returning deferred updates.

The drawback to using runners is there is no assumed backend service, e.g. a long-lived orchestrator service, which has direct jurisdiction over queued and ongoing actions/experiments/sequences. Instead, the runner is known only to its calling frame.

A runner object maintains state:
    1. counter for dispatched children
    2. run status -- not started / running / paused / finished
    3. child outputs
    4. caller
    5. subscribed servers