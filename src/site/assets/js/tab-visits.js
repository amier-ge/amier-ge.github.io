(function () {
  "use strict";

  const counter = document.getElementById("visitor-counter");
  if (!counter || !globalThis.crypto?.randomUUID) return;
  const allowed = ["https://amier.ge", "https://www.amier.ge", "https://amier-ge.github.io"];
  if (!allowed.includes(location.origin)) return;
  const api = counter.dataset.api;
  const storageKey = "amier-visit-tab";
  let tabId;
  let channel;

  function remember(id) {
    try { sessionStorage.setItem(storageKey, id); } catch {}
    tabId = id;
    return id;
  }

  function claimLock(id) {
    return new Promise((resolve, reject) => {
      navigator.locks.request("amier-visit:" + id, { ifAvailable: true }, async lock => {
        if (!lock) return resolve(false);
        const closing = new Promise(done => addEventListener("pagehide", done, { once: true }));
        resolve(true);
        await closing;
      }).catch(reject);
    });
  }

  function claimByMessage(id) {
    if (!globalThis.BroadcastChannel) return Promise.resolve(true);
    channel = new BroadcastChannel("amier-visit-tabs");
    addEventListener("pagehide", () => {
      channel?.close();
      channel = null;
    }, { once: true });
    return new Promise(resolve => {
      const probe = crypto.randomUUID();
      const liveChannel = channel;
      let claimed = false;
      liveChannel.onmessage = ({ data }) => {
        if (claimed && data?.probe && data.id === tabId) {
          liveChannel.postMessage({ response: data.probe });
        } else if (!claimed && data?.response === probe) {
          clearTimeout(timer);
          resolve(false);
        }
      };
      const timer = setTimeout(() => { claimed = true; resolve(true); }, 120);
      liveChannel.postMessage({ id, probe });
    });
  }

  async function identifyTab() {
    let saved;
    try { saved = sessionStorage.getItem(storageKey); } catch {}
    const id = saved || tabId || crypto.randomUUID();
    if (navigator.locks) {
      if (await claimLock(id)) return remember(id);
      const fresh = crypto.randomUUID();
      await claimLock(fresh);
      return remember(fresh);
    }
    if (await claimByMessage(id)) return remember(id);
    channel?.close();
    const fresh = remember(crypto.randomUUID());
    await claimByMessage(fresh);
    return fresh;
  }

  function show(stats) {
    if (!Number.isSafeInteger(stats.today) || !Number.isSafeInteger(stats.total)) return;
    document.getElementById("visit-today").textContent = stats.today.toLocaleString();
    document.getElementById("visit-total").textContent = stats.total.toLocaleString();
  }

  async function count() {
    try {
      const id = await identifyTab();
      const result = await fetch(api + "/api/visitors/visit", {
        method: "POST",
        headers: { "Content-Type": "text/plain" },
        body: id,
        credentials: "omit",
        cache: "no-store",
        keepalive: true,
      });
      if (!result.ok) throw new Error("Visit was not recorded");
      show(await result.json());
    } catch {
      try {
        const stats = await fetch(api + "/api/visitors/stats", { cache: "no-store" });
        if (stats.ok) show(await stats.json());
      } catch {}
    }
  }

  if (document.prerendering) {
    document.addEventListener("prerenderingchange", count, { once: true });
  } else {
    count();
  }
  addEventListener("pageshow", event => { if (event.persisted) count(); });
})();
