import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('crawler', Path(__file__).resolve().parents[1] / 'get_menu.py')
crawler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crawler)
VALID = '<table><tr><th>월(10/05)</th></tr><tr><td>비빔밥 5,000원</td></tr></table>'
def response(text, status=200):
    return SimpleNamespace(text=text, content=text.encode(), status_code=status)

class CrawlerTests(unittest.TestCase):
    def setUp(self):
        crawler.DIRECT_BLOCKED = False
        crawler.PROXY_REQUEST_COUNT = 0
        crawler.DIRECT_REQUEST_COUNT = 0

    def test_http_200_without_menu_uses_proxy(self):
        with patch.object(crawler, 'SCRAPER_KEY', 'secret'), patch.object(crawler.session, 'get', side_effect=[response('Access denied' * 100), response(VALID)]):
            result = crawler.fetch_html('https://example.invalid')
        self.assertEqual(result.text, VALID)
        self.assertEqual(crawler.PROXY_REQUEST_COUNT, 1)

    def test_empty_table_and_http_error_rejected(self):
        self.assertFalse(crawler.valid_response(response('<table><tr><th>월(10/05)</th></tr></table>')))
        self.assertFalse(crawler.valid_response(response(VALID, 403)))
        self.assertTrue(crawler.valid_response(response(VALID)))

    def test_no_api_key_retries_direct(self):
        with patch.object(crawler, 'SCRAPER_KEY', ''), patch.object(crawler.session, 'get', side_effect=[response('denied', 403), response(VALID)]), patch.object(crawler.time, 'sleep'):
            self.assertEqual(crawler.fetch_html('https://example.invalid').text, VALID)

    def test_failure_preserves_meals_and_returns_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'menu.json'
            old = dict(updated_at='2026-09-14 00:46:27', data={'old': {'menu': ['saved']}}, days=['월(09/14)'])
            path.write_text(json.dumps(old), encoding='utf-8')
            with patch.object(crawler, 'JSON_PATH', str(path)), patch.object(crawler, 'fetch_html', side_effect=RuntimeError('invalid response')), patch.object(crawler, 'crawl_menus', return_value=([], {}, 0, 0)):
                self.assertEqual(crawler.main(), 1)
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved['data'], old['data'])
            self.assertEqual(saved['updated_at'], old['updated_at'])
            self.assertEqual(saved['crawl_status'], 'failed')
            self.assertIn('last_checked', saved)

    def test_success_counts_real_menu(self):
        with patch.object(crawler, 'fetch_html', return_value=response(VALID)), patch.object(crawler.time, 'sleep'):
            days, data, successes, items = crawler.crawl_menus({'shop': '35'})
        self.assertEqual((successes, items), (1, 1))
        self.assertEqual(data['shop'][days[0]]['중식']['items'], ['비빔밥 5,000원'])

    def test_headers_alone_do_not_count_as_success(self):
        with patch.object(crawler, 'fetch_html', return_value=response('<table><tr><th>월(10/05)</th></tr></table>')), patch.object(crawler.time, 'sleep'):
            _, _, successes, items = crawler.crawl_menus({'shop': '35'})
        self.assertEqual((successes, items), (0, 0))

class DataIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.now = crawler.datetime(2026, 10, 23, 9, tzinfo=crawler.timezone(crawler.timedelta(hours=9)))
        self.weekly = {'금(10/23)': {'중식': {'items': ['비빔밥 5,000원'], 'time': '11:00~13:00'}}}
        self.old = dict(updated_at='2026-10-22 09:00:00', last_checked='2026-10-22 09:00:00',
                        shops=['A', 'B'], days=['금(10/23)'], data={'A': self.weekly, 'B': self.weekly})

    def test_partial_preserves_failed_shop_and_marks_failure(self):
        result = crawler.build_result(self.old, ['A', 'B'], {'A': self.weekly, 'B': {}}, self.now, self.now)
        self.assertEqual(result['crawl_status'], 'partial')
        self.assertEqual(result['data']['B'], self.weekly)
        self.assertEqual(result['shop_status']['B']['status'], 'failed')
        self.assertEqual(result['updated_at'], self.old['updated_at'])

    def test_stale_week_cannot_refresh_timestamp(self):
        stale = {'금(10/16)': self.weekly['금(10/23)']}
        result = crawler.build_result(self.old, ['A', 'B'], {'A': stale, 'B': stale}, self.now, self.now)
        self.assertEqual(result['crawl_status'], 'failed')
        self.assertEqual(result['data'], self.old['data'])
        self.assertEqual(result['updated_at'], self.old['updated_at'])

    def test_unchanged_and_changed_content_timestamps(self):
        result = crawler.build_result(self.old, ['A', 'B'], self.old['data'], self.now, self.now)
        self.assertEqual(result['crawl_status'], 'success')
        self.assertEqual(result['updated_at'], self.old['updated_at'])
        self.assertEqual(result['last_checked'], '2026-10-23 09:00:00')
        changed = {'금(10/23)': {'중식': {'items': ['새 메뉴 6,000원']}}}
        result = crawler.build_result(self.old, ['A', 'B'], {'A': changed, 'B': self.weekly}, self.now, self.now)
        self.assertEqual(result['updated_at'], '2026-10-23 09:00:00')

    def test_removed_shop_is_visible_as_failed(self):
        result = crawler.build_result(self.old, ['A'], {'A': self.weekly}, self.now, self.now)
        self.assertIn('B', result['shops'])
        self.assertEqual(result['crawl_status'], 'partial')

    def test_short_week_year_boundary_and_wrong_weekday(self):
        target = crawler.datetime(2027, 1, 1)
        self.assertTrue(crawler.valid_week(['목(12/31)', '금(01/01)'], target))
        self.assertFalse(crawler.valid_week(['금(12/31)'], target))
        self.assertFalse(crawler.valid_week(['금(10/16)'], self.now))
        self.assertFalse(crawler.valid_week([], self.now))

    def test_atomic_replace_failure_keeps_original_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'menu.json'
            path.write_text(json.dumps(self.old), encoding='utf-8')
            before = path.read_bytes()
            with patch.object(crawler, 'JSON_PATH', str(path)), patch.object(crawler.os, 'replace', side_effect=OSError('disk error')):
                with self.assertRaises(OSError):
                    crawler.atomic_save({'data': 'replacement'})
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_partial_main_returns_error_and_saves_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'menu.json'
            with patch.object(crawler, 'JSON_PATH', str(path)), patch.object(crawler, 'fetch_html', side_effect=RuntimeError('offline')), patch.object(crawler, 'crawl_menus', return_value=(['금(10/23)'], {'A': self.weekly, 'B': {}}, 1, 1)), patch.object(crawler, 'DEFAULT_SHOPS', {'A': '35', 'B': '36'}), patch.object(crawler, 'datetime') as clock:
                clock.now.return_value = self.now
                self.assertEqual(crawler.main(), 1)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['crawl_status'], 'partial')

    def test_save_error_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'menu.json'
            with patch.object(crawler, 'JSON_PATH', str(path)), patch.object(crawler, 'fetch_html', side_effect=RuntimeError('offline')), patch.object(crawler, 'crawl_menus', return_value=([], {}, 0, 0)), patch.object(crawler, 'atomic_save', side_effect=OSError('disk error')):
                self.assertEqual(crawler.main(), 1)


if __name__ == '__main__':
    unittest.main()
