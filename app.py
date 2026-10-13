from __future__ import annotations

import argparse
import heapq
import ipaddress
import math
import os
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.etree import ElementTree as ET


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_TILE_CACHE_MAX_BYTES = 512 * 1024 * 1024
DEFAULT_TILE_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
MAX_ZOOM = 18
MIN_ZOOM = 5
INITIAL_VIEW_LONGITUDE = 139.7671
INITIAL_VIEW_LATITUDE = 35.6812
INITIAL_VIEW_RANGE_METERS = 30000
TILE_HOST = "https://cyberjapandata.gsi.go.jp"
KML_NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML_NS)


def tag(name: str) -> str:
    return f"{{{KML_NS}}}{name}"


def default_cache_directory() -> str:
    if os.name == "nt":
        return os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "gsi-earth-overlay",
            "cache",
        )
    return os.path.join(os.path.expanduser("~"), ".cache", "gsi-earth-overlay")


class TileCache:
    def __init__(self, directory: str, max_bytes: int, ttl_seconds: int) -> None:
        if max_bytes <= 0:
            raise ValueError("tile cache maximum size must be positive")
        if ttl_seconds <= 0:
            raise ValueError("tile cache TTL must be positive")
        self.directory = os.path.abspath(directory)
        self.max_bytes = max_bytes
        self.ttl_seconds = ttl_seconds
        self.lock = threading.Lock()
        self.entries: OrderedDict[str, tuple[float, int]] = OrderedDict()
        self.expirations: list[tuple[float, str, float]] = []
        self.total_bytes = 0
        os.makedirs(self.directory, exist_ok=True)
        self._load_index(time.time())

    def tile_path(self, z: int, x: int, y: int) -> str:
        return os.path.join(self.directory, f"{z}-{x}-{y}.png")

    def get(self, z: int, x: int, y: int) -> bytes | None:
        path = self.tile_path(z, x, y)
        with self.lock:
            try:
                metadata = os.stat(path)
            except FileNotFoundError:
                self._remove_entry(path)
                return None
            now = time.time()
            if now - metadata.st_mtime >= self.ttl_seconds:
                os.remove(path)
                self._remove_entry(path)
                return None
            with open(path, "rb") as cached_file:
                body = cached_file.read()
            os.utime(path, (now, metadata.st_mtime))
            self.entries[path] = (metadata.st_mtime, metadata.st_size)
            self.entries.move_to_end(path)
            return body

    def put(self, z: int, x: int, y: int, body: bytes) -> None:
        if len(body) > self.max_bytes:
            return
        path = self.tile_path(z, x, y)
        with self.lock:
            handle = tempfile.NamedTemporaryFile(
                mode="wb", dir=self.directory, suffix=".tmp", delete=False
            )
            temporary_path = handle.name
            try:
                with handle:
                    handle.write(body)
                now = time.time()
                os.utime(temporary_path, (now, now))
                os.replace(temporary_path, path)
                self._remove_entry(path)
                self.entries[path] = (now, len(body))
                self.total_bytes += len(body)
                heapq.heappush(
                    self.expirations, (now + self.ttl_seconds, path, now)
                )
                self._prune_locked(now)
            finally:
                if os.path.exists(temporary_path):
                    os.remove(temporary_path)

    def prune(self) -> None:
        with self.lock:
            self._prune_locked(time.time())

    def _load_index(self, now: float) -> None:
        with self.lock:
            files = []
            for name in os.listdir(self.directory):
                if not name.endswith(".png"):
                    continue
                path = os.path.join(self.directory, name)
                try:
                    metadata = os.stat(path)
                except FileNotFoundError:
                    continue
                if now - metadata.st_mtime >= self.ttl_seconds:
                    os.remove(path)
                    continue
                files.append((metadata.st_atime, path, metadata.st_mtime, metadata.st_size))
            for atime, path, mtime, size in sorted(files):
                self.entries[path] = (mtime, size)
                self.total_bytes += size
                heapq.heappush(
                    self.expirations, (mtime + self.ttl_seconds, path, mtime)
                )
                try:
                    os.utime(path, (atime, mtime))
                except FileNotFoundError:
                    self._remove_entry(path)
            self._prune_locked(now)

    def _remove_entry(self, path: str) -> None:
        entry = self.entries.pop(path, None)
        if entry is not None:
            self.total_bytes -= entry[1]

    def _prune_locked(self, now: float) -> None:
        while self.expirations and self.expirations[0][0] <= now:
            _, path, mtime = heapq.heappop(self.expirations)
            entry = self.entries.get(path)
            if entry is None or entry[0] != mtime:
                continue
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            self._remove_entry(path)
        while self.total_bytes > self.max_bytes and self.entries:
            path, (_, size) = self.entries.popitem(last=False)
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            self.total_bytes -= size


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    count = 1 << z
    west = x / count * 360.0 - 180.0
    east = (x + 1) / count * 360.0 - 180.0

    def latitude(tile_y: int) -> float:
        mercator_y = math.pi * (1.0 - 2.0 * tile_y / count)
        return math.degrees(math.atan(math.sinh(mercator_y)))

    return west, latitude(y + 1), east, latitude(y)


