# 地理院地図 for Google Earth Pro

Google Earth Pro（デスクトップ版）で国土地理院の標準地図を表示するための中継ツールです。Windows PC上で直接起動する方法と、Linuxサーバー上で動かしてWindows PCから利用する方法があります。

Google Earth ProはXYZタイルURLを直接扱えないため、このツールがKMLスーパーオーバーレイを配信し、Google Earth Proから要求された地図タイルを国土地理院のXYZ URL
`https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png`
から取得して中継します。

## Windows PC上で実行する場合

- Windows 10/11
- Python 3.10以降（追加パッケージ不要）
- インターネット接続
- Google Earth Pro

1. `start.bat` を実行します。ブラウザーに操作画面が開きます。
2. ズーム上限を選び、「KMLをダウンロード」を押します。
3. Google Earth Proの「ファイル」→「開く」から、ダウンロードした `gsi_std_z*.kml` を選択します。
4. 表示を終了するときは、起動した黒いウィンドウで `Ctrl+C` を押します。

中継サーバーを終了すると、KMLを開いたままでも地図タイルを取得できなくなります。地図を表示している間はサーバーを起動しておいてください。ポート8765が使用中の場合は `start.bat --port 8766` で別ポートを指定できます。

## Linuxサーバーで実行する場合

以下はUbuntu/Debian系Linuxで、systemdを使って常駐起動する例です。サーバーにはPython 3.10以降とインターネット接続が必要です。

1. プロジェクトを `/opt/gsi-earth-overlay` に配置します（GitHubから取得する例）。

   ```sh
   sudo git clone https://github.com/yossh1/gsi-earth-bridge.git /opt/gsi-earth-overlay
   ```

2. 専用ユーザーを作成し、設定ファイルを作成します。

   ```sh
   sudo useradd --system --user-group --no-create-home --home-dir /opt/gsi-earth-overlay --shell /usr/sbin/nologin gsi-earth-overlay
   sudo install -o root -g root -m 600 /opt/gsi-earth-overlay/deploy/gsi-earth-overlay.env.example /etc/default/gsi-earth-overlay
   sudoedit /etc/default/gsi-earth-overlay
   ```

   `GSI_OVERLAY_PUBLIC_URL` をWindows PCから到達できるサーバーのアドレスに変更してください。たとえばLAN内なら `http://192.168.1.20:8765`、TLS終端リバースプロキシを使うなら `https://maps.example.com` です。公開URLにはパスを付けず、ホスト名と必要に応じてポートだけを指定します。`GSI_OVERLAY_HOST=0.0.0.0` は全IPv4インターフェースで待ち受ける設定です。

3. systemdサービスを有効にします。

   ```sh
   sudo cp /opt/gsi-earth-overlay/deploy/gsi-earth-overlay.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now gsi-earth-overlay
   sudo systemctl status gsi-earth-overlay
   ```

4. ネットワーク経路上のファイアウォールで、設定したポートへのアクセスをWindows PCから許可します。サーバー上では `curl http://127.0.0.1:8765/healthz`、Windows PCからはブラウザーで設定した公開URLを開いて疎通を確認してください。
5. 公開URLのトップ画面でKMLをダウンロードし、Windows版Google Earth Proから開きます。KML内のタイルURLも同じ公開URLを使用するため、Windows PCからそのURLへ継続してアクセスできる必要があります。

VPN/LAN内での利用を推奨します。インターネットへ公開する場合は、HTTPS対応のリバースプロキシの背後に置き、ファイアウォール等で接続元を制限してください。このツール自体にはユーザー認証やアクセス制限機能はありません。サービスログは `sudo journalctl -u gsi-earth-overlay -f` で確認できます。

## 補足

- Windowsでの単独起動時は `127.0.0.1` だけで待ち受けます。別ホストからアクセスさせるには、`--host` で待ち受けアドレス、`--public-url` でクライアントが接続するURLを指定してください。例: `python3 app.py --host 0.0.0.0 --port 8765 --public-url http://192.168.1.20:8765`。ループバック以外で待ち受ける場合、誤ったURLがKMLに入らないよう `--public-url` は必須です。
- 地図タイルの中継先は国土地理院の標準地図に固定しています。
- 地理院地図のタイル提供範囲外では地図が表示されません。利用にあたっては[地理院タイル一覧](https://maps.gsi.go.jp/development/ichiran.html)および[国土地理院の地図の利用手続](https://www.gsi.go.jp/LAW/2930-index.html)を確認してください。
- ズーム上限を高くすると、詳細な表示が可能になる一方、Google Earth Proが取得するタイル数が増えます。
