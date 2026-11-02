# Provider-scoped spatial analysis bridge

New routes: GET /sofascore/match-analysis?match_url=... and GET /sofascore/player-points?match_url=...&player_id=...

Only HTTPS SofaScore URLs with a #id: provider event ID are accepted. Match metadata must echo the requested event. Player ID must exist in that match's source lineup before points are fetched. A missing section is explicit; no substitute coordinates or statistics are generated. Library capability failures return 501, provider failures 502. This does not enable FotMob or introduce a different network/client path to bypass provider errors.

The old /sofascore/heatmap route called a nonexistent get_player_heatmap_match method. It now calls get_player_heatmap and returns source-scoped coordinate points instead of claiming an image URL. Callers expecting an image URL must migrate.

Validation: python -m unittest discover -s . -p 'test_*.py' (4 synthetic tests). Production verification is required after Render deploy. Current live observation: FotMob is disabled; an existing SofaScore shotmap request returned HTTP 502. Do not claim successful live data coverage until actual upstream data is returned.

Requirements remain those of the project. The provider methods are checked at runtime because LanusStats is unpinned; an upgrade is not performed silently.


## Safe source diagnostics

The analysis routes now distinguish `UPSTREAM_REJECTED` (401/403), `UPSTREAM_RATE_LIMITED` (429), `UPSTREAM_TIMEOUT`, `SOURCE_DATA_NOT_FOUND` (404), `PROVIDER_VERSION_UNSUPPORTED` and identity/response failures. Errors contain a safe Arabic message, provider name and requestId. Render logs correlate the requestId with the exception class, fixed provider path and installed LanusStats version; raw exception text, response bodies and secrets are not logged by this adapter. Optional sections expose `sectionErrors` alongside existing warnings. A denial/rate limit stops subsequent optional requests, without automatic retries. Sessions close after success or failure.

`GET /sofascore/capabilities` checks local library support/version only; `liveConnectivityTested` is always false. It makes no upstream request.

Deployment verification:
1. Merge this change into the Python repository and let Render deploy that commit.
2. Check `/sofascore/capabilities` returns diagnosticsVersion 1.
3. Test a genuinely retrieved SofaScore event URL (not an ESPN/FotMob ID). Inspect the API error detail and the matching Render log requestId.
4. If version support fails, review the installed version/API compatibility before choosing a dependency change. If connection times out, investigate service/network health. A denied connection requires authorized provider access or another supported data source; this patch does not change client impersonation, proxies, IPs or provider protections.

Validation: 11 synthetic tests and Python compilation. The previously deployed endpoint only exposed a generic 502, so the root cause and live provider recovery remain unverified until this diagnostic version is deployed. This patch repairs diagnosis and session cleanup; it does not claim to restore upstream availability.
