---
slug: "13"
aliases: ["/blog/siem-project-sigma-rules/"]
commentTerm: "blog/siem-project-sigma-rules/"
title: "Windows 로그를 위한 Sigma 룰 구축"
date: 2026-11-22
categories: ["Project", "Tooling", "Education"]
tags: ["Sigma", "Windows", "Sysmon", "Elasticsearch", "MITRE ATT&CK"]
summary: "Windows 로그에서 조사할 이벤트를 찾기 위해, 단일 이벤트 중심의 Sigma 룰 54개를 설계하고 DEDALE 로그로 검증한 과정을 정리합니다."
---

## Intro

앞선 글에서는 Sigma Alert를 시작점으로 Qwen이 Elasticsearch의 관련 로그를 조회하고, 마지막에 HTML 보고서를 만드는 구조를 정리했습니다.

이번에는 그 시작점이 되는 **Sigma 룰**을 구축했습니다.<br>
룰이 Alert를 만들지 못하면 LLM도 실행되지 않기 때문에, 어떤 이벤트를 조사 대상으로 넘길지 정하는 과정이 생각보다 중요했습니다.

처음부터 목표를 ‘DEDALE 공격을 전부 외워서 잡는 룰’로 두지는 않았습니다. 특정 호스트명이나 파일명을 넣으면 현재 데이터에서는 잘 동작하겠지만, 다른 Windows 환경에서는 사용하기 어려워집니다.

그래서 이번 룰팩은 아래 질문을 기준으로 만들었습니다.

> Windows 환경에서 공격의 시작점이 될 만한 단일 이벤트를 찾고,<br>
> 나머지 맥락은 LLM이 직접 조사하게 만들 수 있을까?

최종적으로 Windows 단말에서 사용할 수 있는 **단일 이벤트 Sigma 룰 54개**를 구성했고, DEDALE의 침해 구간과 정상 구간으로 동작을 확인했습니다.
<br><br>

---

## 00_룰의 역할 정하기

이 프로젝트에서 Sigma의 역할은 공격 전체를 완성하는 것이 아닙니다.

하나의 이벤트에서 의심스러운 조건을 찾고, Qwen이 조사를 시작할 수 있는 Alert를 만드는 역할입니다.

```text
Windows 로그
  → Sigma 단일 이벤트 룰
  → Alert 원본 로그 + 탐지 룰
  → Qwen 조사 시작
  → Elasticsearch 관련 로그 조회
  → 실제 공격 여부 판단
```

예를 들어 PowerShell에서 다운로드 명령이 발견됐다고 해보겠습니다. Sigma는 해당 명령을 빠르게 찾을 수 있지만, 파일이 실제로 생성됐는지와 이후 실행됐는지까지 한 이벤트에서 알 수는 없습니다.

이때 Sigma가 파일 생성과 네트워크 연결, 자식 프로세스까지 미리 묶어주면 탐지 결과는 풍부해집니다. 하지만 LLM은 이미 완성된 공격 흐름을 전달받게 되고, 직접 관련 로그를 찾을 이유가 줄어듭니다.

그래서 역할을 다음처럼 분리했습니다.

| 구성 | 담당하는 판단 |
|---|---|
| Sigma | 지금 조사할 가치가 있는 이벤트인가? |
| Qwen + MCP | 앞뒤 로그를 연결했을 때 실제 침해로 볼 수 있는가? |
| 보안 담당자 | 근거를 확인하고 실제 대응할 것인가? |

이 기준 덕분에 룰이 복잡해지는 것을 줄이고, 룰 단독 성능과 LLM 조사 성능도 따로 비교할 수 있었습니다.
<br><br>

---

## 01_룰의 기준 잡기

