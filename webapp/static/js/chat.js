(function () {
if (window.__acuChatInitialized) {
    return;
}
window.__acuChatInitialized = true;

/**
 * ACU AI Chatbot — Frontend JavaScript
 *
 * Multi-conversation: each conversation has its own DOM panel,
 * AbortController, and loading state. Switching tabs never cancels streams.
 */

const ENABLE_RENDER_TEST_INJECTION = false;
const REQUEST_TIMEOUT_MS = 70000;

// ── Multi-conversation state ─────────────────────────────
// Map<id, { id, title, isLoading, isSending, abortController, container }>
const conversations = new Map();
let activeConversationId = null;
let cachedConversations = []; // last API result, used to re-render sidebar
const upgradingConversationIds = new Set();

// ── DOM Elements ─────────────────────────────────────────
const chatForm = document.getElementById("chatForm");
const questionInput = document.getElementById("questionInput");
const sendBtn = document.getElementById("sendBtn");
const stopBtn = document.getElementById("stopBtn");
const chatContainer = document.getElementById("chatContainer");
const welcomeScreen = document.getElementById("welcomeScreen");
const conversationList = document.getElementById("conversationList");
const topbarTitle = document.getElementById("topbarTitle");
const charCount = document.getElementById("charCount");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const sidebar = document.getElementById("sidebar");
const sidebarToggle = document.getElementById("sidebarToggle");
const sidebarClose = document.getElementById("sidebarClose");
const newChatBtn = document.getElementById("newChatBtn");
const themeToggle = document.getElementById("themeToggle");

// ── CSRF Token ───────────────────────────────────────────
function getCsrfToken() {
    const cookie = document.cookie.split("; ").find(r => r.startsWith("csrftoken="));
    return cookie ? cookie.split("=")[1] : "";
}

// ── Configure Marked ──────────────────────────────────────
if (typeof marked !== "undefined") {
    marked.setOptions({
        breaks: true,
        gfm: true,
        highlight: function(code, lang) {
            if (typeof hljs !== "undefined" && lang && hljs.getLanguage(lang)) {
                return hljs.highlight(code, { language: lang }).value;
            }
            return code;
        },
    });
}

// ── Initialize ────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadConversations();
    checkSystemStatus();
    initTheme();
    autoResizeTextarea();
    setInterval(checkSystemStatus, 30000);
});

// ── Theme Management ──────────────────────────────────────
function initTheme() {
    const saved = localStorage.getItem("acu-theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);
}

themeToggle.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("acu-theme", next);
});

// ── Sidebar ───────────────────────────────────────────────
sidebarToggle.addEventListener("click", () => sidebar.classList.add("open"));
sidebarClose.addEventListener("click", () => sidebar.classList.remove("open"));

// ── Textarea Auto-resize ──────────────────────────────────
function autoResizeTextarea() {
    questionInput.addEventListener("input", () => {
        questionInput.style.height = "auto";
        questionInput.style.height = Math.min(questionInput.scrollHeight, 150) + "px";
        charCount.textContent = `${questionInput.value.length} / 2000`;
    });
}

// ── Form Submit ───────────────────────────────────────────
function submitCurrentMessage() {
    const question = questionInput.value.trim();
    const conv = getActiveConv();
    if (!question || !conv || conv.isLoading || conv.isSending) return;
    sendMessage(question);
}

chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    submitCurrentMessage();
});

questionInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submitCurrentMessage();
    }
});

// ── Suggestion Cards ──────────────────────────────────────
document.querySelectorAll(".suggestion-card").forEach(card => {
    card.addEventListener("click", () => {
        let conv = getActiveConv();
        if (!conv) {
            conv = createNewConversation();
            activateConversation(conv.id);
        }
        if (conv.isLoading || conv.isSending) return;
        const question = card.getAttribute("data-question");
        sendMessage(question);
    });
});

// ── Conversation State Helpers ────────────────────────────
function getActiveConv() {
    return activeConversationId ? conversations.get(activeConversationId) : null;
}

