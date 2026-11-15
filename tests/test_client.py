import unittest
import io
import json
from urllib.error import HTTPError
from getodds import GetOdds, GetOddsError, validate_markets
STAMP = '2026-11-07T00:00:00Z'
FIXTURE = {'request_id':'fixture','data':[{'id':'1','source':'prizepicks','player':'Fixture','market':'Points','line':22.5,'odds':None,'league':'NBA','observed_at':STAMP,'starts_at':None,'source_updated_at':None}], 'meta':{'source':'prizepicks','complete':False,'observed_at':STAMP}}
class Opener:
    def __init__(self, body=None, error=None):
        self.body, self.error, self.calls = body, error, 0
    def open(self, req, timeout):
        self.calls += 1
        assert req.full_url.startswith('https://getoddsapi.com/api/v1/')
        assert req.get_header('Authorization') == 'Bearer fixture'
        assert timeout == 20
        if self.error:
            raise self.error
        return io.BytesIO(self.body)
class ClientTest(unittest.TestCase):
    def test_all_sources(self):
        for source in ['prizepicks','underdog','draftkings','fanduel']:
            body={**FIXTURE,'data':[{**FIXTURE['data'][0],'source':source}],'meta':{**FIXTURE['meta'],'source':source}}
            self.assertEqual(GetOdds('fixture',Opener(json.dumps(body).encode())).markets(source=source)['data'][0]['source'],source)
            with self.assertRaises(GetOddsError):
                validate_markets({**body,'data':[{**body['data'][0],'source':'unknown'}]},50,source)
    def test_real_contract(self):
        opener=Opener(json.dumps(FIXTURE).encode())
        self.assertEqual(GetOdds('fixture',opener).markets(limit=1),FIXTURE)
        self.assertEqual(opener.calls,1)
    def test_invalid_parameters(self):
        opener=Opener(b'')
        client=GetOdds('fixture',opener)
        for limit in [True,0,201,1.5,'5']:
            with self.assertRaises(GetOddsError): client.markets(limit=limit)
        with self.assertRaises(GetOddsError): client.markets(source='unknown')
        self.assertEqual(opener.calls,0)
    def test_refusal(self):
        opener=Opener(error=HTTPError('https://example.invalid',429,'private',{'Retry-After':'60'},None))
        with self.assertRaises(GetOddsError) as error: GetOdds('fixture',opener).markets()
        self.assertEqual(error.exception.status,429)
        self.assertEqual(error.exception.retry_after,60)
        self.assertNotIn('private',str(error.exception))
        self.assertEqual(opener.calls,1)
    def test_bad_contract(self):
        for row in [{**FIXTURE['data'][0],'line':True},{**FIXTURE['data'][0],'line':float('nan')},{**FIXTURE['data'][0],'odds':-110}]:
            with self.assertRaises(GetOddsError): validate_markets({**FIXTURE,'data':[row]},50)
        with self.assertRaises(GetOddsError): validate_markets({**FIXTURE,'data':FIXTURE['data']*2},50)
        for body in [b'not json', b'x'*(2*1024*1024+1)]:
            with self.assertRaises(GetOddsError): GetOdds('fixture',Opener(body)).markets()
    def test_sportsbook_pagination(self):
        fixture={'request_id':'fixture','data':[], 'meta':{'source':'draftkings','transport':'stored_espn_draftkings','snapshot_consistent':False,'checked_at':STAMP},'pagination':{'limit':2,'offset':4,'has_more':False,'next_offset':None}}
        opener=Opener(json.dumps(fixture).encode())
        client=GetOdds('fixture',opener)
        for resource in ('events','odds','history','sports','bookmakers','market-types'):
            options={'limit':2,'offset':4}
            if resource=='history': options['offer_id']='source:fixture'
            self.assertEqual(client.sportsbook(resource,**options),fixture)
        self.assertEqual(opener.calls,6)
    def test_sportsbook_validation(self):
        opener=Opener(b'{}');client=GetOdds('fixture',opener)
        for options in ({'limit':True},{'offset':10001},{'source':'fanduel'},{'fresh_only':'true'},{'event_id':'x&y'},{'unknown':1}):
            with self.assertRaises(GetOddsError): client.odds(**options)
        with self.assertRaises(GetOddsError): client.history()
        self.assertEqual(opener.calls,0)
        with self.assertRaises(GetOddsError): client.odds()
    def test_sportsbook_prices(self):
        row={'id':'fixture','event_id':'event','sport':'NBA','market':'moneyline','period':'full','side':'home','starts_at':STAMP,'observed_at':STAMP,'source_updated_at':None,'age_seconds':0,'stale':False,'line':None,'american':-110,'decimal':1.909}
        for change,valid in [({},True),({'decimal':None},False),({'american':True},False),({'line':'5'},False),({'observed_at':'invalid'},False)]:
            body={'request_id':'fixture','data':[{**row,**change}],'meta':{'source':'draftkings','transport':'stored_espn_draftkings','snapshot_consistent':False,'checked_at':STAMP},'pagination':{'limit':2,'offset':0,'has_more':False,'next_offset':None}}
            client=GetOdds('fixture',Opener(json.dumps(body).encode()))
            if valid: self.assertEqual(client.odds(limit=2),body)
            else:
                with self.assertRaises(GetOddsError): client.odds(limit=2)

