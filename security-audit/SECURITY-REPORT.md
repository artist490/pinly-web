# Аудит безопасности — Pinly (pinly-web)

**Цель:** репозиторий `pinly-web` (Next.js 16 + FastAPI, локальная копия)
**Стек:** Next.js 16.4.3 / React 19, FastAPI 0.139, SQLite, Netlify или Docker
**Режим:** пассивный (код + зависимости + конфиг; активных проб по сети не было)
**Дата:** 2026-11-09

> Активные проверки не выполнялись: ни один сервер не слушал `:3000`/`:8000`,
> а публичный домен проекта в задаче не назван. Всё ниже — по коду и конфигу.

## Сводка

| severity | найдено | исправлено |
|---|---|---|
| critical | 0 | 0 |
| high | 4 | 1 |
| medium | 7 | 3 |
| low | 5 | 1 |
| info | — | 3 |

> **Обновлено 2026-11-09:** патчи применены. HIGH (заголовки), оба MEDIUM по
> доступу (fail-open админка, отзыв сессии) и LOW (minimatch) закрыты в
> рабочей копии — подробности в разделе «Проверено повторно». Счётчики
> rate-limit по-прежнему в памяти процесса: лимит по e-mail добавлен, но
> полноценный вынос — отдельная задача.

Сканеры дали 15 находок; после ручной проверки **11 из них — ложные
срабатывания** (разбор в конце). Реальных проблем — 5, из них 1 высокая.

Главное: **у приложения нет ни одного заголовка безопасности** (CSP, HSTS,
X-Frame-Options, Referrer-Policy), и **панель модерации открыта всем
зарегистрированным пользователям, если не задан `PINLY_OWNER_EMAIL`**.
Криптография, работа с сессией, загрузки, SQL и SSRF-защита сделаны аккуратно.

---

## Находки

### [HIGH] Нет CSP и вообще нет security-заголовков — CWE-693, OWASP A05:2021

- **Где:** `next.config.ts:59-68` — `headers()` отдаёт только `Cache-Control`
  для `/sw.js`. Middleware (`src/middleware.ts`) отсутствует. Файла
  `public/_headers` (Netlify) нет. В Docker-пути заголовки не ставит ни
  entrypoint, ни reverse-proxy (его в репозитории нет).
- **Проверено:** `grep` по всему репозиторию — ни `Content-Security-Policy`,
  ни `Strict-Transport-Security`, ни `X-Frame-Options`, ни
  `Referrer-Policy`, ни `Permissions-Policy` не встречаются ни разу.
- **Риск:** любая XSS-находка исполняется без ограничений; сайт можно
  встроить в iframe (кликджекинг на форме входа и настройках); referrer
  утекает на внешние хосты картинок; нет принудительного HTTPS.
- **Почему это high, а не medium:** сайт публичный, с аккаунтами и личными
  сообщениями; CSP здесь — единственный слой, который останавливает
  последствия ошибки в рендере, а его нет совсем.

**Исправление (шаг 1 — базовые заголовки).** В `next.config.ts`:

```ts
async headers() {
  return [
    { source: "/sw.js", headers: [{ key: "Cache-Control", value: "no-cache" }] },
    {
      source: "/(.*)",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        {
          key: "Content-Security-Policy",
          value: [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob: https://images.weserv.nl",
            "media-src 'self' blob:",
            "connect-src 'self'",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "object-src 'none'",
          ].join("; "),
        },
      ],
    },
  ];
}
```

**Исправление (шаг 2 — убрать `'unsafe-inline'` из `script-src`).**
`'unsafe-inline'` оставлен временно, потому что в `src/app/layout.tsx:66,81`
два инлайн-скрипта (тема и заставка) пишутся литералами. Правильный путь —
nonce через middleware: Next 16 проставляет nonce своим скриптам сам, а два
ручных `<script>` получают его из `headers()`. Пока этого нет, CSP защищает
от `object`/`base`/`frame`-векторов, но не от инлайн-XSS.

