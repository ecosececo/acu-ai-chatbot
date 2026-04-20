/**
 * ACU AI Chatbot — Frontend JavaScript
 *
 * Handles:
 * - Chat messaging with streaming (SSE)
 * - Conversation management
 * - UI state (sidebar, theme, etc.)
 * - Markdown rendering
 */

// ── State ───────────────────────────────────────────────
let currentConversationId = null;
let isGenerating = false;
let abortController = null;
const ENABLE_RENDER_TEST_INJECTION = false;

// ── DOM Elements ────────────────────────────────────────
const chatForm = document.getElementById("chatForm");
const questionInput = document.getElementById("questionInput");
const sendBtn = document.getElementById("sendBtn");
const stopBtn = document.getElementById("stopBtn");
const messagesContainer = document.getElementById("messages");
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

// ── CSRF Token ──────────────────────────────────────────
function getCsrfToken() {
    const cookie = document.cookie
        .split("; ")
        .find((row) => row.startsWith("csrftoken="));
    return cookie ? cookie.split("=")[1] : "";
}

// ── Configure Marked ────────────────────────────────────
if (typeof marked !== "undefined") {
    marked.setOptions({
        breaks: true,
        gfm: true,
        highlight: function (code, lang) {
            if (typeof hljs !== "undefined" && lang && hljs.getLanguage(lang)) {
                return hljs.highlight(code, { language: lang }).value;
            }
            return code;
        },
    });
}

// ── Initialize ──────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadConversations();
    checkSystemStatus();
    initTheme();
    autoResizeTextarea();

    // Check status every 30 seconds
    setInterval(checkSystemStatus, 30000);
});

// ── Theme Management ────────────────────────────────────
function initTheme() {
    const saved = localStorage.getItem("acu-theme");
    if (saved) {
        document.documentElement.setAttribute("data-theme", saved);
    }
}

themeToggle.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("acu-theme", next);
});

// ── Sidebar Toggle ──────────────────────────────────────
sidebarToggle.addEventListener("click", () => sidebar.classList.add("open"));
sidebarClose.addEventListener("click", () => sidebar.classList.remove("open"));

// ── Textarea Auto-resize ────────────────────────────────
function autoResizeTextarea() {
    questionInput.addEventListener("input", () => {
        questionInput.style.height = "auto";
        questionInput.style.height = Math.min(questionInput.scrollHeight, 150) + "px";
        charCount.textContent = `${questionInput.value.length} / 2000`;
    });
}

// ── Form Submit ─────────────────────────────────────────
chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const question = questionInput.value.trim();
    if (!question || isGenerating) return;
    sendMessage(question);
});

// Handle Enter key (submit) and Shift+Enter (new line)
questionInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        chatForm.dispatchEvent(new Event("submit"));
    }
});

// ── Suggestion Cards ────────────────────────────────────
document.querySelectorAll(".suggestion-card").forEach((card) => {
    card.addEventListener("click", () => {
        const question = card.getAttribute("data-question");
        questionInput.value = question;
        sendMessage(question);
    });
});

// ── New Chat ────────────────────────────────────────────
newChatBtn.addEventListener("click", () => {
    currentConversationId = null;
    messagesContainer.innerHTML = "";
    welcomeScreen.classList.remove("hidden");
    welcomeScreen.style.display = "";
    topbarTitle.textContent = "Yeni Sohbet";
    sidebar.classList.remove("open");

    // Remove active class from conversations
    document.querySelectorAll(".conversation-item").forEach((el) =>
        el.classList.remove("active")
    );
});

