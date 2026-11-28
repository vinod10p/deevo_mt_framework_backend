# Prompt — Business units (stores) in the React app

Paste this whole file into a **chat whose workspace is `deevoflow_react`**.

A tenant (company) now has **business units**: one root unit, "All stores" (code `COMPANY` by
default), and one or more **stores** (the first is `MAIN`). Staff log in to one store, can switch
store inside the app, and their permissions follow the store. The backend is finished in
`deevo_mt_framework_backend` (branch `dev/bu`); this file is the frontend contract.

Do **not** implement this from `deevo_mt_framework_backend`. Do **not** change the backend.
Adapt §0 to this repo's folder names. Keep the API facts (§3–§8) unchanged.

Backend source of truth:

- `../deevo_mt_framework_backend/mtf/auth/schemas/session.py` (`LoginRequest`,
  `AccessTokenResponse`, `BusinessUnitSwitchRequest`)
- `../deevo_mt_framework_backend/mtf/auth/api/session.py` (login, refresh, switch, `/me`)
- `../deevo_mt_framework_backend/mtf/auth/schemas/user.py` (`UserMeRead`, `MeBusinessUnitRead`)
- `../deevo_mt_framework_backend/mtf/auth/schemas/user_role.py` (`UserRoleCreate`)
- `../deevo_mt_framework_backend/prompts/tenant/BUSINESS_UNIT_BACKEND_PROMPT.md` (decisions)

If OpenAPI does not show `business_unit_code` on the login body, stop: the backend is not
deployed yet. Do not mock it.

---

## 0. Adapt before use

| Placeholder | Meaning | Example (DeevoFlow React) |
|---|---|---|
| `{API_BASE}` | Origin + prefix where `mtf.auth` / `mtf.tenant` are mounted | `http://localhost:8010/api/v1` |
| HTTP client | Authenticated client (Bearer + refresh interceptor) | `src/lib/api.ts` |
| Auth store | Where tokens, user and tenant live | `useAuthStore()` |
| Login page | Existing Company / Email / Password screen | `src/features/auth/LoginPage.tsx` |
| App header | Top bar that shows the user menu | `src/components/AppHeader.tsx` |
| User page | Staff user detail with the role assignment block | the page that lists `/tenant/users/{id}/roles` |
| UI kit | App components | lucide-react + shadcn + TanStack Query + Zod |

Use the login / refresh family the app **already** uses: either the token endpoints
(`/auth/login`, `/auth/refresh`) or the browser endpoints (`/auth/browser/login`,
`/auth/browser/refresh`, refresh token in an HttpOnly cookie). Use the matching switch endpoint
in §5.

---

## 1. Product rules (never violate)

1. **Store is a typed text field.** Login shows Company, **Store**, Email, Password — all plain
   text inputs. No dropdown, no autocomplete, no lookup of stores before login.
2. **Remember the store per device and per company.** Prefill Store with the last store this
   device used for the typed Company. Save it only after a successful staff login or switch.
3. **The backend decides whether a store is needed.** Staff must send one; portal and system
   users don't (the backend ignores it). So do **not** block submit on an empty Store; show the
   server message instead (§4).
4. **The session's store comes from the server**, never from your own state: use the login /
   refresh / switch response and `GET /auth/me`. Never send `business_unit_id` or `tenant_id`
   to the switch endpoint.
5. **Permissions change with the store.** After a switch, refetch `/auth/me` and every query
   that depends on permissions or tenant data before showing the new store's screens.
6. **A refused switch is not an expired session.** The switch endpoint answers **401** with
   "You don't have access to this store". Show that message and stay logged in at the current
   store. The refresh-and-retry / logout interceptor must **not** handle a 401 from the switch
   endpoint that carries this message (an expired-token 401 there is handled as usual).
7. **Hide store UI for single-store companies.** When `multi_store` is `false`, hide the header
   store badge and the switcher. The login Store field stays (staff still type `MAIN`; the
   remembered value fills it in).
8. **Do not invent store codes.** Never default the Store field to `MAIN` in code; only the
   remembered value prefills it.

---

## 2. Screens and flows