**Важно про `/api/*`:** эти пути уходят в FastAPI через `rewrites`. После
правки проверьте `curl -I https://<домен>/api/ev` — если заголовков нет,
значит их надо ставить на reverse-proxy/Netlify (для Netlify — файл
`public/_headers`), а не в `next.config.ts`.

**HSTS** ставится только на уровне TLS-терминатора (Netlify/nginx/Caddy), не
в Next — иначе на http-стенде он залипнет в браузере:

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

---

### [MEDIUM] Панель модерации fail-open: без `PINLY_OWNER_EMAIL` админ — любой вошедший — CWE-284, OWASP A01:2021

- **Где:** `backend/deps.py:70-88` (`require_admin`), `backend/events.py:116-134`
  (`summary`), маршруты `backend/routers/moderation.py:19-35`.
- **Суть:** логика такая —
  ```python
  if owner and email != owner: raise 403
  if production and not owner: raise 404
  ```
  То есть если `PINLY_OWNER_EMAIL` пуст, а `PINLY_ENV` **не** равен ровно
  `production`, админ-панель (`/api/admin/reports`, скрытие пинов, бан
  аккаунтов) доступна **любому зарегистрированному пользователю**.
- **Риск:** один забытый env-файл или опечатка в `PINLY_ENV=prod` на боевом
  сервере — и любой посетитель банит пользователей и скрывает пины.
  Это классический fail-open: отказ конфигурации открывает доступ, а не
  закрывает.
- **Доказательство:** `deps.py:78-83` — обе проверки построены на «если
  настроено, то проверяем». Комментарий в коде это признаёт: «локально без
  настроек панель не заперта».
- **Исправление:** перевернуть логику — локальный обход должен требовать
  явного флага, а не отсутствия настройки.

```python
def require_admin(request: Request) -> sqlite3.Row:
    payload = session_payload(request)
    if not payload or "sub" not in payload:
        raise HTTPException(401, "login required")
    owner = os.environ.get("PINLY_OWNER_EMAIL", "").strip().lower()
    local_dev = os.environ.get("PINLY_ALLOW_LOCAL_ADMIN") == "1"
    if not (owner or local_dev):
        raise HTTPException(404, "moderation disabled")
    if owner and str(payload.get("email", "")).lower() != owner:
        raise HTTPException(403, "not owner")
    row = user_by_id(payload["sub"])
    if row is None:
        raise HTTPException(401, "no session")
    return row
```

Ту же правку — в `events.summary` (там дублируется тот же код; лучше вынести
общую функцию `require_owner`). Тестам и локальному стенду добавить
`PINLY_ALLOW_LOCAL_ADMIN=1` в `conftest.py`/`.env.local`.

---

### [MEDIUM] Сессию нельзя отозвать: logout не инвалидирует токен — CWE-613, OWASP A07:2021

- **Где:** `backend/session.py:126-129` (`clear_session_cookie` только удаляет
  куку), `backend/session.py:96-110` (`jwt_decode` проверяет подпись и `exp`).
- **Суть:** JWT живёт 30 дней и не имеет ни `jti`, ни списка отзыва. Копия
  куки, снятая до «выхода», работает все 30 дней. Смена пароля тоже ничего
  не отзывает — эндпоинта смены пароля в `routers/auth.py` нет вовсе.
- **Смягчает:** бан работает — `deps.current_user` проверяет `is_blocked`
  на каждом запросе (`deps.py:31-35`), так что заблокированный аккаунт
  теряет доступ сразу.
- **Риск:** украденная кука не отзывается пострадавшим; «выйти со всех
  устройств» невозможно.
- **Исправление (минимальное):** добавить в users колонку `session_version`
  (int, default 0), класть её в payload как `sv`, сверять в
  `current_user`/`optional_user`; инкрементировать при logout, смене пароля
  и бане. Это ~20 строк и не ломает формат токена.

---

### [MEDIUM] Rate limit живёт в памяти процесса и опирается на доверие к IP — CWE-307 / CWE-770

- **Где:** `backend/ratelimit.py:14-52`, `backend/ratelimit.py:60-72`
  (`client_ip`).
