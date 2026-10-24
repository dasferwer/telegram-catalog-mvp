"use client";
export default function ErrorPage({ reset }: { reset(): void }) {
  return <><h1>Не удалось загрузить страницу</h1><p role="alert">Сервис временно недоступен.</p><button onClick={reset}>Повторить</button></>;
}
