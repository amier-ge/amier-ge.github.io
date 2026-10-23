---
title: "CVE-2026-109618: php2shell"
date: 2026-10-23
categories: ["1-day", "Education"]
tags: ["CVE-2026-109618", "php2shell", "PHP", "RCE", "Memory Corruption"]
summary: "I analyze php2shell (CVE-2026-109618), one of the biggest recent security issues, and reproduce a shell connection on a local PHP website."
---

## 00_Intro

Hello! This time, I'll take a look at **CVE-2026-109618**, also known as **php2shell**.

php2shell is the name used for two vulnerabilities in the PHP engine: CVE-2026-109618 and CVE-2026-109619. This post focuses on CVE-2026-109618, which involves **state corruption after an out-of-memory (OOM) error**. The [official PHP advisory](https://github.com/php/php-src/security/advisories/GHSA-w8hw-w9fx-j79w) confirms that an unauthenticated attacker can achieve remote code execution as the web worker in an Apache mod_php environment.

I'll follow a request from start to finish to explain how an ordinary PHP website can be exposed. At the end, I'll use the storefront in my [local lab repository](https://github.com/amier-ge/php2shell) to demonstrate the exploit and connect to a `www-data` shell.
<br><br>

---

## 01_Root Cause Analysis

### 01-1_PHP Processes the Request Before Running the Page

When a browser sends a request to `index.php`, PHP does not immediately run the first line of the page. It first reads the request body, parses form data, and prepares its internal state. That makes **PHP's input processing** an attack surface even when the page itself has no special vulnerability.

The problem appears when PHP runs out of memory during that preparation. On OOM, PHP uses `longjmp()` to leave the current operation and abort the request. But some internal objects can become reachable by other code **before they are fully initialized**. If execution stops at that point, cleanup code may read incomplete state as though it were valid. [[PHP's explanation of the root cause]](https://github.com/php/php-src/security/advisories/GHSA-w8hw-w9fx-j79w)

```text
HTTP request → PHP parses input → out of memory
                                  ↓
                         longjmp() aborts the work
                                  ↓
                    request ends with incomplete state
                                  ↓
                       cleanup reads invalid state
```
<br>

This is more than sending a large request to slow down the server. **Where execution stops, and how cleanup proceeds afterward, can corrupt memory state.** The official advisory explains that mod_php runs request shutdown even when request startup fails. That shutdown can consume invalid state before any application code has run.

### 01-2_How Can This Become RCE?

An invalid memory reference does not automatically lead to code execution. An attacker must also line up which memory gets reused and how cleanup interprets its contents. Under the right conditions, cleanup can treat attacker-controlled bytes as PHP's internal pointers or function-call data.

PHP stores a variable's value and type in a `zval`, and manages arrays with a `HashTable`. In the demo, repeated input replacements encourage memory reuse. During shutdown, the reused region can then be interpreted as one of these internal structures. **OOM starts the chain; interpreting the wrong data structure is the link to code execution.**

`RCE (Remote Code Execution)` means an external request causes commands to run inside the server process. <br>The official advisory confirms execution with the web worker's privileges. It does not mean the attacker immediately gains `root` access. In the demo, commands run as `www-data`. [[Impact]](https://github.com/php/php-src/security/advisories/GHSA-w8hw-w9fx-j79w)

### 01-3_The Addresses This Exploit Needs and an ASLR Leak

The exploit request in this demo includes **a heap chunk address and the address of libc's `system()`**. ASLR changes these addresses between processes, so values from an earlier run cannot reliably be reused for command execution.

To apply the same approach to a remote server, an attacker would need **an ASLR leak that reveals the live addresses, or an equivalent way to work around address randomization**. The OOM-related memory corruption can occur without knowing those addresses, but turning it into RCE through this particular chain is much harder without them.

My demo does not implement an ASLR leak. Instead, it reads the lab container's addresses with **local GDB and the process memory map**. The shell result is therefore a local reproduction with known addresses, not proof that arbitrary remote servers can be exploited using HTTP requests alone.
<br><br>

---

## 02_How the Attack Chain Comes Together

OOM is only the starting point. The remaining memory state must be used again during shutdown, and the attacker must align both the intended data structure and the relevant addresses before command execution becomes possible. The official advisory also notes that reliability depends on the PHP build, extensions, web server, and memory layout. [[PHP advisory]](https://github.com/php/php-src/security/advisories/GHSA-w8hw-w9fx-j79w)

```text
OOM during input processing
    → incomplete state remains
    → shutdown reads the wrong data structure
    → RCE, if memory addresses and control flow can be controlled
```

One more point! A shell is not the vulnerability itself; it is **one way to demonstrate successful RCE**. The same code-execution ability could lead to reading files or modifying a website, depending on the environment. I'll show how my local demo verifies the chain later in the post.
<br><br>

---

## 03_AI Lowered the Barrier, but the Work Is Still Hard

A [FORTUNE KOREA article](https://www.fortunekorea.co.kr/news/articleView.html?idxno=54461) reports that the security firm Calif used **GPT-5.6 Sol** to find the PHP vulnerability. [OpenAI's account](https://openai.com/index/coordinated-disclosure-of-critical-vulnerabilities/) also distinguishes Calif's use of AI, Wiz's independent discovery, and the PHP maintainers' work on the fixes.

AI has made it faster to trace a large codebase and revisit failed hypotheses. It has clearly **lowered the barrier to entry** for vulnerability research. Even so, understanding memory lifetimes and request order, reproducing the conditions for exploitation, and dealing with constraints such as ASLR remain difficult. AI can find a lead quickly, but confirming that it is a real vulnerability and turning the finding into a safe patch still requires deep expertise.
<br><br>

---

## 04_Patch and Response

According to the [official PHP advisory](https://github.com/php/php-src/security/advisories/GHSA-w8hw-w9fx-j79w), the fixed versions are **8.2.35, 8.3.36, 8.4.27, and 8.5.12**. The patch changes the OOM path so it does not always escape through `longjmp()`, preventing request shutdown from reading incomplete state.

For a production server, checking the PHP version is not enough. Confirm that the Apache or PHP-FPM workers actually handling requests have restarted with the fixed binary. If PHP runs in containers, rebuild or replace the images. **Temporary configuration changes and WAF rules do not replace patching.** Check the related CVE-2026-109619 as well. [[Official CVE-2026-109619 advisory]](https://github.com/php/php-src/security/advisories/GHSA-6wmf-4rv5-p3rp)
<br><br>

---

## 05_Local Lab Environment

Before the demo, it helps to separate the target website from the vulnerable component. **Onda Living** is a fictional PHP storefront with a product list and search feature. It has no command-execution feature, and it escapes search text before displaying it. The flaw is in the **PHP runtime** processing the request, not in the storefront's business logic.

| Component | Role | What it means in this demo |
| --- | --- | --- |
| `website/` | PHP and CSS files for the storefront | A realistic-looking site to run in the lab |
| PHP 8.2.6 + Apache mod_php | Debug environment for reproducing the vulnerability | Shell connection verified on `127.0.0.1:18085` |
| PHP 8.4.26 / 8.4.27 | Vulnerable and patched versions serving the same page | Used for version comparison; shell acquisition was not verified on these two containers |

<br>

The storefront in the screenshot is therefore **a website running on vulnerable PHP**. It is not an exploit of a bug unique to this shop. In a real service, exposure and exploit reliability also depend on the PHP version, SAPI, server configuration, extensions, and memory layout. [[PHP advisory]](https://github.com/php/php-src/security/advisories/GHSA-w8hw-w9fx-j79w)

![Onda Living storefront running in the PHP 8.2.6 lab](/img/posts/php2shell-storefront.png)

*Figure 1. Onda Living served by the local vulnerable PHP container*
<br><br>

---

## 06_Exploit Demo

The lab separates its files into `website/` and `exploit/`. The storefront lives under `website/`; `exploit/` contains the PHP 8.2.6 debug container, address-calibration code, request generator, and shell relay. **Copying only `exp.py` is not enough.** It needs the Docker Compose configuration and the other supporting files.

From the project's `php2shell` directory, run the following in Windows PowerShell. Docker and Python 3.10 or later are required.

```powershell
docker compose up -d
python .\exploit\exp.py
```
<br>

The first command serves the same storefront through PHP 8.4.26 and 8.4.27. The second starts a separate PHP 8.2.6 debug environment and reproduces the shell connection. The demo site is available at `http://127.0.0.1:18085/`; the comparison environments use ports `18080` and `18081`. Enter `exit` to end the shell session.

The `[+]` messages show the sequence: preparing containers, calibrating with GDB, sending the request, and verifying the shell. In the screenshot below, `whoami` returns `www-data`, while `ls` shows the storefront files. That confirms **commands are running with the web worker's privileges**.

The screenshot was taken before I reorganized the folders, so it shows `python .\exp.py`. In the current project layout, use `python .\exploit\exp.py` as shown above.

![php2shell local exploit and www-data shell connection](/img/posts/php2shell-shell.png)

*Figure 2. Running `whoami` and `ls` after connecting to the shell in the local lab*

Memory addresses and PIDs in the screenshot can change between runs. This result was obtained in **my pinned PHP 8.2.6 mod_php debug environment**. It does not claim that the same exploit was run and validated against the PHP 8.4.26 and 8.4.27 comparison containers.

> The demo code and run instructions are in my [GitHub lab repository](https://github.com/amier-ge/php2shell).

<br>

---

## 07_Outro

What stood out to me is that the problem starts **before** the PHP page code runs. The request stops on OOM, but cleanup then trusts incomplete state and can turn that mistake into RCE. Even an ordinary website therefore needs its runtime version and execution environment checked.

As I write this on **October 23, 2026**, **Node2Shell**, a flaw in Node.js's Brotli handling, was also disclosed just days ago! [[Node.js security release]](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases) [[Node2Shell analysis]](https://www.imperva.com/blog/node2shell-from-brotli-data-to-remote-code-execution/) We need to spot these issues in the runtimes beneath our web applications and apply the relevant patches quickly. <br>I hope services still exposed to php2shell get patched as soon as possible!
<br><br>

Thanks for reading all the way through :)
