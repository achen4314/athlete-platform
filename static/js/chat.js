/**
 * 运动员平台 — AI 对话 JS
 * SSE 流式响应 · Markdown 渲染 · 快捷提示 · 自动滚动
 */
(function() {
  'use strict';

  /* ========== DOM 引用 ========== */
  var chatMessages  = document.getElementById('chatMessages');
  var chatInput     = document.getElementById('chatInput');
  var sendBtn       = document.getElementById('sendBtn');
  var quickPrompts  = document.getElementById('quickPrompts');

  /* ========== 状态 ========== */
  var isStreaming  = false;
  var currentEventSource = null;
  var thinkingEl   = null;

  /* ========== Markdown 渲染 ========== */
  function renderMarkdown(text) {
    if (!text) return '';

    // 转义 HTML
    var escaped = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // 代码块 ```
    escaped = escaped.replace(/```(\w*)\n([\s\S]*?)```/g, function(_, lang, code) {
      return '<pre><code class="language-' + (lang || 'plaintext') + '">' + code.trim() + '</code></pre>';
    });

    // 行内代码 `
    escaped = escaped.replace(/`([^`]+)`/g, '<code>$1</code>');

    // 粗体 **
    escaped = escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // 斜体 *
    escaped = escaped.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // 标题 ### ... ## ... #
    escaped = escaped.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    escaped = escaped.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    escaped = escaped.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // 无序列表
    escaped = escaped.replace(/^[\-\*] (.+)$/gm, '<li>$1</li>');
    escaped = escaped.replace(/(<li>[\s\S]*?<\/li>)/g, function(match) {
      if (!match.startsWith('<ul>')) {
        return '<ul>' + match + '</ul>';
      }
      return match;
    });

    // 有序列表
    escaped = escaped.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

    // 分隔线 ---
    escaped = escaped.replace(/^---$/gm, '<hr>');

    // 换行 → <br> → <p> 包裹
    var paragraphs = escaped.split(/\n\n+/);
    paragraphs = paragraphs.map(function(p) {
      p = p.trim();
      if (!p) return '';
      // 如果已经是 block 元素，不包裹
      if (/^<(h[1-3]|ul|ol|pre|hr|li)/.test(p)) return p;
      // 行内换行 → <br>
      p = p.replace(/\n/g, '<br>');
      return '<p>' + p + '</p>';
    });

    return paragraphs.join('\n');
  }

  /* ========== 辅助函数 ========== */

  /** 创建一条消息元素 */
  function createMessageElement(role) {
    var msg = document.createElement('div');
    msg.className = 'message ' + role + ' animate-fade-up';

    var avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    avatar.textContent = role === 'user' ? '我' : '🏃';

    var bubble = document.createElement('div');
    bubble.className = 'msg-bubble';

    msg.appendChild(avatar);
    msg.appendChild(bubble);
    return msg;
  }

  /** 滚动到底部 */
  function scrollToBottom() {
    if (chatMessages) {
      chatMessages.scrollTop = chatMessages.scrollHeight;
    }
  }

  /** 实时滚动（流式输出时用 requestAnimationFrame 节流） */
  var scrollRAF = null;
  function smoothScrollToBottom() {
    if (scrollRAF) return;
    scrollRAF = requestAnimationFrame(function() {
      scrollToBottom();
      scrollRAF = null;
    });
  }

  /** 移除思考动画 */
  function removeThinking() {
    if (thinkingEl) {
      thinkingEl.remove();
      thinkingEl = null;
    }
  }

  /** 创建 "正在思考..." 动画 */
  function createThinking() {
    removeThinking();

    var msg = document.createElement('div');
    msg.className = 'message assistant animate-fade-up';

    var avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    avatar.textContent = '🏃';

    var bubble = document.createElement('div');
    bubble.className = 'msg-bubble thinking-indicator';

    bubble.innerHTML = '<span class="thinking-dot"></span>' +
                       '<span class="thinking-dot"></span>' +
                       '<span class="thinking-dot"></span>' +
                       '<span class="thinking-text">正在思考...</span>';

    msg.appendChild(avatar);
    msg.appendChild(bubble);

    chatMessages.appendChild(msg);
    thinkingEl = msg;
    scrollToBottom();
  }

  /** 禁用/启用输入 */
  function setInputEnabled(enabled) {
    chatInput.disabled = !enabled;
    sendBtn.disabled   = !enabled;
    if (enabled) {
      chatInput.focus();
    }
  }

  /* ========== 发送消息 ========== */

  function sendMessage(messageText) {
    if (isStreaming) return;
    if (!messageText || !messageText.trim()) return;

    messageText = messageText.trim();
    isStreaming = true;
    setInputEnabled(false);

    // 添加用户消息
    var userMsg = createMessageElement('user');
    userMsg.querySelector('.msg-bubble').textContent = messageText;
    chatMessages.appendChild(userMsg);
    scrollToBottom();

    // 思考动画
    createThinking();

    // 清空输入
    chatInput.value = '';
    chatInput.style.height = 'auto';

    // 发起 SSE 请求
    var encodedMsg = encodeURIComponent(messageText);
    var sseUrl = '/api/chat/stream?message=' + encodedMsg;

    var es = new EventSource(sseUrl);
    currentEventSource = es;

    var assistantMsg   = null;
    var assistantBubble = null;
    var fullContent     = '';

    es.addEventListener('message', function(event) {
      // 首次收到消息时移除思考动画并创建真实消息
      if (!assistantMsg) {
        removeThinking();
        assistantMsg = createMessageElement('assistant');
        assistantBubble = assistantMsg.querySelector('.msg-bubble');
        chatMessages.appendChild(assistantMsg);
      }

      var data;
      try {
        data = JSON.parse(event.data);
      } catch(e) {
        data = { content: event.data };
      }

      // 检测 API 密钥未配置错误
      if (data.error && data.error.indexOf('API') !== -1) {
        assistantBubble.innerHTML = '<span style="color:#ff6b6b;">⚠️ ' + data.error + '</span>';
        showApiKeyWarning();
        closeSSE();
        return;
      }

      if (data.token !== undefined) {
        fullContent += data.token;
        assistantBubble.innerHTML = renderMarkdown(fullContent);
        smoothScrollToBottom();
      }

      if (data.done) {
        closeSSE();
      }
    });

    es.addEventListener('error', function(event) {
      removeThinking();

      if (!assistantMsg) {
        assistantMsg = createMessageElement('assistant');
        assistantBubble = assistantMsg.querySelector('.msg-bubble');
        chatMessages.appendChild(assistantMsg);
      }

      if (fullContent) {
        assistantBubble.innerHTML = renderMarkdown(fullContent);
      } else {
        assistantBubble.innerHTML = '⚠️ 连接中断，请检查 API 配置后重试。';
        showApiKeyWarning();
      }

      closeSSE();
      scrollToBottom();
    });

    es.addEventListener('open', function() {
      // SSE 连接已建立
    });
  }

  function showApiKeyWarning() {
    var warning = document.getElementById('apiKeyWarning');
    if (warning) {
      warning.style.display = 'block';
      // 禁快速提示
      var prompts = document.getElementById('quickPrompts');
      if (prompts) prompts.style.opacity = '0.5';
    }
  }

  function closeSSE() {
    if (currentEventSource) {
      currentEventSource.close();
      currentEventSource = null;
    }
    removeThinking();
    isStreaming = false;
    setInputEnabled(true);
    scrollToBottom();
  }

  /* ========== 事件绑定 ========== */

  // 发送按钮
  sendBtn.addEventListener('click', function() {
    sendMessage(chatInput.value);
  });

  // Enter 发送，Shift+Enter 换行
  chatInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(chatInput.value);
    }
  });

  // 自动调整输入框高度
  chatInput.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
  });

  // 快捷提示
  if (quickPrompts) {
    quickPrompts.addEventListener('click', function(e) {
      var btn = e.target.closest('.quick-prompt-btn');
      if (!btn) return;
      var prompt = btn.getAttribute('data-prompt');
      if (prompt) {
        chatInput.value = prompt;
        chatInput.focus();
        sendMessage(prompt);
      }
    });
  }

  // 初始聚焦
  setTimeout(function() {
    chatInput.focus();
  }, 300);

})();
