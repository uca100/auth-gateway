## Project Reference

- **Project**: auth-gateway
- **Description**: Unified authentication service for all home network apps
- **Port**: 4001 on Pi5 (192.168.40.99)
- **Nginx path**: `/auth` on myweb.tail075174.ts.net
- **Notion Page**: (create on first deploy — Technical / Projects / auth-gateway)

## Architecture

Flask app (Python) running on Pi5 port 4001.
Nginx on tec (.100) uses `auth_request /auth/check` to gate all apps.
SQLite DB at `/home/uri/auth_gateway.db` stores users and TOTP secrets.

### Key routes
- `/auth/login` — login page (public, used by all apps for redirect)
- `/auth/check` — nginx subrequest endpoint (returns 200/401 + X-Auth-User header)
- `/auth/admin` — user management (admin only)
- `/auth/logout` — clear session
- `/auth/version` — JSON version endpoint

## Versioning

Version is defined as `VERSION` constant in `app.py`.
Bump it in `app.py` before deploying and tag the release.

## Deployment

```bash
./deploy.sh
```

Deploys to Pi5, runs one-time migration from alwayson JSON files on first run.

## Environment

Env file: `/usr/local/bin/auth-gateway.env` on Pi5.
See `auth-gateway.env.example` for required vars.
