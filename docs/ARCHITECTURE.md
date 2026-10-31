# 1.6.0 相容性與研究紀錄

研究基準：Apache Guacamole client tag **1.6.0**，commit `0537c89cd783681b986ff8f8c4e0b97ec6873371`。參考 LibreNMS 文件中的設備分組與分類／搜尋操作、現行前端 layout/menu，重新實作企業管理介面；沒有複製 LibreNMS 程式碼或素材。

## 官方擴充機制

[Guacamole 1.6.0 guacamole-ext 文件](https://guacamole.apache.org/doc/1.6.0/gug/guacamole-ext.html) 定義 JAR 根目錄 `guac-manifest.json`，以及 `guacamoleVersion`、`name`、`namespace`、`css`、`js`、`html`、`translations` 與 `resources`。本專案使用 `before-children` HTML patch 將主題控制器加到 `.home-view`，不改寫原生首頁 template 或 WAR。原生清單僅在主題資料已載入且選擇自訂外觀後隱藏；個人 Default 或主題模型建立失敗時保留原生介面。

純靜態 JAR 使用 Python zipfile 建立，無 Java class、Maven 或認證提供者。名稱空間 `gtm-librenms` / `gtm-dark`。Marker 透過官方 resources 路徑 `app/ext/NAMESPACE/theme-marker.json` 提供，用於 CLI 載入驗證。

1.1.0 另用 before-children patch 在 `.settings-view`、五種原生 `.manage-*` editor 與匯入說明根節點加入 `guac-theme-settings`。共用 chrome HTML 以官方 resources 提供。導覽內容仍由 `userPageService.getSettingsPages()` 產生；不重寫原生 controller、不接管 save/delete、不複製含帳密的 scope 資料。偏好設定的外觀區以 after-children patch 加入配色選單，與首頁使用同一個使用者隔離的偏好服務。

樣式限定於已加上 `gtm-native-page` 的原生管理頁。切至個人 Default 即移除頁面標記，保留小型外觀切換列。側欄及工具列的層級低於原生全域確認視窗，確保刪除確認及錯誤訊息可正常操作。實際 remote client 與沉浸式 recording viewport 不加入此 chrome。

## 經原始碼確認的整合點

| 原始碼（均在 1.6.0 tag） | 用途 | 穩定性 |
| --- | --- | --- |
| [homeController.js](https://github.com/apache/guacamole-client/blob/1.6.0/guacamole/src/main/frontend/src/app/home/controllers/homeController.js) | 繼承已授權的 `rootConnectionGroups`，保留原生錯誤處理 | 內部 frontend |
| [home.html](https://github.com/apache/guacamole-client/blob/1.6.0/guacamole/src/main/frontend/src/app/home/templates/home.html) | HTML patch selector 與原生 fallback | 內部 DOM |
| [index.html](https://github.com/apache/guacamole-client/blob/1.6.0/guacamole/src/main/frontend/src/index.html) | 全域 Angular、app module、extension JS 載入時機 | 內部 frontend |
| [ClientIdentifier.js](https://github.com/apache/guacamole-client/blob/1.6.0/guacamole/src/main/frontend/src/app/navigation/types/ClientIdentifier.js) | 使用官方原生 base64url 連線識別碼，含資料來源與物件類型 | 內部 frontend |
| [userPageService.js](https://github.com/apache/guacamole-client/blob/1.6.0/guacamole/src/main/frontend/src/app/navigation/services/userPageService.js) | 原生權限產生的 settings/history 連結 | 內部 frontend |
| [permissionService.js](https://github.com/apache/guacamole-client/blob/1.6.0/guacamole/src/main/frontend/src/app/rest/services/permissionService.js) | 每個資料來源目前使用者的 effectivePermissions | 內部 frontend |
| [ConnectionResource.java](https://github.com/apache/guacamole-client/blob/1.6.0/guacamole/src/main/java/org/apache/guacamole/rest/connection/ConnectionResource.java) | 參數讀取須 UPDATE 或系統 ADMINISTER；hostname 按需顯示 | 內部 REST |
| [ExtensionModule.java](https://github.com/apache/guacamole-client/blob/1.6.0/guacamole/src/main/java/org/apache/guacamole/extension/ExtensionModule.java) | 官方載入成功日誌格式與名稱空間資源路徑 | 內部 server |

這些服務不是獨立承諾的公開前端 API。僅宣告 `1.6.0` 相容；無法假設後續版本 selector、服務名稱、路由或授權規則不變。後續升級需要重讀原始碼、更新 adapter、跑權限矩陣及實際連線驗收。

`getConnectionParameters` 原生 frontend service 會使用快取，因此本主題不直接呼叫它；改用同一認證服務發出 `cache:false` 的授權請求，立即只保留 hostname。請求仍由原生 server 同樣的授權檢查保護。JS 瀏覽器內仍會收到已授權參數完整內容，無法將此端點描述成「只回傳 IP」的 API。

`userPageService` 對僅有單一連線的使用者可能自動導向連線，這是原生行為，本主題不攔截。需要查看儀表板可返回原生首頁路由。使用者已開啟的遠端 client 不會由主題程式接管。

## LibreNMS 設計參考及授權

- [LibreNMS 官方專案](https://github.com/librenms/librenms) 與 [官方文件](https://docs.librenms.org/)：設備清單、篩選、dashboard 工作流程。
- [Grouping Devices](https://docs.librenms.org/Extensions/Device-Groups/)：分組瀏覽的概念參考。本專案直接使用 Guacamole 原生群組，沒有 SQL 動態群組。
- 研究時官方 `resources/views/layouts/menu.blade.php` 仍有多種選單位置與 responsive navigation，並非只有固定左欄。第一套主題依使用者需求採深色固定左欄，並非 LibreNMS 畫面複刻。
- LibreNMS 專案採 GPL；本專案未重用其程式碼／素材。若未來加入實際 GPL 程式碼或資產，應先確認各檔授權並履行相應散布義務。

## 管理器資料流

```text
Release ZIP -> validated import -> state/themes/ID/
                                     |
                            version/hash/trust checks
                                     |
Compose+runtime preflight -> backup -> pending transaction
                                     |
                        extensions/guac-theme-managed.jar
                                     |
                       recreate only Web -> load verification
                                     |
                     success: commit / failure: restore backup
```

不讀取資料庫、不解析正式 .env，不把 Docker stdout/stderr 或 inspect JSON 印出。Compose 解析結果及 inspect 只在記憶體內檢查必要欄位。theme/current/config/backups 都放在主題專用 state directory；config 僅含路徑、服務名、URL、版本、timeout 與非機密的部署保護要求。

## ADR：P00 的共同部署清單（CLI 1.2.0）

沿用 `state/config.json` 作為共同 deployment manifest，沿用 `Manager.lock()` 序列化本機工具；不新增另一份容易分歧的安全 Compose 設定。`protect-deployment` 可在主題仍啟用時採納經實際容器驗證的完整檔案清單，驗證後先備份設定，再原子更新；不必為加入 overlay 先 reset。

`deploymentGuard` schemaVersion 1 僅儲存 feature ID 列表與非主題 JAR 的 SHA-256 映射，不儲存環境變數值或憑證。第一版 feature allowlist 為 totp、recording。要求只能增加；所有重建使用目前清單，主題備份不回復安全要求。一般 preflight 也比對實際 Compose config_files label，阻止沿用過時的主檔清單重建 Web。缺少 label 或帶逗號的檔名無法可靠比對，採拒絕處理。

這個鎖只協調使用同一 state 的工具；不能阻止主機管理員直接執行 Docker，也不取代後續的伺服器 admission gate 或入口 fail-closed。載入 recording-storage 也不代表已設定每條連線錄影。完整驗證範圍見 [實作狀態 TXT](PAM_IMPLEMENTATION_STATUS.zh-TW.txt)。
