const NAV_LINKS = [
  ["/ui", "Home"],
  ["/ui/how-it-works", "How it works"],
  ["/ui/pricing", "Pricing"],
  ["/ui/balance", "Balance"],
  ["/ui/faq", "FAQ"],
  ["/ui/docs", "Docs"],
  ["/ui/contact", "Contact"]
];

export function renderTopNav(targetId = "siteNav") {
  const nav = document.getElementById(targetId);
  if (!nav) return;
  const current = window.location.pathname;
  nav.innerHTML = NAV_LINKS.map(([href, label]) => {
    const active = current === href;
    return `<a href="${href}" class="${active ? "active" : ""}">${label}</a>`;
  }).join("");
}

export function renderFounderLinks(targetId = "founderLinks") {
  const node = document.getElementById(targetId);
  if (!node) return;
  node.innerHTML = `<a href="/ui/slidedeck/01-cover.html" class="text-mono-sm">[ FOUNDER DECK ]</a>`;
}

export function installAssetGuard() {
  window.addEventListener(
    "error",
    (e) => {
      const src = String(e?.target?.src || e?.target?.href || "");
      if (!src.includes("/ui/assets/")) return;
      if (document.getElementById("asset-guard-banner")) return;
      const n = document.createElement("div");
      n.id = "asset-guard-banner";
      n.textContent = "UI asset failed to load. Check /ui/assets paths.";
      n.style.cssText =
        "position:fixed;top:0;left:0;right:0;padding:8px;background:#ff7b7b;color:#040404;z-index:9999;font-family:monospace";
      document.body.appendChild(n);
    },
    true,
  );
}

export function byId(id) {
  return document.getElementById(id);
}
