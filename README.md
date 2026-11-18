<div dir="rtl">

# راهنمای راه‌اندازی Paperclip + Herdr برای تقسیم کار بین چند ایجنت

این راهنما یک سیستم سه‌ایجنتی را از صفر راه می‌اندازد:

| ایجنت | نقش | نحوهٔ اتصال به Paperclip | خودکار؟ |
|---|---|---|---|
| **Hermes** | مدیر؛ کار بزرگ را به تیکت می‌شکند | آداپتور داخلی `hermes_local` | بله |
| **Antigravity** (`agy`) | مجری | آداپتور `process` + اسکریپت `bridge.sh` + Herdr | بله |
| **Freebuff** | مجری | دستی، از طریق MCP داخل Herdr | خیر |

- **Paperclip** تابلوی تیکت و مدیر تقسیم کار است.
- **Herdr** محیط ترمینالی است که ایجنت‌ها در پنجره‌های آن زنده اجرا می‌شوند و از بیرون با دستور قابل کنترل‌اند.
- **`bridge.sh`** (در همین پوشه) تیکت را از Paperclip می‌خواند، در پنجرهٔ ایجنت در Herdr تایپ می‌کند و نتیجه را روی تیکت ثبت می‌کند.

**اگر فقط می‌خواهید Paperclip را اجرا کنید:** در ریشهٔ همین مخزن `npm ci` و سپس `npm start` را بزنید. در PowerShell می‌توانید از `npm.cmd` استفاده کنید. **برای اجرای Paperclip و داشبورد با هم در ویندوز**، بعد از نصب Node، npm سازگار و Python، `setup-dashboard.cmd` را باز کنید. نیازی به نصب سراسری Paperclip، Herdr یا کلید مدل برای بالا آمدن سرور نیست. جزئیات و روش تشخیص خطا در بخش ۲ آمده است.

> **وضعیت آزمایش:** اجرای بستهٔ رسمی `paperclipai@2026.1106.0`، پایگاه دادهٔ داخلی و اتصال داشبورد در لینوکس بررسی شده‌اند. این آزمایش به معنی تأیید اجرای بومی ویندوز یا گردش کار انتها‌به‌انتهای Herdr/Hermes نیست. `bridge.sh` با سرویس‌های ساختگی آزمایش شده است.

---

## فهرست