def add_region(
    parent: ET.Element,
    bounds: tuple[float, float, float, float],
    min_lod_pixels: int,
) -> None:
    west, south, east, north = bounds
    region = ET.SubElement(parent, tag("Region"))
    box = ET.SubElement(region, tag("LatLonAltBox"))
    for name, value in (
        ("north", north),
        ("south", south),
        ("east", east),
        ("west", west),
    ):
        ET.SubElement(box, tag(name)).text = f"{value:.8f}"
    lod = ET.SubElement(region, tag("Lod"))
    ET.SubElement(lod, tag("minLodPixels")).text = str(min_lod_pixels)
    ET.SubElement(lod, tag("maxLodPixels")).text = "-1"


def make_link(
    parent: ET.Element,
    href: str,
    bounds: tuple[float, float, float, float],
    min_lod_pixels: int,
) -> None:
    network_link = ET.SubElement(parent, tag("NetworkLink"))
    link = ET.SubElement(network_link, tag("Link"))
    ET.SubElement(link, tag("href")).text = href
    ET.SubElement(link, tag("viewRefreshMode")).text = "onRegion"
    add_region(network_link, bounds, min_lod_pixels)


def make_root_kml(base_url: str, max_zoom: int) -> bytes:
    root = ET.Element(tag("kml"))
    document = ET.SubElement(root, tag("Document"))
    ET.SubElement(document, tag("name")).text = "地理院地図（標準地図）"
    ET.SubElement(document, tag("description")).text = (
        "Google Earth Pro用スーパーオーバーレイ。"
        "出典：国土地理院「地理院タイル（標準地図）」。"
        "表示に必要な地理院タイルをローカル中継サーバー経由で取得します。"
    )
    look_at = ET.SubElement(document, tag("LookAt"))
    ET.SubElement(look_at, tag("longitude")).text = str(INITIAL_VIEW_LONGITUDE)
    ET.SubElement(look_at, tag("latitude")).text = str(INITIAL_VIEW_LATITUDE)
    ET.SubElement(look_at, tag("altitude")).text = "0"
    ET.SubElement(look_at, tag("heading")).text = "0"
    ET.SubElement(look_at, tag("tilt")).text = "0"
    ET.SubElement(look_at, tag("range")).text = str(INITIAL_VIEW_RANGE_METERS)
    ET.SubElement(look_at, tag("altitudeMode")).text = "clampToGround"
    query = urllib.parse.urlencode({"max_zoom": max_zoom})
    bounds = (-180.0, -85.05112878, 180.0, 85.05112878)
    make_link(
        document,
        f"{base_url}/tiles/0/0/0.kml?{query}",
        bounds,
        0,
    )
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def make_tile_kml(base_url: str, z: int, x: int, y: int, max_zoom: int) -> bytes:
    bounds = tile_bounds(z, x, y)
    west, south, east, north = bounds
    root = ET.Element(tag("kml"))
    document = ET.SubElement(root, tag("Document"))
    ET.SubElement(document, tag("name")).text = f"地理院地図 z{z}/{x}/{y}"

    if z >= MIN_ZOOM:
        overlay = ET.SubElement(document, tag("GroundOverlay"))
        ET.SubElement(overlay, tag("name")).text = f"標準地図 z{z}/{x}/{y}"
        ET.SubElement(overlay, tag("drawOrder")).text = str(z)
        icon = ET.SubElement(overlay, tag("Icon"))
        tile_url = f"{base_url}/tiles/{z}/{x}/{y}.png?layer=std"
        ET.SubElement(icon, tag("href")).text = tile_url
        box = ET.SubElement(overlay, tag("LatLonBox"))
        for name, value in (
            ("north", north),
            ("south", south),
            ("east", east),
            ("west", west),
        ):
            ET.SubElement(box, tag(name)).text = f"{value:.8f}"

    if z < max_zoom:
        query = urllib.parse.urlencode({"max_zoom": max_zoom})
        for child_y in (2 * y, 2 * y + 1):
            for child_x in (2 * x, 2 * x + 1):
                child_z = z + 1
                child_bounds = tile_bounds(child_z, child_x, child_y)
                href = (
                    f"{base_url}/tiles/{child_z}/{child_x}/{child_y}.kml?{query}"
                )
                make_link(document, href, child_bounds, 128)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