from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs
from copy import deepcopy

def page(data=None,meta=None,limit=2,offset=0):
    return {'request_id':'fixture','data':data or [],'meta':{'source':'draftkings','transport':'stored_espn_draftkings','snapshot_consistent':False,'checked_at':STAMP,**(meta or {})},'pagination':{'limit':limit,'offset':offset,'has_more':False,'next_offset':None}}
EVENT={'id':'event:1','sport':'NBA','home':'Home','away':'Away','starts_at':STAMP,'observed_at':STAMP,'age_seconds':0,'stale':False}
HISTORY={'league':'NBA','from_':'2026-01-01T00:00:00Z','to':'2026-01-02T00:00:00Z'}
HISTORY_META={'from':HISTORY['from_'],'to':HISTORY['to'],'event_state':'unknown','finished_events_verified':False,'archive_complete':False}
SUMMARY_META={'independent_bookmakers':1,'cross_book_comparison':False,'normalization':'multiplicative recorded prices'}
SUMMARY={'event_id':'event:1','league':'NBA','market':'spread','period':'game','reference_line':-3.5,'line_orientation':'home','expected_sides_present':True,'capture_times_coherent':True,'bookmaker_count':1,'implied_probability_sum':1,'outcomes':[{'side':side,'line':-3.5 if side=='home' else 3.5,'best_decimal':2,'average_decimal':2,'median_decimal':2,'worst_decimal':2,'bookmaker_count':1,'normalized_price_probability':0.5,'quotes':[{'offer_id':side,'bookmaker':'draftkings','decimal':2,'american':100,'observed_at':STAMP}]} for side in ['home','away']]}
class RecordingOpener(Opener):
    def open(self,req,timeout):
        self.url=req.full_url
        return super().open(req,timeout)