1. [پیش‌نیازها](#۱-پیشنیازها)
2. [نصب Paperclip](#۲-نصب-paperclip)
3. [نصب Herdr](#۳-نصب-herdr)
4. [نصب ایجنت‌ها](#۴-نصب-ایجنتها)
5. [ساخت شرکت و ایجنت مدیر (Hermes)](#۵-ساخت-شرکت-و-ایجنت-مدیر-hermes)
6. [راه‌اندازی ایجنت‌ها در Herdr](#۶-راهاندازی-ایجنتها-در-herdr)
7. [اتصال Antigravity (خودکار)](#۷-اتصال-antigravity-خودکار-با-bridgesh)
8. [اتصال Freebuff (دستی با MCP)](#۸-اتصال-freebuff-دستی-با-mcp)
9. [گردش کار روزانه](#۹-گردش-کار-روزانه)
10. [تنظیمات `bridge.sh`](#۱۰-تنظیمات-bridgesh)
11. [محدودیت‌ها](#۱۱-محدودیتها)
12. [رفع اشکال](#۱۲-رفع-اشکال)

---

## ۱. پیش‌نیازها

| ابزار | برای چه | ویندوز | مک / لینوکس |
|---|---|---|---|
| **Node.js 24 LTS (از 24.15.0) یا 26+** | Paperclip، Freebuff، سرور MCP | از nodejs.org | از nodejs.org یا `nvm install 24` |
| **Git** | worktree و (در ویندوز) Git Bash | `winget install Git.Git` | معمولاً نصب است |
| **jq** | `bridge.sh` | `winget install jqlang.jq` | `brew install jq` یا `apt install jq` |
| **curl** | `bridge.sh` | همراه Git Bash هست | معمولاً نصب است |
| **Python 3.10 یا بالاتر** | داشبورد و Hermes | از python.org | معمولاً نصب است |

بررسی نصب:

</div>

```bash
node --version    # Node 24.15+ (24.x LTS) or 26+
npm --version     # 11.16.0+
git --version
jq --version
python --version
```

<div dir="rtl">

**نکته‌های ویندوز**

- `bridge.sh` یک اسکریپت bash است و با **Git Bash** اجرا می‌شود (همراه Git نصب می‌شود).
- بعد از نصب jq، یک Git Bash جدید باز کنید و `jq --version` را بزنید تا مطمئن شوید از داخل آن در دسترس است.
- Paperclip، Herdr و ایجنت‌ها باید همه با **یک کاربر ویندوز** اجرا شوند.

---

## ۲. نصب Paperclip

این مخزن **سرور Paperclip را از بستهٔ رسمی `paperclipai`** نصب می‌کند؛ `paperclip` در npm پروژهٔ دیگری است. خودِ `npm install` سرور را اجرا نمی‌کند. از پوشه‌ای که `package.json` و `setup-dashboard.cmd` در آن هستند شروع کنید. Node سری ۲۴ را به‌روز کنید: حداقل خودِ CLI نسخهٔ 24.11 است، ولی وابستگی‌های قفل‌شدهٔ این پروژه روی سری ۲۴ به **24.15.0 یا جدیدتر** نیاز دارند. برای رعایت سیاست اسکریپت‌های نصب، **npm 11.16.0 یا بالاتر** لازم است. اگر npm قدیمی است، بعد از به‌روزرسانی Node با `npm install -g npm@11` آن را به‌روز و ترمینال را دوباره باز کنید.

</div>

```bash
npm ci       # نصب اولیه یا پس از تغییر package-lock.json
npm start    # این ترمینال را باز نگه دارید؛ توقف با Ctrl+C
```

<div dir="rtl">

- `npm start` بار اول تنظیمات و PostgreSQL داخلی را می‌سازد و در دفعات بعد تنظیمات موجود را نگه می‌دارد. نصب و مهاجرت اولیه ممکن است چند دقیقه طول بکشد و نصب به چند گیگابایت فضای خالی نیاز دارد. سرویس پس‌زمینه نصب نمی‌شود.
- در این ترکیب به Copilot احتیاجی نیست. مرحلهٔ پرمصرف آماده‌سازی باینری **اختیاری Copilot** از نصب اصلی جدا شده است؛ PostgreSQL و بقیهٔ اجزای لازم همچنان نصب می‌شوند. فقط در صورت نیاز به آن آداپتور روی سکوی پشتیبانی‌شده، بعد از پایان نصب `npm run setup:copilot` را اجرا کنید.
- رابط **Paperclip** معمولاً روی `http://localhost:3100` است. آدرس چاپ‌شده در ترمینال ملاک است. `http://localhost:3100/api/health` باید JSON با `status: "ok"` برگرداند. پاسخ `[]` از `/api/companies` یعنی سرور آماده است ولی هنوز شرکتی نساخته‌اید.
- برای دیدن ایجنت‌ها و تیکت‌ها، در رابط Paperclip شرکت خودتان را بسازید. اگر تنها یک شرکت باشد داشبورد آن را خودکار پیدا می‌کند. اگر چند شرکت دارید، `PAPERCLIP_COMPANY_ID` را در `dashboard/.env` تعیین کنید.
- **داشبورد فارسی** برنامهٔ جداگانه‌ای است. در ترمینال دوم `python dashboard/app.py` (در لینوکس/مک: `python3 dashboard/app.py`) را اجرا کنید و `http://localhost:8000` را باز کنید. [تنظیمات و آزمون اتصال داشبورد](dashboard/README.md).
- **ویندوز:** به‌جای دو ترمینال می‌توانید `setup-dashboard.cmd` را اجرا کنید. اگر سرور آماده باشد دوباره آن را اجرا نمی‌کند؛ در غیر این صورت فقط برای آدرس محلی پیش‌فرض، بستهٔ محلی پروژه را به کار می‌گیرد (در صورت نیاز ابتدا `npm.cmd ci` اجرا می‌شود). نبودن Herdr مانع بالا آمدن داشبورد نیست.
- اگر قبلاً **بستهٔ درست** را سراسری نصب کرده‌اید، می‌توانید به‌جای مسیر پروژه در یک ترمینال `paperclipai onboard --yes` (بار اول) یا `paperclipai run` (با تنظیمات موجود) را اجرا کنید. هم‌زمان `npm start` دیگری برای همان نمونه نزنید. نصب سراسری تابع فایل قفل و اصلاحیه‌های امنیتی این مخزن نیست؛ برای نصب جدید مسیر `npm ci` و `npm start` را ترجیح دهید.

**اگر با npm نصب شد ولی جواب نگرفتید:**

| بررسی | اقدام |
|---|---|
| `ENOENT ... package.json` | ترمینال را در ریشهٔ این مخزن باز کنید. |
| `EBADENGINE`، `node` پیدا نشد یا PowerShell اجرای `npm.ps1` را مسدود کرد | `node -v`، `npm.cmd -v` و در ویندوز `where.exe node` را ببینید. پس از نصب Node سازگار ترمینال جدید باز کنید؛ از `npm.cmd ci` و `npm.cmd start` استفاده کنید. |
| `paperclipai` پیدا نشد یا بستهٔ بومی PostgreSQL نصب نشده | `npm ci` باید بدون خطا تمام شود. وابستگی‌های اختیاری یا اسکریپت‌های نصب را حذف نکنید. `npm ls paperclipai`، فضای دیسک، معماری سیستم (بستهٔ PostgreSQL ویندوز: x64) و **اولین خطای npm** را بررسی کنید. |
| `E404` یا خطای دریافت بسته | با `npm config get registry` مطمئن شوید رجیستری شما بستهٔ رسمی را در دسترس دارد. |
| `/api/health` پاسخ نمی‌دهد | خروجی ترمینال `npm start` و `npm run doctor`، مسیر داده و پورتی که واقعاً چاپ شده را بررسی کنید. دادهٔ نمونهٔ قبلی را پاک نکنید. |
| سرور سالم است ولی داشبورد داده ندارد | `python dashboard/test_connectivity.py` را اجرا کنید. آدرس پایه بدون `/api` است. شناسهٔ ثابت یا کلید نمایشی مانده از نصب قبلی را از `dashboard/.env` بردارید؛ برای نمونهٔ احراز هویت‌شده کلید مجاز تنظیم کنید. بعد از ویرایش، **داشبورد** را دوباره اجرا کنید. |

**مسیر دادهٔ دلخواه:** در هر بار اجرا همان مسیر و همان کاربر سیستم‌عامل را استفاده کنید. داده‌های Paperclip در `node_modules` نیستند.

</div>

```bash
npm start -- --data-dir "D:/AI-Workspace/paperclip-data"
# تشخیص همان نمونه:
npm run doctor -- --data-dir "D:/AI-Workspace/paperclip-data"
```

<div dir="rtl">

---

## ۳. نصب Herdr

</div>

```powershell
# ویندوز (PowerShell)
powershell -ExecutionPolicy Bypass -c "irm https://herdr.dev/install.ps1 | iex"
```

```bash
# مک و لینوکس
curl -fsSL https://herdr.dev/install.sh | sh
# یا: brew install herdr
```

<div dir="rtl">

> بستهٔ `herdr` روی npm فقط یک نام رزروشده است؛ با `npm install -g herdr` نصب **نکنید**.

اجرا:

</div>

```bash
cd /path/to/your/project
herdr
```

<div dir="rtl">

- `Ctrl+B` سپس `Q`: جدا شدن از Herdr (ایجنت‌ها در پس‌زمینه می‌مانند).
- `herdr` را دوباره بزنید تا برگردید.
- `herdr server stop`: خاموش کردن کامل.

---

## ۴. نصب ایجنت‌ها

### Hermes

</div>

```bash
pip install hermes-agent
hermes --version
```

<div dir="rtl">

- حداقل یک کلید API مدل لازم است (Anthropic، OpenRouter یا OpenAI).
- Hermes باید روی همان دستگاهی باشد که Paperclip اجرا می‌شود.
- **تأییدنشده:** پشتیبانی Hermes از ویندوز بومی را بررسی نکرده‌ام. اگر روی ویندوز نصب نشد، مستندات Hermes را ببینید (احتمالاً WSL لازم است). در آن صورت Paperclip هم باید داخل همان WSL اجرا شود، یا از آداپتور `hermes_gateway` استفاده کنید.

### Antigravity CLI

</div>

```bash
# مک و لینوکس
curl -fsSL https://antigravity.google/cli/install.sh | bash
agy --version
```

<div dir="rtl">

- برای ویندوز، نصب‌کننده را از سایت رسمی Antigravity بردارید (دستور ویندوز را تأیید نکرده‌ام).
- یک بار `agy` را دستی اجرا کنید و وارد حساب شوید.

### Freebuff

</div>

```bash
npm install -g freebuff
freebuff          # یک بار اجرا و ورود به حساب
```

<div dir="rtl">

- **هشدار ویندوز:** برای نسخه‌های 0.0.130 تا 0.0.137 گزارش شده که رابط Freebuff روی ویندوز باز نمی‌شود. اگر با پیام `Usage: node test-bootstrap-caching.mjs` بسته شد، نسخهٔ دیگری را امتحان کنید یا از WSL استفاده کنید.

---

## ۵. ساخت شرکت و ایجنت مدیر (Hermes)

1. `http://localhost:3100` را باز کنید و یک شرکت (Company) بسازید.
2. شناسهٔ شرکت را بردارید:

</div>

```bash
curl http://localhost:3100/api/companies
```

<div dir="rtl">

3. در بخش **Agents** روی **Add Agent** بزنید، آداپتور **Hermes** را انتخاب کنید و نقش مدیر (مثلاً CEO) بدهید.
4. دکمهٔ **Test Environment** را بزنید تا مطمئن شوید Hermes پیدا می‌شود.

در ادامه، `<COMPANY_ID>` یعنی همین شناسهٔ شرکت.

---

## ۶. راه‌اندازی ایجنت‌ها در Herdr

هر ایجنت مجری در یک پنجرهٔ Herdr و در **worktree جدا** اجرا می‌شود تا فایل‌های هم را خراب نکنند. پروژه باید یک ریپوی Git باشد.

### Antigravity

</div>

```bash
# Git Bash / مک / لینوکس
created=$(herdr worktree create --cwd /path/to/project --branch feat-agy --no-focus)
echo "$created" | jq .           # ساختار خروجی را ببینید و شناسهٔ پنجره را بردارید
pane=$(echo "$created" | jq -r '.result.root_pane.pane_id')

herdr agent start agy-worker --kind agy --pane "$pane"
```

```powershell
# PowerShell
$created = herdr worktree create --cwd D:\My-Code-Project --branch feat-agy --no-focus | ConvertFrom-Json
$pane = $created.result.root_pane.pane_id
herdr agent start agy-worker --kind agy --pane $pane
```

<div dir="rtl">

- `agy-worker` نامی است که `bridge.sh` با آن ایجنت را پیدا می‌کند.
- **تأییدنشده:** مسیر `.result.root_pane.pane_id` برای دستور `workspace create` مستند است؛ برای `worktree create` فرض کرده‌ام همان است. اگر خالی بود، خروجی JSON را نگاه کنید.

### Freebuff

</div>

```bash
created=$(herdr worktree create --cwd /path/to/project --branch feat-freebuff --no-focus)
fb_pane=$(echo "$created" | jq -r '.result.root_pane.pane_id')
herdr pane run "$fb_pane" "freebuff"
echo "$fb_pane"     # مثلاً w2:p1 — یادداشت کنید
```

<div dir="rtl">

Herdr نوع Freebuff را نمی‌شناسد، پس با `pane run` اجرا می‌شود نه `agent start`.

---

## ۷. اتصال Antigravity (خودکار با `bridge.sh`)

### ۷.۱ آماده‌سازی اسکریپت

- `bridge.sh` را در مسیری ثابت بگذارید، مثلاً `D:/AI-Workspace/bridge.sh`.
- فایل را دانلود کنید؛ متنش را از صفحهٔ چت کپی نکنید (کاراکترهای مخفی وارد می‌شود).
- در ویندوز، در Git Bash بزنید:

</div>

```bash
sed -i 's/\r$//' /d/AI-Workspace/bridge.sh
chmod +x /d/AI-Workspace/bridge.sh
```

<div dir="rtl">

### ۷.۲ ساخت ایجنت در Paperclip

آداپتور `process` در منوی رابط کاربری نیست و باید از API ساخته شود.

</div>

```powershell
# PowerShell (ویندوز)
$body = @{
  name = "Antigravity-Worker"
  role = "engineer"
  adapterType = "process"
  adapterConfig = @{
    command = "C:\Program Files\Git\bin\bash.exe"
    args = @("D:/AI-Workspace/bridge.sh")
    cwd = "D:/My-Code-Project"
    timeoutSec = 2000
    env = @{ HERDR_TARGET = "agy-worker"; HERDR_MODE = "agent" }
  }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri "http://localhost:3100/api/companies/<COMPANY_ID>/agents" `
  -Method Post -ContentType "application/json" -Body $body
```

```bash
# مک / لینوکس
curl -X POST http://localhost:3100/api/companies/<COMPANY_ID>/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Antigravity-Worker",
    "role": "engineer",
    "adapterType": "process",
    "adapterConfig": {
      "command": "bash",
      "args": ["/absolute/path/to/bridge.sh"],
      "cwd": "/absolute/path/to/project",
      "timeoutSec": 2000,
      "env": { "HERDR_TARGET": "agy-worker", "HERDR_MODE": "agent" }
    }
  }'
```

<div dir="rtl">

شناسهٔ ایجنت (`id`) را از پاسخ بردارید.

### ۷.۳ آزمایش

1. در Paperclip یک تیکت ساده بسازید و به `Antigravity-Worker` واگذار کنید.
2. بیدارباش را دستی بزنید:

</div>

```bash
curl -X POST http://localhost:3100/api/agents/<AGENT_ID>/heartbeat/invoke
```

<div dir="rtl">

3. در Herdr باید پرامپت در پنجرهٔ `agy-worker` تایپ شود.
4. بعد از پایان کار، خروجی به‌صورت کامنت روی تیکت می‌آید و وضعیت تیکت `in_review` می‌شود.

---

## ۸. اتصال Freebuff (دستی با MCP)

### ۸.۱ ساخت ایجنت با آداپتور بی‌اثر

هر ایجنت در Paperclip باید آداپتور داشته باشد. برای ایجنت دستی، یک دستور بی‌اثر می‌گذاریم:

</div>

```powershell
# PowerShell (ویندوز)
$body = @{
  name = "Freebuff-Coder"
  role = "engineer"
  adapterType = "process"
  adapterConfig = @{
    command = "cmd.exe"
    args = @("/c", "echo Manual MCP agent - run it in Herdr")
    timeoutSec = 30
  }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri "http://localhost:3100/api/companies/<COMPANY_ID>/agents" `
  -Method Post -ContentType "application/json" -Body $body
```

<div dir="rtl">

در مک و لینوکس به‌جای `cmd.exe` بگذارید: `"command": "echo", "args": ["manual agent"]`.

> **تأییدنشده:** Paperclip برای هر اجرا «وضعیت زنده‌بودن» ثبت می‌کند و ممکن است اجرای بی‌اثر را چند بار (به‌تعداد محدود) تکرار کند یا «بدون پیشرفت» نشان دهد. بعد از اولین تیکت، صفحهٔ اجراهای ایجنت را نگاه کنید.

### ۸.۲ ساخت کلید API

در صفحهٔ ایجنت `Freebuff-Coder` در رابط کاربری، بخش **API keys**، یک کلید بسازید. کلید فقط یک بار نمایش داده می‌شود. راه دیگر:

</div>

```bash
curl -X POST http://localhost:3100/api/agents/<AGENT_ID>/keys
```

<div dir="rtl">

### ۸.۳ افزودن سرور MCP به Freebuff

این بلوک را به تنظیمات MCP ایجنت اضافه کنید:

</div>

```json
{
  "mcpServers": {
    "paperclip": {
      "command": "npx",
      "args": ["-y", "@paperclipai/mcp-server"],
      "env": {
        "PAPERCLIP_API_URL": "http://localhost:3100",
        "PAPERCLIP_API_KEY": "<agent api key>",
        "PAPERCLIP_COMPANY_ID": "<COMPANY_ID>",
        "PAPERCLIP_AGENT_ID": "<AGENT_ID>"
      }
    }
  }
}
```

<div dir="rtl">

- **تأییدنشده:** محل فایل تنظیمات MCP در Freebuff را بررسی نکرده‌ام؛ مستندات Freebuff را ببینید.
- برای Antigravity CLI (اگر بخواهید آن را هم دستی وصل کنید) فایل `.agents/mcp_config.json` در پوشهٔ پروژه یا `~/.gemini/config/mcp_config.json` است.

### ۸.۴ فایل مهارت (اختیاری)

فایل `skills/paperclip/SKILL.md` را از ریپوی Paperclip در پوشهٔ `.agents/skills/paperclip/` پروژهٔ خودتان کپی کنید تا ایجنت روال کار با تیکت‌ها را بداند.

### ۸.۵ استفاده

در پنجرهٔ Freebuff در Herdr بنویسید:

</div>

```text
Check my assigned issues in Paperclip, check out the highest-priority one,
implement it, add a summary comment, and set the issue to in_review.
```

<div dir="rtl">

---

## ۹. گردش کار روزانه

1. **راه‌اندازی:** `npm start` (اگر سرور از قبل اجرا نشده است) و سپس `herdr`. ایجنت‌ها را طبق بخش ۶ در پنجره‌هایشان بالا بیاورید.
2. **تعریف کار:** در Paperclip یک هدف یا تیکت بزرگ بسازید و به Hermes واگذار کنید.
3. **تقسیم کار:** Hermes آن را به زیرتیکت می‌شکند و به `Antigravity-Worker` و `Freebuff-Coder` واگذار می‌کند.
4. **اجرای هم‌زمان:**
   - Antigravity خودکار بیدار می‌شود و کارش را انجام می‌دهد.
   - برای Freebuff، پرامپت بخش ۸.۵ را در پنجره‌اش بزنید.
5. **بازبینی:** تیکت‌های `in_review` را در Paperclip ببینید، کامنت‌ها را بخوانید و branch هر ایجنت را در Git بررسی و ادغام کنید.

---

## ۱۰. تنظیمات `bridge.sh`

این متغیرها در `adapterConfig.env` هر ایجنت تنظیم می‌شوند:

| متغیر | معنی | پیش‌فرض |
|---|---|---|
| `HERDR_TARGET` | نام ایجنت یا شناسهٔ پنجره در Herdr (اجباری) | — |
| `HERDR_MODE` | `agent` برای ایجنت‌های شناخته‌شدهٔ Herdr؛ `pane` برای بقیه (مثل Freebuff) | `agent` |
| `WAIT_MS` | حداکثر زمان یک تیکت (میلی‌ثانیه) | `1800000` (۳۰ دقیقه) |
| `QUIET_SEC` | در حالت `pane`: چند ثانیه صفحهٔ بدون تغییر یعنی «تمام شد» | `45` |
| `DONE_STATUS` | وضعیتی که بعد از پایان روی تیکت گذاشته می‌شود | `in_review` |

**اسکریپت چه می‌کند**

1. اولین تیکت `in_progress` یا `todo` واگذارشده به ایجنت را می‌خواند.
2. آن را برمی‌دارد (checkout). فقط در تداخل مالکیت (`HTTP 409`) کنار می‌رود؛ خطای مجوز یا اتصال را به‌عنوان موفقیت گزارش نمی‌کند.
3. عنوان و شرح تیکت را در پنجرهٔ ایجنت تایپ می‌کند.
4. صبر می‌کند تا کار تمام شود:
   - حالت `agent`: از تشخیص وضعیت خود Herdr استفاده می‌کند.
   - حالت `pane`: منتظر یک نشانهٔ پایان (`PAPERCLIP_DONE_...`) در خروجی می‌ماند؛ اگر نیامد، سکوت صفحه ملاک است.
5. ۱۲۰ خط آخر خروجی را روی تیکت کامنت می‌گذارد و وضعیت را تغییر می‌دهد.
6. اگر ارسال پرامپت یا خواندن خروجی ناموفق باشد، ایجنت گیر کند یا زمان تمام شود، تیکت را باز می‌گذارد.

**خودکار کردن Freebuff (آزمایشی):** می‌توانید به‌جای آداپتور بی‌اثر، همان `bridge.sh` را با `HERDR_TARGET=<شناسهٔ پنجره>` و `HERDR_MODE=pane` بدهید. این حالت شکننده است و ممکن است با شرایط استفادهٔ Freebuff (سرویس رایگان مبتنی بر تبلیغ) سازگار نباشد؛ خودتان بررسی کنید.

---

## ۱۱. محدودیت‌ها

- **امنیت:** این راه‌اندازی برای استفادهٔ محلی است. گزارش وابستگی‌های باقی‌مانده و محدودیت انتشار در [SECURITY.md](SECURITY.md) آمده است.

- **پرسش‌های تأیید:** اگر ایجنت وسط کار اجازه بخواهد، اسکریپت جواب نمی‌دهد و تیکت باز می‌ماند.
- **Antigravity:** طبق مستندات Herdr، به‌محض برگشتن به خط فرمان «بیکار» حساب می‌شود، حتی اگر کار پس‌زمینه‌اش ادامه داشته باشد.
- **گزارش و هزینه:** برای ایجنت‌های `process`، Paperclip فقط کامنت‌های ثبت‌شده را می‌بیند؛ گزارش زندهٔ اجرا و آمار هزینه ندارد.
- **یک تیکت در هر بیدارباش:** اسکریپت در هر اجرا فقط یک تیکت را انجام می‌دهد.
- **شکل پاسخ API:** نام فیلدهای تیکت (`id`، `title`، `description`، `status`) از مستندات برداشته شده و با سرور واقعی آزمایش نشده است.
- **Freebuff:** راه رسمی برای اجرای خودکار ندارد؛ برای همین دستی نگه داشته شده است.

---

## ۱۲. رفع اشکال

| نشانه | علت محتمل | راه‌حل |
|---|---|---|
| `'bash\r': No such file or directory` | پایان خط ویندوزی در اسکریپت | `sed -i 's/\r$//' bridge.sh` |
| `command not found` در خط‌های اسکریپت | متن از چت کپی شده و کاراکتر مخفی دارد | فایل را دانلود کنید |
| `jq: command not found` یا `herdr: command not found` | ابزار در مسیر Git Bash نیست | Git Bash جدید باز کنید؛ در صورت نیاز مسیر را در `adapterConfig.env.PATH` بدهید |
| `checkout refused, skipping` | ایجنت دیگری تیکت را برداشته | طبیعی است؛ تیکت را دوباره واگذار کنید |
| `no assigned work` | تیکتی با وضعیت `todo` یا `in_progress` به این ایجنت واگذار نشده | واگذاری و وضعیت تیکت را بررسی کنید |
| اسکریپت تا ۳۰ دقیقه منتظر می‌ماند | ایجنت نشانهٔ پایان را چاپ نکرده و صفحه متحرک است | `WAIT_MS` را کم کنید یا خروجی پنجره را ببینید |
| `state=blocked` و تیکت باز مانده | ایجنت منتظر تأیید است | در Herdr به پنجرهٔ ایجنت بروید و جواب دهید |
| Herdr ایجنت را پیدا نمی‌کند | Paperclip و Herdr با دو کاربر متفاوت اجرا شده‌اند | هر دو را با یک کاربر اجرا کنید |
| خطای `curl` با کد 4xx در گام اول | شکل پاسخ یا مسیر API با مستندات فرق دارد | متن خطا را نگه دارید تا اسکریپت اصلاح شود |

**دستورهای کمکی Herdr**

</div>

```bash
herdr agent get agy-worker                                     # وضعیت ایجنت
herdr agent read agy-worker --source recent-unwrapped --lines 80   # خروجی اخیر
herdr pane read <pane_id> --source visible                     # صفحهٔ فعلی یک پنجره
herdr api schema --json > herdr-api.json                       # فهرست دقیق دستورهای نسخهٔ نصب‌شده
```

<div dir="rtl">

---

## پیوندها

- Paperclip: https://github.com/paperclipai/paperclip — مستندات: https://docs.paperclip.ing
- Herdr: https://github.com/herdrdev/herdr — مستندات: https://herdr.dev/docs
- Hermes Agent: https://github.com/NousResearch/hermes-agent
- Freebuff: https://freebuff.com

</div>
