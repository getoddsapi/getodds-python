"""Dependency-free GetOdds client. One bounded request; no implicit retries."""
import json
import math
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
import re
from urllib.request import Request, build_opener, HTTPRedirectHandler

class GetOddsError(Exception):
    def __init__(self, code, status=0, retry_after=None):
        super().__init__(code)
        self.code, self.status, self.retry_after = code, status, retry_after

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _text(value):
    return isinstance(value, str) and bool(value)

def _date(value):
    if not _text(value):
        return False
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is not None
    except ValueError:
        return False

SOURCES = ('prizepicks', 'underdog', 'draftkings', 'fanduel')

def validate_markets(body, limit, source='prizepicks'):
    valid = isinstance(body, dict) and _text(body.get('request_id'))
    meta = body.get('meta') if valid else None
    rows = body.get('data') if valid else None
    valid = (valid and isinstance(meta, dict) and meta.get('source') == source
             and meta.get('complete') is False and _date(meta.get('observed_at'))
             and isinstance(rows, list) and len(rows) <= limit)
    seen = set()
    for row in rows if valid else []:
        if not isinstance(row, dict):
            valid = False
            break
        line = row.get('line')
        valid = (valid and _text(row.get('id')) and row['id'] not in seen
                 and row.get('source') == source and _text(row.get('player'))
                 and _text(row.get('market')) and type(line) in (int, float)
                 and math.isfinite(line) and 'odds' in row and row['odds'] is None
                 and _date(row.get('observed_at'))
                 and all(k in row and (row[k] is None or _date(row[k])) for k in ('starts_at', 'source_updated_at'))
                 and 'league' in row and (row['league'] is None or _text(row['league'])))
        if not valid:
            break
        seen.add(row['id'])
    if not valid:
        raise GetOddsError('INVALID_RESPONSE')
    return body

RESOURCES = ('events', 'odds', 'history', 'sports', 'bookmakers', 'market-types',
             'events/search', 'events/{id}', 'odds/multi', 'odds/updated', 'dropping-odds',
             'leagues', 'historical/events', 'historical/events/search', 'odds/summary', 'odds/summary/multi')
LEAGUES = ('NFL','NBA','NHL','NCAAF','NCAAB','MLB','EPL','MLS')
CATEGORIES = ('basketball','american-football','ice-hockey','baseball','soccer')
FILTERS = {
    'events':('sport','event_id'), 'odds':('sport','event_id','market','fresh_only'),
    'history':('sport','event_id','market','offer_id'), 'events/search':('q','sport'),
    'events/{id}':('id',), 'odds/multi':('event_ids','sport','market','fresh_only'),
    'odds/updated':('since','sport','market','fresh_only'), 'dropping-odds':('sport','market','min_drop_pct'),
    'leagues':('sport','upcoming_only'), 'historical/events':('league','from','to'),
    'historical/events/search':('league','from','to','q'), 'odds/summary':('event_id','market'),
    'odds/summary/multi':('event_ids','market'),
}
def _id(value):
    return isinstance(value,str) and bool(re.fullmatch(r'[-A-Za-z0-9_:]{1,180}',value))
def _iso(value, utc_only=False):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})',value):
        return None
    if utc_only and not value.endswith('Z'): return None
    try: return datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError: return None

