"""Provider-scoped analysis: never mixes ESPN and SofaScore identifiers."""
import re
from urllib.parse import urlparse
from fastapi import HTTPException


def match_identity(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('www.sofascore.com', 'sofascore.com') or parsed.username or parsed.password:
        raise HTTPException(400, 'رابط SofaScore غير صالح')
    match = re.search(r'(?:^|[&])id[:=](\d{1,12})(?:$|[&])', parsed.fragment)
    if not match:
        raise HTTPException(400, 'الرابط يجب أن يحتوي معرّف المباراة في SofaScore')
    return match.group(1)


def register_analysis_routes(app, provider, sanitize):
    def request(sofa, path):
        method = getattr(sofa, 'sofascore_request', None)
        if not callable(method):
            raise HTTPException(501, 'إصدار LanusStats لا يدعم عقد الربط المطلوب')
        return method(path)

    @app.get('/sofascore/match-analysis')
    def analysis(match_url: str):
        event_id = match_identity(match_url)
        sofa = provider.SofaScore()
        try:
            payload = request(sofa, f'api/v1/event/{event_id}')
            event = payload.get('event') if isinstance(payload, dict) else None
            if not isinstance(event, dict) or str(event.get('id')) != event_id:
                raise HTTPException(502, 'لم يؤكد المصدر هوية المباراة')
            output = {'source': 'SofaScore', 'sourceUrl': match_url, 'event': event, 'warnings': []}
            for key, suffix in [('lineups', 'lineups'), ('statistics', 'statistics'), ('shotmap', 'shotmap')]:
                try:
                    output[key] = request(sofa, f'api/v1/event/{event_id}/{suffix}')
                except Exception:
                    output[key] = None
                    output['warnings'].append(key)
            return sanitize(output)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502, 'تعذر جلب المباراة من SofaScore؛ لا توجد بيانات بديلة')

    @app.get('/sofascore/player-points')
    def player_points(match_url: str, player_id: int):
        event_id = match_identity(match_url)
        if player_id <= 0:
            raise HTTPException(400, 'معرّف اللاعب غير صالح')
        sofa = provider.SofaScore()
        try:
            roster = request(sofa, f'api/v1/event/{event_id}/lineups')
            players = [p for side in ('home', 'away') for p in (roster.get(side) or {}).get('players', [])]
            player = next((p.get('player') for p in players if str((p.get('player') or {}).get('id')) == str(player_id)), None)
            if player is None:
                raise HTTPException(404, 'اللاعب ليس ضمن قائمة هذه المباراة في المصدر')
            payload = request(sofa, f'api/v1/event/{event_id}/player/{player_id}/heatmap')
            points = payload.get('heatmap') if isinstance(payload, dict) else None
            if not isinstance(points, list):
                raise HTTPException(404, 'الخريطة غير متاحة لهذا اللاعب والمباراة')
            # Coordinates are percentages supplied by this endpoint, not tracking routes.
            points = [p for p in points if isinstance(p, dict) and all(isinstance(p.get(k), (int, float)) and not isinstance(p[k], bool) and 0 <= p[k] <= 100 for k in ('x', 'y'))]
            return sanitize({'source': 'SofaScore', 'eventId': event_id, 'playerId': str(player_id), 'playerName': player.get('name'), 'sourceUrl': match_url, 'coordinates': 'percent-100', 'points': points})
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502, 'تعذر جلب إحداثيات اللاعب من المصدر')
