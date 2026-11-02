# Provider-scoped spatial analysis bridge

New routes: GET /sofascore/match-analysis?match_url=... and GET /sofascore/player-points?match_url=...&player_id=...

Only HTTPS SofaScore URLs with a #id: provider event ID are accepted. Match metadata must echo the requested event. Player ID must exist in that match's source lineup before points are fetched. A missing section is explicit; no substitute coordinates or statistics are generated. Library capability failures return 501, provider failures 502. This does not enable FotMob or introduce a different network/client path to bypass provider errors.

The old /sofascore/heatmap route called a nonexistent get_player_heatmap_match method. It now calls get_player_heatmap and returns source-scoped coordinate points instead of claiming an image URL. Callers expecting an image URL must migrate.

Validation: python -m unittest discover -s . -p 'test_*.py' (4 synthetic tests). Production verification is required after Render deploy. Current live observation: FotMob is disabled; an existing SofaScore shotmap request returned HTTP 502. Do not claim successful live data coverage until actual upstream data is returned.

Requirements remain those of the project. The provider methods are checked at runtime because LanusStats is unpinned; an upgrade is not performed silently.
