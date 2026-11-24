(() => {
  "use strict";

  const get = id => document.getElementById(id);
  const body = get("body");
  const fieldset = get("edit-fields");
  const status = get("status");
  let csrf = "";
  let current = { kind: "post", number: 0, lang: "ko", revision: 0 };
  let dirty = false;
  let working = false;
  let library = [];
  let previewTimer;
  let previewVersion = 0;

  function report(text, error = false) {
    status.textContent = text;
    status.classList.toggle("error", error);
  }

  async function api(path, data, options = {}) {
    const headers = {};
    if (csrf) headers["X-CSRF-Token"] = csrf;
    if (data && !(data instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      data = JSON.stringify(data);
    }
    const response = await fetch("/api/editor/" + path, {
      method: data === undefined && !options.post ? "GET" : "POST",
      cache: "no-store",
      headers,
      body: data,
    });
    if (response.status === 204) return null;
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = payload.error || "요청을 처리하지 못했습니다. 다시 시도하세요.";
      throw new Error(message);
    }
    return payload;
  }

  function initializeGoogle(config) {
    const message = get("login-message");
    message.textContent = "승인된 Google 계정으로 로그인하세요.";
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onerror = () => { message.textContent = "Google 로그인 버튼을 불러오지 못했습니다."; };
    script.onload = () => {
      google.accounts.id.initialize({
        client_id: config.clientId,
        nonce: config.nonce,
        ux_mode: "popup",
        use_fedcm_for_button: true,
        callback: async ({ credential }) => {
          message.textContent = "Google 계정 확인 중";
          try {
            await api("login", { credential });
            await enter(await api("session"));
          } catch (error) {
            message.textContent = error.message;
          }
        },
      });
      google.accounts.id.renderButton(get("google-button"), {
        theme: "outline", size: "large", text: "signin_with", locale: "ko",
      });
    };
    document.head.appendChild(script);
  }

  async function enter(session) {
    if (!session.signedIn) {
      if (session.configured) initializeGoogle(session);
      else get("login-message").textContent = "Google 로그인이 아직 설정되지 않았습니다.";
      return;
    }
    csrf = session.csrf;
    const records = await api("posts");
    setCategories(records.categories);
    library = records.posts;
    await openDocument("post", 0, "ko");
    get("login").hidden = true;
    get("workspace").hidden = false;
    get("logout").hidden = false;
  }

  function setCategories(categories) {
    const group = get("categories");
    for (const category of categories) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = category;
      label.append(input, document.createTextNode(category));
      group.append(label);
    }
  }

  async function reloadLibrary() {
    library = (await api("posts")).posts;
    drawLibrary();
  }

  function drawLibrary() {
    const list = get("posts");
    list.replaceChildren();
    for (const { number, languages } of library) {
      const row = document.createElement("li");
      const button = document.createElement("button");
      const title = languages.ko?.title || languages.en?.title || "제목 없음";
      const languagesLabel = Object.keys(languages).map(lang => lang.toUpperCase()).sort().join(" · ");
      const hasDraft = Object.values(languages).some(record => record.draft);
      const meta = document.createElement("span");
      meta.className = "post-meta";
      meta.textContent = "#" + number + " · " + languagesLabel + (hasDraft ? " · 초안 있음" : "");
      button.type = "button";
      button.textContent = title;
      button.setAttribute("aria-current", String(current.kind === "post" && current.number === number));
      button.append(meta);
      button.addEventListener("click", () => openDocument("post", number, current.lang).catch(() => {}));
      row.append(button);
      list.append(row);
    }
  }

  function canLeave() {
    return !dirty || window.confirm("저장하지 않은 변경이 있습니다. 이 문서를 나갈까요?");
  }

  async function openDocument(kind, number, lang) {
    if (working || !canLeave()) return;
    working = true;
    fieldset.disabled = true;
    try {
      const query = new URLSearchParams({ kind, number, lang });
      fill(await api("document?" + query));
      report("");
    } catch (error) {
      report(error.message, true);
      throw error;
    } finally {
      fieldset.disabled = false;
      working = false;
    }
  }

  function fill(data) {
    const { kind, number, lang } = data;
    current = data;
    get("title").value = data.title || "";
    get("summary").value = data.summary || "";
    get("date").value = data.date || "";
    get("tags").value = (data.tags || []).join(", ");
    body.value = data.body;
    get("post-fields").hidden = kind !== "post";
    for (const option of get("categories").querySelectorAll("input")) {
      option.checked = (data.categories || []).includes(option.value);
    }
    get("editor-heading").textContent = kind === "about" ? "About 편집" : number ? "글 #" + number : "새 글";
    for (const button of get("languages").querySelectorAll("button")) {
      button.setAttribute("aria-pressed", String(button.dataset.lang === lang));
    }
    const published = get("published-link");
    const route = kind === "about" ? "/about/" : "/blog/" + number + "/";
    published.href = (lang === "en" ? "/en" : "") + route;
    published.hidden = !data.published;
    dirty = false;
    drawLibrary();
    queuePreview();
  }

  function fields() {
    return {
      kind: current.kind, number: current.number, lang: current.lang, revision: current.revision,
      title: get("title").value, summary: get("summary").value, date: get("date").value,
      tags: get("tags").value.split(",").map(tag => tag.trim()).filter(Boolean),
      categories: [...get("categories").querySelectorAll("input:checked")].map(input => input.value),
      body: body.value,
    };
  }

  async function save(action) {
    if (working) return;
    const data = fields();
    if (action === "publish" && !window.confirm("이 버전을 공개 사이트에 게시할까요?")) return;
    working = true;
    fieldset.disabled = true;
    report(action === "publish" ? "사이트 빌드 중" : "초안 저장 중");
    try {
      fill(await api("document/" + action, data));
      report(action === "publish" ? "게시했습니다." : "초안을 저장했습니다.");
      await reloadLibrary().catch(() => {});
    } catch (error) {
      report(error.message, true);
    } finally {
      fieldset.disabled = false;
      working = false;
    }
  }

  function queuePreview() {
    clearTimeout(previewTimer);
    const version = ++previewVersion;
    previewTimer = setTimeout(async () => {
      try {
        const result = await api("preview", { body: body.value });
        if (version === previewVersion) get("preview").innerHTML = result.html;
      } catch {
        if (version === previewVersion) get("preview").textContent = "미리보기를 불러올 수 없습니다.";
      }
    }, 230);
  }

  function insert(text) {
    const start = body.selectionStart;
    body.setRangeText(text, start, body.selectionEnd, "end");
    body.dispatchEvent(new Event("input", { bubbles: true }));
    body.focus();
  }

  async function upload(files) {
    if (working || !files.length) return;
    working = true;
    report("파일 업로드 중");
    try {
      for (const file of files) {
        const data = new FormData();
        data.append("file", file);
        const media = await api("upload", data);
        const alt = file.name.replace(/[\[\]\r\n]/g, "").slice(0, 100);
        const markup = media.type.startsWith("video/")
          ? '<video controls preload="metadata" src="' + media.url + '"></video>'
          : "![" + alt + "](" + media.url + ")";
        insert("\n\n" + markup + "\n\n");
      }
      report("파일을 본문에 추가했습니다.");
    } catch (error) {
      report(error.message, true);
    } finally {
      working = false;
    }
  }

  function format(action) {
    const selected = body.value.slice(body.selectionStart, body.selectionEnd);
    const fence = String.fromCharCode(96).repeat(3);
    const snippets = {
      heading: "\n## " + (selected || "제목") + "\n",
      bold: "**" + (selected || "굵게") + "**",
      italic: "*" + (selected || "기울임") + "*",
      quote: "\n> " + (selected || "인용문") + "\n",
      list: "\n- " + (selected || "항목") + "\n",
      code: "\n" + fence + "\n" + (selected || "코드") + "\n" + fence + "\n",
      link: "[" + (selected || "링크 제목") + "](https://)",
      table: "\n| 제목 | 제목 |\n| --- | --- |\n| 값 | 값 |\n",
    };
    if (snippets[action]) insert(snippets[action]);
  }

  get("new-post").addEventListener("click", () => openDocument("post", 0, "ko").catch(() => {}));
  get("edit-about").addEventListener("click", () => openDocument("about", 0, current.lang).catch(() => {}));
  get("languages").addEventListener("click", event => {
    const lang = event.target.closest("button")?.dataset.lang;
    if (lang && lang !== current.lang) openDocument(current.kind, current.number, lang).catch(() => {});
  });
  get("document-form").addEventListener("submit", event => event.preventDefault());
  get("document-form").addEventListener("input", () => { dirty = true; });
  body.addEventListener("input", queuePreview);
  get("save").addEventListener("click", () => save("save"));
  get("publish").addEventListener("click", () => save("publish"));
  get("toolbar").addEventListener("click", event => format(event.target.closest("button")?.dataset.insert));
  get("choose-media").addEventListener("click", () => get("media").click());
  get("media").addEventListener("change", event => {
    upload([...event.target.files]);
    event.target.value = "";
  });
  body.addEventListener("paste", event => {
    const files = [...event.clipboardData.files];
    if (!files.length) return;
    event.preventDefault();
    upload(files);
  });
  body.addEventListener("dragover", event => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    body.classList.add("dragging");
  });
  body.addEventListener("dragleave", () => body.classList.remove("dragging"));
  body.addEventListener("drop", event => {
    body.classList.remove("dragging");
    if (!event.dataTransfer.files.length) return;
    event.preventDefault();
    upload([...event.dataTransfer.files]);
  });
  get("logout").addEventListener("click", async () => {
    if (working || !canLeave()) return;
    try {
      await api("logout", undefined, { post: true });
      dirty = false;
      location.reload();
    } catch (error) { report(error.message, true); }
  });
  addEventListener("beforeunload", event => {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });

  api("session").then(enter).catch(error => { get("login-message").textContent = error.message; });
})();
