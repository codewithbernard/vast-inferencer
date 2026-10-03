# Must match functions.src/app.py.maxDuration in vercel.json.
VERCEL_MAX_DURATION_SECONDS = 800

VAST_WORKER_TIMEOUT_SECONDS = 600.0
# Only bounds waiting for a worker; the worker call adds up to VAST_WORKER_TIMEOUT_SECONDS,
# and the sum must stay under VERCEL_MAX_DURATION_SECONDS.
VAST_REQUEST_TIMEOUT_SECONDS = 160.0
# Must match the worker's per-request workload (pyworker default: 100).
VAST_REQUEST_COST = 100
VAST_MAX_RETRIES: int | None = None

QSTASH_RETRIES = 2
QSTASH_TIMEOUT = "810s"
QSTASH_RETRY_DELAY = "pow(2, retried) * 1000"

SWEEP_BATCH_SIZE = 50
STUCK_RUNNING_SECONDS = VERCEL_MAX_DURATION_SECONDS + 60
# Every QStash delivery attempt must have ended before a queued row counts as stuck.
STUCK_QUEUED_SECONDS = (QSTASH_RETRIES + 1) * (VERCEL_MAX_DURATION_SECONDS + 60)
