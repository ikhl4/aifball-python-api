"""365Scores reports: exact event identity, source values and source heatmap images."""
import io
import json
import math
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, urlencode
from urllib.request import build_opener, HTTPRedirectHandler, Request
from urllib.error import HTTPError, URLError

from fastapi import HTTPException
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError

API_BASE = 'https://webws.365scores.com/web/game/'
MAX_IMAGE_BYTES = 3 * 1024 * 1024
TEAM_LABELS = {1: 'البطاقات الصفراء', 2: 'البطاقات الحمراء', 3: 'التسديدات', 4: 'على المرمى',
    5: 'خارج المرمى', 6: 'تسديدات محجوبة', 8: 'الركنيات', 9: 'التسلل', 10: 'الاستحواذ',
    11: 'الهجمات', 12: 'الأخطاء', 13: 'الركلات الحرة', 14: 'ركلات المرمى', 15: 'رميات التماس',
    16: 'الهجمات الخطيرة', 19: 'التمريرات المكتملة', 21: 'إجمالي التمريرات', 23: 'التصديات',
    24: 'الفرص الكبيرة المصنوعة', 76: 'الأهداف المتوقعة xG', 77: 'الأهداف المتوقعة المستقبلة', 78: 'الصناعة المتوقعة xA'}
PLAYER_LABELS = {**TEAM_LABELS, 26: 'صناعة الأهداف', 27: 'الأهداف', 30: 'دقائق اللعب',
    35: 'الأهداف المستقبلة', 36: 'فرص كبيرة ضائعة', 37: 'الأخطاء المكتسبة', 39: 'التدخلات الناجحة',
    40: 'التشتيت', 41: 'الاعتراضات', 42: 'الأخطاء المرتكبة', 43: 'إبعاد الكرة بالقبضة',
    45: 'اللمسات', 46: 'التمريرات المفتاحية', 52: 'العرضيات المكتملة', 53: 'التمريرات الطويلة المكتملة',
    54: 'المراوغات الناجحة', 55: 'الالتحامات الأرضية الناجحة', 56: 'الالتحامات الهوائية الناجحة',
    59: 'حجب التسديدات', 60: 'المراوغات التي تعرض لها', 73: 'فقدان الاستحواذ',
    79: 'الأهداف المتوقعة على المرمى xGOT', 80: 'تمريرات الثلث الأخير', 81: 'التمريرات للخلف',
    82: 'الأهداف المتوقعة على المرمى المستقبلة', 83: 'الأهداف المتوقعة الممنوعة',
    84: 'استعادة الكرة في الثلث الأخير', 85: 'الخروج لتغطية الدفاع', 86: 'استعادة الكرة', 87: 'فرص كبيرة مسجلة'}
POSITIONS = {'Goalkeeper': 'حارس مرمى', 'Defender': 'مدافع', 'Midfielder': 'وسط', 'Forward': 'مهاجم',
    'Striker': 'مهاجم', 'Left Back': 'ظهير أيسر', 'Right Back': 'ظهير أيمن', 'Centre Back': 'قلب دفاع',
    'Left Midfielder': 'وسط أيسر', 'Right Midfielder': 'وسط أيمن', 'Centre Midfielder': 'وسط',
    'Defensive Midfielder': 'محور', 'Attacking Midfielder': 'وسط هجومي', 'Left Winger': 'جناح أيسر', 'Right Winger': 'جناح أيمن'}


def fail(code, message, status=502):
    return HTTPException(status, {'code': code, 'source': '365Scores', 'message': message})