- **Суть:** счётчики — обычный `dict` в процессе. Перезапуск сбрасывает их;
  при нескольких воркерах uvicorn лимит умножается на число воркеров.
  Комментарий в коде это признаёт, но на брутфорс входа (`limit=20` на 5 мин)
  это влияет прямо.
- **Вторая половина:** если `PINLY_TRUST_PROXY` **не** задан, а сайт стоит за
  nginx/Netlify, все запросы приходят с одного адреса прокси → один общий
  бакет на всех. 20 неудачных входов от кого угодно блокируют вход **всем**
  на 5 минут (DoS на аутентификацию). Обратная ошибка — задать
  `PINLY_TRUST_PROXY=1` без прокси — позволяет обходить лимит заголовком
  `X-Forwarded-For`.
- **Исправление:** для логина добавить второй счётчик по `email` (а не только
  по IP) — это дороже для атакующего и не блокирует чужих; в проде
  документировать, что `PINLY_TRUST_PROXY=1` обязателен ровно тогда, когда
  перед приложением стоит свой прокси, и что воркер должен быть один (или
  счётчики — в Redis/SQLite).

---

### [LOW] Уязвимая dev-зависимость: minimatch 10.2.6 (CVE-2026-118764) — CWE-400

- **Где:** `node_modules/minimatch@10.2.6` (dev, транзитивно через eslint).
- **Риск:** DoS через «globparts amplification»; в рантайм сайта не попадает.
- **Исправление:** `npm i -D minimatch@^11.0.1` либо дождаться обновления
  `eslint-config-next`. Не срочно.

---

### [INFO] Прочее, что стоит знать

- **CORS** (`backend/server.py:118-122`): `allow_methods=["*"]`,
  `allow_headers=["*"]`, `allow_credentials` не задан (значит `False`).
  Так как фронтенд ходит на тот же origin через rewrites, CORS здесь вообще
  не нужен — можно сузить до `["GET","POST","PUT","PATCH","DELETE"]` и
  `["Content-Type","X-Request-Id"]`, но это гигиена, не дыра.
- **`PINLY_DISABLE_RATE_LIMIT=1`** (`ratelimit.py:24`) — глобальный рубильник
  всех лимитов. В `.env.example` помечен «только для тестов», но кода,
  который мешает выставить его в проде, нет. Стоит добавить проверку
  `if production and disabled(): raise` на старте.
- **`target="_blank"`** в `BoardView.tsx:76`, `PinDetail.tsx:56`,
  `signup/page.tsx:97,105` — без `rel="noopener"`. Современные браузеры
  подставляют `noopener` сами, так что это не уязвимость, но добавить
  `rel="noopener noreferrer"` бесплатно.
- **SHA-1/MD5** в `backend/cache.py:34`, `backend/imgproxy.py:43`,
  `src/lib/server/providers/cache.ts:27`, `src/lib/server/img-proxy.ts:9` —
  это ключи дискового кэша, не пароли и не подписи. Коллизия даёт подмену
  файла в кэше между двумя URL, но оба URL уже прошли allowlist. Оставить.

---

## Ложные срабатывания сканеров (проверено вручную)

**4 × «SQL injection» — не подтверждено.** Все четыре места — `f`-строки,
в которые подставляются только статические фрагменты, а значения идут
параметрами:
- `backend/groups.py:162` — `' and '.join(where)`, где `where` — литералы
  `"(is_hidden = 0 or ...)"` и `"category = ?"`; значение категории в `args`.
- `backend/pins.py:118,127,133` — подставляется `visible_clause()`
  (`pins.py:89-94`), которая возвращает константную строку; `pin_id`,
  `category`, `limit` — связанные параметры.
  Пользовательский ввод в текст запроса не попадает.