def sportsbook_query(resource, options, now=None):
    def bad(): raise GetOddsError('INVALID_QUERY')
    if resource not in RESOURCES or not isinstance(options,dict): bad()
    options=dict(options)
    if 'from_' in options:
        if not resource.startswith('historical/') or 'from' in options: bad()
        options['from']=options.pop('from_')
    now=now or datetime.now(timezone.utc)
    single=resource=='events/{id}'
    allowed={'source', *(() if single else ('limit','offset')), *FILTERS.get(resource,())}
    limit, offset = options.get('limit',50), options.get('offset',0)
    if (set(options)-allowed or options.get('source','draftkings')!='draftkings'
        or type(limit) is not int or not 1<=limit<=200 or type(offset) is not int or not 0<=offset<=10000): bad()
    if 'sport' in options and options['sport'] not in (CATEGORIES if resource=='leagues' else LEAGUES): bad()
    if 'league' in options and options['league'] not in LEAGUES: bad()
    if 'market' in options and options['market'] not in ('moneyline','spread','total'): bad()
    for key in ('id','event_id','offer_id'):
        if key in options and not _id(options[key]): bad()
    for key in ('fresh_only','upcoming_only'):
        if key in options and type(options[key]) is not bool: bad()
    if resource=='history' and not options.get('event_id') and not options.get('offer_id'): raise GetOddsError('HISTORY_ID_REQUIRED')
    if single and not _id(options.get('id')): bad()
    if resource in ('events/search','historical/events/search'):
        q=options.get('q')
        if not isinstance(q,str) or not 2<=len(q.strip())<=100: bad()
        options['q']=q.strip()
    if resource in ('odds/multi','odds/summary/multi'):
        ids=options.get('event_ids')
        if isinstance(ids,str): ids=ids.split(',')
        if not isinstance(ids,(list,tuple)) or not 1<=len(ids)<=20 or not all(_id(i) for i in ids) or len(set(ids))!=len(ids): bad()
        options['event_ids']=','.join(ids)
    if resource=='odds/summary' and not _id(options.get('event_id')): bad()
    if resource=='odds/updated':
        since=_iso(options.get('since'))
        if since is None or not 0<=(now-since).total_seconds()<=7*86400: bad()
    if 'min_drop_pct' in options:
        drop=options['min_drop_pct']
        if type(drop) not in (int,float) or not re.fullmatch(r'\d+(?:\.\d{1,3})?',str(drop)) or not 0.1<=drop<100: bad()
    if resource.startswith('historical/'):
        start,end=_iso(options.get('from'),True),_iso(options.get('to'),True)
        if options.get('league') not in LEAGUES or start is None or end is None or not 0<(end-start).total_seconds()<=31*86400 or end>now: bad()
    query={**options,'source':'draftkings'}
    if single: query.pop('id');limit,offset=1,0
    else: query.update(limit=limit,offset=offset)
    for key in ('fresh_only','upcoming_only'):
        if key in query: query[key]=str(query[key]).lower()
    return urlencode(query),limit,offset

def validate_sportsbook(body, resource, limit, offset):
    def fail(): raise GetOddsError('INVALID_RESPONSE')
    def number(v): return type(v) in (int, float) and math.isfinite(v)
    if not isinstance(body,dict) or not _text(body.get('request_id')): fail()
    meta, rows, page = body.get('meta'), body.get('data'), body.get('pagination')
    if (not isinstance(meta,dict) or meta.get('source') != 'draftkings'
        or meta.get('transport') != 'stored_espn_draftkings' or meta.get('snapshot_consistent') is not False
        or not _date(meta.get('checked_at')) or not isinstance(rows,list) or len(rows)>limit): fail()
    if (not isinstance(page,dict) or type(page.get('limit')) is not int or page['limit']!=limit
        or type(page.get('offset')) is not int or page['offset']!=offset
        or type(page.get('has_more')) is not bool or 'next_offset' not in page): fail()
    next_offset=page['next_offset']
    if next_offset is not None and (not page['has_more'] or type(next_offset) is not int or next_offset!=offset+limit or next_offset>10000): fail()
    original=resource
    if resource in ('events/search','events/{id}','historical/events','historical/events/search'): resource='events'
    if resource in ('odds/multi','odds/updated','dropping-odds'): resource='odds'
    fields = {'events':('id','sport','home','away'), 'odds':('id','event_id','sport','market','period','side'),
              'history':('seq','offer_id','event_id','sport','market','period','side'), 'market-types':('market','period')}.get(resource,() if resource.startswith('odds/summary') else ('id','name'))
    for row in rows:
        if not isinstance(row,dict) or not all(_text(row.get(k)) for k in fields): fail()
        if resource in ('events','odds','history') and (not _date(row.get('observed_at')) or type(row.get('age_seconds')) is not int or row['age_seconds']<0 or type(row.get('stale')) is not bool): fail()
        if resource in ('events','odds') and not _date(row.get('starts_at')): fail()
        if resource in ('odds','history') and (not number(row.get('decimal')) or row['decimal']<=1 or type(row.get('american')) is not int or abs(row['american'])<100 or 'line' not in row or (row['line'] is not None and not number(row['line']))): fail()
    if original=='events/{id}' and (len(rows)!=1 or page['has_more'] or page['next_offset'] is not None): fail()
    if original.startswith('historical/') and (meta.get('event_state')!='unknown' or meta.get('finished_events_verified') is not False or meta.get('archive_complete') is not False or not _date(meta.get('from')) or not _date(meta.get('to'))): fail()
    for row in rows:
        if original=='leagues' and (row.get('sport') not in CATEGORIES or type(row.get('event_count')) is not int or row['event_count']<0 or type(row.get('upcoming_event_count')) is not int or not 0<=row['upcoming_event_count']<=row['event_count']): fail()
        if original in ('odds/updated','dropping-odds') and not _date(row.get('changed_at')): fail()
        if original=='dropping-odds' and (not _date(row.get('previous_observed_at')) or not number(row.get('previous_decimal')) or row['previous_decimal']<=1 or not number(row.get('drop_pct')) or not 0<row['drop_pct']<100): fail()
    if original.startswith('odds/summary'): _validate_summaries(body,fail)
    return body

