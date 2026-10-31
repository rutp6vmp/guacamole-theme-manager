# 安裝、切換及故障還原

新 VM 尚未有 Guacamole 時，請先依 [新 VM 從零安裝教學](NEW_VM_INSTALL.zh-TW.txt) 建立 Docker、Guacamole 與資料庫。以下步驟用於已存在的部署；從 Git 下載後先執行 `python3 scripts/build.py`，才會有下方使用的主題 ZIP。

## 設定部署位置

先確認 Python 3.10+、Docker Compose v2 及正式服務正常。避免以會把環境變數完整印出的命令收集診斷資料；Compose 與容器 inspect 常含資料庫密碼。

`configure` 只保存路徑，不重啟。所有命令使用同一個 state directory，預設 `/var/lib/guac-theme`；可透過 `--state-dir /absolute/path` 或 `GUAC_THEME_STATE_DIR` 改變。不同部署必須使用不同狀態目錄。

```bash
sudo guac-theme --state-dir /var/lib/guac-theme configure \
  --extensions-dir /your/deployment/custom/extensions \
  --compose-file /your/deployment/compose.yaml \
  --service your-web-service \
  --web-url http://127.0.0.1:8080/guacamole/
```

有多份 Compose 設定時依原順序重複 `--compose-file`；使用自訂 project name 時加 `--project-name NAME`。請使用原本的 Compose 專案名稱，不要因此建立第二套正式服務。`--timeout` 預設 90 秒，可設 5～600 秒。唯讀掛載必須指向 `/etc/guacamole/extensions`，主機來源須與 `--extensions-dir` 一致。路徑不允許符號連結，請使用實際路徑。

Web 映像限制為 `guacamole/guacamole:1.6.0`（可含 `docker.io/` 及 digest），且不可有 `build`。此版本不支援自訂 Guacamole 映像、非 Docker 部署或其他 Guacamole 版本。容器名稱不作為服務名稱，請以 Compose 的 service key 設定。

診斷與啟用會檢查設定及實際容器映像、Compose labels、唯讀掛載。只有一個既有 Web 容器時才繼續；使用多副本或由其他服務共用擴充目錄會拒絕操作。`GUACAMOLE_HOME` template 須為預設 `/etc/guacamole`。重建前再次核對完整 Compose 設定的記憶體摘要，設定在檢查後遭改動時拒絕重建。請直接使用能到達該 Web 服務的 URL，不使用另台主機或會導向 SSO 的入口。驗證請求不附帶登入憑證、不使用 Proxy 環境、不跟隨重新導向。

## 匯入及啟用

```bash
sudo guac-theme doctor
sudo guac-theme import /download/guac-theme-librenms-1.1.0.zip
sudo guac-theme switch librenms
```

匯入只會存入主題 repository，不執行程式碼、不複製到擴充目錄。預設拒絕同 ID 覆寫；1.1.0 新增明確的 `import --replace`，會先把既有 repository 複本保存至 state directory 的 `repository-backups`，再換成新版，**不改變啟用中的 JAR**。每次啟用仍重驗 JAR 校驗與相容性。

## 從 1.0.0 升級

```bash
sudo sh scripts/install.sh --upgrade
sudo guac-theme import dist/guac-theme-librenms-1.1.0.zip --replace
sudo guac-theme import dist/guac-theme-dark-1.1.0.zip --replace
sudo guac-theme switch librenms
```

`install.sh --upgrade` 只替換已辨識的 GuacTheme CLI，會先把舊執行檔保存於安裝 prefix 下的 `share/guac-theme/cli-backups`。匯入及 CLI 升級均不重啟服務；最後一次 switch 才會備份舊啟用狀態並重建 Web。若要回到上一版外觀，使用該次切換輸出的備份 ID 執行 restore，無須移除翻譯或認證套件。

切換須信任 JS/HTML 並接受工作階段可能中斷。非互動範例：

```bash
sudo guac-theme switch librenms --trust-theme --yes
```

工具先保存備份及 pending transaction，再原子替換專用 JAR。僅執行：

```text
docker compose [原有檔案與專案選項] up -d --no-deps --force-recreate --pull never --no-build WEB_SERVICE
```

不執行 down、不重建 guacd 或 PostgreSQL、不拉取新映像、不編譯映像。驗證檢查容器執行／health 狀態、Guacamole HTML、目前容器的官方 extension loaded 訊息，以及名稱空間下的版本 marker。`reset` 驗證沒有載入 `gtm-*` 主題。請於套用後以 Ctrl+Shift+R 清除舊快取。

請勿另外手動將 dist JAR 放進擴充目錄後再使用 CLI，避免兩套主題同時載入。`guac-theme-managed.jar` 若已存在但沒有管理狀態，或內容與管理狀態不符，工具會拒絕覆寫／刪除，必須先由管理員確認來源。

## 備份與還原

```bash
sudo guac-theme backup
sudo guac-theme restore 20261030T000000Z-0123456789
sudo guac-theme reset
```

備份 ID 以上一步實際輸出為準。備份位於狀態目錄 `backups/ID/`，包含 `snapshot.json`、先前的 `active.jar`（原生介面時沒有 JAR）、SHA-256 及非主題 JAR 的摘要。不包含帳密、環境變數、Compose 檔或 PostgreSQL 資料。備份只讀取主題檔與既有 JAR 的校驗值，不變更資料庫。

切換或重建失敗時自動恢復先前 JAR、重建同一 Web 服務並再次驗證。若連還原後的 Web 都不能通過驗證，保留 `pending.json`，不宣稱恢復成功。

## 故障流程

1. 確認 Docker 權限、現有映像、Compose 設定及本機 Web URL。一般帳號無 Docker socket 權限時，以管理員執行工具；不要為此開放 socket 給所有人。
2. 若顯示 unfinished transaction，執行 `sudo guac-theme recover`。它從 pending 記錄的備份還原，不依賴目前主題 repository，適用在 JAR 已寫入但 state 尚未更新時中斷。若先前重建失敗造成 Web 容器不存在，recover 仍會先嚴格驗證 Compose 範圍，再建立同一 Web 服務。
3. 若 Web 原因另有問題，先由管理員在本機檢查該 Web 容器日誌，不要公開原始日誌或 inspect JSON。修正原因後重試 `recover`。
4. 若非主題 JAR 在切換期間遭其他程式改動，工具不會覆蓋那個變更；保留 pending 供管理員檢查。使用自己的服務備份還原那些擴充後再 `recover`。
5. 僅在工具無法運行時手動恢復：停止操作，讀取 pending 指向的 snapshot，核對 active.jar 的 SHA-256；只還原 `guac-theme-managed.jar`（snapshot 為 default 則只移除該專用 JAR）。不要使用 `rm *.jar`。仍需修復狀態檔，建議恢復 CLI 後交由 `recover` 執行。

工具保證管理範圍，但無法使硬碟損毀、Docker daemon 故障、第三方套件錯誤或外部同步寫入自動消失。狀態目錄應僅由管理員寫入；不要同時手動維護同一專用 JAR。

## 移除管理工具

```bash
sudo guac-theme reset
sudo sh scripts/uninstall.sh
```

有啟用主題或 pending transaction 時卸載腳本會拒絕。備份及 repository 保留。自訂安裝位置：`PREFIX=/custom/prefix sh scripts/install.sh`，卸載使用同一 PREFIX；自訂 state directory 也需傳入同一 `GUAC_THEME_STATE_DIR`。