// ── Send Message ────────────────────────────────────────
async function sendMessage(question) {
    // Hide welcome screen
    welcomeScreen.style.display = "none";

    // Show user message
    appendMessage("user", question);

    // Clear input
    questionInput.value = "";
    questionInput.style.height = "auto";
    charCount.textContent = "0 / 2000";

    // UI state
    setGenerating(true);

    // Show typing indicator
    const typingEl = showTypingIndicator();

    try {
        abortController = new AbortController();

        const response = await fetch("/api/chat/", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCsrfToken(),
            },
            body: JSON.stringify({
                question: question,
                conversation_id: currentConversationId,
                stream: true,
            }),
            signal: abortController.signal,
        });

        // Remove typing indicator
        typingEl.remove();

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP ${response.status}`);
        }

        // Check if streaming response
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.includes("text/event-stream")) {
            await handleStreamResponse(response);
        } else {
            const data = await response.json();
            handleRegularResponse(data);
        }
    } catch (error) {
        typingEl.remove();

        if (error.name === "AbortError") {
            appendMessage("assistant", "_Yanıt oluşturma durduruldu._");
        } else {
            appendErrorMessage(
                error.message || "Bir hata oluştu. Lütfen tekrar deneyin."
            );
        }
    } finally {
        setGenerating(false);
        abortController = null;
        loadConversations();
    }
}

// ── Handle Stream Response ──────────────────────────────
async function handleStreamResponse(response) {
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
                const chunkContent = data.content || "";
                if (chunkContent) {
                    fullResponse += chunkContent;
                    if (!messageEl) {
                        messageEl = appendMessage("assistant", "", sources, true);
                    }
                    updateMessageContent(messageEl, fullResponse);
                }
            } else if (data.type === "done") {
                currentConversationId = data.conversation_id;
                if (!messageEl && fullResponse) {
                    messageEl = appendMessage("assistant", "", sources, true);
                }
                if (messageEl) {
                    finishMessage(messageEl, fullResponse, sources, data.response_time_ms);
                }
            }
        } catch (e) {
            // Skip malformed JSON payloads
        }
    };

    while (true) {
        const { done, value } = await reader.read();
        if (done) {
            // Process any trailing buffered event without requiring a final delimiter.
            const trailing = buffer.trim();
            if (trailing) {
                const dataLines = trailing
                    .split("\n")
                    .map((line) => line.replace(/\r$/, ""))
                    .filter((line) => line.startsWith("data:"))
                    .map((line) => line.slice(5).replace(/^\s/, ""));
                if (dataLines.length > 0) {
                    processEventData(dataLines.join("\n"));
                }
            }
            break;
        }

        buffer += decoder.decode(value, { stream: true });
        buffer = buffer.replace(/\r\n/g, "\n");

        // SSE events are separated by an empty line.
        let eventBoundary = buffer.indexOf("\n\n");
        while (eventBoundary !== -1) {
            const rawEvent = buffer.slice(0, eventBoundary);
            buffer = buffer.slice(eventBoundary + 2);

            const dataLines = rawEvent
                .split("\n")
                .map((line) => line.replace(/\r$/, ""))
                .filter((line) => line.startsWith("data:"))
                .map((line) => line.slice(5).replace(/^\s/, ""));

            if (dataLines.length > 0) {
                processEventData(dataLines.join("\n"));
            }

            eventBoundary = buffer.indexOf("\n\n");
        }
    }

    // If no message element was created, show what we have
    if (!messageEl && fullResponse) {
        appendMessage("assistant", fullResponse, sources);
    }
}

// ── Handle Regular (non-stream) Response ────────────────
function handleRegularResponse(data) {
    currentConversationId = data.conversation_id;
    appendMessage("assistant", data.answer, data.sources, false, data.response_time_ms);
    topbarTitle.textContent = data.answer.substring(0, 60) + "...";
}

// ── Stop Generation ─────────────────────────────────────
stopBtn.addEventListener("click", () => {
    if (abortController) {
        abortController.abort();
    }
});

// ── UI Helpers ──────────────────────────────────────────
function setGenerating(state) {
    isGenerating = state;
    sendBtn.classList.toggle("hidden", state);
    stopBtn.classList.toggle("hidden", !state);
    sendBtn.disabled = state;
    questionInput.disabled = false;
    questionInput.placeholder = state ? "Yanıt bekleniyor... (⏎ ile gönderebilirsiniz)" : "Bir soru sorun...";
}

function showTypingIndicator() {
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
    messagesContainer.appendChild(el);
    scrollToBottom();
    return el;
}

function appendMessage(role, content, sources = [], isStreaming = false, responseTimeMs = null) {
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
        if (bodyEl) {
            setAssistantMessageHtml(bodyEl, content || "");
        }
    }

    messagesContainer.appendChild(el);
    scrollToBottom();
    return el;
}

function setAssistantMessageHtml(element, message) {
    console.log("RAW MESSAGE:", message);
    const html = renderMarkdown(message || "");
    console.log("RENDERED HTML:", html);
    element.innerHTML = html;

    // Temporary injection for render verification.
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
    // Body was already rendered by the last updateMessageContent call during streaming.
    // Re-rendering here would cause a visible flash (innerHTML reset), so we skip it.

    // Add sources
    const contentEl = messageEl.querySelector(".message-content");
    if (sources && sources.length > 0) {
        const existingSources = contentEl.querySelector(".message-sources");
        if (!existingSources) {
            contentEl.insertAdjacentHTML("beforeend", renderSources(sources));
        }
    }

    // Add response time
    if (responseTimeMs) {
        contentEl.insertAdjacentHTML(
            "beforeend",
            `<div class="message-meta">⏱️ ${(responseTimeMs / 1000).toFixed(1)}s</div>`
        );
    }

    // Highlight code blocks
    messageEl.querySelectorAll("pre code").forEach((block) => {
        if (typeof hljs !== "undefined") {
            hljs.highlightElement(block);
        }
    });

    scrollToBottom();
}

function appendErrorMessage(message) {
    const el = document.createElement("div");
    el.className = "message assistant";
    el.innerHTML = `
        <div class="message-avatar">⚠️</div>
        <div class="message-content">
            <div class="error-message">${escapeHtml(message)}</div>
        </div>
    `;
    messagesContainer.appendChild(el);
    scrollToBottom();
}

function renderSources(sources) {
    if (!sources || sources.length === 0) return "";

    const items = sources
        .map(
            (s) => `
        <div class="source-item">
            📄 <a href="${escapeHtml(s.url)}" target="_blank" title="${escapeHtml(s.title)}">${escapeHtml(s.title || s.url)}</a>
            ${s.score ? `<span class="source-score">(${(s.score * 100).toFixed(0)}%)</span>` : ""}
        </div>`
        )
        .join("");

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
            if (currentBullet) {
                bulletItems.push(currentBullet.trim());
            }
            currentBullet = rawLine.replace(/^\s*-\s+/, "").trim();
        } else if (currentBullet) {
            currentBullet += ` ${line}`;
        } else {
            prefixLines.push(line);
        }
    }

    if (currentBullet) {
        bulletItems.push(currentBullet.trim());
    }

    if (bulletItems.length > 0) {
        const itemsHtml = bulletItems
            .filter(Boolean)
            .map((item) => `<li>${escapeHtml(item)}</li>`)
            .join("");
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

// ── Conversations ───────────────────────────────────────
async function loadConversations() {
    try {
        const response = await fetch("/api/conversations/");
        if (!response.ok) return;

        const conversations = await response.json();
        renderConversationList(conversations);
    } catch (error) {
        console.warn("Failed to load conversations:", error);
    }
}

function renderConversationList(conversations) {
    conversationList.innerHTML = "";

    if (conversations.length === 0) {
        conversationList.innerHTML = `
            <div style="padding: 20px; text-align: center; color: var(--text-tertiary); font-size: 13px;">
                Henüz sohbet yok
            </div>
        `;
        return;
    }

    conversations.forEach((conv) => {
        const el = document.createElement("div");
        el.className = `conversation-item${conv.id === currentConversationId ? " active" : ""}`;
        el.innerHTML = `
            <span class="conv-icon">💬</span>
            <span class="conv-title">${escapeHtml(conv.title || "Başlıksız Sohbet")}</span>
            <button class="conv-delete" title="Sil" data-id="${conv.id}">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            </button>
        `;

        // Click to load conversation
        el.addEventListener("click", (e) => {
            if (e.target.closest(".conv-delete")) return;
            loadConversation(conv.id);
            sidebar.classList.remove("open");
        });

        // Delete button
        el.querySelector(".conv-delete").addEventListener("click", (e) => {
            e.stopPropagation();
            deleteConversation(conv.id);
        });

        conversationList.appendChild(el);
    });
}

async function loadConversation(conversationId) {
    try {
        const response = await fetch(`/api/conversations/${conversationId}/`);
        if (!response.ok) return;

        const data = await response.json();

        currentConversationId = data.id;
        topbarTitle.textContent = data.title || "Sohbet";
        welcomeScreen.style.display = "none";
        messagesContainer.innerHTML = "";

        // Render messages
        (data.messages || []).forEach((msg) => {
            if (msg.role === "user") {
                appendMessage("user", msg.content);
            } else if (msg.role === "assistant") {
                const sources = (msg.sources || []).map((url) => ({ url, title: url }));
                appendMessage("assistant", msg.content, sources, false, msg.response_time_ms);
            }
        });

        // Update active state in sidebar
        document.querySelectorAll(".conversation-item").forEach((el) =>
            el.classList.remove("active")
        );
        const activeItem = document.querySelector(`[data-id="${conversationId}"]`);
        if (activeItem) {
            activeItem.closest(".conversation-item").classList.add("active");
        }
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

        if (currentConversationId === conversationId) {
            currentConversationId = null;
            messagesContainer.innerHTML = "";
            welcomeScreen.style.display = "";
            topbarTitle.textContent = "Yeni Sohbet";
        }

        loadConversations();
    } catch (error) {
        console.error("Failed to delete conversation:", error);
    }
}

// ── System Status ───────────────────────────────────────
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