def _validate_summaries(body,fail):
    def number(v): return type(v) in (int,float) and math.isfinite(v)
    def nullable(v): return v is None or number(v)
    meta=body['meta']
    if type(meta.get('independent_bookmakers')) is not int or meta['independent_bookmakers']!=1 or meta.get('cross_book_comparison') is not False or not _text(meta.get('normalization')): fail()
    groups=set()
    for row in body['data']:
        if (not all(_text(row.get(k)) for k in ('event_id','league','market','period')) or row['market'] not in ('moneyline','spread','total')
            or 'reference_line' not in row or not nullable(row['reference_line']) or type(row.get('bookmaker_count')) is not int or row['bookmaker_count']!=1
            or type(row.get('expected_sides_present')) is not bool or type(row.get('capture_times_coherent')) is not bool
            or 'implied_probability_sum' not in row or not nullable(row['implied_probability_sum']) or not isinstance(row.get('outcomes'),list) or not row['outcomes']): fail()
        orientation={'spread':'home','total':'total'}.get(row['market'])
        if 'line_orientation' not in row or row['line_orientation']!=orientation or (row['reference_line'] is None)!=(row['market']=='moneyline'): fail()
        identity=(row['event_id'],row['market'],row['period'],row['reference_line'])
        if identity in groups: fail()
        groups.add(identity)
        complete=row['expected_sides_present'] and row['capture_times_coherent']
        if complete:
            if not number(row['implied_probability_sum']) or row['implied_probability_sum']<=0: fail()
        elif row['implied_probability_sum'] is not None: fail()
        sides=set();implied=0;clocks=[]
        for outcome in row['outcomes']:
            if (not isinstance(outcome,dict) or not _text(outcome.get('side')) or outcome['side'] in sides or 'line' not in outcome or not nullable(outcome['line'])
                or type(outcome.get('bookmaker_count')) is not int or outcome['bookmaker_count']!=1 or not isinstance(outcome.get('quotes'),list) or len(outcome['quotes'])!=1): fail()
            sides.add(outcome['side']);quote=outcome['quotes'][0]
            if (not isinstance(quote,dict) or not _text(quote.get('offer_id')) or quote.get('bookmaker')!='draftkings' or not number(quote.get('decimal')) or quote['decimal']<=1
                or type(quote.get('american')) is not int or abs(quote['american'])<100 or not _date(quote.get('observed_at'))): fail()
            if not all(number(outcome.get(k)) and outcome[k]==quote['decimal'] for k in ('best_decimal','average_decimal','median_decimal','worst_decimal')): fail()
            implied+=1/quote['decimal'];clocks.append(datetime.fromisoformat(quote['observed_at'].replace('Z','+00:00')).timestamp())
            line=None if row['market']=='moneyline' else -row['reference_line'] if row['market']=='spread' and outcome['side']=='away' else row['reference_line']
            if outcome['line']!=line: fail()
            if 'normalized_price_probability' not in outcome: fail()
            probability=outcome['normalized_price_probability']
            if complete:
                if not number(probability) or not 0<=probability<=1 or abs(probability-(1/quote['decimal'])/row['implied_probability_sum'])>1e-9: fail()
            elif probability is not None: fail()
        if row['capture_times_coherent']!=(max(clocks)-min(clocks)<=60) or (complete and abs(implied-row['implied_probability_sum'])>1e-9): fail()
        expected={'over','under'} if row['market']=='total' else {'home','away','draw'} if row['market']=='moneyline' and row['league'] in ('EPL','MLS') else {'home','away'}
        if sides-expected or row['expected_sides_present']!=(sides==expected): fail()

