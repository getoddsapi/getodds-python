# getodds (Python)

Python client for the [GetOdds sports odds API](https://getoddsapi.com): DraftKings, FanDuel and BetRivers
sportsbook prices plus PrizePicks, Underdog and DraftKings Pick6 pick'em lines, with capture times on every row.
No dependencies (standard library only), Python 3.10+.

```sh
pip install getodds
```

## Try it with no key

The public boards need no account and use no credits. They return DraftKings prices (read through ESPN's odds data),
cached for up to five minutes.

```python
from getodds import public_board

board = public_board("nhl")          # nfl, nba, nhl, college-football, soccer-odds-api
for row in board["rows"][:2]:
    print(row["away"], "@", row["home"], row["market"], row["side"], row["american"], row["observed_at"])
```

Output from a real run on 15 Nov 2026 (05:50 UTC):

```
Edmonton Oilers @ Philadelphia Flyers moneyline away -155 2026-11-15T05:44:25.914Z
Edmonton Oilers @ Philadelphia Flyers moneyline home 130 2026-11-15T05:44:25.914Z
```

Prices move; your numbers will differ. From the shell: `getodds board --sport nba` (or `python -m getodds board`).

## With a free key

Create a free key at <https://getoddsapi.com/sign-up> (1,000 requests a UTC day, 60 a minute, no card) and set it in
the server environment:

```sh
export GETODDS_API_KEY=...   # never commit it
```

```python
from getodds import GetOdds, GetOddsError

client = GetOdds()  # reads GETODDS_API_KEY

# DraftKings NBA moneylines, only rows captured recently
odds = client.odds(sport="NBA", market="moneyline", fresh_only=True, limit=10)

# Pick'em thresholds from PrizePicks or Underdog (the key needs that source granted)
lines = client.markets(source="prizepicks", limit=20)

# FanDuel native game markets
fd = client.fanduel_markets(league="NBA", limit=5)

try:
    client.history(event_id="espn-draftkings:espn:NBA:401909985")
except GetOddsError as err:
    print(err.code, err.status, err.retry_after)  # e.g. HTTP_ERROR 429 60
```

Each call makes one bounded request (20 s timeout, 2 MiB cap, no redirects) and validates the response contract.
There are no automatic retries or pagination: pass `offset` (or the returned cursor) yourself.
A successful data request uses one credit; failed reads use none.

| Method | Route |
| --- | --- |
| `odds`, `events`, `history`, `sports`, `bookmakers`, `market_types` | DraftKings (via ESPN) stored odds |
| `search_events`, `event`, `odds_multi`, `updated_odds`, `dropping_odds`, `leagues` | event search and change feeds |
| `historical_events`, `odds_summary`, `replay`, `event_state`, `participants` | history, replay and metadata |
| `markets(source=...)` | PrizePicks, Underdog, DraftKings Pick6 thresholds |
| `fanduel_markets`, `outrights`, `outright_odds`, `live_events` | FanDuel native markets |

Full reference: <https://getoddsapi.com/docs> and the OpenAPI spec at <https://getoddsapi.com/openapi.json>.

## Tests

```sh
PYTHONPATH=. python3 -m unittest discover -s tests
```

Tests run offline against fixtures and a fake opener.

GetOdds is an independent developer product, not affiliated with any sportsbook. Operated by Stunning Couches LLC.
MIT licensed.
