import axios from "axios";

import { apiBaseUrl } from "./config";

export const api = axios.create({
  baseURL: apiBaseUrl,
  withCredentials: true,
  headers: { "X-Requested-With": "deflake" },
});

export function normalizeError(error) {
  const body = error?.response?.data?.error;
  if (body && typeof body.message === "string") {
    return {
      message: body.message,
      code: body.code || "error",
      requestId: body.request_id || null,
      fields: Array.isArray(body.fields) ? body.fields : [],
      runId: body.run_id || null,
      status: error.response.status,
    };
  }
  if (error?.response) {
    return {
      message: "The request failed.",
      code: "error",
      requestId: null,
      fields: [],
      runId: null,
      status: error.response.status,
    };
  }
  return {
    message: "The workspace could not be reached.",
    code: "network",
    requestId: null,
    fields: [],
    runId: null,
    status: 0,
  };
}

function isLocalPath(value) {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) {
    return false;
  }
  if (/[\\%@\s\u0000-\u001f]/.test(value) || /%5c|%2f%2f/i.test(value)) {
    return false;
  }
  return true;
}

function returnPath() {
  const path = `${window.location.pathname}${window.location.search}`;
  if (!isLocalPath(path) || path.startsWith("/sign-in")) {
    return "/";
  }
  return path;
}

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const normalized = normalizeError(error);
    error.normalized = normalized;
    const url = error.config?.url || "";
    const signing = url.includes("/auth/session") || url.includes("/auth/me") || url.includes("/auth/register");
    if (normalized.status === 401 && !signing && !window.location.pathname.startsWith("/sign-in")) {
      sessionStorage.setItem("deflake.expired", "1");
      const next = encodeURIComponent(returnPath());
      window.location.assign(`/sign-in?next=${next}`);
    }
    return Promise.reject(error);
  },
);

export function safeNext(value) {
  if (!isLocalPath(value)) {
    return "/";
  }
  if (value.startsWith("/sign-in") || value.startsWith("/create-account")) {
    return "/";
  }
  return value;
}