READ_RESOURCES=['events/{id}/state','participants','participants/{id}','odds/replay','sportsbook/markets','outrights','outrights/odds','events/live']
def _seq(value): return isinstance(value,str) and re.fullmatch(r'(0|[1-9]\d{0,18})',value) is not None and int(value)<=9223372036854775807
def _native(value): return isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,180}',value) is not None
def _event_identity(value): return isinstance(value,str) and re.fullmatch(r'espn-draftkings:espn:(NBA|NFL|NHL|NCAAF|NCAAB|MLB|EPL|MLS):\d{1,20}',value) is not None
def read_query(resource,options):
    def bad(): raise GetOddsError('INVALID_QUERY')
    if resource not in READ_RESOURCES or not isinstance(options,dict): bad()
    fd=resource in READ_RESOURCES[4:];metadata=resource in READ_RESOURCES[:3];source='fanduel' if fd else 'draftkings'
    fields=(['id'] if resource=='events/{id}/state' else ['event_id'] if resource=='participants' else ['event_id','id']) if metadata else ['after','through','limit','event_ids','sport','market'] if resource=='odds/replay' else ['limit','after','event_id','league']+(['sport'] if resource=='events/live' else ['market_id','family','status'])
    if set(options)-set(['source']+fields) or options.get('source',source)!=source: bad()
    query={**options,'source':source};path=resource
    if metadata:
        event=options.get('id') if resource=='events/{id}/state' else options.get('event_id')
        if not _event_identity(event): bad()
        if resource=='participants/{id}' and (not isinstance(options.get('id'),str) or not re.fullmatch(r'espn:(NBA|NFL|NHL|NCAAF|NCAAB|MLB|EPL|MLS):team:\d{1,20}',options['id']) or options['id'].split(':')[1]!=event.split(':')[2]): bad()
        if '{id}' in resource: path=resource.replace('{id}',quote(options['id'],safe=''));del query['id']
        limit=2 if resource=='participants' else 1
    else:
        limit=options.get('limit',50);query['limit']=limit
        if type(limit) is not int or not 1<=limit<=(100 if fd else 200): bad()
        if fd:
            if any(key in options and not _native(options[key]) for key in fields if key!='limit'): bad()
            if 'status' in options and options['status'] not in ('open','suspended','closed','removed'): bad()
        else:
            query['after']=options.get('after','0')
            if not _seq(query['after']) or ('through'in options and (not _seq(options['through']) or int(query['after'])>int(options['through']))): bad()
            if 'sport'in options and options['sport'] not in LEAGUES: bad()
            if 'market'in options and options['market'] not in ('moneyline','spread','total'): bad()
            if 'event_ids'in options:
                ids=options['event_ids'] if isinstance(options['event_ids'],list) else options['event_ids'].split(',') if isinstance(options['event_ids'],str) else []
                if not 1<=len(ids)<=20 or not all(_id(value) for value in ids) or len(set(ids))!=len(ids): bad()
                query['event_ids']=','.join(ids)
    return {'path':path,'query':query,'source':source,'limit':limit,'options':options}
