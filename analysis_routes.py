"""Provider-scoped analysis with safe, actionable upstream diagnostics."""
import logging
import re
from importlib.metadata import PackageNotFoundError, version
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import HTTPException

logger = logging.getLogger('aifball.sofascore')


def library_version():
    try:
        return version('lanusstats')
    except PackageNotFoundError:
        return 'unknown'


def match_identity(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('www.sofascore.com', 'sofascore.com') or parsed.username or parsed.password:
        raise HTTPException(400, 'رابط SofaScore غير صالح')
    match = re.search(r'(?:^|[&])id[:=](\d{1,12})(?:$|[&])', parsed.fragment)
    if not match:
        raise HTTPException(400, 'الرابط يجب أن يحتوي معرّف المباراة في SofaScore')
    return match.group(1)


def source_failure(code, status, message, *, retryable=False, upstream_status=None):
    request_id = uuid4().hex[:12]
    detail = {'code': code, 'message': message, 'source': 'SofaScore',
              'retryable': retryable, 'requestId': request_id}
    if upstream_status is not None:
        detail['upstreamStatus'] = upstream_status
    return HTTPException(status, detail)


def classify_failure(error):
    """Never expose exception text, URLs, response bodies, headers or secrets."""
    name = type(error).__name__
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    if status is None and name == 'SofaScoreConnectionError':
        # LanusStats wraps the source status inside this specific exception.
        match = re.search(r'(?<!\d)(403|429)(?!\d)', str(error))
        status = int(match.group(1)) if match else None
    if status in (401, 403):
        return source_failure('UPSTREAM_REJECTED', 502,
                              'رفض SofaScore اتصال خادم البيانات. يلزم وصول مصرح به من المصدر.', upstream_status=status)
    if status == 429:
        return source_failure('UPSTREAM_RATE_LIMITED', 503,
                              'المصدر يحدّ الطلبات حالياً. لا توجد إعادة محاولات تلقائية.', upstream_status=status)
    if status == 404:
        return source_failure('SOURCE_DATA_NOT_FOUND', 404, 'البيانات غير موجودة في المصدر.', upstream_status=status)
    if 'Timeout' in name:
        return source_failure('UPSTREAM_TIMEOUT', 504, 'انتهت مهلة اتصال المصدر.', retryable=True)
    if name in ('ConnectionError', 'ConnectError', 'DNSError'):
        return source_failure('UPSTREAM_CONNECTION_ERROR', 502, 'تعذر اتصال خادم البيانات بالمصدر.', retryable=True)
    return source_failure('UPSTREAM_REQUEST_FAILED', 502,
                          'فشل طلب المصدر؛ راجع سجل Render باستخدام معرّف التشخيص.')


def register_analysis_routes(app, provider, sanitize):
    def request(sofa, path):
        method = getattr(sofa, 'sofascore_request', None)
        if not callable(method):
            raise source_failure('PROVIDER_VERSION_UNSUPPORTED', 501, 'إصدار LanusStats لا يدعم عقد الربط المطلوب.')
        try:
            payload = method(path)
            if not isinstance(payload, dict):
                raise source_failure('UPSTREAM_INVALID_RESPONSE', 502, 'صيغة استجابة المصدر غير صالحة.')
            if 'error' in payload:
                error = payload['error']
                status = error.get('code') if isinstance(error, dict) else None
                try:
                    status = int(status)
                except (TypeError, ValueError):
                    status = None
                if status in (401, 403, 404, 429):
                    class SourceHTTPError(Exception):
                        pass
                    fault = SourceHTTPError()
                    fault.response = type('ResponseStatus', (), {'status_code': status})()
                    raise fault
                raise source_failure('UPSTREAM_INVALID_RESPONSE', 502, 'المصدر أعاد خطأ دون بيانات صالحة.')
            return payload
        except Exception as error:
            failure = error if isinstance(error, HTTPException) else classify_failure(error)
            detail = failure.detail if isinstance(failure.detail, dict) else {}
            logger.warning('provider_request_failed code=%s request_id=%s library=%s exception_type=%s path=%s',
                           detail.get('code'), detail.get('requestId'), library_version(), type(error).__name__, path)
            raise failure from None

    def close(sofa):
        method = getattr(sofa, 'close', None)
        if callable(method):
            try:
                method()
            except Exception:
                logger.warning('provider_session_close_failed')

    @app.get('/sofascore/capabilities')
    def capabilities():
        supported = callable(getattr(provider.SofaScore, 'sofascore_request', None))
        return {'source': 'SofaScore', 'libraryVersion': library_version(),
                'analysisSupported': supported, 'diagnosticsVersion': 1,
                'liveConnectivityTested': False}

    @app.get('/sofascore/match-analysis')
    def analysis(match_url: str):
        event_id = match_identity(match_url)
        sofa = None
        try:
            sofa = provider.SofaScore()
            payload = request(sofa, f'api/v1/event/{event_id}')
            event = payload.get('event')
            if not isinstance(event, dict) or str(event.get('id')) != event_id:
                raise source_failure('MATCH_IDENTITY_MISMATCH', 502, 'لم يؤكد المصدر هوية المباراة.')
            output = {'source': 'SofaScore', 'sourceUrl': match_url, 'event': event,
                      'warnings': [], 'sectionErrors': {}}
            sections = [('lineups', 'lineups'), ('statistics', 'statistics'), ('shotmap', 'shotmap')]
            stopped = False
            for key, suffix in sections:
                if stopped:
                    output[key] = None
                    output['warnings'].append(key)
                    output['sectionErrors'][key] = {'code': 'UPSTREAM_NOT_REQUESTED', 'retryable': False}
                    continue
                try:
                    output[key] = request(sofa, f'api/v1/event/{event_id}/{suffix}')
                except HTTPException as error:
                    output[key] = None
                    output['warnings'].append(key)
                    output['sectionErrors'][key] = error.detail
                    code = error.detail.get('code') if isinstance(error.detail, dict) else None
                    stopped = code in ('UPSTREAM_REJECTED', 'UPSTREAM_RATE_LIMITED')
            return sanitize(output)
        except HTTPException:
            raise
        except Exception as error:
            raise classify_failure(error) from None
        finally:
            close(sofa)

    @app.get('/sofascore/player-points')
    def player_points(match_url: str, player_id: int):
        event_id = match_identity(match_url)
        if player_id <= 0:
            raise HTTPException(400, 'معرّف اللاعب غير صالح')
        sofa = None
        try:
            sofa = provider.SofaScore()
            roster = request(sofa, f'api/v1/event/{event_id}/lineups')
            players = [p for side in ('home', 'away') for p in (roster.get(side) or {}).get('players', [])]
            player = next((p.get('player') for p in players if str((p.get('player') or {}).get('id')) == str(player_id)), None)
            if player is None:
                raise HTTPException(404, 'اللاعب ليس ضمن قائمة هذه المباراة في المصدر')
            payload = request(sofa, f'api/v1/event/{event_id}/player/{player_id}/heatmap')
            points = payload.get('heatmap')
            if not isinstance(points, list):
                raise HTTPException(404, 'الخريطة غير متاحة لهذا اللاعب والمباراة')
            points = [p for p in points if isinstance(p, dict) and all(isinstance(p.get(k), (int, float)) and not isinstance(p[k], bool) and 0 <= p[k] <= 100 for k in ('x', 'y'))]
            return sanitize({'source': 'SofaScore', 'eventId': event_id, 'playerId': str(player_id), 'playerName': player.get('name'), 'sourceUrl': match_url, 'coordinates': 'percent-100', 'points': points})
        except HTTPException:
            raise
        except Exception as error:
            raise classify_failure(error) from None
        finally:
            close(sofa)