function createNewConversation() {
    const tempId = "pending-" + Date.now();
    const container = document.createElement("div");
    container.className = "messages messages-panel";
    container.dataset.convId = tempId;
    container.style.display = "none";
    chatContainer.appendChild(container);
    const conv = {
        id: tempId,
        title: "Yeni Sohbet",
        isLoading: false,
        isSending: false,
        abortController: null,
        container,
    };
    conversations.set(tempId, conv);
    return conv;
}

function activateConversation(id) {
    conversations.forEach(c => { c.container.style.display = "none"; });
    const conv = conversations.get(id);
    if (!conv) return;
    activeConversationId = id;
    conv.container.style.display = "flex";
    welcomeScreen.style.display = conv.container.children.length > 0 ? "none" : "";
    topbarTitle.textContent = conv.title || "Yeni Sohbet";
    setGenerating(conv.isLoading);
    renderTabs(); // re-renders sidebar with correct active state

    // Clear input so previous typed-but-unsent text does not bleed into a new conversation
    questionInput.value = "";
    questionInput.style.height = "auto";
    charCount.textContent = "0 / 2000";
}

// ── New Chat ──────────────────────────────────────────────
newChatBtn.addEventListener("click", () => {
    const active = getActiveConv();
    if (active && active.container.children.length === 0 && active.id.startsWith("pending-")) {
        activateConversation(active.id);
    } else {
        const conv = createNewConversation();
        activateConversation(conv.id);
    }
    sidebar.classList.remove("open");
});

// ── Sidebar state (replaces top tab bar) ─────────────────
function renderTabs() {
    // All conversation state is shown in the sidebar, not a top tab bar.
    renderConversationList(cachedConversations);
}

function closeConversation(id) {
    const conv = conversations.get(id);
    if (!conv) return;
    if (conv.abortController) conv.abortController.abort();
    conv.container.remove();
    conversations.delete(id);
    if (activeConversationId === id) {
        if (conversations.size > 0) {
            activateConversation(conversations.keys().next().value);
        } else {
            activeConversationId = null;
            welcomeScreen.style.display = "";
            topbarTitle.textContent = "Yeni Sohbet";
            setGenerating(false);
            renderTabs();
        }
    } else {
        renderTabs();
    }
}

