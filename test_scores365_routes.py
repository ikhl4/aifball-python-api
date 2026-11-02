import copy
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from PIL import Image
from scores365_routes import match_identity, report_data, source_game, player_heatmap_response, register_365_routes, ScoresClient, NoRedirect

URL = 'https://www.365scores.com/football/match/league-3/a-b-1-2-3#id=123'

def game():
    return {'id':123,'sportId':1,'competitionId':3,'startTime':'2024-03-28T00:30:00+00:00','statusGroup':4,'statusText':'Ended',
        'members':[{'id':10,'name':'Player','competitorId':1,'jerseyNumber':4},{'id':20,'name':'Other','competitorId':2}],
        'homeCompetitor':{'id':1,'name':'A','score':0,'lineups':{'formation':'4-3-3','members':[{'id':10,'status':1,'stats':[{'type':27,'value':'0'},{'type':76,'value':'-'}],'heatMap':'https://imagecache.365scores.com/map.webp'},{'id':99,'status':4}]}},
        'awayCompetitor':{'id':2,'name':'B','score':1,'lineups':{'members':[{'id':20,'status':2}]}},
        'chartEvents':{'events':[{'gameId':123,'competitorNum':1,'playerId':10,'side':90,'line':40,'xg':'0','xgot':'-','outcome':{'y':99,'z':1,'name':'Goal'}}, {'gameId':999,'competitorNum':1,'side':30,'line':40}]}}

def stats():
    return {'games':[{'id':123,'homeCompetitor':{'id':1},'awayCompetitor':{'id':2}}],
            'statistics':[{'id':76,'competitorId':1,'value':'0.00'},{'id':19,'competitorId':1,'value':'16/28 (57%)'}]}

class App:
    def __init__(self): self.routes={}
    def get(self,path):
        def wrap(fn): self.routes[path]=fn;return fn
        return wrap

class Test365(unittest.TestCase):
    def test_specific_identity_required_before_network(self):
        self.assertEqual(match_identity(URL)['event'],'123')
        for url in [URL.split('#')[0],URL.replace('https:','http:'),URL.replace('www.365scores.com','evil.com'),URL.replace('#id=123','#id:123'),URL.replace('www.365scores.com','u:p@www.365scores.com'),URL.replace('-1-2-3','-1-1-3')]:
            with self.assertRaises(HTTPException): match_identity(url)
        with self.assertRaises(HTTPException): player_heatmap_response(URL.split('#')[0],player_id=10,client_factory=lambda:self.fail('network opened'))

    def test_event_teams_competition_and_sport_all_match(self):
        identity=match_identity(URL)
        for field,value in [('id',999),('competitionId',5),('sportId',2)]:
            g=game();g[field]=value
            with self.assertRaises(HTTPException):source_game({'game':g},identity)
        g=game();g['awayCompetitor']['id']=1
        with self.assertRaises(HTTPException):source_game({'game':g},identity)

    def test_missing_is_not_zero_and_compound_pass_stats_are_preserved(self):
        data,_=report_data(game(),stats(),match_identity(URL),URL)
        self.assertEqual(data['statistics'][0]['home'],'16/28 (57%)')
        xg=next(s for s in data['statistics'] if s['key']=='76')
        self.assertEqual(xg['home'],'0.00');self.assertIsNone(xg['away'])
        self.assertEqual(len(data['home']['players']),1)
        self.assertEqual(data['home']['players'][0]['statistics'],[{'key':'27','label':'الأهداف','value':'0'}])
        self.assertFalse(data['away']['players'][0]['starter'])

    def test_statistics_for_another_event_never_merge(self):
        s=stats();s['games'][0]['id']=999
        with self.assertRaises(HTTPException):report_data(game(),s,match_identity(URL),URL)

    def test_shots_use_field_coordinates_not_goal_target_coordinates(self):
        data,_=report_data(game(),None,match_identity(URL),URL)
        self.assertEqual(len(data['shots']),1)
        self.assertEqual((data['shots'][0]['x'],data['shots'][0]['y']),(90,40))
        self.assertEqual(data['shots'][0]['xg'],0)
        self.assertIsNone(data['shots'][0]['xgot'])

    def test_heatmap_is_binary_png_bound_to_source_player(self):
        owner=self
        class Client:
            def get_json(self,*args):return {'game':game()}
            def image(self,url):owner.assertEqual(url,'https://imagecache.365scores.com/map.webp');return b'\x89PNG\r\n\x1a\nbytes'
            def close(self):owner.closed=True
        self.closed=False
        r=player_heatmap_response(URL,player_id=10,client_factory=Client)
        self.assertEqual(r.media_type,'image/png');self.assertEqual(r.headers['x-aifball-event'],'123');self.assertEqual(r.headers['x-aifball-player'],'10');self.assertTrue(self.closed)

    def test_unknown_player_is_not_replaced_and_session_closes(self):
        owner=self
        class Client:
            def get_json(self,*args):return {'game':game()}
            def image(self,*args):owner.fail('unknown player requested image')
            def close(self):owner.closed=True
        self.closed=False
        with self.assertRaises(HTTPException) as error:player_heatmap_response(URL,player_id=999,client_factory=Client)
        self.assertEqual(error.exception.status_code,404);self.assertTrue(self.closed)

    def test_both_teams_support_images(self):
        g=game();g['awayCompetitor']['lineups']['members'][0]['heatMap']='https://imagecache.365scores.com/away.webp'
        class Client:
            def get_json(self,*args):return {'game':g}
            def image(self,url):return url.encode()
            def close(self):pass
        r=player_heatmap_response(URL,player_id=20,client_factory=Client)
        self.assertIn(b'away.webp',r.body)

    def test_external_heatmap_url_is_rejected_before_request(self):
        client=ScoresClient()
        try:
            with patch.object(client.opener,'open',side_effect=AssertionError('network called')):
                with self.assertRaises(HTTPException):client.image('https://evil.com/image.png')
                with self.assertRaises(HTTPException):client.image('https://imagecache.365scores.com.evil.com/map')
        finally:client.close()

    def test_webp_becomes_png_and_redirect_is_rejected(self):
        buf=io.BytesIO();Image.new('RGB',(3,3),'green').save(buf,format='WEBP')
        class R:
            status_code=200;headers={'Content-Type':'image/webp'}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,n):return buf.getvalue()
        c=ScoresClient()
        try:
            with patch.object(c.opener,'open',return_value=R()) as get:
                self.assertTrue(c.image('https://imagecache.365scores.com/map').startswith(b'\x89PNG\r\n\x1a\n'))
                self.assertEqual(get.call_args.kwargs['timeout'],20)
                self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://evil.com'))
            from urllib.error import HTTPError
            with patch.object(c.opener,'open',side_effect=HTTPError('https://imagecache.365scores.com/map',302,'redirect',{},None)):
                with self.assertRaises(HTTPException):c.image('https://imagecache.365scores.com/map')
        finally:c.close()

    def test_optional_statistics_failure_keeps_verified_game(self):
        owner=self
        class Client:
            def get_json(self,path,params):
                if path:raise HTTPException(502,{'code':'UPSTREAM_ERROR'})
                return {'game':game()}
            def close(self):owner.closed=True
        app=App();register_365_routes(app,Client);self.closed=False
        data=app.routes['/365scores/match-analysis'](URL)
        self.assertEqual(data['eventId'],'123');self.assertEqual(data['statistics'],[]);self.assertEqual(len(data['warnings']),1);self.assertTrue(self.closed)

if __name__=='__main__':unittest.main()
