import { expect, test, type Route } from "@playwright/test";
import { createHmac } from "node:crypto";

test("catalog, real image, cart quantities, order snapshot and reload", async ({ page, context }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Каталог", exact: true })).toBeVisible();
  const product = page.locator(".products a").first();
  const name = await product.getByRole("heading").innerText();
  await product.click();
  await expect(page.getByRole("heading", { name, exact: true, level: 1 })).toBeVisible();
  await expect(page.getByRole("img", { name })).toBeVisible();
  expect(await page.getByRole("img", { name }).evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBeTruthy();
  const add = page.getByRole("button", { name: "Добавить в корзину" });
  await expect(add).toBeEnabled();
  await add.click();
  await expect(page.getByRole("status")).toHaveText("Товар добавлен в корзину");
  await page.getByRole("link", { name: "Перейти в корзину" }).click();
  const quantity = page.getByRole("spinbutton");
  await expect(quantity).toHaveValue("1");
  await quantity.fill("3");
  await page.getByRole("button", { name: "Сохранить количество" }).click();
  await expect(quantity).toHaveValue("3");
  await page.reload();
  await expect(page.getByRole("spinbutton")).toHaveValue("3");
  await page.getByRole("button", { name: "Оформить заказ" }).click();
  await expect(page.getByText("Заказ оформлен.", { exact: true })).toBeVisible();
  await expect(page.getByRole("listitem")).toHaveText(`${name} — 3 шт.`);
  const orderURL = page.url();
  await page.reload();
  await expect(page.getByText("Заказ оформлен.", { exact: true })).toBeVisible();
  const isolated = await context.browser()!.newContext();
  const other = await isolated.newPage();
  await other.goto(orderURL, { waitUntil: "domcontentloaded" });
  await expect(other.getByRole("main").getByRole("alert")).toHaveText("Заказ не найден");
  await isolated.close();
  await page.getByRole("link", { name: "Корзина", exact: true }).click();
  await expect(page.getByText("Корзина пуста.")).toBeVisible();
  expect(errors).toEqual([]);
});

test("empty catalog and actual product 404", async ({ page, request }) => {
  await page.goto("/?before=1");
  await expect(page.getByRole("main").getByText("В каталоге пока нет товаров.")).toBeVisible();
  const response = await request.get("/products/9007199254740991");
  expect(response.status()).toBe(404);
  expect((await request.get("/products/999999999999999999")).status()).toBe(404);
  await page.goto("/products/9007199254740991");
  await expect(page.getByRole("heading", { name: "Страница не найдена" })).toBeVisible();
});

test("remove cart item", async ({ page }) => {
  await page.goto("/");
  await page.locator(".products a").first().click();
  await page.getByRole("button", { name: "Добавить в корзину" }).click();
  await expect(page.getByRole("status")).toHaveText("Товар добавлен в корзину");
  await page.getByRole("link", { name: "Перейти в корзину" }).click();
  await page.getByRole("button", { name: "Удалить", exact: true }).click();
  await expect(page.getByText("Корзина пуста.")).toBeVisible();
});


test("ordinary browser works without Telegram SDK", async ({ page }) => {
  const sdkRequests: string[] = [];
  await page.route("https://telegram.org/**", route => { sdkRequests.push(route.request().url()); return route.abort(); });
  await page.goto("/");
  await page.locator(".products a").first().click();
  await expect(page.getByRole("button", { name: "Добавить в корзину" })).toBeEnabled();
  expect(sdkRequests).toEqual([]);
});

test("Mini App SDK failure is explicit and does not enable a guest cart", async ({ page }) => {
  await page.route("https://telegram.org/**", route => route.abort());
  await page.goto("/#tgWebAppData=test-launch");
  await expect(page.getByText("Не удалось загрузить Telegram SDK.", { exact: true })).toBeVisible();
  await page.locator(".products a").first().click();
  await expect(page.getByRole("button", { name: "Добавить в корзину" })).toBeDisabled();
});

test("invalid transmitted Telegram authorization never falls back to a guest cart", async ({ page }) => {
  await page.addInitScript(() => {
    window.Telegram = { WebApp: { initData: "hash=bad", ready() {}, expand() {} } };
  });
  await page.goto("/");
  await expect(page.getByText("Авторизация Telegram отклонена. Откройте каталог заново через бота.", { exact: true })).toBeVisible();
  await page.locator(".products a").first().click();
  await expect(page.getByRole("button", { name: "Добавить в корзину" })).toBeDisabled();
});

test("Telegram launch without identity asks to reopen through the bot", async ({ page }) => {
  await page.route("https://telegram.org/js/telegram-web-app.js", route => route.fulfill({
    contentType: "text/javascript", body: 'window.Telegram={WebApp:{initData:"",ready(){},expand(){}}};',
  }));
  await page.goto("/#tgWebAppVersion=9.6&tgWebAppPlatform=web");
  await expect(page.getByText("Telegram не передал данные авторизации. Откройте каталог через бота.", { exact: true })).toBeVisible();
  await page.locator(".products a").first().click();
  await expect(page.getByRole("button", { name: "Добавить в корзину" })).toBeDisabled();
});

test("session bootstrap timeout shows an error and keeps the cart disabled", async ({ page }) => {
  await page.route("**/api/session", () => new Promise<void>(() => {}));
  await page.goto("/");
  await expect(page.getByText("Истекло время ожидания. Обновите страницу.", { exact: true })).toBeVisible({ timeout: 20000 });
  await page.locator(".products a").first().click();
  await expect(page.getByRole("button", { name: "Добавить в корзину" })).toBeDisabled();
});

test("navigation before hydration cannot discard Telegram authorization", async ({ page }) => {
  let blockScripts = true;
  await page.route("**/_next/static/chunks/*.js", route => blockScripts ? route.abort() : route.continue());
  await page.route("https://telegram.org/js/telegram-web-app.js", route => route.fulfill({
    contentType: "text/javascript", body: 'window.Telegram={WebApp:{initData:"",ready(){},expand(){}}};',
  }));
  await page.goto("/#tgWebAppData=hash%3Dbad&tgWebAppVersion=9.6", { waitUntil: "domcontentloaded" });
  const product = await page.locator(".products a").first().getAttribute("href");
  blockScripts = false;
  await page.goto(product!);
  await expect(page.getByText("Авторизация Telegram отклонена. Откройте каталог заново через бота.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Добавить в корзину" })).toBeDisabled();
});

