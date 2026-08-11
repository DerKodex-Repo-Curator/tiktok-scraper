# tiktok-api Specification

## Purpose
FastAPI-based REST API for managing TikTok download jobs, with Scalar/Swagger
documentation.

## Requirements

### Requirement: Download Endpoint
The API MUST expose `POST /api/v1/download` to start a download job.

#### Scenario: Start Download via API
- GIVEN a request body `{ "target": "username_or_url" }`
- WHEN a POST request is sent to `/api/v1/download`
- THEN the system enqueues a download job and returns `{ "job_id": "..." }`
- AND the job appears in `/api/v1/jobs` list

### Requirement: Job Management
The API MUST provide `GET /api/v1/jobs` and `GET /api/v1/jobs/{id}` endpoints.

#### Scenario: Check Job Status
- GIVEN a job ID exists
- WHEN a GET request is sent to `/api/v1/jobs/{id}`
- THEN the response includes status (`pending`, `running`, `completed`, `failed`)
- AND detailed progress information (downloaded, skipped, failed counts)

### Requirement: History Endpoints
The API MUST implement `GET /api/v1/history` and `DELETE /api/v1/history/{video_id}`.

#### Scenario: List Downloaded Videos
- GIVEN videos have been downloaded
- WHEN a GET request is sent to `/api/v1/history`
- THEN a paginated list of video records is returned
- AND each record includes video_id, target, status, path, updated_at

### Requirement: Health Check and Documentation
The API MUST expose `GET /api/v1/health` and serve Scalar UI at `/docs`.

#### Scenario: Health Check
- GIVEN the service is running
- WHEN a GET request is sent to `/api/v1/health`
- THEN a 200 OK response with `{ "status": "ok" }` is returned
- AND the Scalar API documentation is accessible at `/docs`