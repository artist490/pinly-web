"use client";

// Регистрация service worker: после загрузки страницы, чтобы не конкурировать
// с ней за сеть. Ошибка регистрации не мешает работе сайта — это прогрессивное
// улучшение.

import { useEffect } from "react";

export function SwRegister() {
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  }, []);
  return null;
}
