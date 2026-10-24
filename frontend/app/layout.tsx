import type { Metadata } from "next";
import Link from "next/link";
import { SessionProvider } from "@/components/session";
import "./style.css";

export const metadata: Metadata = { title: "Каталог", icons: { icon: "data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22/>" } };
// Capture launch data before links can navigate, including when application chunks fail to load.
const captureTelegramLaunch = `(function(){
  var params=new URLSearchParams(window.location.hash.slice(1));
  if(params.has('tgWebAppData')||params.has('tgWebAppVersion')){
    sessionStorage.setItem('telegram-launch','1');
    sessionStorage.setItem('telegram-init-data',params.get('tgWebAppData')||'');
  }
})();`;
export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="ru"><head><script dangerouslySetInnerHTML={{ __html: captureTelegramLaunch }} /></head><body>
    <header><nav aria-label="Основная навигация"><Link href="/">Каталог</Link>{" · "}<Link href="/cart">Корзина</Link></nav></header>
    <SessionProvider><main>{children}</main></SessionProvider>
  </body></html>;
}
