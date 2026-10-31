# 主題製作與分享規格 v1

`theme.json` 是 **GuacTheme Manager 自訂格式**，不是 Guacamole 原生格式。原生擴充仍由 JAR 內的 `guac-manifest.json` 定義。

## 分享 ZIP

ZIP 根目錄必須恰好包含三個檔案：

```text
theme.json
guacamole-YOUR-ID.jar
SHA256SUMS
```

不接受外層資料夾、額外安裝腳本、其他檔案或多個 JAR。資源放在 JAR 內。

```json
{
  "schemaVersion": 1,
  "id": "mytheme",
  "name": "My Theme",
  "version": "1.1.0",
  "author": "Your Name",
  "guacamoleVersions": ["1.6.0"],
  "description": "Original theme description",
  "entry": "guacamole-mytheme.jar",
  "sha256": {
    "guacamole-mytheme.jar": "REPLACE_WITH_64_LOWERCASE_HEX_CHARACTERS"
  }
}
```

ID 須符合 `[a-z][a-z0-9-]{0,47}`，且不能為 `default`。entry 必須是 `guacamole-ID.jar`。version 為 `MAJOR.MINOR.PATCH`，可帶 prerelease 字尾。相容版本目前只接受 `['1.6.0']`。名稱、作者、描述及版本不允許控制字元。

`SHA256SUMS` 是 UTF-8，依檔名字典序，每行 `sha256 + 兩個空白 + 檔名 + 換行`，只涵蓋 JAR 與 theme.json，不校驗自身。例如使用：

```bash
sha256sum guacamole-mytheme.jar theme.json > SHA256SUMS
zip guac-theme-mytheme-1.1.0.zip theme.json guacamole-mytheme.jar SHA256SUMS
```

此檔名順序適用此例；其他 ID 仍須按完整檔名排序。先把實際 JAR hash 寫入 theme.json，再產生外部 SHA256SUMS。

## JAR

最小 CSS-only 主題也應包含載入驗證 marker：

```json
{
  "guacamoleVersion": "1.6.0",
  "name": "My Theme",
  "namespace": "gtm-mytheme",
  "css": ["css/theme.css"],
  "resources": {"theme-marker.json": "application/json"}
}
```

JAR 根目錄的 `theme-marker.json` 必須恰好是 `{"id":"mytheme","version":"1.1.0"}`。name 必須與 theme.json 一致，namespace 必須是 `gtm-ID`。marker 使用官方 resources 機制，供 CLI 確認實際 Web URL 已載入正確版本。

可宣告的 manifest keys：`guacamoleVersion`、`name`、`namespace`、`css`、`js`、`html`、`translations`、`resources`。所有宣告的檔案必須存在；所有 JAR 檔案必須宣告（manifest 自身除外）。禁止 Java class、巢狀 JAR、META-INF、原生執行檔、shell/Python 腳本、authProviders、listeners 及額外 manifest 欄位。這個管理器刻意只支援靜態視覺擴充。

## 修改內建主題

- 共用介面：`themes/common/dashboard.{css,js,html}`。
- 可單獨測試的授權資料樹模型：`themes/common/model.js`。
- 顏色：CSS 的 `--gtm-*` variables；新增配色時同時調整字色、邊框、hover 與 focus 對比。
- 語言：`themes/common/en.json` 與 `zh_TW.json`，只加 `GTM` key，避免覆寫既有翻譯套件的原生 keys。
- 每套主題身份與官方 manifest：`themes/ID/theme.json` 及 `guac-manifest.json`。
- 系統設定 chrome、個人配色共享：`settings.js` / `settings-chrome.html` / `settings.css`；設定及外觀欄位透過兩個 HTML patch 加入，未取代原生表單。

```bash
sh scripts/build.sh
sh scripts/test.sh
```

建置器不用 Java；使用 ZIP 容器格式建立合法靜態 JAR，固定排序、時間戳及權限，以便重現。內建主題共用實作但具有不同 namespace 與預設配色；同一伺服器同時只啟用一個 JAR。

新增獨立主題時可仿照 build.py 並將 ID 加入建置清單，或自行產生符合規格的 JAR/ZIP，再用 `guac-theme import` 驗證。發布前請遵守素材授權，不要把資料庫、帳號、設備內部資訊、環境變數或測試 token 打包。

## 信任模型

上限：ZIP/JAR 各 32 MiB、512 個項目、解壓合計 32 MiB、最大壓縮比 250。拒絕絕對路徑、`..`、反斜線、Windows drive、控制字元、重複 ZIP 路徑、重複 JSON key、加密 ZIP、符號連結及特殊檔案。

匯入不執行腳本。已匯入的主題不會自動被信任，啟用仍需明確確認。主題 JS/HTML 與登入者同源，可以使用該使用者的授權 API，故應視同可執行程式碼審查。SHA-256 不提供簽章或可信發行者認證。
