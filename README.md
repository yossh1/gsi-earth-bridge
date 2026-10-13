# 地理院地図 for Google Earth Pro

Google Earth Pro（デスクトップ版）で国土地理院の標準地図を表示するための、Windows向けローカル中継ツールです。

Google Earth ProはXYZタイルURLを直接扱えないため、このツールがKMLスーパーオーバーレイを配信し、Google Earth Proから要求された地図タイルを国土地理院のXYZ URL
`https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png`
から取得して中継します。

## 必要なもの

- Windows 10/11
- Python 3.10以降（追加パッケージ不要）
- インターネット接続
- Google Earth Pro

## 使い方

1. `start.bat` を実行します。ブラウザーに操作画面が開きます。
2. ズーム上限を選び、「KMLをダウンロード」を押します。
3. Google Earth Proの「ファイル」→「開く」から、ダウンロードした `gsi_std_z*.kml` を選択します。
4. 表示を終了するときは、起動した黒いウィンドウで `Ctrl+C` を押します。

中継サーバーを終了すると、KMLを開いたままでも地図タイルを取得できなくなります。地図を表示している間はサーバーを起動しておいてください。ポート8765が使用中の場合は `start.bat --port 8766` で別ポートを指定できます。

## 補足

- サーバーはこのPC内（`127.0.0.1`）だけで待ち受け、地図タイルの中継先は国土地理院の標準地図に固定しています。
- 地理院地図のタイル提供範囲外では地図が表示されません。利用にあたっては[地理院タイル一覧](https://maps.gsi.go.jp/development/ichiran.html)および[国土地理院の地図の利用手続](https://www.gsi.go.jp/LAW/2930-index.html)を確認してください。
- ズーム上限を高くすると、詳細な表示が可能になる一方、Google Earth Proが取得するタイル数が増えます。
