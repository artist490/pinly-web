// Манифест PWA: сайт устанавливается на телефон как приложение.
// Тема светлая (#ffffff): тёмный вариант управляется data-theme на <html>,
// а манифест медиа-запросов не умеет — тот же компромисс, что у favicon.
import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Pinly — идеи и вдохновение",
    short_name: "Pinly",
    description:
      "Лента идей: картинки, видео, доски и подписки. Свои загрузки и поиск по фото.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#ffffff",
    lang: "ru",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      // маска под круглые иконки Android: знак по центру не обрезается
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
