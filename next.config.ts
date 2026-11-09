import type { NextConfig } from "next";

// canonical, og:url и sitemap строятся из NEXT_PUBLIC_SITE_URL; при пустом
// значении site.ts подставляет localhost:3000. Сайт при этом собирается и
// работает — просто все его адреса ведут на машинку разработчика. Проверка
// включается явным флагом, потому что CI и локальные прогоны собирают без
// боевого домена намеренно.
if (process.env.PINLY_REQUIRE_SITE_URL === "1" && !process.env.NEXT_PUBLIC_SITE_URL) {
  throw new Error(
    "NEXT_PUBLIC_SITE_URL пуст, а PINLY_REQUIRE_SITE_URL=1: соберётся сайт, у которого " +
      "canonical, og:image и sitemap.xml указывают на localhost. Задайте домен в окружении сборки.",
  );
}

// Same-origin прокси в Python-бэкенд: cookie-сессия ставится для домена сайта,
// поэтому CORS не нужен ни в браузере, ни в тестах.
//
// Список — то, чем владеет бэкенд. source и destination здесь всегда
// совпадают, поэтому один перечень префиксов вместо 25 рукописных пар:
// забытый подпуть — это не 404, а тихо вернувшийся Next-роут.
//
// Особые случаи отдельно: /api/feed и /api/img — роуты самого Next (у ленты
// оттуда только /api/feed/subscriptions), /api/pin/:pid/comments живёт внутри
// чужого префикса.
const BACKEND_PREFIXES = [
  "/api/auth",
  "/api/boards",
  "/api/likes",
  "/api/pins",
  "/api/uploads",
  "/api/users",
  "/api/notifications",
  "/api/media",
  "/api/comments",
  "/api/chats",
  "/api/messages",
  "/api/tags",
  "/api/reports",
  "/api/admin",
  "/api/groups",
];

const BACKEND_EXACT = [
  // События продукта: POST принимает бэкенд (пишет в свою SQLite).
  "/api/ev",
  "/api/ev/summary",
  "/api/ev/board",
  "/api/img/download",
  "/api/feed/subscriptions",
];

function toBackend(backend: string, path: string) {
  return { source: path, destination: `${backend}${path}` };
}

// Заголовки безопасности ставятся один раз на весь сайт, а не в каждом роуте.
// CSP — единственный слой, который переживает ошибку в рендере: без него любая
// инъекция в разметку исполняется с полными правами страницы.
//
// script-src пока с 'unsafe-inline': в layout.tsx два инлайн-скрипта (тема и
// заставка) пишутся литералами, а Next добавляет свои для гидрации. Переход на
// nonce — отдельный шаг через middleware; до него CSP закрывает object, base,
// frame и form-action, но не инлайн-XSS.
//
// 'unsafe-eval' и ws: нужны только dev-серверу (HMR и React Refresh). В
// прод-сборку они не попадают — иначе CSP перестаёт что-либо значить.
const isDev = process.env.NODE_ENV !== "production";

const CSP = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  // свои /api/img и /api/uploads, оптимизатор next/image (self),
  // data:/blob: для превью и офлайн-кэша service worker'а
  "img-src 'self' data: blob: https://images.weserv.nl",
  "media-src 'self' blob:",
  `connect-src 'self'${isDev ? " ws: wss:" : ""}`,
  "font-src 'self'",
  "worker-src 'self'",
  "manifest-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
  // Браузеру нечего угадывать тип. Загрузки и прокси уже отдают nosniff,
  // здесь — на весь сайт, включая HTML-страницы.
  { key: "X-Content-Type-Options", value: "nosniff" },
  // Встраиваний нет ни у одного экрана: форма входа в iframe — это кликджекинг
  { key: "X-Frame-Options", value: "DENY" },
  // Полный адрес страницы уходит только на свой origin; внешним хостам
  // (CDN картинок) достаётся лишь имя домена
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  async headers() {
    return [
      {
        // Service worker обязан обновляться: браузер проверяет скрипт на
        // каждый заход, и кэш здесь ломал бы обновления бэкенда логики.
        source: "/sw.js",
        headers: [
          { key: "Cache-Control", value: "no-cache" },
          ...SECURITY_HEADERS,
        ],
      },
      {
        // Всё остальное, включая ответы проксированного /api/*: заголовки
        // должны быть и на JSON, и на HTML — перебор путей и MIME-sniffing
        // начинаются именно с ответов API.
        source: "/(.*)",
        headers: SECURITY_HEADERS,
      },
    ];
  },
  async rewrites() {
    const backend = process.env.ACCOUNTS_BACKEND_URL ?? "http://127.0.0.1:8000";
    return {
      afterFiles: [
        ...BACKEND_PREFIXES.flatMap((prefix) => [
          toBackend(backend, prefix),
          toBackend(backend, `${prefix}/:path*`),
        ]),
        ...BACKEND_EXACT.map((path) => toBackend(backend, path)),
        toBackend(backend, "/api/pin/:pid/comments"),
      ],
    };
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  images: {
    // AVIF для всего, что его понимает: те же 384px весят заметно меньше WebP.
    formats: ["image/avif", "image/webp"],
    // Оптимизированные варианты живут сутки — столько же, сколько кэш ленты.
    minimumCacheTTL: 86400,
    // Ограниченный набор ширины: 100..7000 с шагом выносил в кэш отдельную
    // копию на каждый размер. 12 значений вместо 17 — не вкусовщина, а потолок
    // того, что сайт действительно рисует: карточка ленты на широком экране
    // при DPR 2 — ~730 px, крупный носитель на странице пина — ~1536 px
    // (45vw от 1920 при DPR 2). Каждый кандидат живёт и в HTML (~1,5 КБ на
    // картинку), и в <link rel=preload> первых карточек, поэтому список
    // измеряется байтами, которые летят пользователю.
    deviceSizes: [390, 768, 1024, 1280, 1536],
    imageSizes: [96, 128, 192, 256, 384, 512, 640],
    // Моки ленты едут через weserv (picsum блокирует хотлинкинг), остальные
    // картинки — внутренние пути /api/img и /api/uploads.
    remotePatterns: [{ protocol: "https", hostname: "images.weserv.nl" }],
    // Внутренние пути next/image пропускает только перечисленные в
    // localPatterns; у /api/img адрес источника живёт в query, поэтому
    // search не ограничиваем — сам прокси уже проверяет хосты.
    localPatterns: [
      { pathname: "/api/img" },
      { pathname: "/api/uploads/**" },
      // Знак в шапке и на заставке: 186-килобайтный PNG отдавался как есть,
      // хотя на экране это 36 и 64 px. Через оптимизатор те же пиксели весят
      // единицы килобайт (см. docs/performance.md).
      { pathname: "/logo-mark.png" },
    ],
  },
};

export default nextConfig;