PAGE = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>地理院地図 for Google Earth Pro</title>
  <style>
    body { max-width: 720px; margin: 3rem auto; padding: 0 1rem; color: #202124;
           font: 16px/1.65 system-ui, sans-serif; }
    h1 { font-size: 1.55rem; }
    form { display: flex; flex-wrap: wrap; align-items: end; gap: 1rem;
           margin: 1.5rem 0; padding: 1.25rem; background: #f4f6f8; }
    label { display: grid; gap: .35rem; }
    select, button { padding: .65rem .85rem; font: inherit; }
    button { border: 0; border-radius: 4px; color: white; background: #1769aa;
             cursor: pointer; }
    code { overflow-wrap: anywhere; }
  </style>
</head>
<body>
  <h1>地理院地図 for Google Earth Pro</h1>
  <p>地図のズーム上限を選び、KMLをダウンロードしてください。
     ダウンロードしたKMLをGoogle Earth Proで開くと、表示範囲のタイルを
     地理院から取得して地図を重ねます。</p>
  <form action="/overlay.kml" method="get">
    <label>ズーム上限
      <select name="max_zoom">
        <option value="12">12（軽量）</option>
        <option value="15">15</option>
        <option value="18" selected>18（詳細）</option>
      </select>
    </label>
    <button type="submit">KMLをダウンロード</button>
  </form>
  <h2>使い方</h2>
  <ol>
    <li>この画面を開いたままにしておきます。</li>
    <li>上のボタンでKMLを保存します。</li>
    <li>Google Earth Proの「ファイル」→「開く」からKMLを選択します。</li>
  </ol>
  <p>このPC上で中継サーバーが動作している間だけ表示できます。
     地図タイルの取得にはインターネット接続が必要です。</p>
</body>
</html>
"""


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "GSI-Earth-Overlay/1.0"
    sys_version = ""

    def respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/":
            self.respond(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/healthz":
            self.respond(200, b"ok\n", "text/plain; charset=utf-8")
            return
        if parsed.path == "/overlay.kml":
            params = urllib.parse.parse_qs(parsed.query)
            try:
                max_zoom = int(params.get("max_zoom", ["18"])[0])
            except ValueError:
                self.send_error(400, "max_zoom must be an integer")
                return
            if not MIN_ZOOM <= max_zoom <= MAX_ZOOM:
                self.send_error(
                    400, f"max_zoom must be between {MIN_ZOOM} and {MAX_ZOOM}"
                )
                return
            body = make_root_kml(self.server.overlay_base_url, max_zoom)
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.google-earth.kml+xml")
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="gsi_std_z{max_zoom}.kml"',
            )
            self.end_headers()
            self.wfile.write(body)
            return

        kml_match = re.fullmatch(
            r"/tiles/([0-9]{1,2})/([0-9]{1,6})/([0-9]{1,6})\.kml",
            parsed.path,
        )
        if kml_match:
            z, x, y = map(int, kml_match.groups())
            params = urllib.parse.parse_qs(parsed.query)
            try:
                max_zoom = int(params.get("max_zoom", ["18"])[0])
            except ValueError:
                self.send_error(400, "max_zoom must be an integer")
                return
            if not MIN_ZOOM <= max_zoom <= MAX_ZOOM or not self.valid_tile(z, x, y):
                self.send_error(400, "invalid tile coordinates or max_zoom")
                return
            if z > max_zoom:
                self.send_error(404, "tile is beyond the selected zoom limit")
                return
            body = make_tile_kml(self.server.overlay_base_url, z, x, y, max_zoom)
            self.respond(200, body, "application/vnd.google-earth.kml+xml")
            return

        tile_match = re.fullmatch(
            r"/tiles/([0-9]{1,2})/([0-9]{1,6})/([0-9]{1,6})\.png",
            parsed.path,
        )
        if tile_match:
            z, x, y = map(int, tile_match.groups())
            params = urllib.parse.parse_qs(parsed.query)
            if params.get("layer", ["std"])[0] != "std" or not self.valid_tile(z, x, y):
                self.send_error(400, "invalid tile request")
                return
            self.proxy_tile(z, x, y)
            return

        self.send_error(404, "not found")

    @staticmethod
    def valid_tile(z: int, x: int, y: int) -> bool:
        return 0 <= z <= MAX_ZOOM and 0 <= x < (1 << z) and 0 <= y < (1 << z)

    def proxy_tile(self, z: int, x: int, y: int) -> None:
        cache = self.server.tile_cache
        try:
            body = cache.get(z, x, y)
        except OSError as error:
            self.log_error("tile cache read failed: %s", error)
            self.send_error(500, "tile cache read failed")
            return
        if body is not None:
            self.send_tile(body)
            return

        url = f"{TILE_HOST}/xyz/std/{z}/{x}/{y}.png"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "GSI-Earth-Overlay/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read()
                content_type = response.headers.get_content_type()
        except urllib.error.HTTPError as error:
            self.send_error(error.code, f"GSI tile request failed: HTTP {error.code}")
            return
        except urllib.error.URLError as error:
            self.send_error(502, f"GSI tile request failed: {error.reason}")
            return
        if content_type != "image/png":
            self.send_error(502, f"unexpected GSI tile content type: {content_type}")
            return
        try:
            cache.put(z, x, y, body)
        except OSError as error:
            self.log_error("tile cache write failed: %s", error)
            self.send_error(500, "tile cache write failed")
            return
        self.send_tile(body)

    def send_tile(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            self.close_connection = True

    def log_message(self, format: str, *args: object) -> None:
        super().log_message(format, *args)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="地理院地図をGoogle Earth Proへ中継")
    parser.add_argument(
        "--host",
        default=os.environ.get("GSI_OVERLAY_HOST", DEFAULT_HOST),
        help="待ち受けアドレス（環境変数: GSI_OVERLAY_HOST）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("GSI_OVERLAY_PORT", str(DEFAULT_PORT))),
        help="待ち受けポート（環境変数: GSI_OVERLAY_PORT）",
    )
    parser.add_argument(
        "--public-url",
        default=os.environ.get("GSI_OVERLAY_PUBLIC_URL"),
        help="KML内でWindowsクライアントに案内する公開URL（環境変数: GSI_OVERLAY_PUBLIC_URL）",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="起動時にブラウザーを開かない",
    )
    parser.add_argument(
        "--cache-dir",
        default=os.environ.get("GSI_TILE_CACHE_DIR", default_cache_directory()),
        help="タイルキャッシュ保存先（環境変数: GSI_TILE_CACHE_DIR）",
    )
    parser.add_argument(
        "--cache-max-bytes",
        type=int,
        default=int(
            os.environ.get(
                "GSI_TILE_CACHE_MAX_BYTES", str(DEFAULT_TILE_CACHE_MAX_BYTES)
            )
        ),
        help="タイルキャッシュ最大容量（バイト、環境変数: GSI_TILE_CACHE_MAX_BYTES）",
    )
    parser.add_argument(
        "--cache-ttl-seconds",
        type=int,
        default=int(
            os.environ.get(
                "GSI_TILE_CACHE_TTL_SECONDS", str(DEFAULT_TILE_CACHE_TTL_SECONDS)
            )
        ),
        help="タイルキャッシュ有効期間（秒、環境変数: GSI_TILE_CACHE_TTL_SECONDS）",
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.cache_max_bytes <= 0:
        parser.error("--cache-max-bytes must be positive")
    if args.cache_ttl_seconds <= 0:
        parser.error("--cache-ttl-seconds must be positive")
    if args.host in ("", "0.0.0.0", "::"):
        is_loopback = False
    elif args.host.lower() == "localhost":
        is_loopback = True
    else:
        try:
            is_loopback = ipaddress.ip_address(args.host).is_loopback
        except ValueError:
            is_loopback = False
    if not args.public_url and not is_loopback:
        parser.error("--public-url is required when --host is not a loopback address")
    public_url = args.public_url or f"http://{args.host}:{args.port}"
    parsed_public_url = urllib.parse.urlsplit(public_url)
    if (
        parsed_public_url.scheme not in ("http", "https")
        or not parsed_public_url.hostname
        or parsed_public_url.username is not None
        or parsed_public_url.password is not None
        or parsed_public_url.path not in ("", "/")
        or parsed_public_url.query
        or parsed_public_url.fragment
    ):
        parser.error("--public-url must be an http(s) origin without a path or credentials")
    try:
        parsed_public_url.port
    except ValueError:
        parser.error("--public-url contains an invalid port")
    public_url = public_url.rstrip("/")

    try:
        server = ThreadingHTTPServer((args.host, args.port), RequestHandler)
    except OSError as error:
        parser.error(f"could not listen on {args.host}:{args.port}: {error}")
    server.overlay_base_url = public_url
    try:
        server.tile_cache = TileCache(
            args.cache_dir, args.cache_max_bytes, args.cache_ttl_seconds
        )
    except OSError as error:
        server.server_close()
        parser.error(f"could not initialize tile cache: {error}")
    print(f"中継サーバーの待ち受け: {args.host}:{server.server_address[1]}")
    print(f"クライアント向けURL: {public_url}/")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=(f"{public_url}/",)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nサーバーを終了します。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
