# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

## [1.1.0] - 2026-05-15
### Added
- Admin can revoke any user's TOTP authenticator app via new POST /auth/admin/revoke-totp
- Role management: promote/demote users between admin and regular via POST /auth/admin/set-role
- Admin page shows role badge (primary admin / admin / user) per user with Make Admin / Make User toggle
- _is_admin() now checks both ADMIN_USER env var and is_admin DB column — promoted users get full admin access
- Fixed https redirect: @auth_login now returns https:// URL (was http://:8080 due to Tailscale TLS termination)

## [1.0.0] - 2026-05-15
### Added
- Initial release — unified auth service extracted from alwayson
- Flask app on port 4001 with Telegram OTP + TOTP authentication
- SQLite storage replacing JSON files (users and OTP codes)
- /auth/check nginx auth_request endpoint with X-Auth-User response header
- /auth/login with ?next= redirect-back support after authentication
- /auth/admin user management panel
- /auth/version JSON version endpoint
- One-time migration script (migrate.py) to import existing alwayson JSON data
- Systemd service and deploy.sh targeting Pi5