def validate_read(body,resource,input):
    def fail(): raise GetOddsError('INVALID_RESPONSE')
    def number(value): return type(value) in (int,float) and math.isfinite(value)
    if not isinstance(body,dict) or not _text(body.get('request_id')) or not isinstance(body.get('meta'),dict) or not isinstance(body.get('data'),list): fail()
    meta=body['meta'];rows=body['data'];p=body.get('pagination');options=input['options']
    if meta.get('source')!=input['source'] or len(rows)>input['limit'] or not all(isinstance(row,dict) for row in rows): fail()
    if resource in READ_RESOURCES[:3]:
        if meta.get('transport')!='live_espn_summary' or meta.get('metadata_provider')!='espn' or any(meta.get(key) is not False for key in ('canonical_cross_provider_identity','settlement_verified','receipt_time_is_source_freshness')) or not _date(meta.get('observed_at')): fail()
        event=options['id'] if resource=='events/{id}/state' else options['event_id']
        if len(rows)!=(2 if resource=='participants' else 1) or any(row.get('event_id')!=event for row in rows): fail()
        if resource=='events/{id}/state':
            row=rows[0]
            if row.get('state') not in ('pre','in','post') or type(row.get('completed')) is not bool or (row['completed'] and row['state']!='post') or not _text(row.get('source_status')) or not _date(row.get('starts_at')): fail()
        else:
            for row in rows:
                identity=row.get('id')
                if not isinstance(identity,str) or not re.fullmatch(r'espn:(NBA|NFL|NHL|NCAAF|NCAAB|MLB|EPL|MLS):team:\d{1,20}',identity) or identity.split(':')[1]!=event.split(':')[2] or row.get('type')!='team' or not _text(row.get('name')) or row.get('side') not in ('home','away'): fail()
            if len({row['id'] for row in rows})!=len(rows) or (resource=='participants' and len({row['side'] for row in rows})!=2) or (resource=='participants/{id}' and rows[0]['id']!=options['id']): fail()
    else:
        if not _date(meta.get('checked_at')) or not isinstance(p,dict) or type(p.get('limit')) is not int or p['limit']!=input['limit'] or type(p.get('has_more')) is not bool: fail()
        if resource=='odds/replay':
            if meta.get('transport')!='stored_espn_draftkings' or any(meta.get(key) is not False for key in ('source_capture_complete','deletion_events_available','snapshot_consistent')) or not all(_seq(p.get(key)) for key in ('after','through','next_after')): fail()
            if p['after']!=input['query']['after'] or ('through'in options and p['through']!=options['through']) or type(p.get('replay_complete')) is not bool or p['replay_complete']==p['has_more'] or not int(p['after'])<=int(p['next_after'])<=int(p['through']): fail()
            previous=int(p['after'])
            for row in rows:
                if not _seq(row.get('seq')) or not previous<int(row['seq'])<=int(p['through']) or not all(_text(row.get(key)) for key in ('offer_id','event_id')) or not _date(row.get('observed_at')) or not number(row.get('decimal')) or not number(row.get('american')): fail()
                previous=int(row['seq'])
            if (not rows or p['next_after']!=rows[-1]['seq']) if p['has_more'] else p['next_after']!=p['through']: fail()
        else:
            if meta.get('identity')!='source_native' or meta.get('capture_complete') is not False or p.get('snapshot_consistent') is not False or 'next_after' not in p: fail()
            if (not rows or p['next_after']!=rows[-1].get('id')) if p['has_more'] else p['next_after'] is not None: fail()
            if resource=='events/live' and (meta.get('completion_available') is not False or meta.get('freshness_window_minutes')!=15): fail()
            previous=options.get('after','')
            for row in rows:
                if not _native(row.get('id')) or row['id']<=previous or not _text(row.get('sport')) or not _text(row.get('league')) or not _date(row.get('starts_at')): fail()
                previous=row['id']
                if resource=='events/live':
                    if meta.get('completion_available') is not False or meta.get('freshness_window_minutes')!=15 or row.get('observed_in_play') is not True or type(row.get('metadata_ambiguous')) is not bool or not _text(row.get('name')) or not _date(row.get('qualifying_market_observed_at')) or not _date(row.get('qualifying_market_changed_at')): fail()
                else:
                    if row.get('is_future') is not (resource!='sportsbook/markets') or not _native(row.get('event_id')) or not _date(row.get('observed_at')) or not _date(row.get('changed_at')) or row.get('market_status') not in ('open','suspended','closed','removed'): fail()
                    if resource=='outrights':
                        if type(row.get('selection_count')) is not int or row['selection_count']<0 or 'selections'in row: fail()
                    else:
                        if not isinstance(row.get('selections'),list) or len(row['selections'])>1000: fail()
                        for selection in row['selections']:
                            if not isinstance(selection,dict) or not _text(selection.get('id')) or selection.get('status') not in ('active','suspended') or not all(key in selection and (selection[key] is None or number(selection[key])) for key in ('american','decimal','line','fair')): fail()
    return body

