import unittest
from types import SimpleNamespace
from fastapi import HTTPException
from analysis_routes import register_analysis_routes, match_identity
class App:
    def __init__(self): self.routes = {}
    def get(self, path):
        def wrap(fn): self.routes[path] = fn; return fn
        return wrap
class Test(unittest.TestCase):
    def setup_routes(self, responses):
        class Sofa:
            def sofascore_request(self, path):
                value = responses[path]
                if isinstance(value, Exception): raise value
                return value
        app = App(); register_analysis_routes(app, SimpleNamespace(SofaScore=Sofa), lambda d:d); return app.routes
    def test_identity(self):
        self.assertEqual(match_identity('https://www.sofascore.com/test#id:123'), '123')
        for u in ['http://sofascore.com/#id:123', 'https://evil.com/#id:123', 'https://u:p@sofascore.com/#id:123', 'https://sofascore.com/123']:
            with self.assertRaises(HTTPException): match_identity(u)
    def test_partial_is_explicit(self):
        r=self.setup_routes({'api/v1/event/123':{'event':{'id':123}},'api/v1/event/123/lineups':{},'api/v1/event/123/statistics':Exception(),'api/v1/event/123/shotmap':Exception()})
        d=r['/sofascore/match-analysis']('https://sofascore.com/test#id:123');self.assertIsNone(d['statistics']);self.assertIn('statistics', d['warnings'])
    def test_no_cross_match(self):
        r=self.setup_routes({'api/v1/event/123':{'event':{'id':999}}})
        with self.assertRaises(HTTPException):r['/sofascore/match-analysis']('https://sofascore.com/test#id:123')
    def test_player_binding_and_zero_coordinates(self):
        r=self.setup_routes({'api/v1/event/123/lineups':{'home':{'players':[{'player':{'id':4,'name':'Player'}}]}},'api/v1/event/123/player/4/heatmap':{'heatmap':[{'x':0,'y':0},{'x':101,'y':10}]}})
        d=r['/sofascore/player-points']('https://sofascore.com/test#id:123',4);self.assertEqual(d['points'],[{'x':0,'y':0}])
        with self.assertRaises(HTTPException):r['/sofascore/player-points']('https://sofascore.com/test#id:123',999)

class DiagnosticTests(unittest.TestCase):
    def routes(self, outcomes):
        self.calls = []
        self.closed = 0
        owner = self
        class Sofa:
            def sofascore_request(self, path):
                owner.calls.append(path)
                result = outcomes[path]
                if isinstance(result, Exception):
                    raise result
                return result
            def close(self):
                owner.closed += 1
        app = App()
        register_analysis_routes(app, SimpleNamespace(SofaScore=Sofa), lambda d: d)
        return app.routes

    def test_access_denial_is_explicit_and_session_closes(self):
        blocked = type('SofaScoreConnectionError', (Exception,), {})('403 challenge private-token-value')
        route = self.routes({'api/v1/event/123': blocked})
        with self.assertRaises(HTTPException) as raised:
            route['/sofascore/match-analysis']('https://sofascore.com/test#id:123')
        error = raised.exception
        self.assertEqual(error.detail['code'], 'UPSTREAM_REJECTED')
        self.assertEqual(error.detail['upstreamStatus'], 403)
        self.assertFalse(error.detail['retryable'])
        self.assertNotIn('private-token-value', str(error.detail))
        self.assertEqual(self.closed, 1)
        self.assertEqual(len(self.calls), 1)

    def test_partial_denial_stops_remaining_provider_calls(self):
        route = self.routes({'api/v1/event/123': {'event': {'id': 123}},
                             'api/v1/event/123/lineups': {'error': {'code': 403}}})
        data = route['/sofascore/match-analysis']('https://sofascore.com/test#id:123')
        self.assertEqual(data['sectionErrors']['lineups']['code'], 'UPSTREAM_REJECTED')
        self.assertEqual(data['sectionErrors']['statistics']['code'], 'UPSTREAM_NOT_REQUESTED')
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.closed, 1)

    def test_timeout_does_not_masquerade_as_provider_denial(self):
        timeout = type('ReadTimeout', (Exception,), {})('private-url')
        route = self.routes({'api/v1/event/123': timeout})
        with self.assertRaises(HTTPException) as raised:
            route['/sofascore/match-analysis']('https://sofascore.com/test#id:123')
        self.assertEqual(raised.exception.status_code, 504)
        self.assertEqual(raised.exception.detail['code'], 'UPSTREAM_TIMEOUT')
        self.assertNotIn('private-url', str(raised.exception.detail))

    def test_source_404_is_not_identity_failure(self):
        route = self.routes({'api/v1/event/123': {'error': {'code': 404}}})
        with self.assertRaises(HTTPException) as raised:
            route['/sofascore/match-analysis']('https://sofascore.com/test#id:123')
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail['code'], 'SOURCE_DATA_NOT_FOUND')

    def test_unsupported_version_is_explicit(self):
        app = App()
        register_analysis_routes(app, SimpleNamespace(SofaScore=type('OldSofa', (), {})), lambda d: d)
        with self.assertRaises(HTTPException) as raised:
            app.routes['/sofascore/match-analysis']('https://sofascore.com/test#id:123')
        self.assertEqual(raised.exception.status_code, 501)
        self.assertEqual(raised.exception.detail['code'], 'PROVIDER_VERSION_UNSUPPORTED')

    def test_capabilities_never_claim_live_connectivity(self):
        route = self.routes({})
        data = route['/sofascore/capabilities']()
        self.assertTrue(data['analysisSupported'])
        self.assertFalse(data['liveConnectivityTested'])
        self.assertEqual(self.calls, [])

    def test_rate_limit_is_not_retried(self):
        route = self.routes({'api/v1/event/123': {'error': {'code': 429}}})
        with self.assertRaises(HTTPException) as raised:
            route['/sofascore/match-analysis']('https://sofascore.com/test#id:123')
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail['code'], 'UPSTREAM_RATE_LIMITED')
        self.assertEqual(len(self.calls), 1)

if __name__ == '__main__':
    unittest.main()
