/* ===================================================
 * WeBooks - PWA Service Worker
 * 缓存策略：
 *   - 导航 (HTML) → 网络优先，回退缓存
 *   - API GET    → 网络优先，回退缓存（只读数据可离线查看）
 *   - 静态资源   → 缓存优先
 *   - API 写操作 → 仅网络
 * =================================================== */

const CACHE = {
  SHELL:    'webooks-shell-v1',    // HTML 页面
  API:      'webooks-api-v1',      // API GET 响应
  STATIC:   'webooks-static-v1',   // 图标 / manifest
  CDN:      'webooks-cdn-v1',      // 外部 CDN 资源
};

const STATIC_URLS = [
  '/manifest.json',
  '/static/logo.png',
];

const CDN_URLS = [
  'https://maxst.icons8.com',
  'https://cdn.bootcdn.net',
];

/* ---------- install: 预缓存静态资源 ---------- */
self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE.STATIC).then(function (cache) {
      return cache.addAll(STATIC_URLS).catch(function (err) {
        console.warn('[SW] 静态资源预缓存部分失败:', err);
      });
    })
  );
  self.skipWaiting();
});

/* ---------- activate: 清理旧缓存 ---------- */
self.addEventListener('activate', function (event) {
  var keys = Object.values(CACHE);
  event.waitUntil(
    caches.keys().then(function (names) {
      return Promise.all(
        names.filter(function (n) { return keys.indexOf(n) === -1; })
              .map(function (n) { return caches.delete(n); })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

/* ---------- 工具函数 ---------- */
function isNavigation(req) {
  return req.mode === 'navigate';
}

function isApiGet(req) {
  return req.method === 'GET' && /^\/api\//.test(new URL(req.url).pathname);
}

function isStatic(req) {
  var url = new URL(req.url);
  return STATIC_URLS.indexOf(url.pathname) !== -1;
}

function isCdn(url) {
  return CDN_URLS.some(function (prefix) { return url.indexOf(prefix) === 0; });
}

function isMutation(req) {
  return ['POST', 'PUT', 'PATCH', 'DELETE'].indexOf(req.method) !== -1;
}

/* 网络优先：先请求网络，失败读缓存 */
function networkFirst(req, cacheName) {
  return fetch(req).then(function (resp) {
    if (resp && resp.ok) {
      var clone = resp.clone();
      caches.open(cacheName).then(function (c) { c.put(req, clone); });
    }
    return resp;
  }).catch(function () {
    return caches.match(req).then(function (cached) {
      return cached || new Response(
        JSON.stringify({ success: false, message: '网络不可用，请稍后重试' }),
        { status: 503, headers: { 'Content-Type': 'application/json' } }
      );
    });
  });
}

/* 缓存优先：先读缓存，没有则请求网络 */
function cacheFirst(req, cacheName) {
  return caches.match(req).then(function (cached) {
    return cached || fetch(req).then(function (resp) {
      if (resp && resp.ok) {
        var clone = resp.clone();
        caches.open(cacheName).then(function (c) { c.put(req, clone); });
      }
      return resp;
    });
  });
}

/* 离线页面 HTML */
function offlineResponse() {
  return new Response(
    '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<title>离线 - WeBooks</title>' +
    '<style>' +
    'body{font-family:-apple-system,"Microsoft YaHei",sans-serif;background:#f5f5f5;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:20px;}' +
    '.card{background:#fff;border-radius:16px;padding:40px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,.08);max-width:360px;}' +
    '.icon{font-size:64px;display:block;margin-bottom:16px;}' +
    'h1{font-size:20px;color:#333;margin-bottom:8px;}' +
    'p{font-size:14px;color:#888;line-height:1.6;}' +
    '.btn{display:inline-block;margin-top:16px;padding:10px 24px;border-radius:8px;background:#07c160;color:#fff;text-decoration:none;font-size:14px;border:none;cursor:pointer;}' +
    '</style></head><body>' +
    '<div class="card">' +
    '<span class="icon">📡</span>' +
    '<h1>网络已断开</h1>' +
    '<p>当前处于离线状态，部分功能不可用。<br>请检查网络连接后重试。</p>' +
    '<button class="btn" onclick="location.reload()">重新加载</button>' +
    '</div></body></html>',
    { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
  );
}

/* ---------- fetch: 拦截请求 ---------- */
self.addEventListener('fetch', function (event) {
  var req = event.request;
  var url = req.url;

  // 仅处理 GET 请求或导航
  if (req.method !== 'GET' && !isNavigation(req)) {
    return;
  }

  // CDN 资源：缓存优先
  if (isCdn(url)) {
    event.respondWith(cacheFirst(req, CACHE.CDN));
    return;
  }

  // 静态资源：缓存优先
  if (isStatic(req)) {
    event.respondWith(cacheFirst(req, CACHE.STATIC));
    return;
  }

  // API GET 请求：网络优先（离线时可查看缓存数据）
  if (isApiGet(req)) {
    event.respondWith(networkFirst(req, CACHE.API));
    return;
  }

  // 导航（HTML 页面）：网络优先，回退离线页
  if (isNavigation(req)) {
    event.respondWith(
      networkFirst(req, CACHE.SHELL).then(function (resp) {
        return resp;
      }).catch(function () {
        return offlineResponse();
      })
    );
    return;
  }

  // 其他：网络优先
  event.respondWith(
    fetch(req).catch(function () {
      return caches.match(req);
    })
  );
});
