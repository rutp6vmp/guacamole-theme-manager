# GitHub Release 發布流程

這個目錄可直接作為 GitHub 專案根目錄，已提供 CI 與 tag release workflow。程式碼 repository 為 https://github.com/rutp6vmp/guacamole-theme-manager；實際部署設定不納入 Git，發行資產與 Release 需另外建置、審查及發布。

## 本機建置與審查

1. 修改 `bin/guac-theme` 的 VERSION 及 README 中相應版本。主題內容變更時才修改各主題版本及介面頁尾；CLI 1.2.0 仍搭配未變更的 1.1.0 主題。
2. 執行 `sh scripts/test.sh`，再依 `docs/TESTING.md` 執行隔離 Web／Docker／實際連線驗收。更新 `docs/TEST-REPORT.md`，不要把未執行項目標為通過。
3. 執行 `sh scripts/build.sh`。確認 `dist/` 有兩個主題 JAR、獨立 JDBC 繁中 JAR、兩個主題 ZIP、完整專案 ZIP 與 SHA256SUMS。
4. 對照來源審查主題 JS/HTML；確認未包含 `.env`、資料庫、日誌、token、內部設備或使用者資料。Release ZIP 只會從 bin/scripts/themes/docs/tests/modules/.github 與明確的根目錄文件打包。測試探針另建在 dist/poc，不自動安裝到正式環境或混入靜態主題。
5. 在 `dist` 執行 `sha256sum -c SHA256SUMS`。建置固定 archive 時間戳與排序，同一組來源可重現相同檔案。

完整專案 ZIP 內也含四個主題預建檔、獨立 JDBC 繁中 JAR 及其校驗檔，安裝者不需自行編譯。外部 SHA256SUMS 另外包含完整專案 ZIP 的摘要；ZIP 內的 SHA256SUMS 不會自我包含。

## 推送與發布

```bash
git remote add origin https://github.com/YOUR-ACCOUNT/guacamole-theme-manager.git
git add .
git commit -m "Release GuacTheme Manager 1.2.0"
git push -u origin main
git tag -a v1.2.0 -m "GuacTheme Manager 1.2.0"
git push origin v1.2.0
```

必須先在 GitHub 建立 repository。若尚未完成手動驗收，請以預發行版發布，Release 說明清楚列出限制。

`.github/workflows/release.yml` 在 `v*` tag 觸發，執行單元／交易測試、前端模型與語法檢查、建置，並建立 **draft Release** 供管理員審查。所需 token 使用 GitHub 自帶的 `GITHUB_TOKEN`，不要把個人 token 放入 repo。

審查 draft 的 JAR、ZIP、SHA256SUMS 與測試報告，再於 GitHub 發布。新 repository 沒有已發布 Release URL，README 以檔名說明，避免提供虛構下載網址。

也可在本機已登入的 GitHub CLI 使用：

```bash
gh release create v1.2.0 --draft --verify-tag \
  --title "GuacTheme Manager 1.2.0" \
  --notes-file docs/RELEASE-NOTES.md dist/*.jar dist/*.zip dist/SHA256SUMS
```

只有在自己已設定目的 repository 後執行。管理員確認 draft 後再 publish。不要把未經授權的外部傳訊或遠端修改當成這份開發工作的自動步驟。
