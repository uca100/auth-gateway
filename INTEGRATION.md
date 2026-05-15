# auth-gateway — Integration Guide

How to protect a new app with auth-gateway.

## How it works

auth-gateway runs on Pi5 port 4001. nginx uses its `/auth/check` endpoint as an
`auth_request` subrequest before proxying any protected app. If the user has no
valid session, nginx redirects them to `/auth/login`, which handles Telegram OTP
and TOTP authentication. After login, the user lands on the original destination.

```
Browser → nginx
            │  auth_request /auth/check
            └─→ auth-gateway (:4001)
                    ├─ 200 + X-Auth-User header   → nginx proxies to the app
                    └─ 401                         → nginx redirects to /auth/login?next=<original-url>
```

Sessions are cookie-based (Flask signed cookie, 4-hour TTL). The cookie is domain-wide,
so a single login grants access to all gated apps.

---

## Protecting a new app in nginx

Add two lines to the app's `location` block in `nginx-proxy/sites/apps.conf`:

```nginx
location /my-new-app {
    auth_request     /auth/check;       # gate with auth-gateway
    error_page 401 = @auth_login;       # redirect unauthenticated users to login
    proxy_pass       http://192.168.40.99:PORT;
    proxy_set_header Host $host;
    # ... rest of proxy headers
}
```

The `@auth_login` named location and `/auth/check` internal location are already
defined globally in `apps.conf` — do not add them again.

**Do not gate:** the `/auth` location block itself (login page must be public).

### If your app needs to know the logged-in username

Add these two lines to the location block:

```nginx
location /my-new-app {
    auth_request       /auth/check;
    error_page 401   = @auth_login;
    auth_request_set   $auth_user $upstream_http_x_auth_user;   # capture from subrequest
    proxy_set_header   X-Auth-User $auth_user;                  # forward to upstream app
    proxy_pass         http://192.168.40.99:PORT;
    # ...
}
```

Then read it in your app:

**Python/Flask:**
```python
username = request.headers.get("X-Auth-User", "")
```

**Node.js/Express:**
```js
const username = req.headers["x-auth-user"] ?? "";
```

**Next.js API route:**
```ts
const username = req.headers["x-auth-user"] as string ?? "";
```

---

## SSE / long-lived connections

`auth_request` fires once at connection time, not on every event — this is correct
behaviour. Add it to SSE location blocks the same way as regular blocks.

```nginx
location /my-app/api/stream {
    auth_request       /auth/check;
    error_page 401   = @auth_login;
    proxy_pass         http://192.168.40.99:PORT;
    proxy_http_version 1.1;
    proxy_set_header   Connection "";
    proxy_buffering    off;
    proxy_cache        off;
    proxy_read_timeout 300s;
}
```

---

## Adding users

Visit `/auth/admin` (admin only). Users added here can log in to all gated apps.

No per-app access control — the model is: **authenticated = access to everything**.

---

## Auth-gateway endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/login` | GET | Login page (public) |
| `/auth/check` | GET | nginx subrequest endpoint (internal only) |
| `/auth/logout` | GET | Clear session |
| `/auth/admin` | GET | User management (admin only) |
| `/auth/revoke-totp` | POST | Reset 2FA for current user |
| `/auth/version` | GET | `{"version": "1.0.0", "service": "auth-gateway"}` |

---

## Checklist for a new protected app

- [ ] App deployed and reachable on Pi5 at a port
- [ ] `location /my-app` block added to `nginx-proxy/sites/apps.conf` with `auth_request`
- [ ] App port opened in ufw: `sudo ufw allow from 192.168.40.100 to any port PORT proto tcp`
- [ ] nginx deployed: `cd ~/projects/nginx-proxy && ./deploy.sh`
- [ ] App added to myweb dashboard: `cd ~/projects/myweb && ./deploy.sh`
- [ ] Architecture reference updated: `~/projects/architecture/ARCHITECTURE.md`