룰의 기본 구조와 필드명은 [Sigma Rule Specification](https://sigmahq.io/sigma-specification/specification/sigma-rules-specification.html)을 기준으로 했습니다. 탐지 아이디어는 [SigmaHQ Windows Rules](https://github.com/SigmaHQ/sigma/tree/master/rules/windows)와 [MITRE ATT&CK Enterprise Techniques](https://attack.mitre.org/techniques/enterprise/)를 참고했습니다.

다만 SigmaHQ의 Windows 룰을 전부 가져오지는 않았습니다.

룰이 많아도 필요한 로그가 수집되지 않으면 동작하지 않습니다. Defender 로그를 사용한 룰인데 데이터에 Defender 채널이 없다면, 그 룰은 미탐한 것이 아니라 애초에 **적용할 수 없는 룰**에 가깝습니다.

따라서 공격 기법보다 먼저 현재 환경에서 확인 가능한 로그를 정리했습니다.

| 로그 | 룰에서 사용하는 정보 |
|---|---|
| Sysmon Event 1 | 프로세스 경로, 명령행, 부모 프로세스, 사용자 |
| Sysmon Event 10 | LSASS와 같은 프로세스 접근 |
| PowerShell 4104 | Script Block, 다운로드·난독화·AMSI 우회 문자열 |
| Security 4697 | 서비스 설치 |
| Security 4698 | 예약 작업 생성 |
| Security 4720 | 사용자 계정 생성 |
| Security 4732 | 로컬 그룹 구성원 추가 |

그다음 실제 Windows 로그에서 조사 가치가 높은 행위를 골랐습니다.

- PowerShell 다운로드와 난독화
- 사용자 쓰기 가능 경로의 실행 파일
- Run Key, 서비스, 예약 작업 기반 지속성
- LSASS 및 레지스트리 Hive 접근
- 방화벽·로그·보안 기능 비활성화
- 원격 관리 도구를 통한 실행
- 사용자 데이터 압축과 외부 전송
- 복구 방해와 대량 파일 삭제

중요한 것은 특정 악성코드의 이름이 아니라, 공격자가 Windows에서 반복해서 사용하는 **행위의 모양**을 찾는 것이었습니다.
<br><br>

---

## 02_단일 이벤트 시드 룰

이번 룰팩은 모든 YAML이 이벤트 하나를 판단하도록 만들었습니다. 시간창이나 여러 이벤트의 순서를 Sigma 룰 안에서 미리 결합하지 않았습니다.

```yaml
logsource:
  category: process_creation
  product: windows

detection:
  selection_image:
    Image|endswith: '\powershell.exe'
  selection_download:
    CommandLine|contains:
      - 'Invoke-WebRequest'
      - 'DownloadString'
      - 'Start-BitsTransfer'
  condition: selection_image and selection_download
```

위 예시는 PowerShell 프로세스의 명령행에서 네트워크 다운로드 명령을 찾는 형태입니다. 이 룰만으로 다운로드 성공이나 악성 파일 실행까지 단정하지 않습니다.

Alert가 발생하면 Qwen이 같은 호스트와 인접 시간대에서 다음 증거를 조회합니다.

```text
PowerShell Alert
   ├─ 부모 프로세스는 무엇인가?
   ├─ 파일 생성 Event 11이 있는가?
   ├─ 네트워크 연결 Event 3이 있는가?
   └─ 생성된 파일이 Event 1로 실행됐는가?
```

이 구조를 선택한 이유는 세 가지입니다.

1. 어떤 이벤트가 왜 탐지됐는지 설명하기 쉽습니다.
2. Sigma가 찾은 사실과 LLM이 추가로 추론한 내용을 분리할 수 있습니다.
3. DEDALE이 아닌 다른 Windows 로그에도 룰을 옮기기 쉽습니다.

로그인 실패 반복이나 짧은 시간 안의 여러 계정 변경처럼 횟수와 시간창이 중요한 행위는 이번 룰에 억지로 넣지 않았습니다. 이런 행위는 추후 별도의 상관분석 계층에서 다루는 편이 더 적절하다고 판단했습니다.
<br><br>

---

## 03_표준 Sigma와 Elasticsearch 연결

룰 YAML에는 `EventID`, `Image`, `CommandLine`, `ParentImage`, `ScriptBlockText`처럼 Sigma에서 사용하는 Windows 필드를 유지했습니다.

하지만 실제 DEDALE 로그는 Winlogbeat ECS에 가까운 JSON입니다. 따라서 탐지기가 룰을 Elasticsearch 쿼리로 바꿀 때 필드를 변환하도록 했습니다.

| Sigma 필드 | Elasticsearch 필드 |
|---|---|
| `EventID` | `event.code` |
| `Image` | `process.executable.keyword` |
| `CommandLine` | `process.command_line.keyword` |
| `ParentImage` | `process.parent.executable.keyword` |
| `ScriptBlockText` | `powershell.file.script_block_text.keyword` |
| `OriginalFileName` | `winlog.event_data.OriginalFileName` |
| `Company` | `winlog.event_data.Company` |

룰마다 DEDALE 필드를 직접 넣지 않고 공통 변환 계층을 둔 이유는, 룰의 의미와 저장소의 필드 구조를 분리하기 위해서입니다. 나중에 다른 Winlogbeat 인덱스를 사용하더라도 매핑 계층만 조정하면 같은 Sigma 룰을 재사용할 수 있습니다.
<br><br>

### 03-1_대소문자 처리

Windows 경로와 프로세스 이름은 대소문자가 달라도 같은 의미인 경우가 많습니다.

```text
PowerShell.EXE
powershell.exe
POWERSHELL.exe
```

하지만 Elasticsearch 문자열 조건이 대소문자를 구분하면 같은 행위를 놓칠 수 있습니다. 그래서 모든 Sigma 문자열 비교에 `case_insensitive: true`를 적용했습니다.

Windows 경로의 `\`도 Elasticsearch wildcard 문법과 충돌하지 않도록 별도로 이스케이프했습니다.
<br><br>

### 03-2_긴 명령행 처리

DEDALE 인덱스에서는 긴 명령행의 `.keyword` 값이 저장되지 않는 경우가 있었습니다. PowerShell Script Block이나 긴 인코딩 명령은 256자를 넘기기 쉬워, `.keyword`만 조회하면 중요한 이벤트가 빠질 수 있습니다.

이를 보완하기 위해 두 검색 방식을 함께 사용했습니다.

```text
짧은 명령행 → .keyword + 대소문자 무시 wildcard
긴 명령행   → 원본 text 필드 + match_phrase 보조 조회
```

또한 프로세스 생성 Event 1과 PowerShell Script Block Event 4104는 서로 다른 로그소스로 분리했습니다.

- 프로세스 명령행: `category: process_creation`
- PowerShell Script Block: `category: ps_script`

두 이벤트를 한 룰에 섞지 않아 다른 Sigma 백엔드에서도 로그소스의 의미가 유지되도록 했습니다.
<br><br>

---

## 04_54개 룰팩 구성

먼저 공격의 주요 시작점을 다루는 19개 룰을 구성했습니다. 이후 Windows 환경에서 필요한 실행, 지속성, 자격 증명 접근, 횡적 이동, 방어 회피, 수집과 영향 행위를 추가하여 최종 **54개 룰**로 확장했습니다.

심각도 구성은 다음과 같습니다.

| 심각도 | 개수 | 의미 |
|---|---:|---|
| Critical | 7 | 자격 증명 덤프, 복구 방해처럼 즉시 확인할 행위 |
| High | 24 | 악성 가능성이 높은 실행·지속성·방어 회피 행위 |
| Medium | 22 | 정상 관리에도 쓰여 주변 로그 확인이 필요한 행위 |
| Low | 1 | 빈도가 높아 LLM의 문맥 확인이 필요한 행위 |
| 합계 | 54 | Windows 단일 이벤트 시드 룰 |

ATT&CK 전술은 아래 범위를 다룹니다. 하나의 룰이 여러 전술에 포함될 수 있습니다.

| 전술 | 대표 탐지 행위 |
|---|---|
| Execution | PowerShell, WMIC, Office 자식 프로세스, 스크립트 실행 |
| Persistence | Run Key, 서비스, 예약 작업, IFEO |
| Privilege Escalation | 관리자 그룹 추가, 접근성 기능 하이재킹 |
| Defense Evasion | LOLBin, AMSI 우회, 로그 삭제, 타임스탬프 변경 |
| Credential Access | LSASS 접근, Registry Hive·NTDS 덤프 |
| Discovery | 계정·네트워크 정보 수집 |
| Lateral Movement | 관리 공유, RDP, 원격 서비스와 관리 도구 |
| Collection | 파일 압축과 수집 결과 스테이징 |
| Command and Control | 원격 파일 전송과 C2 형태의 실행 인자 |
| Exfiltration | `curl` 등을 이용한 파일 업로드 |
| Impact | 복구 방해와 대량 파일 삭제 |

룰을 54개로 늘리면서도 비슷한 조건을 무작정 복제하지 않았습니다. 하나의 이벤트가 여러 룰에 걸릴 수는 있지만, 각 룰은 서로 다른 조사 관점을 제공해야 합니다.

예를 들어 사용자 임시 경로에서 실행된 파일은 ‘사용자 쓰기 가능 경로 실행’에 걸릴 수 있고, C2 형태의 인자가 있다면 ‘네트워크 명령 옵션’에도 걸릴 수 있습니다. 같은 이벤트라도 전자는 실행 위치를, 후자는 명령행을 조사 근거로 제공합니다.
<br><br>

---

## 05_정상 로그와 침해 로그로 튜닝하기

룰 문법이 맞는 것과 실제 로그에서 유용하게 동작하는 것은 다릅니다. 그래서 침해 구간뿐 아니라 정상 기준일과 별도의 Validation 구간을 함께 사용했습니다.

### 05-1_DEDALE 침해 구간

```text
시간: 2025-01-06 09:00 ~ 14:00 UTC
구성: 정상 역할 PC 5대 + 침해 PC 1대
이벤트: 878,146건
```

실행 결과는 다음과 같습니다.

| 항목 | 결과 |
|---|---:|
| Sigma Alert | 9건 |
| 고유 원본 이벤트 | 6건 |
| 정상 역할 PC의 Alert | 0건 |
| 침해 PC의 Alert | 9건 |
| Ground Truth 악성 프로세스 직접 탐지 | 5/6 |
| 직접 탐지 재현율 | 83.33% |

Alert가 9건이지만 고유 원본 이벤트가 6건인 이유는 일부 이벤트가 서로 다른 관점의 룰에 함께 탐지됐기 때문입니다.

직접 탐지하지 못한 악성 프로세스 한 건은 해당 구간에 Sysmon Event 1이 없었습니다. 대신 같은 명령의 PowerShell Event 4104가 Alert로 발생했기 때문에, Qwen이 이후 PID와 자식 프로세스를 조회할 수 있는 시작점은 남아 있었습니다.
<br><br>

### 05-2_정상 기준일

같은 6대 PC의 정상 기준일 5시간도 검사했습니다.

```text
시간: 2025-01-03 09:00 ~ 14:00 UTC
이벤트: 799,318건
Alert: 0건
```

정상 `sc.exe start wuauserv`처럼 관리 과정에서 나오는 이벤트는 원격 서비스 생성 조건과 구분했습니다. LSASS 접근 룰도 Windows 부팅 과정의 정상 시스템 프로세스를 제외하고, 실제 의심스러운 SourceImage를 판단하도록 조정했습니다.

여기서 Alert가 0건이었다고 해서 모든 회사 환경에서 오탐이 0이라는 뜻은 아닙니다. DEDALE의 해당 6대·5시간 구간에서는 불필요한 Alert가 관측되지 않았다는 의미입니다.
<br><br>

### 05-3_별도 Validation

침해 구간만 계속 보면서 룰을 맞추면 해당 데이터에만 과하게 맞을 수 있습니다. 그래서 다음 날의 별도 구간도 확인했습니다.

```text
시간: 2025-01-07 08:00 ~ 09:00 UTC
이벤트: 25,254건
Ground Truth 악성 프로세스: 1건
직접 탐지: 1건
```

Validation의 악성 프로세스는 사용자 쓰기 가능 경로에서 실행됐고 게시자와 원본 파일 정보가 없었습니다. `Unidentified Executable Started From User-Writable Directory` 룰이 이를 탐지했습니다.

특정 파일명이나 DEDALE IP를 넣지 않고도 행위와 경로 조건으로 다른 구간의 악성 프로세스를 찾을 수 있음을 확인했습니다.
<br><br>

---

## 06_탐지 결과를 Qwen으로 넘기기

룰에 일치한 이벤트는 다음 내용을 가진 Alert로 변환됩니다.

```json
{
  "alert_id": "sigma-alert-id",
  "rule": {
    "id": "rule-id",
    "title": "PowerShell Process With Network Retrieval Command",
    "level": "medium"
  },
  "event": {
    "index": "dedale-winlogbeat-6pc-5h-20250106",
    "id": "elasticsearch-document-id",
    "timestamp": "2025-01-06T10:01:05Z",
    "host": "CLIENT2.breach.local"
  },
  "matched_on": ["process.command_line"]
}
```

Alert에는 룰 제목뿐 아니라 Elasticsearch 원본 문서 ID, 호스트, 시각과 일치 필드를 넣었습니다. Qwen은 이 값을 시작점으로 원본 문서와 관련 로그를 조회합니다.

빠른 검증이 필요하면 룰만 실행할 수 있습니다.

```bash
cd /home/amier_ge/siem/elk/bin
./sigma_replay_detector.py --siem
```

Alert 발생 후 Qwen 조사와 보고서까지 이어가려면 `--speed`를 사용합니다.

```bash
cd /home/amier_ge/siem/elk/bin
./sigma_replay_detector.py --speed
```

룰 탐지와 LLM 조사를 분리해 둔 덕분에, 룰 조건을 수정할 때마다 27B 모델을 다시 실행하지 않고도 먼저 Alert 수와 원본 이벤트를 빠르게 확인할 수 있었습니다.
<br><br>

---

## 07_해석할 때 주의할 점

현재 결과를 ‘Windows 공격을 83.33% 탐지한다’고 일반화하면 안 됩니다.

83.33%는 DEDALE의 특정 6대·5시간 구간에서, Ground Truth로 확인 가능한 악성 프로세스 6개 중 5개가 Sigma Alert의 원본 프로세스로 직접 잡혔다는 뜻입니다.

또한 54개 룰 중 DEDALE 구간에서 실제 양성 표본을 확인할 수 있었던 룰은 일부입니다. LSASS 덤프, 계정 생성, 원격 서비스, 복구 방해처럼 해당 구간에 실행되지 않은 행위는 구조와 변환만 검증한 상태입니다.

실제 조직에 적용한다면 아래 항목을 추가로 고려해야 합니다.

- 소프트웨어 배포 도구와 관리 스크립트
- 백업 및 보안 제품의 정상 행위
- IT 지원용 관리자 계정과 관리 서버
- 조직별 허용 PowerShell 명령
- Sysmon, PowerShell Logging, 고급 감사 정책의 수집 여부

룰의 목적은 악성을 확정하는 것이 아니라 **조사할 가치가 있는 이벤트를 놓치지 않고 넘기는 것**입니다. 정상 관리와 공격 양쪽에서 가능한 이벤트는 Qwen이 주변 로그를 확인한 뒤 판단하도록 남겨두었습니다.
<br><br>

---

## 08_Outro

이번 단계에서는 Windows 로그를 대상으로 단일 이벤트 Sigma 룰 54개를 구성했습니다.

룰을 만들면서 가장 중요했던 것은 개수보다 경계를 정하는 일이었습니다. Sigma는 빠르고 설명 가능한 시작점을 만들고, 여러 이벤트의 관계와 실제 침해 여부는 Qwen이 Elasticsearch를 조회하면서 판단하도록 역할을 나눴습니다.

또한 표준 Sigma 필드와 Elasticsearch 매핑을 분리하고, 대소문자와 긴 명령행을 보완해 특정 DEDALE 값에 의존하지 않도록 했습니다.

다음 단계에서는 이 Alert와 Qwen 조사 결과를 보안 담당자가 한 화면에서 검토할 수 있도록, 실제 관제 플랫폼 형태로 구성해보겠습니다.

읽어주셔서 감사합니다! 🙂