**6 × «XSS через dangerouslySetInnerHTML» — не подтверждено.**
- `src/app/layout.tsx:66,81` — литеральные константы, не данные.
- `src/app/{board,pin,group,profile}/…page.tsx` — везде `jsonLdText()`
  (`src/lib/server/seo.ts:56-58`), который экранирует `<`, `>`, `&` в
  `\uXXXX`. Это ровно тот фикс, что описан в комментарии над функцией
  (stored XSS был найден и закрыт 2026-10-31).

**1 × «секрет в присваивании» — не подтверждено.** `README.md:180`:
`PINLY_JWT_SECRET="$(openssl rand -hex 32)"` — это команда генерации
секрета в инструкции по запуску, а не сам секрет. В git-истории
`.env*`/`.data`/`*.key`/`*.pem` не встречаются (`git ls-files`, `git log --all`).

**4 × «weak crypto»** — см. INFO выше: это ключи кэша.

---

## Что проверено и выглядит хорошо

- **Пароли:** PBKDF2-HMAC-SHA256, 600k итераций, 16-байтовая соль на
  пользователя, сравнение через `hmac.compare_digest` (`accounts.py:43-60`).
- **JWT:** ручная реализация HS256 на `hmac` + `compare_digest`, `exp`
  обязателен, секрет не имеет дефолта — генерируется в `.data/secret.key`
  с `chmod 600`, а в `PINLY_ENV=production` без секрета сервер падает
  (`session.py:36-56, 96-110`).
- **Кука сессии:** `httpOnly`, `SameSite=Lax`, `Secure` только при
  подтверждённом https (не по клиентскому заголовку без `PINLY_TRUST_PROXY`).
- **CSRF:** `SameSite=Lax` + JSON-тела + same-origin proxy — кросс-сайтовый
  POST куку не принесёт. Отдельный CSRF-токен не нужен.
- **IDOR:** проверка владельца есть на каждом объектном эндпоинте —
  `boards.own_board` (`boards.py:120-169`), `pins.update/deletable`
  (`pins.py:322-348`), `chats.require_member` (`chats.py:152-162`),
  `groups` роли (`groups.py:258-275`). Чужой объект отдаёт 404, а не 403 —
  существование не утекает.
- **Загрузки:** имя файла генерирует сервер (uuid4 + расширение из
  сигнатуры байтов), клиентское имя и `Content-Type` игнорируются,
  `FILENAME_RE` защищает от path traversal, отдача с `nosniff` и
  `Content-Disposition: inline` (`uploads.py`, `routers/pins.py:108-124`).
  SVG не принимается — XSS через загруженный файл закрыт.
- **SSRF:** `/api/img` — allowlist хостов с точным матчем домена/поддомена
  (не по хвосту строки), `follow_redirects=False`, потолок 15 МБ, тип по
  байтам (`imgproxy.py`, `images.py:74-76`). Медиатека принимает любой хост,
  но проверяет `ip.is_global` на **всех** DNS-ответах и перепроверяет
  каждый редирект (`media.py:63-118`).
- **SQL:** везде параметризованные запросы; ни одного `executescript`,
  `eval`, `os.system`. `subprocess` только в `video.py`, вызов списком
  аргументов без `shell=True`.
- **Утечка PII:** публичный ответ пина не содержит e-mail
  (`tests/test_security.py:44-60`), лог не пишет query-строку и куки.
- **Секреты:** в репозитории только `.env.example` с пустыми значениями;
  `.data`, `.cache`, `.env*` в `.gitignore`; истории с секретами нет.

---

## Проверено повторно

Патчи применены 2026-11-09. Прогон после правок:

| Что | До | После |
|---|---|---|
| security-заголовки на `/` | нет ни одного | CSP, nosniff, X-Frame-Options, Referrer-Policy, Permissions-Policy, COOP |
| security-заголовки на `/api/*` | нет | nosniff, X-Frame-Options, Referrer-Policy, `default-src 'none'` |
| админ-панель без `PINLY_OWNER_EMAIL` | открыта всем вошедшим | 404 для всех |
| logout | кука стёрта, токен живёт | токен отозван (401 сразу) |
| бан | `is_blocked`, токен жив | `is_blocked` + отзыв поколения сессий |
| уязвимые npm-пакеты | 1 (low) | 0 |
| `pytest backend/tests` | — | 129 passed, 2 failed (падения предсуществующие, см. ниже) |
| `eslint` | — | 0 ошибок |
| `next build` | — | собирается |

