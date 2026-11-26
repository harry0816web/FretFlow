const ROUTES = [
  { name: "library", pattern: /^#\/library\/?$/ },
  { name: "separate", pattern: /^#\/separate\/?$/ },
  { name: "song", pattern: /^#\/songs\/([^/]+)\/?$/, parameter: "songId" },
  { name: "tabs", pattern: /^#\/tabs\/?$/ },
  { name: "tab", pattern: /^#\/tabs\/([^/]+)\/?$/, parameter: "tabId" },
];

export function parseRoute(hash = window.location.hash) {
  const candidate = hash || "#/library";
  for (const route of ROUTES) {
    const match = route.pattern.exec(candidate);
    if (!match) continue;
    const params = route.parameter
      ? { [route.parameter]: decodeURIComponent(match[1]) }
      : {};
    return { name: route.name, params };
  }
  return { name: "not-found", params: {} };
}

export function songRoute(songId) {
  if (!songId) throw new Error("songId is required");
  return `#/songs/${encodeURIComponent(songId)}`;
}

export function tabRoute(tabId) {
  if (!tabId) throw new Error("tabId is required");
  return `#/tabs/${encodeURIComponent(tabId)}`;
}
