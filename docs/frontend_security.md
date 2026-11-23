# Frontend security tasks — deevoflow_react

Prepared from the deevo_mt_framework_backend security review (branch `feature/claude`,
2026-11-21). Backend details: [security.md](security.md).

Two parts:

- **Part A** — changes needed because the backend now behaves differently (new 401 / 403 / 429
  responses). Do these together with, or right after, the backend release.
- **Part B** — security issues found in deevoflow_react itself during the same review.

Paths below are relative to the deevoflow_react repo. Versions and line references are as of
the review date; re-check them before starting.

**Order of work:** B1 (exposed login session) first — it is the only item that is already an
exposure today. Then A1–A4 with the backend release, then the rest of Part B.

---

## Part A — Adapt to the new backend behaviour

### What changed in the API (summary)

| Endpoint / situation | Before | Now |
|---|---|---|
| Any request with an access token from **before** the release (no `sid` / `typ`) | 200 | **401** once — the existing refresh-on-401 flow recovers |
| Any request after **logout**, or with an access token **replaced by a refresh** | 200 until expiry | **401** |
| Any request after the user is **deactivated** or **removed from the tenant** | 200 until expiry | **401** (`detail.message` = `"Membership inactive"` or `"Session expired or revoked"`) |
| `POST /api/v1/auth/refresh` after removal from the tenant, or when the tenant is suspended | 200 (new tokens) | **401** — the session is ended |
| `POST /api/v1/auth/login` after too many wrong passwords from this IP | 401 (and the account locked for everyone after 5) | **429** `{"detail": {"code": "AUTH_RATE_LIMITED", ...}}` + `Retry-After: <seconds>` header |
| `GET /api/v1/audit/logs[/{id}]` as a tenant **member** or non-admin portal user | 200 | **403** `AUTH_FORBIDDEN` |
| `POST /api/v1/auth/refresh` with an **access** token | 401 | 401 (unchanged, now explicit) |
| Refresh tokens issued before the release | — | Still accepted (users stay signed in) |

### Tasks

| # | Task | Details | Done when |
|---|---|---|---|
| **A1** | **Handle 429 on the login page** | In `src/features/auth/hooks/useLogin.ts` / `LoginPage.tsx`, when the login call fails with status 429, show "Too many sign-in attempts. Try again in N minutes." using the `Retry-After` header (seconds); disable the submit button until then. Don't retry automatically. | Wrong password 6× from one browser → friendly message with a countdown, no generic error |
| **A2** | **Log out when refresh "succeeds" but the request still fails** | `src/lib/api.ts`: after a refresh, the original request is retried once (`_retry`). If that retry is **401 again**, the user has lost access (removed / deactivated) — call `redirectToLogin()` instead of just rejecting. Without this, a removed staff member keeps refreshing and seeing errors. *(The backend now also refuses `/refresh` for removed staff and suspended tenants, so the refresh itself fails and the existing flow already redirects to `/login`. A2 still covers any other case where access is revoked between refresh and retry.)* | Remove a logged-in staff user from the tenant → their next action lands on `/login` |
| **A3** | **Treat 403 on audit screens as "not allowed", not as an error** | If any screen calls `/api/v1/audit/logs`, hide it for non-admins (use `role` / `permissions` from `/auth/me`) and show a "not permitted" state on 403 | Member sees no audit menu; direct URL shows "not permitted" |
| **A4** | **Verify the one-time 401 after deploy is invisible** | `src/lib/api.ts` already queues requests and refreshes on 401 — confirm in staging that users signed in before the release are not bounced to `/login` (their refresh tokens are still valid) | Staging check passes |
| **A5** | **Tell the backend team whether you need CORS credentials** | The app authenticates with `Authorization: Bearer` only; at review time it did not use `withCredentials` (axios) or `credentials: "include"` (fetch in `src/features/chat/api/chatApi.ts`). If that is still true, the backend can set `DEEVO_CORS_ALLOW_CREDENTIALS=false` | Confirmed in writing to backend |
| **A6** | **Production API origin must be https** | The backend now refuses `http://` origins in production. Make sure the deployed frontend URL is `https://…` and is listed in the backend's `DEEVO_ALLOWED_ORIGINS` exactly (no path, no trailing `/`) | Prod preflight succeeds |

A1 depends on the backend exposing `Retry-After` to the browser (security.md §2.2, task B4).
Until that is deployed, fall back to a generic "try again in 15 minutes".

Sketch for A1 + A2 (adapt to the existing code):

```ts
// useLogin.ts — in onError / catch
if (axios.isAxiosError(err) && err.response?.status === 429) {
  const seconds = Number(err.response.headers['retry-after']) || 900
  setLockedUntil(Date.now() + seconds * 1000) // drive a countdown + disabled button
  return
}

// api.ts — response interceptor, before the refresh logic
if (error.response?.status === 401 && original._retry) {
  // Refreshed already and still unauthorized: access was revoked.
  redirectToLogin()
  return Promise.reject(error)
}
```

---

## Part B — Security issues in deevoflow_react