class AdvancedTest(unittest.TestCase):
    def test_advanced_routing(self):
        cases=[('search_events',{'q':'  Home  '},'events/search',page([EVENT])),
               ('odds_multi',{'event_ids':['event:1','event:2']},'odds/multi',page()),
               ('updated_odds',{'since':(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat(timespec='milliseconds')},'odds/updated',page()),
               ('dropping_odds',{'min_drop_pct':1.5},'dropping-odds',page()),
               ('leagues',{'sport':'basketball','upcoming_only':True},'leagues',page([{'id':'NBA','name':'NBA','sport':'basketball','event_count':2,'upcoming_event_count':1}])),
               ('historical_events',HISTORY,'historical/events',page([EVENT],HISTORY_META)),
               ('search_historical_events',{**HISTORY,'q':'Home'},'historical/events/search',page([EVENT],HISTORY_META)),
               ('odds_summary',{'event_id':'event:1'},'odds/summary',page([SUMMARY],SUMMARY_META)),
               ('odds_summary_multi',{'event_ids':'event:1,event:2'},'odds/summary/multi',page([SUMMARY],SUMMARY_META))]
        for method,options,path,body in cases:
            opener=RecordingOpener(json.dumps(body).encode());client=GetOdds('fixture',opener)
            self.assertEqual(getattr(client,method)(**options,limit=2),body)
            url=urlparse(opener.url);query=parse_qs(url.query)
            self.assertEqual(url.path,'/api/v1/'+path);self.assertEqual(query['source'],['draftkings']);self.assertEqual(opener.calls,1)
            if 'q' in options:self.assertEqual(query['q'],[options['q'].strip()])
            if 'event_ids' in options:self.assertEqual(query['event_ids'],['event:1,event:2'])
            if 'from_' in options:self.assertEqual(query['from'],[options['from_']]);self.assertNotIn('from_',query)
        opener=RecordingOpener(json.dumps(page([EVENT],limit=1)).encode())
        self.assertEqual(GetOdds('fixture',opener).event('event:1')['data'][0]['id'],'event:1')
        self.assertEqual(urlparse(opener.url).path,'/api/v1/events/event:1')
        self.assertNotIn('limit',parse_qs(urlparse(opener.url).query))
    def test_advanced_bounds(self):
        opener=Opener(b'');client=GetOdds('fixture',opener)
        cases=[('events/search',{}),('events/search',{'q':'x'}),('events/search',{'q':'ok','unknown':1}),('events/{id}',{'id':'a','limit':1}),('events/{id}',{'id':'../secret'}),('odds/multi',{'event_ids':['a','a']}),('odds/multi',{'event_ids':[]}),('odds/multi',{'event_ids':['e'+str(i) for i in range(21)]}),('odds/updated',{'since':'2020-01-01T00:00:00Z'}),('odds/updated',{'since':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(timespec='milliseconds')}),('dropping-odds',{'min_drop_pct':True}),('dropping-odds',{'min_drop_pct':100}),('leagues',{'sport':'NBA'}),('leagues',{'upcoming_only':'true'}),('historical/events',{**HISTORY,'from_':'2026-02-30T00:00:00Z'}),('historical/events',{**HISTORY,'to':'2026-03-01T00:00:00Z'}),('historical/events',{**HISTORY,'from':'2026-01-01T00:00:00Z'}),('historical/events',{}),('odds/summary',{}),('odds/summary/multi',{'event_ids':'a,'})]
        for resource,options in cases:
            with self.assertRaises(GetOddsError) as error:client.sportsbook(resource,**options)
            self.assertEqual(error.exception.code,'INVALID_QUERY')
        self.assertEqual(opener.calls,0)
    def test_summary_contract(self):
        mutations=[lambda b:b['meta'].update(cross_book_comparison=True),lambda b:b['data'][0]['outcomes'][0].update(best_decimal=3),lambda b:b['data'][0]['outcomes'][0].update(line=-4.5),lambda b:b['data'][0]['outcomes'][0].update(normalized_price_probability=0.9),lambda b:b['data'][0].update(implied_probability_sum=2),lambda b:b['data'][0]['outcomes'].pop(),lambda b:b['data'][0].update(capture_times_coherent=False),lambda b:b['data'][0]['outcomes'][0]['quotes'][0].update(american=True)]
        for mutate in mutations:
            body=deepcopy(page([SUMMARY],SUMMARY_META));mutate(body)
            with self.assertRaises(GetOddsError) as error:GetOdds('fixture',Opener(json.dumps(body).encode())).odds_summary(event_id='event:1',limit=2)
            self.assertEqual(error.exception.code,'INVALID_RESPONSE')
        partial=deepcopy(SUMMARY);partial['outcomes'].pop();partial['expected_sides_present']=False;partial['implied_probability_sum']=None;partial['outcomes'][0]['normalized_price_probability']=None
        body=page([partial],SUMMARY_META)
        self.assertEqual(GetOdds('fixture',Opener(json.dumps(body).encode())).odds_summary(event_id='event:1',limit=2),body)
    def test_single_event_identity_and_sanitized_refusal(self):
        with self.assertRaises(GetOddsError) as error:GetOdds('fixture',Opener(json.dumps(page([EVENT],limit=1)).encode())).event('wrong')
        self.assertEqual(error.exception.code,'INVALID_RESPONSE')
        with self.assertRaises(GetOddsError) as error:GetOdds('fixture',Opener(error=HTTPError('https://example.invalid',503,'private',{},None))).leagues()
        self.assertEqual(error.exception.status,503);self.assertNotIn('private',str(error.exception))

class CliTest(unittest.TestCase):
    def test_commands_and_invalid_options(self):
        import subprocess,sys,os
        def run(args):return subprocess.run([sys.executable,'-m','getodds',*args],capture_output=True,text=True,timeout=3,env={**os.environ,'GETODDS_API_KEY':'fixture'})
        help=run(['--help']);self.assertEqual(help.returncode,0);self.assertIn('odds/summary/multi',help.stdout);self.assertIn('--from',help.stdout)
        for args in [['events/search','--q','x'],['events/search','--q','ok','--q','again'],['events/{id}','--id','bad/path'],['leagues','--sport','NBA'],['historical/events','--league','NBA']]:
            result=run(args);self.assertNotEqual(result.returncode,0);self.assertTrue('INVALID_QUERY' in result.stderr or 'duplicate options' in result.stderr,result.stderr)

if __name__ == '__main__': unittest.main()

class NewReadTest(unittest.TestCase):
    def test_new_route_transport_and_validation(self):
        from pathlib import Path
        from getodds import read_query,validate_read
        from urllib.parse import urlparse,parse_qs
        cases=json.loads((Path(__file__).parents[1]/'read-fixtures.json').read_text())
        for resource,options,body in cases:
            info=read_query(resource,options)
            class Capture(Opener):
                def open(self,req,timeout):
                    parsed=urlparse(req.full_url);query=parse_qs(parsed.query)
                    assert parsed.path=='/api/v1/'+info['path']
                    assert query['source']==[info['source']]
                    for field in ('after','through','league','sport','family'):
                        if field in options: assert query[field]==[options[field]]
                    return super().open(req,timeout)
            transport=Capture(json.dumps(body).encode())
            self.assertEqual(GetOdds('fixture',transport).sportsbook(resource,**options),body)
            self.assertEqual(transport.calls,1)
            with self.assertRaises(GetOddsError): validate_read({**body,'meta':{**body['meta'],'source':'wrong'}},resource,info)
    def test_invalid_read_never_sends(self):
        transport=Opener(b'');client=GetOdds('fixture',transport)
        for resource,args in [('odds/replay',{'after':9007199254740993}),('odds/replay',{'after':'9223372036854775808'}),('odds/replay',{'after':'2','through':'1'}),('events/live',{'source':'draftkings'}),('sportsbook/markets',{'limit':101}),('participants',{'event_id':'https://evil.invalid'}),('participants/{id}',{'event_id':'espn-draftkings:espn:NBA:123','id':'espn:NFL:team:1'}),('outrights',{'offset':1})]:
            with self.assertRaises(GetOddsError): client.sportsbook(resource,**args)
        self.assertEqual(transport.calls,0)
    def test_replay_never_coerces_or_accepts_rollback(self):
        from pathlib import Path
        from getodds import read_query,validate_read
        resource,args,body=json.loads((Path(__file__).parents[1]/'read-fixtures.json').read_text())[3]
        for broken in [{**body,'pagination':{**body['pagination'],'next_after':9007199254740994}},{**body,'data':[{**body['data'][0],'seq':args['after']}]},{**body,'pagination':{**body['pagination'],'through':'9007199254740995'}}]:
            with self.assertRaises(GetOddsError): validate_read(broken,resource,read_query(resource,args))

class NewCliTest(unittest.TestCase):
    def test_cli_preserves_string_cursor(self):
        import contextlib,sys
        from pathlib import Path
        from unittest.mock import patch
        from getodds.__main__ import main
        body=json.loads((Path(__file__).parents[1]/'read-fixtures.json').read_text())[3][2]
        class Capture:
            def sportsbook(self,resource,**options):
                assert resource=='odds/replay'
                assert options=={'after':'9007199254740993','through':'9007199254740994'}
                return body
        output=io.StringIO()
        with patch.object(sys,'argv',['getodds','odds/replay','--after','9007199254740993','--through','9007199254740994']),patch('getodds.__main__.GetOdds',return_value=Capture()),contextlib.redirect_stdout(output):
            self.assertEqual(main(),0)
        self.assertEqual(json.loads(output.getvalue())['pagination']['next_after'],'9007199254740994')