// ── Send Message ──────────────────────────────────────────
async function sendMessage(question) {
    const conv = conversations.get(activeConversationId);
    if (!conv || conv.isLoading || conv.isSending) return;
    conv.isSending = true;

    welcomeScreen.style.display = "none";
    appendMessage("user", question, [], false, null, conv.container);

    questionInput.value = "";
    questionInput.style.height = "auto";
    charCount.textContent = "0 / 2000";

    // Use question as temporary tab title on first message
    if (conv.id.startsWith("pending-")) {
        conv.title = question.length > 40 ? question.substring(0, 40) + "…" : question;
    }

    conv.isLoading = true;
    conv.abortController = new AbortController();
    setGenerating(true);
    renderTabs();

    const typingEl = showTypingIndicator(conv.container);
    let didTimeout = false;
    const timeoutId = window.setTimeout(() => {
        didTimeout = true;
        if (conv.abortController) conv.abortController.abort();
    }, REQUEST_TIMEOUT_MS);

    try {
        const fetchOpts = {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCsrfToken(),
            },
            body: JSON.stringify({
                question,
                conversation_id: conv.id.startsWith("pending-") ? null : conv.id,
                stream: true,
            }),
            signal: conv.abortController.signal,
        };

        let response;
        try {
            response = await fetch("/api/chat/", fetchOpts);
        } catch (fetchErr) {
            // Retry once after 1 s on transient connection failure (not user-abort)
            if (fetchErr.name === "AbortError") throw fetchErr;
            await new Promise(r => setTimeout(r, 1000));
            if (conv.abortController.signal.aborted) throw new DOMException("Aborted", "AbortError");
            response = await fetch("/api/chat/", fetchOpts);
        }

        typingEl.remove();

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP ${response.status}`);
        }

        const contentType = response.headers.get("content-type");
        if (contentType && contentType.includes("text/event-stream")) {
            await handleStreamResponse(response, conv);
        } else {
            const data = await response.json();
            handleRegularResponse(data, conv);
        }
    } catch (error) {
        typingEl.remove();
        if (error.name === "AbortError") {
            const message = didTimeout
                ? "_Yanıt süresi aşıldı. Lütfen sorunuzu daha kısa veya daha belirli şekilde tekrar deneyin._"
                : "_Yanıt oluşturma durduruldu._";
            appendMessage("assistant", message, [], false, null, conv.container);
        } else {
            appendErrorMessage(error.message || "Bir hata oluştu. Lütfen tekrar deneyin.", conv.container);
        }
    } finally {
        window.clearTimeout(timeoutId);
        conv.isLoading = false;
        conv.isSending = false;
        conv.abortController = null;
        if (activeConversationId === conv.id) setGenerating(false);
        renderTabs();
        loadConversations();
    }
}

// ── Handle Stream Response ────────────────────────────────
async function handleStreamResponse(response, conv) {
    const container = conv.container;
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let fullResponse = "";
    let sources = [];
    let messageEl = null;
    let buffer = "";

    const processEventData = (eventData) => {
        try {
            const data = JSON.parse(eventData);
            if (data.type === "sources") {
                sources = data.sources || [];
            } else if (data.type === "content") {
                const chunk = data.content || "";
                if (chunk) {
                    fullResponse += chunk;
                    if (!messageEl) messageEl = appendMessage("assistant", "", sources, true, null, container);
                    updateMessageContent(messageEl, fullResponse);
                }
            } else if (data.type === "done") {
                const realId = data.conversation_id;
                if (realId && conv.id !== realId) updateConversationId(conv.id, realId, conv);
                if (!messageEl && fullResponse) messageEl = appendMessage("assistant", "", sources, true, null, container);
                if (messageEl) finishMessage(messageEl, fullResponse, sources, data.response_time_ms);
            }
        } catch (e) {
            // skip malformed JSON
        }
    };

    while (true) {
        const { done, value } = await reader.read();
        if (done) {
            const trailing = buffer.trim();
            if (trailing) {
                const dataLines = trailing.split("\n")
                    .map(l => l.replace(/\r$/, ""))
                    .filter(l => l.startsWith("data:"))
                    .map(l => l.slice(5).replace(/^\s/, ""));
                if (dataLines.length > 0) processEventData(dataLines.join("\n"));
            }
            break;
        }
        buffer += decoder.decode(value, { stream: true });
        buffer = buffer.replace(/\r\n/g, "\n");
        let boundary = buffer.indexOf("\n\n");
        while (boundary !== -1) {
            const rawEvent = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const dataLines = rawEvent.split("\n")
                .map(l => l.replace(/\r$/, ""))
                .filter(l => l.startsWith("data:"))
                .map(l => l.slice(5).replace(/^\s/, ""));
            if (dataLines.length > 0) processEventData(dataLines.join("\n"));
            boundary = buffer.indexOf("\n\n");
        }
    }

    if (!messageEl && fullResponse) appendMessage("assistant", fullResponse, sources, false, null, container);
}

function updateConversationId(oldId, newId, convRef) {
    if (!conversations.has(oldId)) return;
    upgradingConversationIds.add(newId);
    convRef.id = newId;
    convRef.container.dataset.convId = newId;
    conversations.delete(oldId);
    conversations.set(newId, convRef);
    if (activeConversationId === oldId) activeConversationId = newId;
    const sidebarBtn = conversationList.querySelector(`[data-id="${oldId}"]`);
    const sidebarItem = sidebarBtn ? sidebarBtn.closest(".conversation-item") : null;
    if (sidebarItem) {
        sidebarItem.dataset.id = newId;
        sidebarItem.classList.toggle("active", activeConversationId === newId);
        sidebarItem.querySelectorAll("[data-id]").forEach(el => { el.dataset.id = newId; });
    }
    requestAnimationFrame(() => upgradingConversationIds.delete(newId));
}

// ── Handle Regular Response ───────────────────────────────
function handleRegularResponse(data, conv) {
    const realId = data.conversation_id;
    if (realId && conv.id !== realId) updateConversationId(conv.id, realId, conv);
    appendMessage("assistant", data.answer, data.sources, false, data.response_time_ms, conv.container);
    if (activeConversationId === conv.id) {
        topbarTitle.textContent = (data.answer || "").substring(0, 60) + "...";
    }
}

// ── Stop Generation ───────────────────────────────────────
stopBtn.addEventListener("click", () => {
    const conv = getActiveConv();
    if (conv && conv.abortController) conv.abortController.abort();
});

// ── UI Helpers ────────────────────────────────────────────
function setGenerating(state) {
    sendBtn.classList.toggle("hidden", state);
    stopBtn.classList.toggle("hidden", !state);
    sendBtn.disabled = state;
    questionInput.disabled = false;
    questionInput.placeholder = state
        ? "Yanıt bekleniyor... (⏎ ile gönderebilirsiniz)"
        : "Bir soru sorun...";
}

function showTypingIndicator(container) {
    const el = document.createElement("div");
    el.className = "message assistant";
    el.innerHTML = `
        <div class="message-avatar">🎓</div>
        <div class="message-content">
            <div class="typing-indicator">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
        </div>
    `;
    container.appendChild(el);
    scrollToBottom();
    return el;
}

function appendMessage(role, content, sources = [], isStreaming = false, responseTimeMs = null, container = null) {
    const target = container || (getActiveConv() ? getActiveConv().container : null);
    if (!target) return null;
    const el = document.createElement("div");
    el.className = `message ${role}`;
    const avatar = role === "user" ? "👤" : "🎓";
    const name = role === "user" ? "Sen" : "ACU Asistan";
    const time = new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
    const renderedContent = role === "assistant" ? "" : escapeHtml(content);
    el.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-content">
            <div class="message-header">
                <span class="message-name">${name}</span>
                <span class="message-time">${time}</span>
            </div>
            <div class="message-body">${renderedContent}</div>
            ${role === "assistant" && sources.length > 0 ? renderSources(sources) : ""}
            ${role === "assistant" && responseTimeMs ? `<div class="message-meta">⏱️ ${(responseTimeMs / 1000).toFixed(1)}s</div>` : ""}
        </div>
    `;
    if (role === "assistant") {
        const bodyEl = el.querySelector(".message-body");
        if (bodyEl) setAssistantMessageHtml(bodyEl, content || "");
    }
    target.appendChild(el);
    scrollToBottom();
    return el;
}

