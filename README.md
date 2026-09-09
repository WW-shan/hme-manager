<p align="center">
  <img src="static/logo.svg" width="96" alt="HME Manager logo">
</p>

<h1 align="center">HME Manager</h1>

<p align="center">自架的 iCloud「隱藏我的電子郵件」管理後台、HTTP API 與服务器浏览器 Session 助手。</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/deploy-Docker-2496ED.svg" alt="Docker">
</p>

## 功能

- 管理「隱藏我的電子郵件」信箱：建立、列出、停用、啟用、刪除與 CSV 匯出。
- **收件匣讀信**：用同一份 Session 直接讀 iCloud 網頁郵件（資料夾、清單、內容），自動偵測並一鍵複製驗證碼——用別名註冊服務後，驗證信不用離開工作台。
- **雙區域支援**：全球（icloud.com）與中國大陸（icloud.com.cn）帳號皆可匯入，區域依主機自動判定，Origin/Referer/langCode 一併處理。
- 固定格式的 HTTP API；所有 `/v1/*` 皆以 `X-API-Key` 驗證。
- Session 只透過 iCloud 網頁請求的 **Copy as cURL (bash)** 或 HAR 匯入，不接收 Apple ID、密碼或 2FA。
- **自動刷新**預設啟用，每 10 分鐘使用現有 Session 保活；失效時自動停用。
- **服务器浏览器自动导入**：通过持久化 noVNC 浏览器完成一次人工登录/2FA，自动捕获 HME 请求并导入 Session；不代填 Apple 密码，也不自动处理 2FA/CAPTCHA。
- 響應式工作台：**信箱清單**、**收件匣**、**API Builder**、**Session & 自動刷新**，支援亮／暗主題、手機版與 toast 操作回饋。
- 純 Python 標準庫、**零第三方相依**；多執行緒 HTTP 服務；支援本機、Docker 與 Render。

## 快速開始

### 1. 取得專案

```bash
git clone https://github.com/WW-shan/hme-manager.git
cd hme-manager
```

### 2. 環境變數

| 變數 | 必填 | 說明 |
| --- | --- | --- |
| `HME_API_KEY` | ✅ | API 與後台共用的金鑰；未設定時拒絕所有請求 |
| `ICLOUD_HME_CONFIG` | | 匯入後的 Session 設定路徑；預設 `hme-config.json`，Docker 為 `/data/hme-config.json` |
| `HME_STATE_DIR` | | Session 檢查與自動刷新狀態目錄；預設 `state`，Docker 為 `/data/state` |
| `HME_BROWSER_VNC_PASSWORD` | 浏览器 compose 必填 | noVNC/VNC 访问密码；不要提交到 Git |
| `HME_BROWSER_CHECK_INTERVAL` | | 浏览器 agent 检查间隔，默认 60 秒 |
| `HME_BROWSER_SESSION_TIMEOUT` | | Selenium 会话超时，默认 1800 秒 |

macOS / Linux：

```bash
export HME_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Windows PowerShell：

```powershell
$env:HME_API_KEY = (python -c "import secrets; print(secrets.token_urlsafe(32))")
```

### 3. 啟動服務

#### 本地（Python 3.10+）

```bash
python web_app.py
```

開啟 <http://127.0.0.1:8000>，輸入剛才的 `HME_API_KEY`。

#### Docker

```bash
cp .env.example .env         # 將 HME_API_KEY 改成隨機金鑰
${EDITOR:-vi} .env            # 同时设置 HME_BROWSER_VNC_PASSWORD
docker compose up -d --build
```

Docker compose 会启动 `hme-api`、带持久化 profile 的 `hme-browser` 和
`hme-browser-agent`。默认 noVNC 地址是
`http://服务器IP:7900`；如果是从 openai-cpa 的主 compose 启动，则通常是
`http://服务器IP:8020`。不要把 noVNC、HME API 或 API key 直接暴露到不受信任的公网，
优先用防火墙、SSH 隧道或反向代理保护它们。

#### Render（一鍵）

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/WW-shan/hme-manager)

### 4. 匯入 Session

