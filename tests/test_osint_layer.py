import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import requests

# Add the parent directory to sys.path so we can import from jack_cli
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import jack_cli

class TestOSINTSearchLayer(unittest.TestCase):

    def setUp(self):
        # Reset globals for each test
        jack_cli.SEARXNG_ALIVE = True
        jack_cli.SEARXNG_URL = "http://localhost:8080"
        
        # Clear the sqlite DB cache to ensure tests run reliably
        import sqlite3
        conn = sqlite3.connect(jack_cli._CACHE_DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM osint_cache")
        conn.commit()
        conn.close()

    @patch('jack_cli.requests.get')
    def test_health_check_success(self, mock_get):
        """Test health check sets SEARXNG_ALIVE to True on 200 OK."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        
        # Initially false to verify it gets set to True
        jack_cli.SEARXNG_ALIVE = False
        
        jack_cli._searxng_health_check()
        
        self.assertTrue(jack_cli.SEARXNG_ALIVE)
        self.assertEqual(mock_get.call_count, 1)

    @patch('jack_cli.requests.get')
    @patch('jack_cli.time.sleep', return_value=None)
    def test_health_check_failure(self, mock_sleep, mock_get):
        """Test health check sets SEARXNG_ALIVE to False on connection error after 3 attempts."""
        mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
        
        jack_cli.SEARXNG_ALIVE = True
        
        jack_cli._searxng_health_check()
        
        self.assertFalse(jack_cli.SEARXNG_ALIVE)
        self.assertEqual(mock_get.call_count, 3)

    @patch('jack_cli.requests.get')
    @patch('jack_cli.time.sleep', return_value=None)
    @patch('jack_cli.trafilatura')
    def test_local_osint_lookup_retry_success(self, mock_trafilatura, mock_sleep, mock_get):
        """Test local_osint_lookup retries on failure and eventually succeeds."""
        mock_resp_success = MagicMock()
        mock_resp_success.status_code = 200
        mock_resp_success.json.return_value = {
            "results": [{"url": "http://example.com"}]
        }
        
        mock_resp_html = MagicMock()
        mock_resp_html.status_code = 200
        mock_resp_html.text = "<html>mocked</html>"
        
        # Fail twice, succeed on the third try, then the 4th call is the parallel HTML fetch
        mock_get.side_effect = [
            requests.exceptions.ConnectionError("Connection timeout"),
            requests.exceptions.Timeout("Read timeout"),
            mock_resp_success,
            mock_resp_html
        ]
        
        mock_trafilatura.extract.return_value = "mocked extracted text"
        
        result = jack_cli.local_osint_lookup(["test query"])
        
        self.assertIn("mocked extracted text", result)
        self.assertEqual(mock_get.call_count, 4)

    @patch('jack_cli.requests.get')
    @patch('jack_cli.requests.post')
    @patch('jack_cli.trafilatura')
    def test_local_osint_lookup_fallback(self, mock_trafilatura, mock_post, mock_get):
        """Test DuckDuckGo fallback activates when SEARXNG_ALIVE is False."""
        jack_cli.SEARXNG_ALIVE = False
        
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '<html><a href="http://duckduckgo.com">ddg</a><a href="http://fallback.com/result">result</a></html>'
        mock_post.return_value = mock_resp
        
        mock_resp_html = MagicMock()
        mock_resp_html.status_code = 200
        mock_resp_html.text = "<html>mocked fallback</html>"
        mock_get.return_value = mock_resp_html
        
        mock_trafilatura.extract.return_value = "mocked fallback text"
        
        result = jack_cli.local_osint_lookup(["test fallback"])
        
        self.assertIn("mocked fallback text", result)
        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(mock_get.call_count, 1)

if __name__ == '__main__':
    unittest.main()
