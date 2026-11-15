import io
import json
import unittest
from urllib.error import HTTPError
from getodds import GetOddsError, public_board, odds_board

BOARD = {'checked_at': '2026-11-15T05:49:50.185Z', 'complete': False, 'source': 'DraftKings via ESPN', 'max_age_seconds': 900,
         'has_more': False, 'state': 'available',
         'rows': [{'id': 'espn-draftkings:abc', 'event_id': 'espn-draftkings:espn:NBA:401909985', 'sport': 'NBA',
                   'home': 'Philadelphia 76ers', 'away': 'Indiana Pacers', 'market': 'moneyline', 'period': 'game',
                   'side': 'away', 'american': 235, 'decimal': 3.35, 'line': None,
                   'starts_at': '2026-11-15T18:00:00.000Z', 'observed_at': '2026-11-15T05:44:23.769Z', 'source_updated_at': None}]}

class Opener:
    def __init__(self, body=None, error=None):
        self.body, self.error, self.urls = body, error, []
    def open(self, req, timeout):
        self.urls.append(req.full_url)
        assert req.get_header('Authorization') is None, 'public boards must not send a key'
        assert timeout == 20
        if self.error:
            raise self.error
        return io.BytesIO(self.body)

class PublicBoardTest(unittest.TestCase):
    def test_sport_board_is_keyless(self):
        opener = Opener(json.dumps(BOARD).encode())
        self.assertEqual(public_board('nba', opener)['rows'][0]['american'], 235)
        self.assertEqual(opener.urls, ['https://getoddsapi.com/api/public/boards/nba'])
    def test_mixed_board(self):
        opener = Opener(json.dumps(BOARD).encode())
        self.assertEqual(odds_board(opener)['state'], 'available')
        self.assertEqual(opener.urls, ['https://getoddsapi.com/api/public/odds-board'])
    def test_unknown_sport_makes_no_request(self):
        opener = Opener(b'{}')
        with self.assertRaises(GetOddsError) as err: public_board('curling', opener)
        self.assertEqual(err.exception.code, 'INVALID_SPORT')
        self.assertEqual(opener.urls, [])
    def test_bad_shape_rejected(self):
        with self.assertRaises(GetOddsError): public_board('nfl', Opener(b'{"rows":"x"}'))
    def test_http_error_surfaces_status(self):
        err = HTTPError('https://getoddsapi.com', 503, 'x', {}, None)
        with self.assertRaises(GetOddsError) as e: public_board('nhl', Opener(error=err))
        self.assertEqual(e.exception.status, 503)

if __name__ == '__main__':
    unittest.main()
