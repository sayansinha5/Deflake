/** Client-side mirror of the server GitHub URL rule. Never fetch the raw string. */

const OWNER = /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/;
const REPO = /^[A-Za-z0-9._-]{1,100}$/;

export function validateGithubRepoUrl(raw) {
  if (typeof raw !== "string" || !raw.trim()) {
    return { ok: false, message: "Enter a GitHub repository URL." };
  }
  const text = raw.trim();
  if (/\s/.test(text)) {
    return { ok: false, message: "Enter a GitHub repository URL." };
  }

  let parsed;
  try {
    parsed = new URL(text);
  } catch {
    return { ok: false, message: "Use an https://github.com/{owner}/{repo} URL." };
  }

  if (parsed.protocol !== "https:") {
    return { ok: false, message: "Use an https://github.com/{owner}/{repo} URL." };
  }
  if (parsed.username || parsed.password) {
    return { ok: false, message: "The repository URL must not include a username or password." };
  }
  if (parsed.port) {
    return { ok: false, message: "The repository URL must not include a port." };
  }
  if (parsed.search) {
    return { ok: false, message: "The repository URL must not include a query string." };
  }
  if (parsed.hash) {
    return { ok: false, message: "The repository URL must not include a fragment." };
  }
  if ((parsed.hostname || "").toLowerCase() !== "github.com") {
    return { ok: false, message: "Only github.com repository URLs are supported." };
  }

  let path = (parsed.pathname || "").replace(/^\/+|\/+$/g, "");
  if (path.endsWith(".git")) path = path.slice(0, -4);
  path = path.replace(/^\/+|\/+$/g, "");
  const parts = path.split("/").filter(Boolean);
  if (parts.length !== 2) {
    return { ok: false, message: "Use an https://github.com/{owner}/{repo} URL." };
  }

  const [owner, name] = parts;
  if (!OWNER.test(owner)) {
    return { ok: false, message: "The repository owner is invalid." };
  }
  if (name === "." || name === ".." || !REPO.test(name)) {
    return { ok: false, message: "The repository name is invalid." };
  }
  return { ok: true, owner, name, display: `https://github.com/${owner}/${name}` };
}