| # | Severity | Issue | Where | Fix |
|---|---|---|---|---|
| **B1** | 🔴 High | **A logged-in session and a test password are committed to git.** `playwright/.auth/user.json` (tracked since the first commit) contains a full saved login for tenant `lg` — access **and refresh** token. `playwright/auth.setup.ts` hard-codes that account's email and password. Other live specs already read credentials from env vars; this one does not | `playwright/.auth/user.json`, `playwright/auth.setup.ts` | 1) **Revoke** that user's sessions on the backend (`POST /api/v1/auth/logout-all` as that user, or deactivate/reactivate) — revocation now takes effect immediately. 2) **Change that account's password.** 3) `git rm --cached playwright/.auth/user.json` and add `playwright/.auth/` to `.gitignore`. 4) Read credentials from env vars (e.g. `E2E_EMAIL`, `E2E_PASSWORD`). 5) Optional: purge from history (`git filter-repo`) — the tokens are dead after step 1 either way |
| **B2** | 🟠 High | **Vulnerable runtime dependencies** (`npm audit`, review date): `axios` ≤ 1.19.0 (prototype pollution → Basic-auth injection), `react-router` ≤ 7.18.1 (open redirect via backslash in `<Link>` / `useNavigate`), `zod` < 4.6.6 (memory exhaustion). `shadcn` (a CLI) is in `dependencies` and pulls in most of the other 29 findings | `package.json` | `npm audit fix`; bump `axios`, `react-router-dom`, `zod`; move `shadcn` to `devDependencies`; re-run `npm audit --omit=dev` |
| **B3** | 🟠 Medium | **Tokens in `localStorage`, no Content-Security-Policy.** Access and refresh tokens persist under `deevoflow-auth`; any XSS (own code or a dependency) can steal the refresh token. There is no `staticwebapp.config.json`, so no CSP, no clickjacking protection, no `Referrer-Policy` | `src/store/authStore.ts`, deploy config | Add security headers via `staticwebapp.config.json` (template below). Longer term: refresh token in an `HttpOnly; Secure; SameSite=Strict` cookie — needs backend work, coordinate first |
| **B4** | 🟠 Medium | **React Query Devtools ship to production** — anyone can browse every cached API response | `src/main.tsx` | Render only when `import.meta.env.DEV` (lazy-import so it is not bundled) |
| **B5** | 🟡 Low | **Mock Service Worker is deployed** (`dist/mockServiceWorker.js`). Not started outside mocks, but should not be served | `public/mockServiceWorker.js` | Exclude from production build (move worker setup to a dev-only path, or delete it from `dist` in the build step) |
| **B6** | 🟡 Low | **Tenant switch keeps the previous tenant's data in memory.** On tenant mismatch, `clearAuth()` runs without clearing the React Query cache or reloading | `src/router/guards.tsx`, `src/store/authStore.ts` | Call `queryClient.clear()` inside `clearAuth` (or do a full reload) |
| **B7** | 🟡 Low | **CI uses old, unpinned actions** (`actions/checkout@v3`, `actions/github-script@v6`) and an unnecessary `npm install @actions/core@1.6.0` step | `.github/workflows/*` | Pin actions to commit SHAs at current versions; drop the extra install step |
| **B8** | ℹ️ Check | **Logout** clears local state even if the API call fails — correct. With backend #4 the server now really revokes the session | `src/features/auth/hooks/useLogout.ts` | No change; keep calling the API before clearing |

### B3 — `staticwebapp.config.json` starting point

Replace `https://api.example.com` with the real API origin and test in staging — a too-strict
CSP breaks the app, so start with `Content-Security-Policy-Report-Only` if unsure.

```json
{
  "navigationFallback": { "rewrite": "/index.html" },
  "globalHeaders": {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob:; connect-src 'self' https://api.example.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains"
  }
}
```

### B4 — devtools only in development

```tsx
// src/main.tsx
const ReactQueryDevtools = import.meta.env.DEV
  ? lazy(() =>
      import('@tanstack/react-query-devtools').then((m) => ({ default: m.ReactQueryDevtools })),
    )
  : () => null
```

---

## Already fine (no action)

- No `dangerouslySetInnerHTML`, `eval`, or `innerHTML`; chat messages render as plain text.
- CSV export neutralises spreadsheet formulas (`csvCell`); the Excel export writes values, not formulas.
- Refresh uses a separate axios instance and a queue (no 401 loop) and re-checks the user scope.
- No open-redirect parameters (`returnTo` / `next`) found.
- `.env.local` is git-ignored and only holds the API URL.

## Checklist

- [ ] B1 session revoked, password changed, auth file untracked, credentials from env
- [ ] A1 login 429 message with countdown
- [ ] A2 second 401 after refresh → login
- [ ] A3 audit screens: admins only, 403 handled
- [ ] A4 staging: existing users not logged out by the release
- [ ] A5 confirmed to backend whether CORS credentials are needed
- [ ] A6 production frontend is https and listed exactly in `DEEVO_ALLOWED_ORIGINS`
- [ ] B2 dependencies upgraded, `npm audit --omit=dev` clean
- [ ] B3 security headers deployed (CSP tested in staging)
- [ ] B4 devtools dev-only
- [ ] B5 mock worker not deployed
- [ ] B6 query cache cleared on auth reset
- [ ] B7 CI actions pinned
