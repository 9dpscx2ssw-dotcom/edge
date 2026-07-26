// Thin fetch wrapper matching the vanilla-JS dashboard's api() contract:
// attaches the control-plane token on writes, prompts for one on 401 and
// retries once, and surfaces the server's {error|message} in thrown errors.
export async function api(path, opts) {
  opts = opts || {};
  const tok = localStorage.getItem("dash_token");
  if (tok) opts.headers = Object.assign({}, opts.headers, { "X-Dashboard-Token": tok });
  let r = await fetch(path, opts);
  if (r.status === 401) {
    const t = window.prompt("Dashboard token required for control actions:");
    if (t) {
      localStorage.setItem("dash_token", t);
      opts.headers = Object.assign({}, opts.headers, { "X-Dashboard-Token": t });
      r = await fetch(path, opts);
    }
  }
  if (!r.ok) {
    let detail = "";
    try { const d = await r.clone().json(); detail = d.error || d.message || ""; } catch (e) { /* not json */ }
    throw new Error(path + " " + r.status + (detail ? ": " + detail : ""));
  }
  return r.json();
}

export const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
