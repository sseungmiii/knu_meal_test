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

if __name__ == '__main__':
    unittest.main()
