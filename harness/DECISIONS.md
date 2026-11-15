# Harness decisions log

Deviations from `specs/harness.md` and choices it left open. Each has its reason.

| # | Decision | Reason |
|---|---|---|
| 1 | No separate `mock_world`. Tests run the real backend on a synthetic fixture database | One implementation of `put_claim` and of every tool instead of two that can drift. The fixture holds no licensed data |
| 2 | Router classifies facets with keyword rules by default; the one-call model classifier is behind `ROUTER_USE_MODEL=1` | The Gemini key was on the free tier (20 requests per day per model) when this was built. Rules cost nothing and are deterministic |
| 3 | Card rendering (`card.md`, `coverage:` line) lives in the backend at `GET /v1/places/{id}/card`; `WorldBackend` fetches it | The frontend and the harness read the same card. `claims.jsonl`, `neighbors.md` and `index.md` are rendered in the harness from REST calls |
| 4 | The run id is `configurable.run_id` when the caller sets it, otherwise the thread id. It is sent to the backend as `X-Run-Id` on every REST call and, through an MCP tool interceptor, on every MCP call | Lets the eval runner separate interleaved runs in backend stats without relying on resets |
| 5 | `MetricsMiddleware` sits before `RouterMiddleware` on the orchestrator | Metrics resets the per-run record; the router must write the route after that reset |
| 6 | Numeric claims flagged `exact` in `shared/predicates.yaml` (years, counts) must match exactly; the 5% tolerance of harness spec 4d applies to the rest | With a flat 5% rule, "built 1990" and "built 1975" merged into one claim |
| 7 | `metrics` events also carry `time_to_first_action_ms`, `tokens_total`, per-tool counts and `subagents_used` | The eval design records time to first action, tool calls and tokens per run |
| 8 | Image caps (12 pano images, 4 aerial images) are counted per run, not per subagent task | The run record is the only state shared by tools; a run has one interior task and one aerial task |
| 9 | `PRICES` starts empty and is filled from `MODEL_PRICES`; `est_cost_usd` is null when a model has no price | Prices were not verified in the session that built this. A wrong number is worse than a missing one |
| 10 | H11 (`similar_to`), H12 (curator) and H13 (context-arms eval) are not built | Stretch items, or blocked on decisions listed in harness spec 10b |
