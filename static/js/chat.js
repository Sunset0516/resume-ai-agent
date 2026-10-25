/* =========================================================
   简历 AI Agent - 前端交互逻辑
   ========================================================= */
(function () {
    'use strict';

    // ------------------ 状态管理 ------------------
    const OWNER_STORAGE_KEY = 'resume_owner_key';
    const state = {
        sessionId: null,
        loading: false,
        resume: null,
        ownerKey: localStorage.getItem(OWNER_STORAGE_KEY) || null,
    };

    function saveOwnerKeyFromResponse(resp) {
        if (!resp || !resp.headers) return;
        const k = resp.headers.get('X-Owner-Key');
        if (k && state.ownerKey !== k) {
            state.ownerKey = k;
            try { localStorage.setItem(OWNER_STORAGE_KEY, k); } catch(e){}
        }
    }
    function authHeaders() {
        const h = { 'Content-Type': 'application/json' };
        if (state.ownerKey) h['X-Owner-Key'] = state.ownerKey;
        return h;
    }
    // 基础路径：从 window.ROOT_PATH 读取，或从 URL 自动检测（容错：即使 index.html 没设置也能工作）
    const BASE_PATH = (window.ROOT_PATH || (function() {
        const m = location.pathname.match(/^(\/[^/]+)/);
        return m ? m[1] : '';
    })()).replace(/\/$/, '');

    function _applyBasePath(url) {
        // 只对以 / 开头的相对路径加前缀，已经是完整 URL 的不动
        if (typeof url !== 'string') return url;
        if (url.startsWith('http://') || url.startsWith('https://')) return url;
        if (url.startsWith(BASE_PATH + '/')) return url;  // 已加过前缀
        if (url.startsWith('/')) return BASE_PATH + url;
        return url;
    }

    function addOwnerQuery(url) {
        url = _applyBasePath(url);  // 先加 BASE_PATH 前缀
        if (!state.ownerKey) return url;
        const sep = url.indexOf('?') >= 0 ? '&' : '?';
        return url + sep + 'owner_key=' + encodeURIComponent(state.ownerKey);
    }

    // ------------------ DOM 快捷访问 ------------------
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);
    const chatMessagesEl = $('#chat-messages');
    const inputEl = $('#chat-input');
    const sendBtnEl = $('#send-btn');
    const welcomeEl = $('#welcome');

    // ------------------ 初始化 ------------------
    document.addEventListener('DOMContentLoaded', init);

    // 从分享链接 URL ?owner_key=xxx 读取并写入 localStorage（面试官场景）
    function applyOwnerFromUrl() {
        try {
            const p = new URL(location.href).searchParams.get('owner_key');
            if (p) {
                const cleaned = decodeURIComponent(p).trim();
                if (cleaned && state.ownerKey !== cleaned) {
                    state.ownerKey = cleaned;
                    try { localStorage.setItem(OWNER_STORAGE_KEY, cleaned); } catch(e){}
                    // 写入 Cookie（7天），同域下其他页面保持同一分享身份
                    try {
                        document.cookie = 'x_owner_key=' + encodeURIComponent(cleaned)
                            + '; max-age=604800; path=/; SameSite=Lax';
                    } catch(e) {}
                }
            }
        } catch (e) { /* ignore malformed URL */ }
    }

    async function init() {
        applyOwnerFromUrl();
        bindEvents();
        await loadResume();
        autoResize();
        inputEl.focus();
    }

    function bindEvents() {
        sendBtnEl.addEventListener('click', onSendClick);
        inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                onSendClick();
            }
        });
        inputEl.addEventListener('input', autoResize);

        // 欢迎页快捷建议点击
        document.addEventListener('click', (e) => {
            const card = e.target.closest('.suggestion-card');
            if (card) {
                const text = card.querySelector('.q')?.textContent.trim();
                if (text) {
                    inputEl.value = text;
                    onSendClick();
                }
            }
        });

        // 新会话按钮
        $('#btn-new-chat')?.addEventListener('click', () => {
            state.sessionId = null;
            clearMessages();
            showWelcome();
            inputEl.focus();
        });
    }

    function autoResize() {
        inputEl.style.height = 'auto';
        inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + 'px';
    }

    // ------------------ 加载简历 ------------------
    async function loadResume() {
        try {
            const resp = await fetch(addOwnerQuery('/api/resume'), {
                headers: authHeaders(),
            });
            saveOwnerKeyFromResponse(resp);
            const data = await resp.json();
            if (data.success && data.data) {
                state.resume = data.data;
                renderResume(data.data);
                updateTopbar(data.data);
            } else {
                renderEmptyResume();
            }
        } catch (e) {
            console.error('加载简历失败', e);
            renderEmptyResume();
        }
    }

    function updateTopbar(resume) {
        const el = $('#visitor-name');
        if (el && resume?.name) el.textContent = resume.name;
    }

    // ------------------ 渲染简历侧栏 ------------------
    function renderResume(r) {
        const avatarEl = $('#resume-avatar');
        if (avatarEl) {
            if (r.avatar) {
                avatarEl.innerHTML = `<img src="${r.avatar}" alt="">`;
            } else {
                avatarEl.textContent = r.name?.charAt(0) || '?';
            }
        }
        setText('#resume-name', r.name || '未命名');
        setText('#resume-title', r.title || '求职中');

        const contacts = [];
        if (r.email) contacts.push(`<span>✉ ${escapeHtml(r.email)}</span>`);
        if (r.phone) contacts.push(`<span>📞 ${escapeHtml(r.phone)}</span>`);
        if (r.location) contacts.push(`<span>📍 ${escapeHtml(r.location)}</span>`);
        if (r.github) contacts.push(`<span>💻 ${escapeHtml(r.github)}</span>`);
        $('#resume-contacts').innerHTML = contacts.join('');

        setText('#resume-summary', r.summary || '（暂无简介）', true);

        // 教育经历
        const eduHtml = (r.educations || []).map((e) => `
            <div class="timeline-item">
                <div class="timeline-title">${escapeHtml(e.school)}</div>
                <div class="timeline-subtitle">${escapeHtml([e.degree, e.major].filter(Boolean).join(' · '))}</div>
                <div class="timeline-date">${escapeHtml([e.start_date, e.end_date].filter(Boolean).join(' - ') || '')}</div>
                ${e.description ? `<div class="timeline-desc">${escapeHtml(e.description)}</div>` : ''}
            </div>
        `).join('');
        $('#sec-education').innerHTML = eduHtml || '<div class="empty">暂无教育经历</div>';

        // 实习
        const intHtml = (r.internships || []).map((it) => `
            <div class="timeline-item">
                <div class="timeline-title">${escapeHtml(it.company)} · ${escapeHtml(it.position || '实习生')}</div>
                <div class="timeline-date">${escapeHtml([it.start_date, it.end_date].filter(Boolean).join(' - ') || '')}</div>
                ${it.highlights && it.highlights.length ? `
                    <ul class="timeline-list">
                        ${it.highlights.map((h) => `<li>${escapeHtml(h)}</li>`).join('')}
                    </ul>
                ` : ''}
            </div>
        `).join('');
        $('#sec-internship').innerHTML = intHtml || '<div class="empty">暂无实习经历</div>';

        // 项目
        const pjHtml = (r.projects || []).map((p) => `
            <div class="timeline-item">
                <div class="timeline-title">${escapeHtml(p.name)} · ${escapeHtml(p.role || '参与')}</div>
                <div class="timeline-date">${escapeHtml([p.start_date, p.end_date].filter(Boolean).join(' - ') || '')}</div>
                ${p.tech_stack && p.tech_stack.length ? `
                    <div class="timeline-desc" style="margin-top:6px;"><b>技术栈：</b>${escapeHtml(p.tech_stack.join(', '))}</div>
                ` : ''}
                ${p.description ? `<div class="timeline-desc">${escapeHtml(p.description)}</div>` : ''}
                ${p.highlights && p.highlights.length ? `
                    <ul class="timeline-list">
                        ${p.highlights.map((h) => `<li>${escapeHtml(h)}</li>`).join('')}
                    </ul>
                ` : ''}
            </div>
        `).join('');
        $('#sec-projects').innerHTML = pjHtml || '<div class="empty">暂无项目经验</div>';

        // 技能
        const skHtml = (r.skills || []).map((s) => `
            <div class="skill-group">
                <div class="skill-label">${escapeHtml(s.category || '技能')}</div>
                <div class="skill-tags">
                    ${(s.items || []).map((i) => `<span class="skill-tag">${escapeHtml(i)}</span>`).join('')}
                </div>
            </div>
        `).join('');
        $('#sec-skills').innerHTML = skHtml || '<div class="empty">暂无技能</div>';
    }

    function renderEmptyResume() {
        const name = $('#resume-name');
        if (name) name.textContent = '未录入简历';
        $('#resume-title').textContent = '请先添加简历数据';
        $('#resume-summary').textContent = '请访问 /admin 页面录入您的个人简历信息，或通过 POST /api/resume 接口创建。';
    }

    function setText(sel, text, isHtml = false) {
        const el = document.querySelector(sel);
        if (!el) return;
        if (isHtml) el.textContent = text;
        else el.textContent = text;
    }

    // ------------------ 发送消息 ------------------
    function onSendClick() {
        const msg = inputEl.value.trim();
        if (!msg || state.loading) return;
        hideWelcome();
        // 用户发送新消息：重置滚动锁定，期望看到 AI 回答
        _userScrolledUp = false;
        appendMessage('user', msg);
        inputEl.value = '';
        autoResize();
        sendMessageStream(msg);
    }

    function appendMessage(role, content) {
        const row = document.createElement('div');
        row.className = `message-row ${role}`;

        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.textContent = role === 'user' ? '我' : 'AI';

        const col = document.createElement('div');
        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';
        bubble.textContent = content;

        col.appendChild(bubble);
        row.appendChild(avatar);
        row.appendChild(col);
        chatMessagesEl.appendChild(row);
        scrollBottom();
        return bubble;
    }

    function appendTyping() {
        const row = document.createElement('div');
        row.className = 'message-row assistant';
        row.id = 'typing-row';
        row.innerHTML = `
            <div class="message-avatar">AI</div>
            <div><div class="message-bubble"><div class="typing"><span></span><span></span><span></span></div></div></div>
        `;
        chatMessagesEl.appendChild(row);
        scrollBottom();
        return row;
    }

    function removeTyping() {
        const el = document.getElementById('typing-row');
        if (el) el.remove();
    }

    function clearMessages() {
        chatMessagesEl.innerHTML = '';
    }

    function showWelcome() {
        if (welcomeEl) welcomeEl.style.display = '';
    }
    function hideWelcome() {
        if (welcomeEl) welcomeEl.style.display = 'none';
    }

    // 用户主动滚动检测：用 wheel/touchmove（程序设置 scrollTop 不会触发这些事件）
    let _userScrolledUp = false;
    let _userInteractedTs = 0;

    function _isAtBottom() {
        return chatMessagesEl.scrollHeight - chatMessagesEl.scrollTop - chatMessagesEl.clientHeight < 80;
    }

    // 鼠标滚轮：用户主动滚动检测
    chatMessagesEl.addEventListener('wheel', (e) => {
        _userInteractedTs = Date.now();
        if (e.deltaY < 0) {
            // 向上滚动：若不在底部附近，标记为用户主动向上
            if (!_isAtBottom()) _userScrolledUp = true;
        } else if (e.deltaY > 0) {
            // 向下滚动：若已接近底部，取消锁定
            if (_isAtBottom()) _userScrolledUp = false;
        }
    }, { passive: true });

    // 触摸设备：滑动检测
    let _touchStartY = 0;
    chatMessagesEl.addEventListener('touchstart', (e) => {
        _touchStartY = e.touches[0]?.clientY || 0;
        _userInteractedTs = Date.now();
    }, { passive: true });
    chatMessagesEl.addEventListener('touchmove', () => {
        _userInteractedTs = Date.now();
        if (!_isAtBottom()) _userScrolledUp = true;
        else _userScrolledUp = false;
    }, { passive: true });
    chatMessagesEl.addEventListener('touchend', () => {
        if (_isAtBottom()) _userScrolledUp = false;
    }, { passive: true });

    function scrollBottom() {
        if (_userScrolledUp) return;
        requestAnimationFrame(() => {
            chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
        });
    }

    // ------------------ 流式请求 ------------------
    async function sendMessageStream(text) {
        state.loading = true;
        sendBtnEl.disabled = true;
        const typingEl = appendTyping();

        let assistantBubble = null;

        try {
            let streamDone = false;
            let lastDataTs = Date.now();      // 任意事件（含心跳）时间，用于判断连接是否存活
            let lastContentTs = Date.now();   // 最后一次收到正文内容的时间
            let started = false;
            const CONNECT_TIMEOUT_MS = 30_000;  // 30s 收不到任何事件 → 连接问题
            const CONTENT_TIMEOUT_MS = 60_000;  // 60s 只有心跳没有正文 → 上游 LLM 卡住
            const resp = await fetch(addOwnerQuery('/api/chat/stream'), {
                method: 'POST',
                headers: authHeaders(),
                body: JSON.stringify({
                    message: text,
                    session_id: state.sessionId,
                    stream: true,
                }),
            });
            saveOwnerKeyFromResponse(resp);

            if (!resp.ok || !resp.body) {
                throw new Error(`HTTP ${resp.status}`);
            }

            removeTyping();

            const reader = resp.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';
            let assistantText = '';
            let hbCount = 0;

            const abortStream = (msg) => {
                if (streamDone) return;
                streamDone = true;
                clearInterval(watchdog);
                if (!assistantBubble) assistantBubble = appendMessage('assistant', '');
                assistantBubble.textContent = assistantText + (assistantText ? '\n\n' : '') + '⚠ ' + msg;
                scrollBottom();
                try { reader.cancel(); } catch (e) {}
            };

            const watchdog = setInterval(() => {
                if (streamDone) { clearInterval(watchdog); return; }
                // 注意：心跳会不断刷新 lastDataTs，所以"无正文"必须单独计时，
                // 否则服务端一直发心跳时前端永远等不到超时（曾导致气泡转圈数分钟）
                if (!started && Date.now() - lastDataTs > CONNECT_TIMEOUT_MS) {
                    abortStream('连接超时：30 秒内没有收到服务端响应，请稍后重试。');
                } else if (started && Date.now() - lastContentTs > CONTENT_TIMEOUT_MS) {
                    abortStream('AI 响应超时：60 秒内没有返回新内容，已停止等待。请稍后重试。');
                }
            }, 2000);

            try {
              while (true) {
                const { done, value } = await reader.read();
                if (done) { streamDone = true; break; }
                lastDataTs = Date.now();
                buffer += decoder.decode(value, { stream: true });

                const lines = buffer.split('\n');
                buffer = lines.pop() || '';
                for (const raw of lines) {
                    const line = raw.trim();
                    if (!line) continue;
                    if (!line.startsWith('data:')) continue;
                    const payload = line.slice(5).trim();
                    if (!payload) continue;
                    let evt;
                    try { evt = JSON.parse(payload); }
                    catch { continue; }

                    if (evt.type === 'start') {
                        state.sessionId = evt.session_id;
                        started = true;
                        lastContentTs = Date.now();
                        // AI 开始回答：重置滚动锁定，让用户能看到流式输出
                        _userScrolledUp = false;
                        assistantBubble = appendMessage('assistant', '');
                        scrollBottom();
                    } else if (evt.type === 'chunk') {
                        assistantText += evt.content;
                        lastContentTs = Date.now();
                        if (assistantBubble) assistantBubble.textContent = assistantText;
                        scrollBottom();
                    } else if (evt.type === 'heartbeat') {
                        hbCount += 1;
                    } else if (evt.type === 'end') {
                        streamDone = true;
                    } else if (evt.type === 'error') {
                        if (!assistantBubble) assistantBubble = appendMessage('assistant', '');
                        assistantBubble.textContent = assistantText + (assistantText ? '\n\n' : '') + `⚠ ${evt.message}`;
                    }
                }
              }
            } finally {
              streamDone = true;
              clearInterval(watchdog);
            }

        } catch (err) {
            console.error('聊天请求失败', err);
            removeTyping();
            appendMessage('assistant', `抱歉，请求失败：${err.message}。请检查服务或稍后再试。`);
        } finally {
            state.loading = false;
            sendBtnEl.disabled = false;
            inputEl.focus();
            // 不重置 _userScrolledUp，也不强制 scrollBottom
            // 保留用户当前的滚动位置（避免AI回答后强行拉回底部，让用户能看上下文）
        }
    }

    // ------------------ 工具 ------------------
    function escapeHtml(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

})();
