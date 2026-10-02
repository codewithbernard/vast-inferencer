# Vast Inferencer

FastAPI control plane for [Vast Serverless](https://docs.vast.ai/guides/serverless) ComfyUI video generation. Vast runs the GPU work. This service is the source of truth for inference endpoints, projects, generation requests, statuses, timings, outputs, errors, and provider responses.

The public API returns as soon as the job is durable. [Upstash QStash](https://upstash.com/docs/qstash) calls the worker, and the worker calls Vast `POST /generate/sync` so the GPU stays occupied until generation finishes. Do not switch that worker route to `POST /generate`.

## Flow

1. `POST /v1/projects/{project_id}/generations` checks the bearer token, writes a `queued` generation, and publishes that generation ID to QStash.
2. The API responds `202` with `{"id", "status": "queued"}`.
3. QStash signs and delivers the job to `POST /internal/generations`.
4. The worker claims the row with a conditional update. Only a `queued` row can move to `running`. A retry finds `running`, `completed`, or `failed` and does not call Vast again.
5. The worker calls that generation's Vast endpoint at `/generate/sync`, with S3 and webhook settings copied from the project.
6. Vast uploads the file to the project bucket and POSTs the wrapper result to `/webhooks/comfyui`.
7. Whichever completion signal arrives first updates the generation. The other one fills in anything still empty.
8. If the generation or the project has a webhook URL, this service POSTs the Vast webhook body and `X-Webhook-Signature` to that URL.

S3 credentials, the Vast API key, the QStash token, and webhook secrets are never accepted on the public generation route. They are loaded from the project row. The stored provider request redacts those values. Generation outputs and the stored webhook payload are kept as Vast sent them.

## Local setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Generate an encryption key and put it in `SECRETS_ENCRYPTION_KEY`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put the Neon pooled Postgres URL in `DATABASE_URL`. Apply the schema yourself:

```bash
alembic upgrade head
```

```bash
uvicorn app:app --app-dir src --reload
```

Open [http://127.0.0.1:8000/admin](http://127.0.0.1:8000/admin) to manage endpoints and projects. Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) for the request playground. The bearer key is kept in page memory only.

## Configuration

Set these in `.env` locally and as encrypted environment variables on Vercel:

| Variable | Purpose |
| --- | --- |
| `VAST_API_KEY` | Vast API key used by the Python SDK |
| `QSTASH_URL` | QStash region URL, such as `https://qstash-us-east-1.upstash.io` |
| `QSTASH_TOKEN` | Token used to publish background jobs |
| `QSTASH_CURRENT_SIGNING_KEY` | Current QStash signing key |
| `QSTASH_NEXT_SIGNING_KEY` | Next QStash signing key, used during key rotation |
| `PUBLIC_APP_URL` | Exact public origin QStash and Vast call, without a trailing slash |
| `API_BEARER_KEY` | Bearer token required by the management and generation routes |
| `DATABASE_URL` | Neon Postgres URL. `sslmode=require` is accepted |
| `SECRETS_ENCRYPTION_KEY` | Fernet key for project S3 and webhook secrets |

Timeouts, retries, and QStash delivery limits are constants in [`src/vast_inferencer/limits.py`](src/vast_inferencer/limits.py).

Changing `SECRETS_ENCRYPTION_KEY` makes existing project secrets unreadable. Create the key once and keep it.

## Seed the existing project

Create an inference endpoint and a project. The storage password that used to live in `AI_OFM_STUDIO_STORAGE_PASSWORD` is now the project S3 secret. The old environment variable is not read.

```bash
curl -X POST http://127.0.0.1:8000/v1/inference-endpoints \
  -H "Authorization: Bearer $API_BEARER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"MiniMax H3","vast_endpoint_name":"minimax-h3","enabled":true}'
```

```bash
curl -X POST http://127.0.0.1:8000/v1/projects \
  -H "Authorization: Bearer $API_BEARER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "AI OFM Studio",
    "slug": "ai-ofm-studio",
    "s3": {
      "access_key_id": "ai-ofm-studio",
      "secret_access_key": "<bunny storage password>",
      "endpoint_url": "https://de-s3.storage.bunnycdn.com",
      "bucket_name": "ai-ofm-studio",
      "region": "de"
    },
    "webhook_url": "https://example.com/hooks/generation",
    "webhook_secret": "<shared secret>"
  }'
```

A project stores S3 and webhook settings. Each generation request chooses its Vast endpoint by `vast_endpoint_name` and stores the endpoint ID it actually used, so later endpoint changes do not rewrite history.

If you omit `webhook_secret`, one is generated and stored encrypted. Set it yourself when the downstream receiver verifies `X-Webhook-Signature`.

## API

All `/v1` routes require `Authorization: Bearer $API_BEARER_KEY`.

```text
GET    /v1/inference-endpoints
POST   /v1/inference-endpoints
GET    /v1/inference-endpoints/{endpoint_id}
PATCH  /v1/inference-endpoints/{endpoint_id}

GET    /v1/projects
POST   /v1/projects
GET    /v1/projects/{project_id}
PATCH  /v1/projects/{project_id}

GET    /v1/generations
GET    /v1/projects/{project_id}/generations
POST   /v1/projects/{project_id}/generations
GET    /v1/generations/{generation_id}
POST   /v1/generations
```

`POST /v1/generations` is the previous caller shape: `project_id` is the project slug. Both generation POST routes require `vast_endpoint_name`.

```bash
curl -X POST http://127.0.0.1:8000/v1/generations \
  -H "Authorization: Bearer $API_BEARER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "ai-ofm-studio",
    "vast_endpoint_name": "minimax-h3",
    "workflow_json": {"90": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5"}}},
    "webhook_extra_params": {"user_id": "12345"},
    "webhook_url": "https://example.com/hooks/this-request"
  }'
```

```json
{
  "id": "5d0c0c3e-1f2a-4d4e-9c1a-0a0c2f5e6b7d",
  "status": "queued"
}
```

`workflow_json` must be ComfyUI API-format JSON. `webhook_url` overrides the project forward destination for that generation only. `GET /health` is unauthenticated.

Generation lists accept `status`, `limit` (1–200), and `before` (a `created_at` cursor).

Project responses show S3 keys as `[REDACTED]` and `webhook_secret_set`. They never return the secret values.

## Webhooks

Vast is given this service's `/webhooks/comfyui` URL and the project webhook secret. The wrapper signs the raw body with HMAC-SHA256 and sends `X-Webhook-Signature: sha256=<hex>`.

When that webhook arrives, this service stores it, then POSTs the same body and `X-Webhook-Signature` to the generation webhook URL, or the project webhook URL when the request did not set one. A failed forward is logged and not retried.

The wrapper payload and the `/generate/sync` result can both arrive. That is expected. A completed generation is not moved back to failed.

## Idempotency

QStash delivery is at least once. The generation ID is the deduplication ID, and the claim update is the real guard:

```sql
UPDATE generations
SET status = 'running', started_at = NOW(), attempts = attempts + 1
WHERE id = :id AND status = 'queued'
```

A delivery that loses the claim returns success and does not call Vast. If a claimed generation is still `running` after the Vercel function limit, a later delivery marks it `failed` with `worker_lost` and still does not start another GPU job.

Permanent QStash failures return HTTP 489 with `Upstash-NonRetryable-Error: true`. Once a generation is claimed, worker failures are stored on the row and the delivery returns HTTP 200 so QStash does not launch a second attempt.

## Deployment

Vercel loads the FastAPI app from `src/app.py` through `[tool.vercel] entrypoint = "src.app:app"` in `pyproject.toml`. The function `maxDuration` is 800 seconds, which requires a Vercel plan that allows it.

After deployment, confirm `PUBLIC_APP_URL` is the canonical HTTPS origin. QStash signature checks compare the signed URL with `${PUBLIC_APP_URL}/internal/generations`.

QStash must be allowed to wait at least as long as the function duration. The delivery limit is `QSTASH_TIMEOUT` in `src/vast_inferencer/limits.py`.

Run `alembic upgrade head` against the Neon database before serving traffic. Set `DATABASE_URL` and `SECRETS_ENCRYPTION_KEY` on Vercel.

## Limits

- Cold worker startup, video generation, and S3 upload must finish before both the Vast worker timeout and the Vercel function limit.
- Presigned S3 URLs in `output` expire. Keep the bucket and object key if the file must remain available.
- There is no provider abstraction. This service talks to Vast only.
