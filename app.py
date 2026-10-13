from __future__ import annotations

import argparse
import math
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.etree import ElementTree as ET


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_ZOOM = 18
MIN_ZOOM = 5
TILE_HOST = "https://cyberjapandata.gsi.go.jp"
KML_NS = "http://www.opengis.net/kml/2.2"
ET.register_namespace("", KML_NS)


def tag(name: str) -> str:
    return f"{{{KML_NS}}}{name}"


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
            base_url = f"http://{self.server.server_address[0]}:{self.server.server_address[1]}"
            body = make_root_kml(base_url, max_zoom)
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
            base_url = (
                f"http://{self.server.server_address[0]}:"
                f"{self.server.server_address[1]}"
            )
            body = make_tile_kml(base_url, z, x, y, max_zoom)
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
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        super().log_message(format, *args)


def main() -> None:
    parser = argparse.ArgumentParser(description="地理院地図をGoogle Earth Proへ中継")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    server = ThreadingHTTPServer((HOST, args.port), RequestHandler)
    url = f"http://{HOST}:{server.server_address[1]}/"
    print(f"中継サーバーを起動しました: {url}")
    print("終了するにはこのウィンドウで Ctrl+C を押してください。")
    threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nサーバーを終了します。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