| Where | What changes |
|---|---|
| Login page | New **Store** field between Company and Email; prefilled per device; field-level error messages |
| Auth store | Keeps `businessUnit` (`id`, `code`, `name`, `type`) and `multiStore` from login / refresh / switch |
| App header | Store badge (name; "All stores" for the root) + switcher menu when `multiStore` |
| User page → roles | Assign a role **at a store**; list shows the store; revoke at one store |

---

## 3. Login

`POST {API_BASE}/auth/login` (or `/auth/browser/login`). Body — today's fields plus one:

```json
{
  "email": "jane@london-jeweler.com",
  "password": "…",
  "tenant_id": "01J…",
  "created_from": "web",
  "business_unit_code": "MAYFAIR"
}
```

- `business_unit_code`: string, **max 30** chars. Send exactly what the user typed; the backend
  trims it and ignores case (`" mayfair "` works). Omit or send `""` when blank.
- Keep resolving Company → `tenant_id` the way the app does today.

New fields in the response (token **and** browser shapes):

| Field | Type | Notes |
|---|---|---|
| `business_unit_id` | `string \| null` | Session's unit. Portal users: the company root. System users: `null` |
| `business_unit_code` | `string \| null` | Canonical code (e.g. `MAYFAIR`) — save this one, not the typed text |
| `business_unit_name` | `string \| null` | Show in the header |
| `business_unit_type` | `"root" \| "store" \| null` | `root` = "All stores" mode |
| `multi_store` | `boolean` | Company has more than one active store |

The access token also carries a `business_unit_id` claim. Do not read it; use the fields above.

On success for a staff user (`user_scope === "tenant"`), save `business_unit_code` as the
remembered store for this Company on this device (§7).

---

## 4. Login errors

All are `401` with `detail.code === "AUTH_UNAUTHORIZED"`; branch on `detail.message`:

| `detail.message` | Show it on | Meaning |
|---|---|---|
| `Store is required` | Store field | Staff user left Store empty |
| `You don't have access to this store` | Store field | Unknown store, closed store, another company's store, or a store the user may not use — the backend deliberately does not say which |
| `Invalid email or password` | Form (as today) | Wrong credentials |
| anything else | Form (as today) | Existing handling |

A wrong store does **not** count toward the login lockout, so the user can simply retry.

---

## 5. Header store badge and switcher

Data: `GET {API_BASE}/auth/me` now also returns:

```json
{
  "business_unit": { "id": "01J…", "code": "MAYFAIR", "name": "Mayfair", "bu_type": "store" },
  "multi_store": true,
  "business_units": [
    { "id": "01J…", "code": "COMPANY", "name": "London Jeweler", "bu_type": "root" },
    { "id": "01J…", "code": "MAIN", "name": "Main Store", "bu_type": "store" },
    { "id": "01J…", "code": "MAYFAIR", "name": "Mayfair", "bu_type": "store" }
  ]
}
```

- `business_units` is exactly the list the user may switch to, already sorted. The root
  (`bu_type === "root"`) appears only for users allowed "All stores". Portal users get `[]`.
- Badge: `business_unit.name`; for `bu_type === "root"` show **"All stores"** with a read-only
  hint ("Viewing all stores — read-only for store data").
- Switcher: hidden when `multi_store` is false or `business_units.length < 2`. Mark the current
  one. Label the root item "All stores".

Switch request — send the **code** of the chosen item:

| App uses | Endpoint | Response |
|---|---|---|
| Token endpoints | `POST {API_BASE}/auth/session/business-unit` | Same body as `/auth/refresh`: new `access_token` **and** new `refresh_token` + the §3 fields |
| Browser endpoints | `POST {API_BASE}/auth/browser/session/business-unit` | Browser shape (`session_id`, `access_token`, §3 fields); new refresh token is set in the cookie |

```json
{ "business_unit_code": "MAYFAIR" }
```

Send it with the current Bearer access token (the browser variant also needs the app's
`Origin`, as the other browser endpoints do).

On **200**:
1. Replace the access token (and the refresh token for the token family). The old access token
   stops working immediately.
