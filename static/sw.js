/* ===================================================
 * WeBooks - PWA Service Worker
 * 仅用于 PWA 安装注册，不缓存业务数据。
 * __ENTRY_CODE__ / __ENTRY_PREFIX__ 由后端动态注入
 * =================================================== */
var ENTRY_CODE = /* __ENTRY_CODE__ */;
var ENTRY_PREFIX = /* __ENTRY_PREFIX__ */;

self.addEventListener('install', function () {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', function () {
  return;
});
