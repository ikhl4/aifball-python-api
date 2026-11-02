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
if __name__=='__main__': unittest.main()
