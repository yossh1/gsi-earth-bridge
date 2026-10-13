from __future__ import annotations

import http.client
import os
import tempfile
import threading
import time
import unittest
from email.message import Message
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import app


class TileCacheTests(unittest.TestCase):
    def test_expired_tile_is_not_returned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = app.TileCache(directory, max_bytes=1024, ttl_seconds=60)
            cache.put(5, 28, 12, b"png")
            path = cache.tile_path(5, 28, 12)
            old = time.time() - 61
            os.utime(path, (old, old))

            self.assertIsNone(cache.get(5, 28, 12))
            self.assertFalse(os.path.exists(path))

    def test_cache_survives_reinitialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = app.TileCache(directory, max_bytes=1024, ttl_seconds=3600)
            cache.put(5, 28, 12, b"png")

            restarted_cache = app.TileCache(
                directory, max_bytes=1024, ttl_seconds=3600
            )

            self.assertEqual(restarted_cache.get(5, 28, 12), b"png")

    def test_least_recently_used_tile_is_evicted_at_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = app.TileCache(directory, max_bytes=6, ttl_seconds=3600)
            cache.put(5, 1, 1, b"one")
            cache.put(5, 2, 2, b"two")
            time.sleep(0.01)
            self.assertEqual(cache.get(5, 1, 1), b"one")
            time.sleep(0.01)

            cache.put(5, 3, 3, b"new")

            self.assertIsNotNone(cache.get(5, 1, 1))
            self.assertIsNone(cache.get(5, 2, 2))
            self.assertIsNotNone(cache.get(5, 3, 3))
            self.assertLessEqual(cache.total_bytes, cache.max_bytes)


class TileProxyTests(unittest.TestCase):
    def test_repeated_tile_request_uses_disk_cache(self) -> None:
        class FakeResponse:
            headers = Message()
            headers["Content-Type"] = "image/png"

            def __enter__(self) -> FakeResponse:
                return self

            def __exit__(self, *args: object) -> bool:
                return False

            def read(self) -> bytes:
                return b"\x89PNG\r\n\x1a\ncached-tile"

        with tempfile.TemporaryDirectory() as directory:
            server = ThreadingHTTPServer(("127.0.0.1", 0), app.RequestHandler)
            server.overlay_base_url = "http://127.0.0.1"
            server.tile_cache = app.TileCache(directory, 1024, 3600)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch(
                    "app.urllib.request.urlopen", return_value=FakeResponse()
                ) as urlopen:
                    responses = []
                    for _ in range(2):
                        connection = http.client.HTTPConnection(
                            "127.0.0.1", server.server_address[1]
                        )
                        connection.request("GET", "/tiles/5/28/12.png?layer=std")
                        response = connection.getresponse()
                        responses.append(
                            (response.status, response.getheader("Content-Type"), response.read())
                        )
                        connection.close()

                    self.assertEqual(urlopen.call_count, 1)
                    self.assertEqual(responses[0], responses[1])
                    self.assertEqual(responses[0][0:2], (200, "image/png"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