for (const legacy of [false, true]) test(`checkout survives lost response, reload and repeated recovery failures (legacy storage: ${legacy})`, async ({ page }) => {
  await page.goto("/");
  await page.locator(".products a").first().click();
  await page.getByRole("button", { name: "Добавить в корзину" }).click();
  await expect(page.getByRole("status")).toHaveText("Товар добавлен в корзину");
  await page.getByRole("link", { name: "Перейти в корзину" }).click();
  const ids: string[] = [];
  const keys: string[] = [];
  let drop = true;
  await page.route("**/api/orders", async route => {
    if (route.request().method() !== "POST") return route.continue();
    keys.push(route.request().headers()["idempotency-key"]);
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    ids.push((await response.json()).id);
    if (drop) await route.abort("connectionfailed");
    else await route.fulfill({ response });
  });
  await page.getByRole("button", { name: "Оформить заказ", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  if (legacy) {
    const session = await (await page.request.get("/api/session")).json();
    await page.evaluate(({ csrf_token, checkout_scope }) => {
      const raw = sessionStorage.getItem(`checkout:pending:${checkout_scope}`)!;
      sessionStorage.setItem(`checkout:pending:${csrf_token}`, raw);
      sessionStorage.removeItem(`checkout:pending:${checkout_scope}`);
    }, session);
  }
  await page.reload();
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  await expect(page.getByRole("button", { name: "Повторить оформление", exact: true })).toBeEnabled();
  drop = false;
  await page.reload();
  await expect(page.getByText("Заказ оформлен.", { exact: true })).toBeVisible();
  expect(ids.length).toBeGreaterThanOrEqual(3);
  expect(new Set(ids).size).toBe(1);
  expect(new Set(keys).size).toBe(1);
  await page.getByRole("link", { name: "Корзина", exact: true }).click();
  await expect(page.getByText("Корзина пуста.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Оформить заказ", exact: true })).toBeDisabled();
});

test("checkout retries the same attempt when connection fails before commit", async ({ page }) => {
  await page.goto("/");
  await page.locator(".products a").first().click();
  await page.getByRole("button", { name: "Добавить в корзину" }).click();
  await expect(page.getByRole("status")).toHaveText("Товар добавлен в корзину");
  await page.getByRole("link", { name: "Перейти в корзину" }).click();
  let first = true;
  const keys: string[] = [];
  await page.route("**/api/orders", async route => {
    keys.push(route.request().headers()["idempotency-key"]);
    if (first) { first = false; await route.abort("connectionfailed"); }
    else await route.continue();
  });
  await page.getByRole("button", { name: "Оформить заказ", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText("Не удалось связаться с сервером. Проверьте соединение и повторите запрос.");
  await page.reload();
  await expect(page.getByText("Заказ оформлен.", { exact: true })).toBeVisible();
  expect(keys.length).toBeGreaterThanOrEqual(2);
  expect(new Set(keys).size).toBe(1);
});

test("checkout conflict allows a new attempt with the updated cart", async ({ page }) => {
  await page.goto("/");
  await page.locator(".products a").first().click();
  await page.getByRole("button", { name: "Добавить в корзину" }).click();
  await expect(page.getByRole("status")).toHaveText("Товар добавлен в корзину");
  await page.getByRole("link", { name: "Перейти в корзину" }).click();
  const keys: string[] = [];
  await page.route("**/api/orders", async route => {
    keys.push(route.request().headers()["idempotency-key"]);
    if (keys.length === 1) {
      const cart = await (await page.request.get("/api/cart")).json();
      const session = await (await page.request.get("/api/session")).json();
      const changed = await page.request.put(`/api/cart/items/${cart.items[0].product_id}`, {
        headers: { Origin: new URL(page.url()).origin, "X-CSRF-Token": session.csrf_token },
        data: { quantity: 2, version: cart.version },
      });
      expect(changed.status()).toBe(200);
    }
    await route.continue();
  });
  await page.getByRole("button", { name: "Оформить заказ", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  await expect(page.getByRole("spinbutton")).toHaveValue("2");
  await page.getByRole("button", { name: "Оформить заказ", exact: true }).click();
  await expect(page.getByText("Заказ оформлен.", { exact: true })).toBeVisible();
  await expect(page.getByRole("main").getByRole("listitem")).toContainText("2 шт.");
  expect(new Set(keys).size).toBe(2);
});

test("Telegram tabs keep working after another tab logs in and reloads", async ({ page, context }) => {
  const fields: Record<string, string> = {
    auth_date: String(Math.floor(Date.now() / 1000)),
    user: JSON.stringify({ id: Date.now(), first_name: "Test" }),
  };
  const secret = createHmac("sha256", "WebAppData").update("123456:TEST_ONLY_NOT_A_REAL_TOKEN").digest();
  fields.hash = createHmac("sha256", secret).update(Object.keys(fields).sort().map(key => `${key}=${fields[key]}`).join("\n")).digest("hex");
  const initData = new URLSearchParams(fields).toString();
  await context.addInitScript(data => {
    window.Telegram = { WebApp: { initData: data, ready() {}, expand() {} } };
  }, initData);
  await page.goto("/");
  await page.locator(".products a").first().click();
  const add = page.getByRole("button", { name: "Добавить в корзину" });
  await expect(add).toBeEnabled();
  const other = await context.newPage();
  await other.goto(page.url());
  await expect(other.getByRole("button", { name: "Добавить в корзину" })).toBeEnabled();
  await other.reload();
  await expect(other.getByRole("button", { name: "Добавить в корзину" })).toBeEnabled();
  await add.click();
  await expect(page.getByRole("status")).toHaveText("Товар добавлен в корзину");
  await other.getByRole("button", { name: "Добавить в корзину" }).click();
  await expect(other.getByRole("status")).toHaveText("Товар добавлен в корзину");
  await page.getByRole("link", { name: "Перейти в корзину" }).click();
  await expect(page.getByRole("spinbutton")).toHaveValue("2");
  await other.close();
});

for (const webLocks of [true, false]) test(`concurrent Telegram login with a shared guest cookie (Web Locks: ${webLocks})`, async ({ context }) => {
  await context.request.get("/api/session");
  const fields: Record<string, string> = {
    auth_date: String(Math.floor(Date.now() / 1000)),
    user: JSON.stringify({ id: Date.now(), first_name: "Test" }),
  };
  const secret = createHmac("sha256", "WebAppData").update("123456:TEST_ONLY_NOT_A_REAL_TOKEN").digest();
  fields.hash = createHmac("sha256", secret).update(Object.keys(fields).sort().map(key => `${key}=${fields[key]}`).join("\n")).digest("hex");
  await context.addInitScript(({ initData, webLocks }) => {
    if (!webLocks) Object.defineProperty(navigator, "locks", { value: undefined });
    window.Telegram = { WebApp: { initData, ready() {}, expand() {} } };
  }, { initData: new URLSearchParams(fields).toString(), webLocks });
  const authHeaders: Promise<Record<string, string>>[] = [];
  context.on("response", response => {
    if (response.url().endsWith("/api/session/telegram")) authHeaders.push(response.allHeaders());
  });
  const product = (await (await context.request.get("/api/products")).json()).items[0];
  const pages = await Promise.all(Array.from({ length: 4 }, () => context.newPage()));
  await Promise.all(pages.map(page => page.goto(`/products/${product.id}`)));
  for (const page of pages) {
    const add = page.getByRole("button", { name: "Добавить в корзину" });
    await expect(add).toBeEnabled();
    await add.click();
    await expect(page.getByRole("status")).toHaveText("Товар добавлен в корзину");
  }
  const headers = await Promise.all(authHeaders);
  expect(headers.length).toBeGreaterThanOrEqual(4);
  expect(headers.filter(value => value["set-cookie"]).length).toBe(1);
  await pages[0].getByRole("link", { name: "Перейти в корзину" }).click();
  await expect(pages[0].getByRole("spinbutton")).toHaveValue("4");
  await Promise.all(pages.map(page => page.close()));
});

test("first Telegram tabs without cookies or Web Locks recover after two successful logins", async ({ context }) => {
  expect(await context.cookies()).toEqual([]);
  const fields: Record<string, string> = {
    auth_date: String(Math.floor(Date.now() / 1000)),
    user: JSON.stringify({ id: Date.now(), first_name: "Test" }),
  };
  const secret = createHmac("sha256", "WebAppData").update("123456:TEST_ONLY_NOT_A_REAL_TOKEN").digest();
  fields.hash = createHmac("sha256", secret).update(Object.keys(fields).sort().map(key => `${key}=${fields[key]}`).join("\n")).digest("hex");
  await context.addInitScript(initData => {
    Object.defineProperty(navigator, "locks", { value: undefined });
    window.Telegram = { WebApp: { initData, ready() {}, expand() {} } };
  }, new URLSearchParams(fields).toString());
  let releaseBootstrap!: () => void, releaseFirstAuth!: () => void, releaseBothAuth!: () => void;
  const bothBootstrap = new Promise<void>(resolve => { releaseBootstrap = resolve; });
  const firstAuth = new Promise<void>(resolve => { releaseFirstAuth = resolve; });
  const bothAuth = new Promise<void>(resolve => { releaseBothAuth = resolve; });
  let bootstraps = 0, auths = 0;
  async function forward(route: Route) {
    const request = route.request();
    // Node fetch deliberately has no shared cookie jar: Set-Cookie is delivered only on fulfill.
    const response = await fetch(request.url(), {
      method: request.method(), headers: request.headers(), body: request.postData() || undefined,
    });
    return { status: response.status, headers: Object.fromEntries(response.headers), body: await response.text() };
  }
  await context.route("**/api/session", async route => {
    const n = ++bootstraps;
    if (n > 2) return route.continue();
    const response = await forward(route);
    if (bootstraps === 2) releaseBootstrap();
    await bothBootstrap;
    if (n === 2) await firstAuth;
    await route.fulfill(response);
  });
  const initialStatuses: number[] = [];
  await context.route("**/api/session/telegram", async route => {
    if (auths >= 2) return route.continue();
    const response = await forward(route);
    initialStatuses.push(response.status);
    auths++;
    if (auths === 1) releaseFirstAuth();
    if (auths === 2) releaseBothAuth();
    await bothAuth;
    await route.fulfill(response);
  });
  const product = (await (await context.request.get("/api/products")).json()).items[0];
  const pages = await Promise.all([context.newPage(), context.newPage()]);
  await Promise.all(pages.map(page => page.goto(`/products/${product.id}`)));
  for (const page of pages) await expect(page.getByRole("button", { name: "Добавить в корзину" })).toBeEnabled();
  expect(initialStatuses).toEqual([200, 200]);
  for (const page of pages) {
    await page.getByRole("button", { name: "Добавить в корзину" }).click();
    await expect(page.getByRole("status")).toHaveText("Товар добавлен в корзину");
  }
  await pages[0].getByRole("link", { name: "Перейти в корзину" }).click();
  await expect(pages[0].getByRole("spinbutton")).toHaveValue("2");
  await Promise.all(pages.map(page => page.close()));
});

test("checkout keeps its attempt across CSRF recovery, a lost response and reload", async ({ page, context }) => {
  const fields: Record<string, string> = {
    auth_date: String(Math.floor(Date.now() / 1000)),
    user: JSON.stringify({ id: Date.now(), first_name: "Test" }),
  };
  const secret = createHmac("sha256", "WebAppData").update("123456:TEST_ONLY_NOT_A_REAL_TOKEN").digest();
  fields.hash = createHmac("sha256", secret).update(Object.keys(fields).sort().map(key => `${key}=${fields[key]}`).join("\n")).digest("hex");
  const initData = new URLSearchParams(fields).toString();
  await context.addInitScript(initData => {
    window.Telegram = { WebApp: { initData, ready() {}, expand() {} } };
  }, initData);
  await page.goto("/");
  await page.locator(".products a").first().click();
  await page.getByRole("button", { name: "Добавить в корзину" }).click();
  await expect(page.getByRole("status")).toHaveText("Товар добавлен в корзину");
  await page.getByRole("link", { name: "Перейти в корзину" }).click();
  const keys: string[] = [], ids: string[] = [];
  await page.route("**/api/orders", async route => {
    keys.push(route.request().headers()["idempotency-key"]);
    if (keys.length === 1) {
      await context.clearCookies();
      const bootstrap = await (await context.request.get("/api/session")).json();
      const login = await context.request.post("/api/session/telegram", {
        headers: { Origin: new URL(page.url()).origin, "X-CSRF-Token": bootstrap.csrf_token },
        data: { init_data: initData },
      });
      expect(login.status()).toBe(200);
      const cookies = await context.cookies();
      return route.continue({ headers: { ...route.request().headers(), cookie: cookies.map(c => `${c.name}=${c.value}`).join("; ") } });
    }
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    ids.push((await response.json()).id);
    if (ids.length === 1) await route.abort("connectionfailed");
    else await route.fulfill({ response });
  });
  await page.getByRole("button", { name: "Оформить заказ", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText("Не удалось связаться с сервером. Проверьте соединение и повторите запрос.");
  await page.reload();
  await expect(page.getByText("Заказ оформлен.", { exact: true })).toBeVisible();
  expect(keys).toHaveLength(3);
  expect(new Set(keys).size).toBe(1);
  expect(ids).toHaveLength(2);
  expect(new Set(ids).size).toBe(1);
});

test("a proxy HTML error has a controlled message and is not retried as CSRF", async ({ page }) => {
  await page.goto("/");
  let requests = 0;
  await page.route("**/api/cart", route => {
    requests++;
    return route.fulfill({ status: 503, contentType: "text/html", body: "<h1>Service unavailable</h1>" });
  });
  await page.getByRole("link", { name: "Корзина", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText("Сервис временно недоступен. Повторите запрос позже.");
  expect(requests).toBe(1);
});

test("CSRF recovery rejects invalid Telegram identity and unrelated 403 is never retried", async ({ page, context }) => {
  const fields: Record<string, string> = {
    auth_date: String(Math.floor(Date.now() / 1000)),
    user: JSON.stringify({ id: Date.now(), first_name: "Test" }),
  };
  const secret = createHmac("sha256", "WebAppData").update("123456:TEST_ONLY_NOT_A_REAL_TOKEN").digest();
  fields.hash = createHmac("sha256", secret).update(Object.keys(fields).sort().map(key => `${key}=${fields[key]}`).join("\n")).digest("hex");
  await context.addInitScript(initData => {
    window.Telegram = { WebApp: { initData, ready() {}, expand() {} } };
  }, new URLSearchParams(fields).toString());
  await page.goto("/");
  await page.locator(".products a").first().click();
  const add = page.getByRole("button", { name: "Добавить в корзину" });
  await expect(add).toBeEnabled();
  let writes = 0, logins = 0;
  await page.route("**/api/session/telegram", async route => {
    logins++;
    const response = await route.fetch({ postData: JSON.stringify({ init_data: "hash=bad" }) });
    expect(response.status()).toBe(401);
    await route.fulfill({ response });
  });
  await page.route("**/api/cart/items/*", route => {
    writes++;
    return route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: "Доступ запрещён" }) });
  });
  await add.click();
  await expect(page.getByRole("status")).toHaveText("Доступ запрещён");
  expect(writes).toBe(1);
  expect(logins).toBe(0);
  await page.unroute("**/api/cart/items/*");
  await context.clearCookies();
  await context.request.get("/api/session");
  await add.click();
  await expect(page.getByRole("alert").filter({ hasText: "Авторизация Telegram отклонена." })).toHaveText("Авторизация Telegram отклонена. Откройте каталог заново через бота.");
  await expect(add).toBeDisabled();
  expect(logins).toBe(3);
  expect((await (await context.request.get("/api/cart")).json()).items).toEqual([]);
});

test("a cookie from another Telegram owner cannot switch an already open cart", async ({ page, context }) => {
  const userId = Date.now();
  function signed(user: number): string {
    const fields: Record<string, string> = {
      auth_date: String(Math.floor(Date.now() / 1000)), user: JSON.stringify({ id: user, first_name: "Test" }),
    };
    const secret = createHmac("sha256", "WebAppData").update("123456:TEST_ONLY_NOT_A_REAL_TOKEN").digest();
    fields.hash = createHmac("sha256", secret).update(Object.keys(fields).sort().map(key => `${key}=${fields[key]}`).join("\n")).digest("hex");
    return new URLSearchParams(fields).toString();
  }
  await context.addInitScript(initData => {
    window.Telegram = { WebApp: { initData, ready() {}, expand() {} } };
  }, signed(userId));
  const productId = (await (await context.request.get("/api/products")).json()).items[0].id;
  await page.goto(`/products/${productId}`);
  await page.getByRole("button", { name: "Добавить в корзину" }).click();
  await expect(page.getByRole("status")).toHaveText("Товар добавлен в корзину");
  await context.clearCookies();
  const bootstrap = await (await context.request.get("/api/session")).json();
  const other = await context.request.post("/api/session/telegram", {
    headers: { Origin: new URL(page.url()).origin, "X-CSRF-Token": bootstrap.csrf_token },
    data: { init_data: signed(userId + 1) },
  });
  expect(other.status()).toBe(200);
  const value = await other.json();
  const changed = await context.request.put(`/api/cart/items/${productId}`, {
    headers: { Origin: new URL(page.url()).origin, "X-CSRF-Token": value.csrf_token },
    data: { quantity: 4, version: 0 },
  });
  expect(changed.status()).toBe(200);
  await page.getByRole("link", { name: "Перейти в корзину" }).click();
  await expect(page.getByRole("spinbutton")).toHaveValue("1");
  expect((await (await context.request.get("/api/cart")).json()).items[0].quantity).toBe(1);
});

test("fallback refreshes stale CSRF after another Telegram tab rotates the cookie", async ({ context }) => {
  await context.request.get("/api/session");
  const fields: Record<string, string> = {
    auth_date: String(Math.floor(Date.now() / 1000)),
    user: JSON.stringify({ id: Date.now(), first_name: "Test" }),
  };
  const secret = createHmac("sha256", "WebAppData").update("123456:TEST_ONLY_NOT_A_REAL_TOKEN").digest();
  fields.hash = createHmac("sha256", secret).update(Object.keys(fields).sort().map(key => `${key}=${fields[key]}`).join("\n")).digest("hex");
  await context.addInitScript(initData => {
    Object.defineProperty(navigator, "locks", { value: undefined });
    window.Telegram = { WebApp: { initData, ready() {}, expand() {} } };
  }, new URLSearchParams(fields).toString());
  const product = (await (await context.request.get("/api/products")).json()).items[0];
  const a = await context.newPage();
  const b = await context.newPage();
  let release!: () => void;
  const hold = new Promise<void>(resolve => { release = resolve; });
  let observed!: () => void;
  const observedBootstrap = new Promise<void>(resolve => { observed = resolve; });
  let delayed = false;
  await a.route("**/api/session", async route => {
    if (delayed) return route.continue();
    delayed = true;
    const response = await route.fetch();
    observed();
    await hold;
    await route.fulfill({ response });
  });
  const statuses: number[] = [];
  a.on("response", response => { if (response.url().endsWith("/api/session/telegram")) statuses.push(response.status()); });
  await a.goto(`/products/${product.id}`);
  await observedBootstrap;
  await b.goto(`/products/${product.id}`);
  await expect(b.getByRole("button", { name: "Добавить в корзину" })).toBeEnabled();
  release();
  await expect(a.getByRole("button", { name: "Добавить в корзину" })).toBeEnabled();
  expect(statuses).toEqual([403, 200]);
  for (const page of [a, b]) {
    await page.getByRole("button", { name: "Добавить в корзину" }).click();
    await expect(page.getByRole("status")).toHaveText("Товар добавлен в корзину");
    await page.close();
  }
});

for (const readEmptyCart of [false, true]) test(`first guest tabs without cookies or Web Locks share a working cart without reload (initial empty read: ${readEmptyCart})`, async ({ context }) => {
  expect(await context.cookies()).toEqual([]);
  await context.addInitScript(() => Object.defineProperty(navigator, "locks", { value: undefined }));
  let arrived = 0, releaseBoth!: () => void, releaseSecond!: () => void;
  const both = new Promise<void>(resolve => { releaseBoth = resolve; });
  const second = new Promise<void>(resolve => { releaseSecond = resolve; });
  await context.route("**/api/session", async route => {
    const n = ++arrived;
    if (n > 2) return route.continue();
    const request = route.request();
    // Neither independent bootstrap receives the other response's cookie before fulfillment.
    const response = await fetch(request.url(), { headers: request.headers() });
    const result = { status: response.status, headers: Object.fromEntries(response.headers), body: await response.text() };
    expect(response.status).toBe(200);
    if (arrived === 2) releaseBoth();
    await both;
    if (n === 2) await second;
    await route.fulfill(result);
  });
  const productId = (await (await context.request.get("/api/products")).json()).items[0].id;
  const a = await context.newPage(), b = await context.newPage();
  await a.goto(readEmptyCart ? "/cart" : `/products/${productId}`);
  await b.goto(`/products/${productId}`);
  if (readEmptyCart) await expect(a.getByText("Корзина пуста.", { exact: true })).toBeVisible();
  else await expect(a.getByRole("button", { name: "Добавить в корзину", exact: true })).toBeEnabled();
  releaseSecond();
  await expect(b.getByRole("button", { name: "Добавить в корзину", exact: true })).toBeEnabled();
  if (readEmptyCart) {
    await a.getByRole("link", { name: "Каталог", exact: true }).click();
    await a.locator(`.products a[href="/products/${productId}"]`).click();
  }
  for (const page of [a, b]) {
    await page.getByRole("button", { name: "Добавить в корзину", exact: true }).click();
    await expect(page.getByRole("status")).toHaveText("Товар добавлен в корзину");
  }
  await a.getByRole("link", { name: "Перейти в корзину" }).click();
  await expect(a.getByRole("spinbutton")).toHaveValue("2");
  expect((await (await context.request.get("/api/cart")).json()).items[0].quantity).toBe(2);
  await Promise.all([a.close(), b.close()]);
});

test("an existing guest cart cannot adopt a late replacement cookie before its first cart read", async ({ page, context, browser }) => {
  await context.addInitScript(() => Object.defineProperty(navigator, "locks", { value: undefined }));
  const origin = new URL(process.env.BASE_URL || "http://localhost:8088").origin;
  const original = await (await context.request.get("/api/session")).json();
  const productId = (await (await context.request.get("/api/products")).json()).items[0].id;
  const saved = await context.request.put(`/api/cart/items/${productId}`, {
    headers: { Origin: origin, "X-CSRF-Token": original.csrf_token }, data: { quantity: 1, version: 0 },
  });
  expect(saved.status()).toBe(200);
  const originalState = await context.storageState();
  let observed!: () => void, release!: () => void;
  const bootstrapReady = new Promise<void>(resolve => { observed = resolve; });
  const hold = new Promise<void>(resolve => { release = resolve; });
  let delayed = false;
  await page.route("**/api/session", async route => {
    if (delayed) return route.continue();
    delayed = true;
    const response = await route.fetch();
    expect(response.status()).toBe(200);
    observed();
    await hold;
    await route.fulfill({ response });
  });
  await page.goto("/cart");
  await bootstrapReady;
  await context.clearCookies();
  const replacement = await (await context.request.get("/api/session")).json();
  expect(replacement.checkout_scope).not.toBe(original.checkout_scope);
  const changed = await context.request.put(`/api/cart/items/${productId}`, {
    headers: { Origin: origin, "X-CSRF-Token": replacement.csrf_token }, data: { quantity: 4, version: 0 },
  });
  expect(changed.status()).toBe(200);
  const rejected = page.waitForResponse(response => response.url().endsWith("/api/cart"));
  release();
  expect((await rejected).status()).toBe(403);
  await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
  await expect(page.getByRole("spinbutton")).toHaveCount(0);
  expect((await (await context.request.get("/api/cart")).json()).items[0].quantity).toBe(4);
  const savedOwner = await browser.newContext({ storageState: originalState });
  try {
    const savedCart = await (await savedOwner.request.get(new URL("/api/cart", page.url()).toString())).json();
    expect(savedCart.items[0].quantity).toBe(1);
  } finally { await savedOwner.close(); }
});

test("a guest tab cannot adopt a Telegram owner from another tab", async ({ page, context }) => {
  await context.addInitScript(() => Object.defineProperty(navigator, "locks", { value: undefined }));
  const productId = (await (await context.request.get("/api/products")).json()).items[0].id;
  await page.goto(`/products/${productId}`);
  const add = page.getByRole("button", { name: "Добавить в корзину", exact: true });
  await expect(add).toBeEnabled();
  const guest = await (await context.request.get("/api/session")).json();
  const fields: Record<string, string> = {
    auth_date: String(Math.floor(Date.now() / 1000)), user: JSON.stringify({ id: Date.now(), first_name: "Test" }),
  };
  const secret = createHmac("sha256", "WebAppData").update("123456:TEST_ONLY_NOT_A_REAL_TOKEN").digest();
  fields.hash = createHmac("sha256", secret).update(Object.keys(fields).sort().map(key => `${key}=${fields[key]}`).join("\n")).digest("hex");
  const login = await context.request.post("/api/session/telegram", {
    headers: { Origin: new URL(page.url()).origin, "X-CSRF-Token": guest.csrf_token },
    data: { init_data: new URLSearchParams(fields).toString() },
  });
  expect(login.status()).toBe(200);
  const telegram = await login.json();
  expect(telegram.checkout_scope).not.toBe(guest.checkout_scope);
  const changed = await context.request.put(`/api/cart/items/${productId}`, {
    headers: { Origin: new URL(page.url()).origin, "X-CSRF-Token": telegram.csrf_token },
    data: { quantity: 4, version: 0 },
  });
  expect(changed.status()).toBe(200);
  await add.click();
  await expect(page.getByRole("status")).not.toBeEmpty();
  await expect(page.getByRole("status")).not.toHaveText("Товар добавлен в корзину");
  expect((await (await context.request.get("/api/cart")).json()).items[0].quantity).toBe(4);
});

test("a pending guest checkout cannot move to a replacement guest owner", async ({ page, context, browser }) => {
  await context.addInitScript(() => Object.defineProperty(navigator, "locks", { value: undefined }));
  await page.goto("/");
  await page.locator(".products a").first().click();
  await page.getByRole("button", { name: "Добавить в корзину", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Товар добавлен в корзину");
  await page.getByRole("link", { name: "Перейти в корзину" }).click();
  await expect(page.getByRole("spinbutton")).toHaveValue("1");
  const original = await (await context.request.get("/api/session")).json();
  const originalState = await context.storageState();
  let failFirst = true;
  const checkoutStatuses: number[] = [];
  page.on("response", response => {
    if (response.url().endsWith("/api/orders") && response.request().method() === "POST") checkoutStatuses.push(response.status());
  });
  await page.route("**/api/orders", route => {
    if (failFirst) { failFirst = false; return route.abort("connectionfailed"); }
    return route.continue();
  });
  await page.getByRole("button", { name: "Оформить заказ", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText("Не удалось связаться с сервером. Проверьте соединение и повторите запрос.");
  const pending = await page.evaluate(scope => sessionStorage.getItem(`checkout:pending:${scope}`), original.checkout_scope);
  expect(pending).not.toBeNull();
  await context.clearCookies();
  const replacement = await (await context.request.get("/api/session")).json();
  expect(replacement.checkout_scope).not.toBe(original.checkout_scope);
  const productId = (await (await context.request.get("/api/products")).json()).items[0].id;
  const changed = await context.request.put(`/api/cart/items/${productId}`, {
    headers: { Origin: new URL(page.url()).origin, "X-CSRF-Token": replacement.csrf_token },
    data: { quantity: 4, version: 0 },
  });
  expect(changed.status()).toBe(200);
  const rejected = page.waitForResponse(response => response.url().endsWith("/api/orders") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Повторить оформление", exact: true }).click();
  expect((await rejected).status()).toBe(403);
  await expect(page.getByRole("button", { name: "Повторить оформление", exact: true })).toBeEnabled();
  await expect(page.getByRole("main").getByRole("alert")).not.toHaveText("Не удалось связаться с сервером. Проверьте соединение и повторите запрос.");
  await expect(page.getByText("Заказ оформлен.", { exact: true })).toHaveCount(0);
  expect(checkoutStatuses).not.toContain(200);
  expect((await (await context.request.get("/api/cart")).json()).items[0].quantity).toBe(4);
  expect(await page.evaluate(scope => sessionStorage.getItem(`checkout:pending:${scope}`), original.checkout_scope)).toBe(pending);
  const savedOwner = await browser.newContext({ storageState: originalState });
  try {
    const savedCart = await (await savedOwner.request.get(new URL("/api/cart", page.url()).toString())).json();
    expect(savedCart.items[0].quantity).toBe(1);
  } finally { await savedOwner.close(); }
});
