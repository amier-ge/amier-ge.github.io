(() => {
  "use strict";

  const get = id => document.getElementById(id);
  const root = document.documentElement;
  try {
    root.dataset.theme = localStorage.getItem("amierge-theme") === "light" ? "light" : "dark";
  } catch {}
  get("copyright-year").textContent = new Date().getFullYear();
  get("nav-burger").addEventListener("click", event => {
    const open = get("nav-links").classList.toggle("open");
    event.currentTarget.setAttribute("aria-expanded", String(open));
  });
  const body = get("body");
  const fieldset = get("edit-fields");
  const status = get("status");
  let csrf = "";
  let current = { kind: "post", number: 0, lang: "ko", revision: 0 };
  let dirty = false;
  let working = false;
  let library = [];
  let previewTimer;
  let previewRequest;
  let previewVersion = 0;
  const previewStyles = new Set([
    "color", "background-color", "font-weight", "font-style", "text-decoration",
    "text-align", "display", "tab-size",
  ]);

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
      signal: options.signal,
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
    const button = get("google-button");
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
      function renderButton() {
        if (get("login").hidden) return;
        button.replaceChildren();
        google.accounts.id.renderButton(button, {
          type: "standard", theme: root.dataset.theme === "light" ? "outline" : "filled_black",
          size: "large", text: "signin_with", shape: "rectangular", logo_alignment: "left",
          locale: "ko", width: Math.min(320, Math.floor(button.getBoundingClientRect().width)),
        });
      }
      renderButton();
      new MutationObserver(renderButton).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
      message.textContent = "";
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
    for (const { number, languages, hidden } of library) {
      const row = document.createElement("li");
      const button = document.createElement("button");
      const title = languages.ko?.title || languages.en?.title || "제목 없음";
      const languagesLabel = Object.keys(languages).map(lang => lang.toUpperCase()).sort().join(" · ");
      const hasDraft = Object.values(languages).some(record => record.draft);
      const meta = document.createElement("span");
      meta.className = "post-meta";
      meta.textContent = "#" + number + " · " + languagesLabel
        + (hidden ? " · 비공개" : "") + (hasDraft ? " · 초안 있음" : "");
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
    get("post-hidden").checked = Boolean(data.hidden);
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
    published.hidden = !data.public;
    updatePublishLabel();
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
      hidden: get("post-hidden").checked,
      visibilityRevision: current.visibilityRevision,
      body: body.value,
    };
  }

  function updatePublishLabel() {
    const isPost = current.kind === "post";
    get("publish").textContent = isPost && get("post-hidden").checked ? "비공개 적용"
      : isPost && current.currentlyHidden ? "다시 공개" : "게시";
  }

  async function save(action) {
    if (working) return;
    const data = fields();
    const hide = data.kind === "post" && data.hidden;
    const confirmation = hide ? "이 글의 한국어·영어 버전을 공개 사이트에서 숨길까요?"
      : current.currentlyHidden ? "이 글을 다시 공개할까요?" : "이 버전을 공개 사이트에 게시할까요?";
    if (action === "publish" && !window.confirm(confirmation)) return;
    working = true;
    fieldset.disabled = true;
    report(action === "publish" ? "사이트 빌드 중" : "초안 저장 중");
    try {
      fill(await api("document/" + action, data));
      report(action === "publish" ? (hide ? "비공개로 전환했습니다." : "게시했습니다.") : "초안을 저장했습니다.");
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
    previewRequest?.abort();
    const version = ++previewVersion;
    const panel = get("preview-panel");
    if (panel.hidden) return;
    const markdown = body.value;
    if (!markdown.trim()) {
      panel.replaceChildren();
      return;
    }
    previewTimer = setTimeout(async () => {
      const request = new AbortController();
      previewRequest = request;
      try {
        const result = await api("preview", { body: markdown }, { signal: request.signal });
        if (version === previewVersion) {
          const preview = document.createElement("template");
          preview.innerHTML = result.html;
          for (const heading of preview.content.querySelectorAll("[id]")) {
            heading.id = "editor-render-" + heading.id;
          }
          for (const link of preview.content.querySelectorAll("a[href]")) {
            const href = link.getAttribute("href");
            if (href.startsWith("#")) {
              link.setAttribute("href", "#editor-render-" + href.slice(1));
            } else {
              link.target = "_blank";
              link.rel = "noopener noreferrer";
            }
          }
          // Apply only Goldmark/Chroma's presentation properties through
          // CSSOM; the editor's CSP continues to reject inline style markup.
          for (const element of preview.content.querySelectorAll("[style]")) {
            const declarations = element.getAttribute("style").split(";");
            element.removeAttribute("style");
            for (const declaration of declarations) {
              const separator = declaration.indexOf(":");
              const property = declaration.slice(0, separator).trim();
              if (separator > 0 && previewStyles.has(property)) {
                element.style.setProperty(property, declaration.slice(separator + 1).trim());
              }
            }
          }
          panel.replaceChildren(preview.content);
        }
      } catch {
        if (version === previewVersion) panel.textContent = "미리보기를 불러올 수 없습니다.";
      } finally {
        if (previewRequest === request) previewRequest = undefined;
      }
    }, 320);
  }

  function insert(text, placeholder = "") {
    const start = body.selectionStart;
    body.setRangeText(text, start, body.selectionEnd, "end");
    body.focus();
    const offset = placeholder ? text.indexOf(placeholder) : -1;
    if (offset !== -1) body.setSelectionRange(start + offset, start + offset + placeholder.length);
    body.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function applyHeading() {
    const cursor = body.selectionStart;
    const start = cursor ? body.value.lastIndexOf("\n", cursor - 1) + 1 : 0;
    const next = body.value.indexOf("\n", cursor);
    const end = next === -1 ? body.value.length : next;
    const title = body.value.slice(start, end).replace(/^ {0,3}#{1,6}(?:[ \t]+|$)/, "").trim();
    body.setSelectionRange(start, end);
    insert("## " + (title || "제목"), title ? "" : "제목");
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
    if (action === "heading") {
      applyHeading();
      return;
    }
    const selected = body.value.slice(body.selectionStart, body.selectionEnd);
    const codeSample = selected || "코드";
    const longestFence = (codeSample.match(/\x60+/g) || [])
      .reduce((length, ticks) => Math.max(length, ticks.length), 2);
    const fence = String.fromCharCode(96).repeat(longestFence + 1);
    const linkURL = "https://example.com";
    const quote = (selected || "인용문").split("\n").map(line => "> " + line).join("\n");
    const list = (selected || "항목").split("\n").map(line => line ? "- " + line : "").join("\n");
    const snippets = {
      bold: ["**" + (selected || "굵게") + "**", selected ? "" : "굵게"],
      italic: ["*" + (selected || "기울임") + "*", selected ? "" : "기울임"],
      quote: ["\n\n" + quote + "\n\n", selected ? "" : "인용문"],
      list: ["\n\n" + list + "\n\n", selected ? "" : "항목"],
      code: ["\n\n" + fence + "\n" + codeSample + "\n" + fence + "\n\n", selected ? "" : "코드"],
      link: ["[" + (selected || "링크 제목") + "](" + linkURL + ")", linkURL],
      table: ["\n\n| 제목 | 제목 |\n| --- | --- |\n| 값 | 값 |\n\n", "제목"],
    };
    if (snippets[action]) insert(...snippets[action]);
  }

  get("new-post").addEventListener("click", () => openDocument("post", 0, "ko").catch(() => {}));
  get("edit-about").addEventListener("click", () => openDocument("about", 0, current.lang).catch(() => {}));
  get("languages").addEventListener("click", event => {
    const lang = event.target.closest("button")?.dataset.lang;
    if (lang && lang !== current.lang) openDocument(current.kind, current.number, lang).catch(() => {});
  });
  get("document-form").addEventListener("submit", event => event.preventDefault());
  get("document-form").addEventListener("input", () => { dirty = true; });
  get("post-hidden").addEventListener("change", updatePublishLabel);
  get("toggle-preview").addEventListener("click", event => {
    const panel = get("preview-panel");
    panel.hidden = !panel.hidden;
    get("preview-title").hidden = panel.hidden;
    event.currentTarget.setAttribute("aria-expanded", String(!panel.hidden));
    event.currentTarget.textContent = panel.hidden ? "미리보기 열기" : "미리보기 닫기";
    queuePreview();
  });
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