function setAssistantMessageHtml(element, message) {
    console.log("RAW MESSAGE:", message);
    const html = renderMarkdown(message || "");
    console.log("RENDERED HTML:", html);
    element.innerHTML = html;
    if (ENABLE_RENDER_TEST_INJECTION) {
        element.innerHTML = "<ul><li>TEST OK</li><li>BULLET WORKING</li></ul>";
    }
    console.log("FINAL DOM:", element.innerHTML);
}

function updateMessageContent(messageEl, content) {
    const bodyEl = messageEl.querySelector(".message-body");
    if (bodyEl) {
        setAssistantMessageHtml(bodyEl, content || "");
        scrollToBottom();
    }
}

function finishMessage(messageEl, content, sources, responseTimeMs) {
    const contentEl = messageEl.querySelector(".message-content");
    if (sources && sources.length > 0) {
        const existingSources = contentEl.querySelector(".message-sources");
        if (!existingSources) contentEl.insertAdjacentHTML("beforeend", renderSources(sources));
    }
    if (responseTimeMs) {
        contentEl.insertAdjacentHTML(
            "beforeend",
            `<div class="message-meta">⏱️ ${(responseTimeMs / 1000).toFixed(1)}s</div>`
        );
    }
    messageEl.querySelectorAll("pre code").forEach(block => {
        if (typeof hljs !== "undefined") hljs.highlightElement(block);
    });
    scrollToBottom();
}

function appendErrorMessage(message, container = null) {
    const target = container || (getActiveConv() ? getActiveConv().container : null);
    if (!target) return;
    const el = document.createElement("div");
    el.className = "message assistant";
    el.innerHTML = `
        <div class="message-avatar">⚠️</div>
        <div class="message-content">
            <div class="error-message">${escapeHtml(message)}</div>
        </div>
    `;
    target.appendChild(el);
    scrollToBottom();
}

