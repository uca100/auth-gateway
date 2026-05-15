# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

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
