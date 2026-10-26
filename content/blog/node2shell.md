---
title: "CVE-2026-111497: Node2Shell"
date: 2026-10-26
categories: ["1-day", "Tooling", "Education"]
tags: ["CVE-2026-111497", "Node2Shell", "Node.js", "Brotli", "RCE"]
summary: "Node2Shell(CVE-2026-111497)을 분석하고, 로컬 Docker의 Express 서버에서 Shell 연결을 재현합니다."
---

## 00_Intro

안녕하세요. 이번 글은 **Node2Shell**([CVE-2026-111497](https://nvd.nist.gov/vuln/detail/cve-2026-111497))이 어떤 조건에서 위험해지는지, 그리고 로컬 Docker에서 하나의 셸 실습을 어떻게 확인했는지 정리합니다. Node.js 프로젝트는 잘못된 Brotli 입력으로 충돌, 메모리 노출, 원격 코드 실행이 가능하다고 공지했습니다. [Node.js 공식 보안 공지](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases)

본 글에서 수행할 실행 시나리오는, 인증 없이 보낸 압축 요청을 Express가 풀다가 취약한 Node.js 디코더에 도달하고, 조건이 맞으면 컨테이너 내부 node 계정의 셸이 현재 연결에 붙는 과정을 담았습니다.
<br><br>

---

## 01_원인과 입력 경로

### 01-1_어떻게 웹 요청이 압축 해제기에 닿는가

Express 5의 express.json()은 Content-Encoding: br인 요청 본문을 지원합니다. 그래서 POST /upload로 들어온 압축 데이터를 라우트 코드가 사용하기 전에 해제할 수 있습니다. 모든 Node HTTP 서버가 요청을 자동으로 Brotli 해제하는 것은 아닙니다. [Express 5 문서](https://github.com/expressjs/expressjs.com/blob/main/src/content/pages/en/guide/migrating-5.mdx)

~~~text
인증 없는 POST /upload
  → Express JSON 본문 파서
  → Node.js Brotli 디코더
  → 메모리 손상
~~~

### 01-2_디코더의 오류

잘못된 Brotli 블록 전환을 영구적인 형식 오류로 처리해야 했지만, 취약한 디코더는 입력이 더 필요한 상태로 취급했습니다. 스트리밍 처리가 계속되면서 8바이트 내부 버퍼 끝을 넘어 쓸 수 있었습니다. 수정 코드는 이 상태를 형식 오류로 구분합니다. [Node.js 원인 설명](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases), [Brotli 수정 커밋](https://github.com/google/brotli/commit/0ed4268a4401abcb4472096340477cf4af7d1a2b)
<br><br>

---

## 02_영향 범위와 제한

공식 수정 버전은 22.23.4, 24.22.1, 26.12.1입니다. 취약 버전을 사용하더라도 신뢰할 수 없는 Brotli 입력을 실제로 해제하는 경로가 있는지 확인해야 합니다. 패치한 런타임으로 다시 빌드하고 실행 중인 컨테이너까지 교체하는 것이 대응의 핵심입니다. [Node.js 공식 공지](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases)

본 실습도 공식 Node.js 24.22.0 Linux x86-64 이미지의 특정 바이너리와 메모리 배치에 맞춘 것임을 참고해주세요!
<br><br>

---

## 03_로컬 실습 구성

Compose에는 shell 서비스 **하나**만 있습니다. 127.0.0.1:18086에서 Express 5.3.0 서버가 POST /upload를 받습니다. Docker 이미지에는 /app/bridge라는 작은 프로그램을 미리 넣었습니다. 취약점으로 이 프로그램이 실행되면 공격 요청의 연결을 /bin/sh의 입출력에 연결합니다.

이는 실습을 위한 기능이며, 이러한 기능이 없는 일반 서버에 같은 payload를 보낸다고 연결형 shell이 생기지는 않습니다. <br>추가적으로 권한은 Docker 내부 node 사용자입니다.

해당 환경 및 PoC는 아래 링크에서 확인 가능합니다.
> [실습 Github Repository](https://github.com/amier-ge/Node2Shell)

### 03-1_PoC 실행 전제

| 전제 | 실습에서 알고 있는 값과 역할 |
| --- | --- |
| 실행 환경 | Docker Desktop의 Linux x86-64 컨테이너, Python 3.10 이상, 루프백 포트 127.0.0.1:18086 |
| 입력 경로 | 인증 없는 `POST /upload`, Express의 `express.json()`, `Content-Encoding: br` 요청 본문 |
| 런타임 | 이미지 다이제스트로 고정한 Node.js 24.22.0과 Express 5.3.0, `UV_THREADPOOL_SIZE=1` |
| 메모리·소켓 프로필 | 특정 바이너리의 메모리 주소와 ROP 가젯 값, 요청 소켓 번호 19를 코드에 고정. 주소 누출이나 자동 프로필 탐지는 없음 |
| 셸 연결 도우미 | `/app/bridge`를 컨테이너에 미리 설치. 실행되면 같은 요청 연결에 `/bin/sh`를 붙임 |

<br>

---
## 04_PoC 실행과 확인

Docker Desktop을 켠 다음 저장소 루트에서 아래 익스 코드를 실행합니다.

~~~powershell
python .\exploit\exp.py
~~~

<br>
`exploit/exp.py`가 컨테이너를 자동으로 빌드/시작하고 이전 실습 컨테이너를 정리합니다. 사이트 응답을 확인한 뒤 잘못된 Brotli 스트림을 나누어 보냅니다. <br>메모리 배치가 맞으면 /app/bridge가 시작되고, PoC는 새 확인 토큰을 같은 연결에서 받아 성공을 판정합니다. 실패할 경우, 실습 프로세스를 새로 시작해서 50회까지 시도합니다.

아래 모습이 exp.py를 실행하여 node 사용자 권한으로 shell을 획득한 모습입니다. 
<br>

<img src="/img/posts/node2shell_poc.png">
<br><br>

---

## 05_점검 도구

최근 매우 많은 취약점들이 터지면서, 실제 보안 담당자들은 자사의 취약점 패치에 많은 시간과 노력을 쏟고 있습니다. 며칠 사이에만 거대한 취약점인 php2shell, node2shell이 공개되었구요.

이러한 노고를 조금이나마 해결해보자, 점검기 하나를 만들어 보았습니다!<br>
이 점검기는 **프로젝트가 취약 범위에 있을 가능성**을 빠르게 추리는 용도입니다. 공격용 요청을 보내거나 RCE를 시험하지 않습니다. 프로젝트 파일에서 Node 버전 단서와 Brotli 해제 가능 코드 경로를 찾고, 실행 중인 컨테이너를 지정하면 그 안의 실제 Node 버전도 확인합니다.

> [Github Repository Link](https://github.com/amier-ge/node2shell-checker)

### 05-1_무엇을 확인하는가

| 확인 항목 | 점검기가 보여주는 근거 |
| --- | --- |
| 프로젝트에 지정된 Node 버전 | Dockerfile의 `FROM node:`, `.nvmrc`, `.node-version`, `package.json`의 `engines.node`, Compose의 `NODE_VERSION` |
| 관련 코드 위치 | `express.json()` 같은 요청 본문 파서, 직접 Brotli 해제 호출, `fetch()` 호출의 파일명·줄 번호·코드 조각 |
| 실행 중인 Node 버전 | `--container`로 지정한 본인 컨테이너에서 `node --version` 실행 결과 |

여기서 **버전 단서**는 프로젝트 파일에 적힌 값이고, **실행 중인 버전**은 컨테이너 안에서 확인한 값입니다. 이미지가 다시 빌드되지 않았거나 배포 구성이 다르면 두 값이 달라질 수 있으므로, 가능하면 둘을 함께 확인하는 편이 좋습니다. 코드 위치도 입력이 실제로 외부에서 도달 가능한지까지 증명하지는 않습니다.

### 05-2_실행 방법

점검기는 PoC와 별도의 저장소이며, PoC 설치·실행이나 두 저장소의 위치에 의존하지 않습니다. 검사할 Node.js 프로젝트의 로컬 폴더만 있으면 파일을 점검할 수 있습니다. Python 3.10 이상이 필요하고, Docker는 실행 중인 컨테이너의 버전까지 확인할 때만 필요합니다.

체커 저장소의 루트에서 PowerShell을 열고 의존성을 설치합니다.

~~~powershell
python -m pip install -r .\requirement.txt
~~~

<br>
프로젝트 파일만 검사하려면 다음과 같이 실행합니다. 경로는 실제 검사할 프로젝트 폴더의 절대 경로로 바꿉니다. <br>이 명령은 Dockerfile 등에 적힌 버전과 관련 코드 위치를 찾으며, 현재 실행 중인 Node 버전은 확인하지 않습니다.

~~~powershell
python .\node2shell_check.py 'C:\path\to\my-node-project'
~~~

<br>
해당 프로젝트의 컨테이너가 이미 실행 중이라면 `--container`에 그 이름을 넣어 실제 Node 버전도 함께 확인할 수 있습니다. <br>프로젝트 파일 없이 컨테이너 버전만 확인하는 것도 가능합니다.

~~~powershell
python .\node2shell_check.py 'C:\path\to\my-node-project' --container my-node-container
python .\node2shell_check.py --container my-node-container
~~~

<br>
PoC 실습은 점검기의 실행 조건이 아닙니다. 실습 환경을 점검해 보고 싶을 때만, 따로 실행한 PoC의 `website` 폴더 경로와 컨테이너 이름을 위 인자에 넣으면 됩니다. 두 저장소가 같은 상위 폴더에 있을 필요는 없습니다. 사용 가능한 옵션과 작성자 표시는 다음 명령으로 확인합니다.

~~~powershell
python .\node2shell_check.py -h
~~~
### 05-3_결과 읽기

아래 사진은 PoC 실습의 프로젝트 폴더와 실행 중인 컨테이너를 지정했을 때의 출력 예시입니다. <br>`Dockerfile.shell:1`은 취약 버전이 적힌 위치, `server.js:7`은 압축 요청 본문을 처리할 수 있는 코드 위치입니다.
<br>

<img src="/img/posts/node2shell_checker.png">
<br>

**높은 위험 가능성**은 실행 버전과 관련 코드가 동시에 확인됐다는 뜻입니다. 공격이 성공했다거나 해당 코드가 외부에서 실제로 호출된다는 판정은 아닙니다. 반대로 **단서 없음**도 안전하다는 보장은 아닙니다! 

점검 후에는 실제 배포 이미지, 인증 여부, 요청의 입력 경로, 보안 수정 적용 여부를 확인해야 합니다. 수정했다면 새 이미지로 재빌드 및 배포한 뒤, 같은 명령으로 실행 버전을 다시 확인할 수 있습니다.

`--json`을 붙이면 `HIGH_EXPOSURE`, `POTENTIAL_EXPOSURE`, `PATCHED_RUNTIME` 같은 판정 코드와 근거를 JSON으로 받을 수 있습니다. 추가 확인이 필요한 결과는 종료 코드 `1`을 반환하므로, 터미널에서 코드 `1`이 보이더라도 점검 명령 자체가 고장 났다는 뜻은 아닙니다.

IP나 URL만으로는 서버 내부의 Node 버전이나 실제 Brotli 입력 경로를 확정할 수 없어 이 도구는 로컬 프로젝트 경로와 본인 컨테이너를 대상으로 합니다. 전체 판정 기준과 다른 실행 옵션은 [Github README](https://github.com/amier-ge/node2shell-checker)를 참고해주세요.
<br><br>

---

## 06_Outro

오늘은 최근 공개된 **Node2Shell**(CVE-2026-111497)의 원인과, 신뢰할 수 없는 Brotli 입력이 Node.js 디코더에 도달할 때 생길 수 있는 위험을 살펴봤습니다.<br>
굉장히 다사다난한 2026년인 것 같습니다. 약 2달 정도 남은 시점에서, 앞으로 또 어떤 취약점이 나올지 궁금하네요..!

그러면 긴 글 읽어주셔서 감사하고, 다른 주제로 또 찾아오겠습니다 :)