function renderSources(sources) {
    if (!sources || sources.length === 0) return "";
    const items = sources.map(s => `
        <div class="source-item">
            📄 <a href="${escapeHtml(s.url)}" target="_blank" title="${escapeHtml(s.title)}">${escapeHtml(s.title || s.url)}</a>
            ${s.score ? `<span class="source-score">(${(s.score * 100).toFixed(0)}%)</span>` : ""}
        </div>`).join("");
    return `
        <details class="message-sources">
            <summary>📚 Kaynaklar (${sources.length})</summary>
            <div class="source-list">${items}</div>
        </details>
    `;
}

function renderMarkdown(text) {
    if (!text) return "";
    const normalized = String(text).replace(/\r\n/g, "\n");
    const lines = normalized.split("\n");
    const bulletItems = [];
    const prefixLines = [];
    let currentBullet = "";
    for (const rawLine of lines) {
        const line = rawLine.trim();
        if (!line) continue;
        if (/^\s*-\s+/.test(rawLine)) {
            if (currentBullet) bulletItems.push(currentBullet.trim());
            currentBullet = rawLine.replace(/^\s*-\s+/, "").trim();
        } else if (currentBullet) {
            currentBullet += ` ${line}`;
        } else {
            prefixLines.push(line);
        }
    }
    if (currentBullet) bulletItems.push(currentBullet.trim());
    if (bulletItems.length > 0) {
        const itemsHtml = bulletItems.filter(Boolean).map(item => `<li>${escapeHtml(item)}</li>`).join("");
        if (itemsHtml) {
            const prefix = prefixLines.length > 0
                ? `<div style="white-space: pre-line;">${escapeHtml(prefixLines.join("\n"))}</div>`
                : "";
            return `${prefix}<ul>${itemsHtml}</ul>`;
        }
    }
    return `<div style="white-space: pre-line;">${escapeHtml(normalized)}</div>`;
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function scrollToBottom() {
    requestAnimationFrame(() => {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    });
}

// ── Conversations (sidebar list) ──────────────────────────
async function loadConversations() {
    try {
        if (Array.from(conversations.values()).some(conv => conv.isLoading || conv.isSending)) return;
        const response = await fetch("/api/conversations/");
        if (!response.ok) return;
        const apiConvs = await response.json();
        const activePending = Array.from(conversations.values()).filter(conv => conv.id.startsWith("pending-"));
        const convs = apiConvs.filter(apiConv => {
            if (conversations.has(apiConv.id) || upgradingConversationIds.has(apiConv.id)) return true;
            return !activePending.some(pending => {
                const pendingTitle = (pending.title || "").trim();
                const apiTitle = (apiConv.title || "").trim();
                return pending.isLoading && pendingTitle && apiTitle && apiTitle.startsWith(pendingTitle);
            });
        });
        cachedConversations = convs;
        // Sync titles for any open conversations
        convs.forEach(c => {
            if (conversations.has(c.id)) {
                const open = conversations.get(c.id);
                open.title = c.title || "Sohbet";
                if (activeConversationId === c.id) topbarTitle.textContent = open.title;
            }
        });
        renderConversationList(convs);
    } catch (error) {
        console.warn("Failed to load conversations:", error);
    }
}

function renderConversationList(convs) {
    conversationList.innerHTML = "";

    // Collect pending conversations (not yet saved to backend)
    const pendingItems = [];
    conversations.forEach((conv, id) => {
        if (id.startsWith("pending-")) pendingItems.push(conv);
    });

    const isEmpty = pendingItems.length === 0 && convs.length === 0;
    if (isEmpty) {
        conversationList.innerHTML = `
            <div style="padding: 20px; text-align: center; color: var(--text-tertiary); font-size: 13px;">
                Henüz sohbet yok
            </div>
        `;
        return;
    }

    // Pending conversations shown at top with a close (×) button
    pendingItems.forEach(conv => {
        conversationList.appendChild(makeSidebarItem({
            id: conv.id,
            title: conv.title || "Yeni Sohbet",
            isLoading: conv.isLoading,
            isPending: true,
        }));
    });

    // API-saved conversations
    convs.forEach(conv => {
        const open = conversations.get(conv.id);
        conversationList.appendChild(makeSidebarItem({
            id: conv.id,
            title: conv.title || "Başlıksız Sohbet",
            isLoading: open ? open.isLoading : false,
            isPending: false,
        }));
    });
}

function makeSidebarItem({ id, title, isLoading, isPending }) {
    const el = document.createElement("div");
    el.className = `conversation-item${id === activeConversationId ? " active" : ""}`;
    el.dataset.id = id;

    const loadingDot = isLoading
        ? `<span class="conv-loading-dot" title="Yanıt bekleniyor"></span>`
        : "";

    const actionBtn = isPending
        ? `<button class="conv-close" title="Kapat" data-id="${id}">
               <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                   <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
               </svg>
           </button>`
        : `<button class="conv-delete" title="Sil" data-id="${id}">
               <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                   <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
               </svg>
           </button>`;

    el.innerHTML = `
        <span class="conv-icon">💬</span>
        <span class="conv-title">${escapeHtml(title)}</span>
        ${loadingDot}
        ${actionBtn}
    `;

    el.addEventListener("click", (e) => {
        if (e.target.closest(".conv-delete") || e.target.closest(".conv-close")) return;
        if (isPending) {
            activateConversation(id);
        } else {
            loadConversation(id);
        }
        sidebar.classList.remove("open");
    });

    const btn = el.querySelector(isPending ? ".conv-close" : ".conv-delete");
    btn.addEventListener("click", (e) => {
        e.stopPropagation();
        isPending ? closeConversation(id) : deleteConversation(id);
    });

    return el;
}

async function loadConversation(conversationId) {
    // If already open in a tab, just switch to it
    if (conversations.has(conversationId)) {
        activateConversation(conversationId);
        return;
    }
    try {
        const response = await fetch(`/api/conversations/${conversationId}/`);
        if (!response.ok) return;
        const data = await response.json();
        const container = document.createElement("div");
        container.className = "messages messages-panel";
        container.dataset.convId = conversationId;
        container.style.display = "none";
        chatContainer.appendChild(container);
        const conv = {
            id: conversationId,
            title: data.title || "Sohbet",
            isLoading: false,
            isSending: false,
            abortController: null,
            container,
        };
        conversations.set(conversationId, conv);
        (data.messages || []).forEach(msg => {
            if (msg.role === "user") {
                appendMessage("user", msg.content, [], false, null, container);
            } else if (msg.role === "assistant") {
                const sources = (msg.sources || []).map(url => ({ url, title: url }));
                appendMessage("assistant", msg.content, sources, false, msg.response_time_ms, container);
            }
        });
        activateConversation(conversationId);
    } catch (error) {
        console.error("Failed to load conversation:", error);
    }
}

async function deleteConversation(conversationId) {
    if (!confirm("Bu sohbeti silmek istediğinize emin misiniz?")) return;
    try {
        await fetch(`/api/conversations/${conversationId}/delete/`, {
            method: "DELETE",
            headers: { "X-CSRFToken": getCsrfToken() },
        });
        if (conversations.has(conversationId)) closeConversation(conversationId);
        loadConversations();
    } catch (error) {
        console.error("Failed to delete conversation:", error);
    }
}

// ── System Status ─────────────────────────────────────────
async function checkSystemStatus() {
    try {
        const response = await fetch("/api/health/");
        if (!response.ok) throw new Error();
        const data = await response.json();
        if (data.llm_available) {
            statusDot.className = "status-dot online";
            statusText.textContent = `Çevrimiçi — ${data.model}`;
        } else {
            statusDot.className = "status-dot";
            statusText.textContent = "Model yükleniyor...";
        }
    } catch (error) {
        statusDot.className = "status-dot offline";
        statusText.textContent = "Bağlantı hatası";
    }
}
// Touch event optimization - OmerV7
})();