1. 前往 [iCloud+](https://www.icloud.com/icloudplus/)（大陸帳號改用 [icloud.com.cn](https://www.icloud.com.cn/icloudplus/)），開啟 **Hide My Email（隱藏我的電子郵件）**。
2. 按 **F12** 開啟 DevTools → Network，找到包含 `list?clientBuildNumber` 的請求。
3. 對該請求選擇 **Copy as cURL (bash)**；也可匯出包含 request cookies 的 HAR。
4. 到後台的 **Session & 自動刷新** → **手動匯入 Session** 貼上並送出。區域（全球／中國大陸）依主機自動判定。
5. 若要在**收件匣**讀信，匯入前請先在 iCloud 網頁開啟過一次「郵件」，確保 cookie 帶有郵件授權（`X-APPLE-WEBAUTH-PCS-Mail`）。

### 服务器浏览器自动导入

1. 打开 HME Manager 的 **Session & 自動刷新** 页面，点击「打开服务器浏览器（noVNC）」；也可以直接打开部署端口。
2. 在 noVNC 中由账号所有者完成 Apple 登录、2FA 或 CAPTCHA，并打开 Hide My Email。浏览器 profile 会保存于 Docker volume，容器重启后可继续使用尚未过期的登录状态。
3. agent 监听 `/v2/hme/list`，捕获带 Mail 权限的请求后自动调用 `/v1/session/import`，随后执行一次 Session 检查。
4. 页面中的「浏览器自动导入」状态用于确认 agent 是否在线、最近是否导入；若 Apple Session 失效，agent 会再次等待你在 noVNC 中完成登录/验证。

此功能不能消除 Apple 的 Session 过期、2FA、CAPTCHA、设备信任或风控要求；它只减少手工复制 cURL/HAR 的步骤。Apple 密码、Cookie、2FA 和 HME API key 不写入镜像、日志或 Git。

## API

所有 `/v1/*` 需帶 `X-API-Key: <你的金鑰>`；`/health` 免驗證。

| 方法 | 路徑 | 說明 |
| --- | --- | --- |
| GET | `/health` | 健康檢查 |
| GET | `/v1/session/status` | 目前 Session 狀態（含 `region`） |
| POST | `/v1/session/refresh` | 用現有 Session 做一次低風險檢查 |
| POST | `/v1/session/import` | 匯入 Session（body：`{"curl_text": "..."}`；支援 icloud.com / icloud.com.cn） |
| GET | `/v1/browser/status` | 读取服务器浏览器 agent 的非敏感状态 |
| GET | `/v1/aliases` | 列出信箱 |
| POST | `/v1/aliases` | 建立信箱（body：`{"label": "...", "note": "..."}`） |
| POST | `/v1/aliases/{id}/disable` · `/enable` · `/delete` | 停用 / 啟用 / 刪除 |
| GET | `/v1/aliases/export.csv` | 匯出 CSV |
| GET | `/v1/mail/folders` | 郵件資料夾清單 |
| GET | `/v1/mail/messages?folder=&limit=&offset=&to=` | 郵件清單（`folder` 省略時自動用收件匣；`to` 可依收件地址過濾，例如單一 HME 別名） |
| GET | `/v1/mail/messages/{guid}` | 讀取單封郵件（text/html/附件中繼資料） |
| GET · POST | `/v1/auto-refresh` | 讀取或更新自動刷新設定 |
| POST | `/v1/auto-refresh/run` | 立即執行一次刷新 |

回應一律是固定信封：

```json
{ "ok": true, "data": {}, "error": null, "meta": { "service": "hme-manager", "version": "1", "requestId": null } }
```

## 收件匣讀信

「收件匣」分頁會用同一份 Session 讀取 iCloud 網頁郵件（JSON-RPC over `pNN-mailws.icloud.com`）。郵件服務的分區（`pNN`）與 HME 分區不一定相同，因此會先向 iCloud `setup` 服務查詢正確的郵件主機，查詢失敗才退回推導值。開啟一封郵件時會自動掃描主旨／內文，偵測到 4–8 位數的驗證碼即可一鍵複製；HTML 內文會放在 `sandbox` 的 iframe 中顯示，避免遠端內容存取工作台。

收件匣可依 **HME 別名** 過濾：用工具列的信箱下拉選單，或在「信箱清單」點某列的 **收件** 直接跳轉。工作台會把資料夾最近的郵件索引**快取在前端**（一次 100 封，可按「載入更早的郵件」續抓），切換別名時直接在本地過濾、不重新請求；「重新整理」才會重抓。郵件內文以原始 RFC822 來源解析（`GET /wm/message?guid=`），並在開啟後快取。

API 消費者也可用 `/v1/mail/messages?to=` 做伺服器端過濾：會掃描該資料夾最近 300 封的收件人欄位（Apple 私有 API 沒有伺服器端收件人搜尋），回應帶 `matchedCount` / `scannedCount` / `scanComplete` 說明掃描範圍。

若收件匣回報 `SESSION_MISSING` 或郵件授權不足，請在 iCloud 網頁先開啟一次「郵件」再重新匯入 Session（cookie 需包含郵件授權）。

## 安全与限制

- 仅使用你有权管理的 Apple 账号、Forward To 邮箱和目标网站账号。
- iCloud+ 别名总量、创建频率、Session 有效期和邮件投递均由 Apple 控制；`create` 限流或 Session 失效不能通过本项目绕过。服务端遇到失效会停止高频重试，等待下一次人工验证。
- `HME_API_KEY`、`HME_BROWSER_VNC_PASSWORD`、Session Cookie、Apple ID 密码、邮箱密码和任何目标站点凭据只放在服务器的 `.env`/持久化数据中，并确保这些文件不进 Git。
- 这个项目不绕过 Apple 或目标网站的验证码、限流、风控或身份验证。

範例：

```bash
curl -X POST "http://127.0.0.1:8000/v1/aliases" \
  -H "X-API-Key: $HME_API_KEY" \
  -H "Content-Type: application/json" \
  --data '{"label":"GPT","note":"memo"}'
```

## 測試

```bash
python -m unittest discover -s tests -v
```

## 授權

[MIT](LICENSE) · [WW-shan/hme-manager](https://github.com/WW-shan/hme-manager)