2. Update the auth store's `businessUnit` / `multiStore` from the response.
3. Save the new `business_unit_code` as the remembered store (§7).
4. Reset tenant data: `queryClient.invalidateQueries()` (or `resetQueries`) and refetch
   `/auth/me` — permissions, menus and reports may differ in the new store. Navigate to the
   app home if the current page is no longer allowed.

On **401 "You don't have access to this store"**: toast the message, keep everything as it is.
In the 401 refresh/logout interceptor, skip responses from the switch endpoint whose
`detail.message` is that text (match URL **and** message), so a refused switch never logs the
user out while an expired token there still refreshes as usual.

Only staff may call it: portal and system users get `403 AUTH_FORBIDDEN` — never show them the
switcher.

---

## 6. Refresh

`/auth/refresh` and `/auth/browser/refresh` return the same §3 fields; update the auth store
from them on every refresh.

If the store was closed, or the user lost every role that opened it, refresh ends the session:
`401 "Invalid refresh token"`. Handle it like any refresh failure (go to login). The Store
field will be prefilled with the old store; the user types another one.

---

## 7. Remembered store

- Key: `deevo.store.{companyKey}` in `localStorage`, where `companyKey` is the Company value the
  login page resolves (subdomain), lower-cased. One entry per company.
- Value: the canonical `business_unit_code` from the last successful **staff** login or switch.
  Do not save on failure, for portal users, or for system users.
- Prefill: when the Company field changes to a known company, fill Store from this key if the
  user has not typed in Store yet.
- Never store tokens or ids here — only the code.

---

## 8. Assigning roles at a store (user page)

Existing: `GET/POST {API_BASE}/tenant/users/{user_id}/roles`,
`DELETE {API_BASE}/tenant/users/{user_id}/roles/{role_id}`.

- `POST` body gains optional `business_unit_id`:
  ```json
  { "role_id": "01J…", "business_unit_id": "01J…" }
  ```
  - Omitted: a tenant-wide role (platform `tenant_admin`, `RoleRead.is_tenant_wide === true`) is
    held at the root; any other role at the user's **default store**.
  - Store choices: the admin's own `/auth/me` → `business_units` (admins see every store). Offer
    the root ("All stores") **only** for roles with `is_tenant_wide === true`.
  - Default option in the picker: "User's default store" (send nothing).
- Each `UserRoleRead` row has `business_unit_id`; show the store name next to the role (look it
  up in `business_units`; unknown id → show the id). The same role may appear once per store.
- Revoke at one store: `DELETE …/roles/{role_id}?business_unit_id={id}`. Always send it.

Errors:

| Status / `detail.code` | Message | Show |
|---|---|---|
| `409 AUTH_ROLE_CONFLICT` | This role can only be assigned to a store | Under the store picker |
| `409 AUTH_USER_ROLE_CONFLICT` | User already holds this role | Under the role picker |
| `409 AUTH_USER_ROLE_CONFLICT` | The user holds this role at more than one store; name the business unit | Should not happen if you always send `business_unit_id` |
| `404 TENANT_BUSINESS_UNIT_NOT_FOUND` | Business unit not found | Refetch `/auth/me`; the store was closed |

---

## 9. Acceptance checks

- [ ] Login with Store `mayfair` succeeds; header shows "Mayfair"; reload keeps it (from refresh).
- [ ] Next visit, Store is prefilled with `MAYFAIR` for that Company, and not for another Company.
- [ ] Empty Store (staff) → "Store is required" under Store; wrong Store → "You don't have
      access to this store" under Store; neither clears Email/Password.
- [ ] A portal user logs in with Store empty.
- [ ] Single-store company: no badge, no switcher.
- [ ] Switch to another store: new token in use, `/auth/me` refetched, menus updated, old token
      no longer sent.
- [ ] Refused switch: toast, still logged in, same store, no refresh loop.
- [ ] "All stores" shows as such, with the read-only hint.
- [ ] Role assignment at a store, listing with store names, revoke at one store only.
- [ ] No request to the switch endpoint includes `tenant_id` or `business_unit_id`.

## 10. Out of scope

Store management screens (create / rename / close stores), store filters on reports and
transaction screens, store-owned data rules, portal store UI, and making custom roles
tenant-wide (backend open item Q1).
