// pondas service worker(item 39, D56⑤) — Web Push 수신 + 딥링크.
// 오프라인 셸은 목적이 아님(푸시 전용). 캐싱 없음 = 배포 즉시 신선.
self.addEventListener("push", (e) => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch { /* payload 없는 푸시 */ }
  e.waitUntil(
    self.registration.showNotification(data.title || "pondas", {
      body: data.body || "",
      icon: "/icon.png",
      badge: "/icon.png",
      data: { url: data.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((tabs) => {
      for (const tab of tabs) {
        if (tab.url.includes(url) && "focus" in tab) return tab.focus();
      }
      return clients.openWindow(url);
    })
  );
});
