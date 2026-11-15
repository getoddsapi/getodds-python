import argparse
import json
import sys
from . import GetOdds, GetOddsError, RESOURCES, SOURCES, READ_RESOURCES, public_board, odds_board

def main():
    parser=argparse.ArgumentParser(description='One bounded GetOdds read. No automatic pagination or retries.')
    parser.add_argument('command', choices=['board', 'markets', *RESOURCES, *READ_RESOURCES])
    for name in ['after','through','market-id','family','status']: parser.add_argument('--'+name)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--source', choices=SOURCES)
    parser.add_argument('--offset', type=int)
    parser.add_argument('--sport')
    parser.add_argument('--event-id')
    parser.add_argument('--offer-id')
    parser.add_argument('--market')
    parser.add_argument('--fresh-only', action='store_true', default=None)
    parser.add_argument('--id')
    parser.add_argument('--q')
    parser.add_argument('--event-ids')
    parser.add_argument('--since')
    parser.add_argument('--min-drop-pct', type=float)
    parser.add_argument('--league')
    parser.add_argument('--from', dest='from_')
    parser.add_argument('--to')
    parser.add_argument('--upcoming-only', action='store_true', default=None)
    flags=[arg.split('=',1)[0] for arg in sys.argv[1:] if arg.startswith('--')]
    if len(flags)!=len(set(flags)): parser.error('duplicate options are not supported')
    args=vars(parser.parse_args())
    command=args.pop('command')
    options={k:v for k,v in args.items() if v is not None}
    if command=='markets' and set(options)-{'limit','source'}: parser.error('markets only supports --limit and --source')
    try:
        if command=='board':
            # Keyless: no GETODDS_API_KEY needed. --sport nfl|nba|nhl|college-football|soccer-odds-api, or omit for the mixed board.
            if set(options)-{'sport'}: parser.error('board only supports --sport')
            print(json.dumps(public_board(options['sport']) if 'sport' in options else odds_board(),indent=2))
            return 0
        client=GetOdds()
        result=client.markets(**options) if command=='markets' else client.sportsbook(command,**options)
        print(json.dumps(result,indent=2))
    except GetOddsError as exc:
        print(json.dumps({'error':exc.code,'status':exc.status,'retry_after':exc.retry_after}),file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__': sys.exit(main())
