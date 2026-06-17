# Authentication

## Glossary

| Abbreviation | Full Form |
|---|---|
| JWT | JSON Web Token |
| CGISESSID | CGI Session ID (Koha's session cookie identifier) |
| HS256 | HMAC with SHA-256 (JWT signing algorithm) |
| HMAC | Hash-based Message Authentication Code |
| AES-GCM | Advanced Encryption Standard — Galois/Counter Mode |
| TTL | Time To Live |
| OPAC | Online Public Access Catalog |
| ILS | Integrated Library System |
| DB | Database |

---

## 1. Overview

```
┌──────────┐   JWT (access/refresh)   ┌──────────────┐   CGISESSID cookie   ┌──────────┐
│  Mobile  │ ◄──────────────────────► │   Backend    │ ◄──────────────────► │  Koha    │
│   App    │                          │  (language   │                      │  OPAC    │
└──────────┘                          │   agnostic)  │                      └──────────┘
                                       └──────┬───────┘
                                               │
                                      ┌────────┴────────┐
                                      │  Database (DB)  │
                                      │  ┌────────────┐ │
                                      │  │ roll_no →  │ │
                                      │  │ CGISESSID  │ │
                                      │  │ name       │ │
                                      │  │ creds(enc) │ │
                                      │  │ refresh_   │ │
                                      │  │ token_hash │ │
                                      │  └────────────┘ │
                                      └─────────────────┘
```

The authentication system has two layers:

- **JWT layer** — authenticates the mobile client with the backend. Tokens are short-lived and statelessly verifiable.
- **CGISESSID layer** — authenticates the backend with Koha ILS. The session cookie is obtained by proxying credentials and is never exposed to the mobile client.

---

## 2. Login Flow

```
Mobile                  Backend                     Koha
  │                        │                         │
  │── POST /login ────────►│                         │
  │   {roll, pass}         │── POST opac-user.pl ───►│
  │                        │   {userid, password}     │
  │                        │◀── CGISESSID cookie ────│
  │                        │                         │
  │                        │── Store in DB ─────────►│
  │                        │   {roll: {CGISESSID,    │
  │                        │    creds(enc), name}}   │
  │                        │                         │
  │◀── {access_token,      │                         │
  │      refresh_token}────┤                         │
```

Steps:

1. Mobile app sends roll number and password to `POST /login` as JSON (`application/json`) or form-encoded (`application/x-www-form-urlencoded`).

2. Backend validates that both fields are present and non-empty.

3. Backend creates a form-encoded POST request to Koha's `opac-user.pl` with:
   - `userid` — roll number
   - `password` — plaintext password
   - `koha_login_context` — set to `opac`

4. Koha responds. A **non-200 status code** indicates login success (Koha returns a redirect on successful auth). A **200 status** means credentials are invalid.

   If Koha is unreachable (connection error, timeout) or returns a 5xx, the backend retries up to `MAX_KOHA_LOGIN_RETRIES` (default 3) times with exponential backoff (1s, 2s, ...) before giving up with `502 Bad Gateway`. A 200 response (wrong credentials) is never retried -- it's a definitive answer, not a transient failure.

5. Backend extracts the `CGISESSID` cookie from Koha's response headers. This is the session token for all subsequent Koha API calls.

6. Backend makes a follow-up GET request to `opac-user.pl` with the CGISESSID cookie to fetch the user's display name from Koha's HTML response.

7. Backend stores the session in the database:

   | Field | Description |
   |---|---|
   | `roll_no` | Primary key — the user's roll number |
   | `CGISESSID` | Koha session cookie value |
   | `name` | User's display name from Koha |
   | `creds(enc)` | AES-GCM encrypted credentials (only if "remember me" is enabled) |
   | `refresh_token_hash` | Bcrypt hash of the current refresh token |

8. Backend generates and returns two JWTs:
   - **Access token** — TTL: 15 minutes
   - **Refresh token** — TTL: 7 days

---

## 3. JWT Structure

A JWT is composed of three base64url-encoded segments separated by dots:

```
<Header>.<Payload>.<Signature>
```

### Header

```json
{
  "alg": "HS256",
  "typ": "JWT"
}
```

- `alg` — signing algorithm (HMAC with SHA-256)
- `typ` — token type (always `JWT`)

### Payload (Claims)

| Claim | Type | Description | Example |
|---|---|---|---|
| `sub` | string | Subject — the user's roll number (unique identifier) | `"B23CS001"` |
| `name` | string | User's display name from Koha | `"John Doe"` |
| `role` | string | User role for authorization | `"student"` |
| `type` | string | Token purpose — `access` or `refresh` | `"access"` |
| `iat` | number | Issued at (Unix timestamp in seconds) | `1712345678` |
| `exp` | number | Expires at (Unix timestamp in seconds) | `1712346578` |

### Signature

The signature is computed as:

```
HMACSHA256(
  base64urlEncode(header) + "." + base64urlEncode(payload),
  secret-key
)
```

The secret key is loaded from an environment variable and never hardcoded. The signature ensures the token cannot be tampered with — any modification to header or payload invalidates the signature.

### Example

Decoded access token:

```json
{
  "alg": "HS256",
  "typ": "JWT"
}
.
{
  "sub": "B23CS001",
  "name": "John Doe",
  "role": "student",
  "type": "access",
  "iat": 1712345678,
  "exp": 1712346578
}
```

Encoded form:

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9
.
eyJzdWIiOiJCMjNDUzAwMSIsIm5hbWUiOiJKb2huIERvZSIsInJvbGUiOiJzdHVkZW50IiwidHlwZSI6ImFjY2VzcyIsImlhdCI6MTcxMjM0NTY3OCwiZXhwIjoxNzEyMzQ2NTc4fQ
.
signature
```

---

## 4. Refresh Token Strategy

### Two-Token Model

| Token | TTL | Storage (Mobile) | Purpose |
|---|---|---|---|
| Access token | 15 minutes | In-memory / app variable | Authorize API requests |
| Refresh token | 7 days | Keychain / Keystore | Obtain new access tokens |

Short access token TTL limits the damage window if a token is intercepted. The refresh token allows seamless re-authentication without asking the user for credentials again.

### Refresh Flow

```
Mobile                          Backend
  │                                │
  │── POST /auth/refresh ────────►│
  │   {refresh_token}             │
  │                                │── Validate refresh token signature + expiry
  │                                │── Look up session in DB by sub claim
  │                                │── Compare provided token hash against stored hash
  │                                │── Invalidate old refresh token (rotation)
  │                                │── Generate new access + refresh tokens
  │◀── {access_token,              │
  │      refresh_token}────────────┤
```

### Token Rotation

Every time a refresh token is used:

- The old refresh token is invalidated (removed from DB)
- A new refresh token is issued
- Its hash is stored in the database

### Reuse Detection

If a revoked refresh token is submitted:

- The session is likely compromised
- All tokens and sessions for that user are invalidated
- The user must log in again with credentials

### Remember Me

When "remember me" is enabled during login:

- Backend encrypts the user's **password** (not the roll number -- that's already the row's primary key) using AES-GCM with a server-side secret key (`CREDS_ENCRYPTION_KEY`)
- The encrypted blob is stored in `creds_enc` alongside the session
- If `CREDS_ENCRYPTION_KEY` isn't configured on the server, `remember_me` is silently ignored (a warning is logged) rather than failing the login -- it's an optional feature, not a hard dependency
- A plain login (`remember_me: false`, or omitted) clears any previously stored `creds_enc` for that user

When a Koha-authenticated call detects a stale CGISESSID, the re-authentication helper:
  1. Decrypts the stored password
  2. Re-authenticates with Koha (reusing the same retry logic as `/login`)
  3. Updates the stored CGISESSID
  4. Retries the original request once

This is transparent to the mobile client. **Implementation note:** this re-authentication plumbing (`reauthenticate()` / `call_with_koha_retry()` in `app/domains/auth/service.py`) exists now, but nothing calls it yet -- the Koha-backed protected endpoints in the table below (`/user/checkouts`, `/user/renew`, etc.) haven't been built. Those endpoints should wrap their Koha calls with `call_with_koha_retry()` once implemented.

---

## 5. Protected Routes

| Endpoint | Method | Auth Required | Description |
|---|---|---|---|
| `/login` | POST | No | Authenticate with Koha, receive tokens |
| `/auth/refresh` | POST | No (requires refresh token) | Rotate tokens |
| `/auth/logout` | POST | Yes | Delete session, invalidate all tokens |
| `/user/checkouts` | GET | Yes | List currently borrowed books |
| `/user/renew` | POST | Yes | Renew a checked-out book |
| `/user/holds` | POST | Yes | Place a hold on a book |
| `/user/holds/{id}` | DELETE | Yes | Cancel a hold |
| `/user/fines` | GET | Yes | View outstanding fines |
| Search, detail, availability | GET | No | Public — no authentication required |

Protected routes use a middleware layer:

```
Request → Extract token from Authorization header (Bearer scheme)
       → Validate signature + expiry
       → Extract claims (sub, role)
       → Look up CGISESSID from DB
       → Forward to handler with user context
       → If invalid/missing → 401 Unauthorized
```

---

## 6. Authorization Rules

### Access Rules

| Role | Search / Browse | Book Details | View Checkouts | Renew | Holds | Fines |
|---|---|---|---|---|---|---|
| **Student** | ✅ | ✅ | ✅ (own) | ✅ (own) | ✅ | ✅ (own) |

- **Students** can only access their own borrowed books, renewals, holds, and fines.

### Enforcement

- Role is extracted from the `role` claim in the JWT
- Middleware compares the required role for the endpoint against the token's role
- Unauthorized access returns `403 Forbidden`

---

## 7. Security Considerations

| Threat | Mitigation |
|---|---|
| **JWT interception** | Short TTL (15 min). Access tokens stored in memory only, never persisted. Use HTTPS for all communication. |
| **Refresh token theft** | Rotation on every use. Reuse detection invalidates all sessions for the user. Stored in OS Keychain/Keystore on mobile. |
| **CGISESSID leakage** | Never transmitted to the mobile client. Stored server-side only. Exchanged only between backend and Koha over internal network. |
| **Password interception** | All API calls over HTTPS. Passwords never logged, never returned in responses. |
| **Brute force login** | Rate limiting on `/login` — 5 attempts per minute per IP address. |
| **JWT secret compromise** | Loaded from environment variable (not hardcoded). Rotatable. Use separate secrets for development/staging/production. |
| **Algorithm confusion attack** | Backend explicitly pins the signing algorithm to HS256. Rejects tokens with `alg: "none"` or asymmetric algorithms. |
| **Stored credential compromise** | Encrypted with AES-GCM using a server-side key from environment. Decrypted only in-memory for re-authentication. Database access alone is insufficient to recover plaintext passwords. |
| **Koha session expiry** | Backend detects stale CGISESSID (Koha returns login page instead of data). If stored credentials exist, auto re-authenticate and retry. Otherwise, return `401` prompting re-login. |
| **Logout** | `POST /auth/logout` deletes the session record from the database, invalidating all tokens immediately. CGISESSID is abandoned. |
| **Token replay** | Access tokens are short-lived. Refresh tokens use rotation + reuse detection. `jti` (unique token ID) can be added for server-side blacklisting if needed. |