Проверка в браузере (Chromium, прод-сборка): `/`, `/pin/ov-1`, `/signup`,
`/privacy`, `/search`, `/pin/new` — 200, гидрация проходит, тема
применяется (в т.ч. `prefers-color-scheme: dark`), заставка отрабатывает,
**ни одного нарушения CSP в консоли**.

Критерий закрытия HIGH выполнен частично: CSP есть, но `script-src` пока с
`'unsafe-inline'` (два инлайн-скрипта в `layout.tsx`). HSTS не ставится —
его место на TLS-терминаторе, в репозитории его нет.

### Что осталось за рамками патчей

- **`'unsafe-inline'` в `script-src`** — снимается переходом на nonce через
  `middleware.ts`; это отдельная правка, затрагивающая layout и гидрацию.
- **HSTS** — добавить на nginx/Caddy/Netlify:
  `Strict-Transport-Security: max-age=31536000; includeSubDomains`.
  На http-стенде не ставить: заголовок залипает в браузере.
- **Netlify:** заголовки из `next.config.ts` работают и там, но если
  CDN что-то перезапишет — продублировать файлом `public/_headers`.
- **Счётчики rate-limit** по-прежнему в памяти процесса: лимит по e-mail
  добавлен, но при нескольких воркерах квоты умножаются. Вынос в Redis/SQLite
  — задача на потом, не дыра.

### Предсуществующие падения тестов

`backend/tests/test_media.py::test_video_pin_gets_duration_and_a_picture_cover`
и `::test_board_snapshot_carries_slides_and_rejects_a_foreign_scheme` падают
и на чистом `HEAD` (проверено через `git worktree` на коммите `c5e460e`):
локальный ffmpeg 2013 года не строит постер в этом окружении. К правкам
отношения не имеют.

`next build`/`tsc` в рабочей копии падают на незакоммиченной ветке групп
(`src/app/group/[id]/page.tsx` импортирует отсутствующий
`@/components/group/GroupView`) — тоже не связано с патчами; сборка и
типизация проходят, если эти неотслеживаемые файлы убрать.

```bash
node <plugin>/scripts/check-headers.mjs https://<домен> --json --out headers.json
node <plugin>/scripts/scan-secrets.mjs . --json --out secrets.json
node <plugin>/scripts/audit-deps.mjs . --json --out deps.json
curl -I https://<домен>/api/ev | grep -i -E "content-security|strict-transport|x-frame"
```

## Остаточные риски и что не проверялось

- **Активные инъекции** (SQLi/XSS/SSRF живыми payload'ами), брутфорс, обход
  лимитов — не выполнялись: не было ни запущенного стенда, ни явного
  согласия на активный режим.
- **Публичный домен** не назван, поэтому реальные заголовки прода проверить
  нельзя: вывод про CSP сделан по конфигу, а CDN/Netlify может добавлять
  свои заголовки (в репозитории их нет).
- **Бизнес-логика:** лимиты на количество пинов, оплата, квоты — вне
  периметра (платежей в проекте нет).
- **Python-зависимости** проверены только по `requirements.txt` глазами;
  `audit-deps.mjs` покрывает npm. Для FastAPI/httpx/uvicorn стоит прогнать
  `pip-audit` в CI — версии зафиксированы и на 2026-11 свежие.
- **Фронтенд-зависимости:** React 19.3 / Next 16.4.3 — OSV по 440 пакетам
  дал одну dev-находку.
- **Секреты в истории git** проверены поиском по именам файлов, не
  `git-secrets`/`gitleaks` по содержимому всех 62 коммитов. Для полной
  уверенности — `gitleaks detect --no-git=false`.

---

Артефакты сканеров: `security-audit/{secrets,code,deps}.json`,
`security-audit/SCANNERS-RAW.md`.