def match_identity(url):
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        raise fail('INVALID_MATCH_URL', 'رابط 365Scores غير صالح.', 400) from None
    if parsed.scheme != 'https' or parsed.hostname not in ('365scores.com', 'www.365scores.com') or parsed.username or parsed.password or port not in (None, 443):
        raise fail('INVALID_MATCH_URL', 'رابط 365Scores غير صالح.', 400)
    matchup = re.search(r'-(\d{1,12})-(\d{1,12})-(\d{1,12})/?$', parsed.path)
    event = re.fullmatch(r'id=(\d{1,12})', parsed.fragment)
    if not matchup or not event or matchup[1] == matchup[2] or int(event[1]) <= 0:
        raise fail('MATCH_ID_REQUIRED', 'يلزم رابط مباراة محددة في 365Scores يتضمن #id=، وليس رابط مواجهة عاماً.', 400)
    return {'event': event[1], 'teams': (matchup[1], matchup[2]), 'competition': matchup[3],
            'matchup': '-'.join(matchup.groups())}


def value(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return str(v) if math.isfinite(v) else None
    return v.strip() if isinstance(v, str) and v.strip() not in ('', '-', '—') and re.fullmatch(r"[0-9\s.%/()+,'−\-:]+", v.strip()) else None


def numeric(v):
    if isinstance(v, bool):
        return None
    try:
        result = float(v)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def source_game(payload, identity):
    game = payload.get('game') if isinstance(payload, dict) else None
    if not isinstance(game, dict) or str(game.get('id')) != identity['event']:
        raise fail('MATCH_IDENTITY_MISMATCH', 'لم يؤكد المصدر معرّف المباراة المطلوبة.')
    ids = [str(game.get(side + 'Competitor', {}).get('id')) for side in ('home', 'away')]
    if len(set(ids)) != 2 or set(ids) != set(identity['teams']) or str(game.get('competitionId')) != identity['competition'] or game.get('sportId') != 1:
        raise fail('MATCH_IDENTITY_MISMATCH', 'الفريقان أو البطولة لا يطابقان رابط المباراة.')
    return game


def report_data(game, stats, identity, source_url, warnings=None):
    # Only actual starters/substitutes are player-card candidates, never management/missing members.
    members = {str(p.get('id')): p for p in game.get('members', []) if isinstance(p, dict)}
    teams = {}
    heatmaps = {}
    for side in ('home', 'away'):
        raw = game[side + 'Competitor']
        lineup = raw.get('lineups') or {}
        players = []
        for p in lineup.get('members', []):
            if not isinstance(p, dict) or p.get('status') not in (1, 2):
                continue
            pid = str(p.get('id', ''))
            member = members.get(pid)
            if not member or str(member.get('competitorId')) != str(raw['id']):
                continue
            position = (p.get('formation') or p.get('position') or {}).get('name', '')
            metrics = [{'key': str(s['type']), 'label': PLAYER_LABELS[s['type']], 'value': value(s.get('value'))}
                       for s in p.get('stats', []) if isinstance(s, dict) and s.get('type') in PLAYER_LABELS and value(s.get('value')) is not None]
            players.append({'id': pid, 'name': member.get('name') or 'الاسم غير متاح',
                'jersey': value(member.get('jerseyNumber')), 'starter': p['status'] == 1,
                'status': 'أساسي' if p['status'] == 1 else 'ضمن البدلاء',
                'position': POSITIONS.get(position, POSITIONS.get((p.get('position') or {}).get('name'), 'المركز غير متاح')),
                'statistics': metrics, 'hasHeatmap': bool(p.get('heatMap'))})
            if p.get('heatMap'):
                heatmaps[pid] = p['heatMap']
        teams[side] = {'id': str(raw['id']), 'name': raw.get('name') or 'الفريق غير متاح',
                       'score': value(raw.get('score')), 'formation': value(lineup.get('formation')), 'players': players}
    metrics = []
    if stats is not None:
        games = stats.get('games', [])
        if len(games) != 1 or str(games[0].get('id')) != identity['event'] or any(str(games[0].get(side+'Competitor', {}).get('id')) != teams[side]['id'] for side in ('home', 'away')):
            raise fail('STATISTICS_IDENTITY_MISMATCH', 'إحصائيات المصدر لا تخص المباراة نفسها.')
        for key, label in TEAM_LABELS.items():
            rows = [s for s in stats.get('statistics', []) if s.get('id') == key]
            if not rows:
                continue
            values = {}
            for side in ('home', 'away'):
                found = [s for s in rows if str(s.get('competitorId')) == teams[side]['id']]
                values[side] = value(found[0].get('value')) if len(found) == 1 else None
            metrics.append({'key': str(key), 'label': label, **values})
    shots = []
    for s in (game.get('chartEvents') or {}).get('events', []):
        if str(s.get('gameId')) != identity['event'] or s.get('competitorNum') not in (1, 2):
            continue
        # 365 coordinates: longitudinal side / lateral line, both teams attacking right.
        x, y = numeric(s.get('side')), numeric(s.get('line'))
        if x is None or y is None or not (0 <= x <= 100 and 0 <= y <= 100):
            continue
        shots.append({'id': str(s.get('key', len(shots))), 'side': 'home' if s['competitorNum'] == 1 else 'away',
            'playerId': str(s.get('playerId', '')), 'x': x, 'y': y, 'xg': numeric(s.get('xg')) if numeric(s.get('xg')) is not None and 0 <= numeric(s.get('xg')) <= 1 else None,
            'xgot': numeric(s.get('xgot')) if numeric(s.get('xgot')) is not None and 0 <= numeric(s.get('xgot')) <= 1 else None, 'minute': value(s.get('time')),
            'outcome': {'Goal': 'هدف', 'Missed': 'خارج المرمى', 'Saved': 'تصدى لها الحارس', 'Blocked': 'محجوبة', 'Post': 'القائم'}.get((s.get('outcome') or {}).get('name'), 'غير محدد')})
    result = {'source': '365Scores', 'sourceUrl': source_url, 'eventId': identity['event'],
        'competitionId': identity['competition'], 'date': game.get('startTime'), 'competition': game.get('competitionDisplayName'),
        'state': 'post' if game.get('statusGroup') == 4 and game.get('statusText') == 'Ended' else 'unknown',
        'home': teams['home'], 'away': teams['away'], 'statistics': metrics, 'shots': shots,
        'coordinates': 'percent-100-attacking-right', 'warnings': warnings or [],
        'fetchedAt': datetime.now(timezone.utc).isoformat()}
    return result, heatmaps


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ScoresClient:
    def __init__(self):
        self.opener = build_opener(NoRedirect())

    def close(self):
        self.opener.close()

    def get_json(self, suffix, params):
        url = API_BASE + suffix + '?' + urlencode({'appTypeId': 5, 'langId': 1, 'timezoneName': 'UTC', **params})
        try:
            with self.opener.open(Request(url, headers={'Accept': 'application/json'}), timeout=20) as response:
                body = response.read(4 * 1024 * 1024 + 1)
                if len(body) > 4 * 1024 * 1024:
                    raise fail('INVALID_UPSTREAM_DATA', 'حجم استجابة المصدر غير مدعوم.')
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise fail('INVALID_UPSTREAM_DATA', 'صيغة بيانات المصدر غير صالحة.')
                return data
        except HTTPError as error:
            error.close()
            if error.code in (401, 403, 429):
                raise fail('UPSTREAM_REJECTED', 'المصدر رفض اتصال خدمة البيانات.') from None
            if error.code == 404:
                raise fail('SOURCE_DATA_NOT_FOUND', 'المباراة غير موجودة في المصدر.', 404) from None
            raise fail('UPSTREAM_ERROR', 'تعذر جلب بيانات المصدر.') from None
        except TimeoutError:
            raise fail('UPSTREAM_TIMEOUT', 'انتهت مهلة الاتصال بالمصدر.', 504) from None
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise fail('UPSTREAM_TIMEOUT', 'انتهت مهلة الاتصال بالمصدر.', 504) from None
            raise fail('UPSTREAM_ERROR', 'تعذر الاتصال بالمصدر.') from None
        except ValueError:
            raise fail('UPSTREAM_ERROR', 'تعذر قراءة استجابة المصدر.') from None

    def image(self, url):
        try:
            parsed = urlparse(url)
            allowed = parsed.scheme == 'https' and parsed.hostname == 'imagecache.365scores.com' and not parsed.username and not parsed.password and parsed.port in (None, 443)
        except ValueError:
            allowed = False
        if not allowed:
            raise fail('INVALID_HEATMAP_URL', 'رابط صورة المصدر غير صالح.')
        try:
            with self.opener.open(Request(url, headers={'Accept': 'image/*'}), timeout=20) as response:
                if not response.headers.get('Content-Type', '').startswith('image/'):
                    raise fail('HEATMAP_UNAVAILABLE', 'صورة الخريطة غير متاحة من المصدر.', 404)
                content = response.read(MAX_IMAGE_BYTES + 1)
                if len(content) > MAX_IMAGE_BYTES:
                    raise fail('HEATMAP_TOO_LARGE', 'حجم صورة المصدر غير مدعوم.')
            with Image.open(io.BytesIO(content)) as image:
                if image.width * image.height > 4_000_000:
                    raise fail('HEATMAP_TOO_LARGE', 'أبعاد صورة المصدر غير مدعومة.')
                output = io.BytesIO()
                image.convert('RGBA').save(output, format='PNG')
                png = output.getvalue()
                if len(png) > 4 * 1024 * 1024:
                    raise fail('HEATMAP_TOO_LARGE', 'حجم الصورة المحولة غير مدعوم.')
                return png
        except HTTPError as error:
            error.close()
            if error.code in (401, 403, 429):
                raise fail('UPSTREAM_REJECTED', 'المصدر رفض جلب صورة الخريطة.') from None
            raise fail('HEATMAP_UNAVAILABLE', 'صورة الخريطة غير متاحة من المصدر.', 404) from None
        except TimeoutError:
            raise fail('UPSTREAM_TIMEOUT', 'انتهت مهلة جلب الخريطة.', 504) from None
        except (URLError, UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise fail('INVALID_HEATMAP_IMAGE', 'تعذر قراءة صورة الخريطة من المصدر.') from None


def load_game(client, match_url):
    identity = match_identity(match_url)
    game = source_game(client.get_json('', {'gameId': identity['event'], 'matchupId': identity['matchup']}), identity)
    return identity, game


def player_heatmap_response(match_url, player_id=None, player_name=None, client_factory=ScoresClient):
    # Validate before opening a network session.
    match_identity(match_url)
    client = client_factory()
    try:
        identity, game = load_game(client, match_url)
        report, maps = report_data(game, None, identity, match_url)
        candidates = [p for side in ('home', 'away') for p in report[side]['players']
                      if (str(p['id']) == str(player_id) if player_id is not None else p['name'] == player_name)]
        if len(candidates) != 1 or candidates[0]['id'] not in maps:
            raise fail('PLAYER_HEATMAP_NOT_FOUND', 'لم يوفر المصدر خريطة لهذا اللاعب في المباراة المحددة.', 404)
        pid = candidates[0]['id']
        png = client.image(maps[pid])
        return Response(png, media_type='image/png', headers={'Cache-Control': 'private, max-age=60',
            'X-AiFBall-Source': '365Scores', 'X-AiFBall-Event': identity['event'], 'X-AiFBall-Player': pid})
    finally:
        client.close()


def register_365_routes(app, client_factory=ScoresClient):
    @app.get('/365scores/match-analysis')
    def analysis(match_url: str):
        match_identity(match_url)
        client = client_factory()
        try:
            identity, game = load_game(client, match_url)
            stats, warnings = None, []
            try:
                stats = client.get_json('stats/', {'games': identity['event']})
            except HTTPException as error:
                warnings.append({'section': 'statistics', 'code': error.detail.get('code') if isinstance(error.detail, dict) else 'UPSTREAM_ERROR'})
            report, _ = report_data(game, stats, identity, match_url, warnings)
            return report
        finally:
            client.close()

    @app.get('/365scores/player-heatmap')
    def heatmap(match_url: str, player_id: int):
        if player_id <= 0:
            raise fail('INVALID_PLAYER', 'معرّف اللاعب غير صالح.', 400)
        return player_heatmap_response(match_url, player_id=player_id, client_factory=client_factory)
