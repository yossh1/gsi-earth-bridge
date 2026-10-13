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

以下はDocker Composeで常駐起動する例です。LinuxサーバーにはDocker EngineとDocker Compose pluginがインストールされ、インターネットへ接続できる必要があります。

1. プロジェクトをサーバーに配置します（GitHubから取得する例）。

   ```sh
   git clone https://github.com/yossh1/gsi-earth-bridge.git
   cd gsi-earth-bridge
   ```

2. `.env` を作成します。

   ```sh
   cp .env.example .env
   chmod 600 .env
   ```

   `GSI_OVERLAY_PUBLIC_URL` をWindows PCから到達できるURLに変更します。LAN内の例は `http://192.168.1.20:8765`、HTTPS終端リバースプロキシを使う例は `https://maps.example.com` です。公開URLにはパスを付けず、ホスト名と必要に応じてポートだけを指定します。

   `GSI_OVERLAY_PORT` はLinuxホストで公開するポートです。`GSI_OVERLAY_BIND_ADDRESS` は公開ポートを待ち受けるホスト側アドレスで、デフォルトの `0.0.0.0` は全IPv4インターフェースを意味します。ローカルのHTTPSリバースプロキシだけから接続させる場合は、`GSI_OVERLAY_BIND_ADDRESS=127.0.0.1` とし、公開URLにはプロキシのHTTPS URLを設定します。

3. コンテナをビルドして起動します。

   ```sh
   docker compose up -d --build
   docker compose ps
   docker compose logs -f
   ```

4. ファイアウォールで、設定したホスト側ポートへのアクセスをWindows PCから許可します。サーバー上では `curl http://127.0.0.1:8765/healthz`（ポートを変更した場合はそのポート）、Windows PCからはブラウザーで公開URLを開いて疎通を確認してください。
5. 公開URLのトップ画面でKMLをダウンロードし、Windows版Google Earth Proから開きます。KML内のタイルURLも同じ公開URLを使います。

停止・再開・更新は次のコマンドで行います。

```sh
docker compose down       # 停止
docker compose up -d      # 再開
git pull
docker compose up -d --build
```

VPN/LAN内での利用を推奨します。インターネットへ公開する場合は、HTTPS対応のリバースプロキシの背後に置き、ファイアウォール等で接続元を制限してください。このツール自体にはユーザー認証やアクセス制限機能はありません。

## ライセンスと地理院タイル

このプロジェクトのコードは[MIT License](./LICENSE)で提供します。MIT Licenseは国土地理院の地図タイルには適用されません。出典表示を行い、申請要否を含む地理院の利用条件を別途ご確認ください。限定されたLAN内の利用は不特定多数への提供に当たりにくいと考えられますが、申請不要を保証するものではありません。判断に迷う場合や公開・配布する場合は国土地理院にご確認ください。

## 補足

- Windowsでの単独起動時は `127.0.0.1` だけで待ち受けます。別ホストからアクセスさせる場合は、`--host` で待ち受けアドレス、`--public-url` でクライアントが接続するURLを指定してください。ループバック以外で待ち受ける場合、`--public-url` は必須です。
- 地図タイルの中継先は国土地理院の標準地図に固定しています。
- 地理院地図のタイル提供範囲外では地図が表示されません。利用にあたっては[地理院タイル一覧](https://maps.gsi.go.jp/development/ichiran.html)および[国土地理院の地図の利用手続](https://www.gsi.go.jp/LAW/2930-index.html)を確認してください。
- ズーム上限を高くすると、詳細な表示が可能になる一方、Google Earth Proが取得するタイル数が増えます。