class GetOdds:
    def __init__(self, api_key=None, opener=None):
        key = api_key if api_key is not None else os.environ.get('GETODDS_API_KEY')
        if not _text(key) or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in key):
            raise GetOddsError('INVALID_API_KEY')
        self._key = key
        self._opener = opener if opener is not None else build_opener(_NoRedirect())

    def markets(self, limit=50, source='prizepicks'):
        if source not in SOURCES:
            raise GetOddsError('SOURCE_UNAVAILABLE')
        if type(limit) is not int or not 1 <= limit <= 200:
            raise GetOddsError('INVALID_LIMIT')
        return validate_markets(self._request(f'markets?source={source}&limit={limit}'), limit, source)

    def sportsbook(self, resource, **options):
        if resource in READ_RESOURCES:
            info=read_query(resource,options)
            return validate_read(self._request(info['path']+'?'+urlencode(info['query'])),resource,info)
        query, limit, offset = sportsbook_query(resource, options)
        path='events/'+options['id'] if resource=='events/{id}' else resource
        body=validate_sportsbook(self._request(path + '?' + query), resource, limit, offset)
        if resource=='events/{id}' and body['data'][0]['id']!=options['id']: raise GetOddsError('INVALID_RESPONSE')
        return body

    def events(self, **options): return self.sportsbook('events', **options)
    def odds(self, **options): return self.sportsbook('odds', **options)
    def history(self, **options): return self.sportsbook('history', **options)
    def sports(self, **options): return self.sportsbook('sports', **options)
    def bookmakers(self, **options): return self.sportsbook('bookmakers', **options)
    def market_types(self, **options): return self.sportsbook('market-types', **options)

    def search_events(self, **options): return self.sportsbook('events/search', **options)
    def event(self, event_id, **options): return self.sportsbook('events/{id}', id=event_id, **options)
    def odds_multi(self, **options): return self.sportsbook('odds/multi', **options)
    def updated_odds(self, **options): return self.sportsbook('odds/updated', **options)
    def dropping_odds(self, **options): return self.sportsbook('dropping-odds', **options)
    def leagues(self, **options): return self.sportsbook('leagues', **options)
    def historical_events(self, **options): return self.sportsbook('historical/events', **options)
    def search_historical_events(self, **options): return self.sportsbook('historical/events/search', **options)
    def odds_summary(self, **options): return self.sportsbook('odds/summary', **options)
    def odds_summary_multi(self, **options): return self.sportsbook('odds/summary/multi', **options)

    def event_state(self, event_id, **options): return self.sportsbook('events/{id}/state',id=event_id,**options)
    def participants(self, **options): return self.sportsbook('participants',**options)
    def participant(self, participant_id, **options): return self.sportsbook('participants/{id}',id=participant_id,**options)
    def replay(self, **options): return self.sportsbook('odds/replay',**options)
    def fanduel_markets(self, **options): return self.sportsbook('sportsbook/markets',**options)
    def outrights(self, **options): return self.sportsbook('outrights',**options)
    def outright_odds(self, **options): return self.sportsbook('outrights/odds',**options)
    def live_events(self, **options): return self.sportsbook('events/live',**options)

    def _request(self, path):
        return _fetch('https://getoddsapi.com/api/v1/' + path,
                      {'Authorization': 'Bearer ' + self._key, 'Accept': 'application/json'}, self._opener)

def _fetch(url, headers, opener):
    req = Request(url, headers=headers)
    try:
        with opener.open(req, timeout=20) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise GetOddsError('RESPONSE_TOO_LARGE')
            body = json.loads(raw)
    except HTTPError as exc:
        retry = exc.headers.get('Retry-After', '') if exc.headers else ''
        delay = int(retry) if retry.isascii() and retry.isdigit() and len(retry) <= 6 else None
        raise GetOddsError('HTTP_ERROR', exc.code, delay) from None
    except (URLError, TimeoutError, OSError):
        raise GetOddsError('NETWORK_ERROR') from None
    except (ValueError, UnicodeError):
        raise GetOddsError('INVALID_RESPONSE') from None
    return body

# Keyless public boards: no API key, no credits. DraftKings prices (via ESPN), cached up to 5 minutes.
PUBLIC_SPORTS = ('nfl', 'nba', 'nhl', 'college-football', 'soccer-odds-api')

def _validate_board(body):
    if (not isinstance(body, dict) or body.get('state') not in ('available', 'empty', 'unavailable')
            or not _date(body.get('checked_at')) or not isinstance(body.get('rows'), list)
            or not all(isinstance(r, dict) for r in body['rows'])):
        raise GetOddsError('INVALID_RESPONSE')
    return body

def public_board(sport, opener=None):
    """Keyless DraftKings board for one sport: moneyline, spread and total rows with capture times."""
    if sport not in PUBLIC_SPORTS:
        raise GetOddsError('INVALID_SPORT')
    return _validate_board(_fetch('https://getoddsapi.com/api/public/boards/' + sport, {'Accept': 'application/json'},
                                  opener if opener is not None else build_opener(_NoRedirect())))

def odds_board(opener=None):
    """Keyless homepage board: the next DraftKings Sportsbook (New Jersey) prices across leagues."""
    return _validate_board(_fetch('https://getoddsapi.com/api/public/odds-board', {'Accept': 'application/json'},
                                  opener if opener is not None else build_opener(_NoRedirect())))
