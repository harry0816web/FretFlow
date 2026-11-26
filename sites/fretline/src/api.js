export class ApiError extends Error {
  constructor(message, { code = "REQUEST_FAILED", status = 0, details = {} } = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export async function apiRequest(path, options = {}) {
  const response = await fetch(path, options);
  if (response.status === 204) return null;
  const type = response.headers.get("content-type") || "";
  const payload = type.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    const error = payload?.error;
    throw new ApiError(error?.message || `Request failed (${response.status})`, {
      code: error?.code,
      status: response.status,
      details: error?.details,
    });
  }
  return payload;
}

export function getSongs({ search = "", status = "" } = {}) {
  const query = new URLSearchParams();
  if (search) query.set("search", search);
  if (status) query.set("status", status);
  return apiRequest(`/api/songs${query.size ? `?${query}` : ""}`);
}

export const getSong = (songId) => apiRequest(`/api/songs/${encodeURIComponent(songId)}`);
export const getStemTypes = () => apiRequest("/api/stem-types");
export const getStems = (songId) => apiRequest(`/api/songs/${encodeURIComponent(songId)}/stems`);
export const getSeparation = (jobId) => apiRequest(`/api/separations/${encodeURIComponent(jobId)}`);
export const getTabs = (status = "") => apiRequest(`/api/tabs${status ? `?status=${encodeURIComponent(status)}` : ""}`);
export const getTab = (tabId) => apiRequest(`/api/tabs/${encodeURIComponent(tabId)}`);

export function createSong(payload) {
  return apiRequest("/api/songs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function uploadSong(songId, file) {
  const body = new FormData();
  body.append("file", file);
  return apiRequest(`/api/songs/${encodeURIComponent(songId)}/upload`, { method: "POST", body });
}

export const completeUpload = (songId) => apiRequest(`/api/songs/${encodeURIComponent(songId)}/upload-complete`, { method: "POST" });

export function createSeparation(songId, payload) {
  return apiRequest(`/api/songs/${encodeURIComponent(songId)}/separations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function createTab(stemId, payload = {}) {
  return apiRequest(`/api/stems/${encodeURIComponent(stemId)}/tabs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export const deleteSong = (songId) => apiRequest(`/api/songs/${encodeURIComponent(songId)}?confirm=true`, { method: "DELETE" });
