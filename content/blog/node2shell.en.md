---
title: "CVE-2026-111497: Node2Shell"
date: 2026-10-26
categories: ["1-day", "Tooling", "Education"]
tags: ["CVE-2026-111497", "Node2Shell", "Node.js", "Brotli", "RCE"]
summary: "Analysis of Node2Shell (CVE-2026-111497) and a local Docker PoC demonstrating a shell connection through an Express server."
---

## 00_Intro

Hello! In this post, I examine the conditions under which **Node2Shell** ([CVE-2026-111497](https://nvd.nist.gov/vuln/detail/cve-2026-111497)) becomes dangerous and show how I reproduced a shell in a local Docker environment. The Node.js project reports that malformed Brotli input can cause a crash, expose process memory, or lead to remote code execution. [Node.js security advisory](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases)

The PoC follows an unauthenticated compressed request through Express to the vulnerable Node.js decoder. Under the specific conditions of this Docker environment, it attaches a shell running as the container's `node` user to the same connection.
<br><br>

---

## 01_Root Cause and Input Path

### 01-1_How Does a Web Request Reach the Decompressor?

In Express 5, `express.json()` supports request bodies with `Content-Encoding: br`. As a result, the middleware can decompress a Brotli-encoded `POST /upload` body before the route handler uses it. Node HTTP servers do not automatically decompress every incoming request; the application's input path matters. [Express 5 documentation](https://github.com/expressjs/expressjs.com/blob/main/src/content/pages/en/guide/migrating-5.mdx)

~~~text
Unauthenticated POST /upload
  → Express JSON body parser
  → Node.js Brotli decoder
  → Memory corruption
~~~

### 01-2_The Decoder Bug

An invalid Brotli block switch should have been treated as a permanent format error. The vulnerable decoder instead treated it as a temporary need for more input. Streaming decompression continued, allowing writes past the end of an eight-byte internal buffer. The fix distinguishes this condition as a format error. [Node.js root-cause description](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases), [Brotli fix](https://github.com/google/brotli/commit/0ed4268a4401abcb4472096340477cf4af7d1a2b)
<br><br>

---

## 02_Affected Versions and Limitations

The first fixed Node.js versions are 22.23.4, 24.22.1, and 26.12.1. Even if an application uses an affected version, you still need to determine whether untrusted Brotli input can reach a decompression path. Remediation requires rebuilding with a patched runtime and replacing the running containers. [Node.js security advisory](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases)

This PoC is tailored to the binary and memory layout of a specific official Node.js 24.22.0 Linux x86-64 image.
<br><br>

---

## 03_Local PoC Environment

The Compose file defines one `shell` service. An Express 5.3.0 server receives `POST /upload` on `127.0.0.1:18086`. The Docker image includes a small program at `/app/bridge`. If the exploit starts that program, it connects the attack request's socket to the input and output of `/bin/sh`.

The bridge is specific to this PoC. Sending the same payload to an ordinary vulnerable server without that program does not automatically produce an interactive shell. The shell runs as the `node` user inside Docker.

The environment and PoC are available here:
> [Node2Shell PoC repository](https://github.com/amier-ge/Node2Shell)

### 03-1_PoC Prerequisites and Assumptions

| Requirement | Value or assumption built into this PoC |
| --- | --- |
| Execution environment | Docker Desktop with a Linux x86-64 container, Python 3.10 or newer, and loopback port `127.0.0.1:18086` |
| Input path | Unauthenticated `POST /upload`, Express `express.json()`, and a request body with `Content-Encoding: br` |
| Runtime | Node.js 24.22.0 pinned by image digest, Express 5.3.0, and `UV_THREADPOOL_SIZE=1` |
| Memory and socket profile | Addresses, ROP gadget values, and request socket descriptor 19 are fixed for this binary; the PoC does not leak addresses or discover a profile automatically |
| Shell bridge | `/app/bridge` is installed in the container ahead of time and connects `/bin/sh` to the request socket if execution reaches it |

<br>

---

## 04_Running and Verifying the PoC

Start Docker Desktop, then run the following command from the PoC repository root:

~~~powershell
python .\exploit\exp.py
~~~

`exploit/exp.py` builds and starts the target container automatically, removes orphaned containers from the same Compose project, and checks that the web server responds. It then sends the malformed Brotli stream in two parts. If the memory layout matches, `/app/bridge` starts. The PoC sends a fresh verification token over the same connection and checks the reply before reporting success. If an attempt fails, it restarts the target Node process and tries again, up to 50 attempts by default.

The screenshot below shows `exp.py` obtaining a shell as the container's `node` user. The `whoami` and `id` commands confirm the identity on that connection.

<img src="/img/posts/node2shell_poc.png">
<br><br>

---

## 05_Exposure Checker

Security teams spend considerable time determining which projects need patches after new vulnerabilities are disclosed. php2shell and Node2Shell are two recent examples. To help narrow that work, I built a checker for this issue.

The checker identifies **possible exposure**. It does not send an exploit request or attempt RCE. It searches project files for Node.js version clues and code that may decompress Brotli data. If you also specify a running container, it reads the Node.js version from inside that container.

> [Node2Shell checker repository](https://github.com/amier-ge/node2shell-checker)

### 05-1_What Does It Check?

| Check | Evidence shown by the tool |
| --- | --- |
| Node.js version specified by the project | `FROM node:` in a Dockerfile, `.nvmrc`, `.node-version`, `engines.node` in `package.json`, and `NODE_VERSION` in Compose |
| Candidate code locations | Request body parsers such as `express.json()`, direct Brotli decompression calls, and `fetch()` calls, with file names, line numbers, and code snippets |
| Running Node.js version | The result of `node --version` inside a container you specify with `--container` |

A **version clue** comes from a project file; a **running version** is read from the container. These can differ if an image was not rebuilt or the deployed configuration differs from the source. It is useful to check both when possible. A matching code location does not prove that untrusted input can actually reach it.

### 05-2_How to Run It

The checker is a separate repository. It does not depend on installing or running the PoC, and the two repositories can be stored anywhere. You only need a local directory containing the Node.js project you want to inspect. Python 3.10 or newer is required. Docker is only needed if you choose to check the version inside a running container.

Open PowerShell in the checker repository root and install its dependency:

~~~powershell
python -m pip install -r .\requirement.txt
~~~

To inspect project files, replace the example below with the absolute path to your project. This finds version declarations and candidate code locations, but does not determine the Node.js version currently running in production.

~~~powershell
python .\node2shell_check.py 'C:\path\to\my-node-project'
~~~

If the project's container is already running, provide its name with `--container` to check its Node.js version as well. You can also check a container without scanning project files:

~~~powershell
python .\node2shell_check.py 'C:\path\to\my-node-project' --container my-node-container
python .\node2shell_check.py --container my-node-container
~~~

The PoC environment is optional. If you want to check it, use the path to its `website` directory and the name of its running container. The repositories do not need to share a parent directory. The help command lists all options and shows the author:

~~~powershell
python .\node2shell_check.py -h
~~~

### 05-3_Reading the Result

The screenshot below shows the checker run against the separate PoC project's directory and running container. Its Korean result label means **high likelihood of exposure**: it found both an affected running Node.js version and a candidate code location. `Dockerfile.shell:1` identifies the version declaration; `server.js:7` identifies the request body parser.

<img src="/img/posts/node2shell_checker.png">

This result does **not** prove that an exploit succeeded or that an external request can reach the code. Conversely, a result of **no evidence** does not prove that a system is safe. Verify the deployed image, authentication, input path, and whether a security fix was applied. After patching, rebuild and redeploy the image, then run the checker again to confirm the running version.

With `--json`, the checker returns evidence and assessment codes such as `HIGH_EXPOSURE`, `POTENTIAL_EXPOSURE`, and `PATCHED_RUNTIME`. Results requiring further review return exit code `1`; that does not mean the checker itself failed.

The tool accepts local project paths and containers you control. An IP address or URL alone cannot establish a server's internal Node.js version or actual Brotli input path. For the full assessment criteria and other options, see the [checker README](https://github.com/amier-ge/node2shell-checker).
<br><br>

---

## 06_Outro

Today, we looked at the root cause of the recently disclosed **Node2Shell** (CVE-2026-111497) and the risks that arise when untrusted Brotli input reaches the Node.js decoder.<br>
It has been quite an eventful year for security. With about two months left in 2026, I wonder what other vulnerabilities we will see!

Thank you for reading this long post. I will be back with another topic :)
