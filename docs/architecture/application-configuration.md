# Application configuration

`GET /api/v1/config` exposes `agent_execution` and `email_recovery`. These describe optional hosted execution and built-in account recovery. Project creation, file access, external keys, and the independent agent library are core functionality.

Projects default to Default filesystem mode. Git and Linear remain explicit choices. Visibility defaults to public; users can choose private. Public visibility exposes only project metadata. Files, artifacts, and conversations retain their access checks.

FastAPI serves the production browser and API. Vite serves local development. The API lifespan runs hosted recovery, artifact cleanup, and document-build maintenance. Research outbox consumers and verification controller configuration are removed.

Use [deployment configuration](../../deploy/README.md) for process and secret settings. Unknown historical verification environment variables no longer enable a service.
