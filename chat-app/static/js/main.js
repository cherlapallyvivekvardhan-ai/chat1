(() => {
  "use strict";

  // ---- elements ----
  const joinScreen   = document.getElementById("join-screen");
  const chatScreen   = document.getElementById("chat-screen");
  const usernameInput= document.getElementById("username-input");
  const roomSelect   = document.getElementById("room-select");
  const joinBtn      = document.getElementById("join-btn");
  const joinError    = document.getElementById("join-error");

  const roomList     = document.getElementById("room-list");
  const rosterList   = document.getElementById("roster-list");
  const rosterCount  = document.getElementById("roster-count");
  const connDot      = document.getElementById("conn-dot");
  const connLabel    = document.getElementById("conn-label");
  const currentRoomEl= document.getElementById("current-room");
  const sessionIdEl  = document.getElementById("session-id");
  const meNameEl     = document.getElementById("me-name");
  const log          = document.getElementById("log");
  const typingStrip  = document.getElementById("typing-strip");
  const composer     = document.getElementById("composer");
  const messageInput = document.getElementById("message-input");

  // ---- state ----
  let socket = null;
  let me = "";
  let room = "general";
  let typingTimeout = null;

  // Deterministic color per username so people are visually recognizable
  // across the session without server-assigned colors.
  const PALETTE = ["#00C2A8", "#FFB454", "#7FA8FF", "#FF8FB3", "#B893FF", "#6FDB8F"];
  function colorFor(name) {
    let h = 0;
    for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
    return PALETTE[h % PALETTE.length];
  }

  function fmtTime(iso) {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function scrollToBottom() {
    log.scrollTop = log.scrollHeight;
  }

  function renderMessage(msg) {
    const wrap = document.createElement("div");
    wrap.className = "msg" + (msg.kind === "system" ? " system" : "");

    if (msg.kind !== "system") {
      const avatar = document.createElement("div");
      avatar.className = "avatar";
      avatar.style.background = colorFor(msg.username);
      avatar.textContent = msg.username.slice(0, 2).toUpperCase();
      wrap.appendChild(avatar);
    }

    const col = document.createElement("div");
    col.className = "body-col";

    if (msg.kind !== "system") {
      const head = document.createElement("div");
      head.className = "msg-head";
      const user = document.createElement("span");
      user.className = "msg-user";
      user.style.color = colorFor(msg.username);
      user.textContent = msg.username;
      const time = document.createElement("span");
      time.className = "msg-time";
      time.textContent = fmtTime(msg.created_at);
      head.appendChild(user);
      head.appendChild(time);
      col.appendChild(head);
    }

    const body = document.createElement("div");
    body.className = "msg-body";
    body.textContent = msg.kind === "system"
      ? `· ${msg.body} · ${fmtTime(msg.created_at)}`
      : msg.body;
    col.appendChild(body);

    wrap.appendChild(col);
    log.appendChild(wrap);
  }

  function renderHistory(messages) {
    log.innerHTML = "";
    messages.forEach(renderMessage);
    scrollToBottom();
  }

  function renderRoster(users) {
    rosterList.innerHTML = "";
    rosterCount.textContent = users.length;
    users.forEach((u) => {
      const li = document.createElement("li");
      li.textContent = u + (u === me ? " (you)" : "");
      rosterList.appendChild(li);
    });
  }

  function renderTyping(users) {
    const others = users.filter((u) => u !== me);
    if (others.length === 0) {
      typingStrip.hidden = true;
      typingStrip.textContent = "";
      return;
    }
    typingStrip.hidden = false;
    const verb = others.length === 1 ? "is" : "are";
    typingStrip.textContent = `${others.join(", ")} ${verb} typing…`;
  }

  function setActiveRoomItem(activeRoom) {
    [...roomList.children].forEach((li) => {
      li.classList.toggle("active", li.dataset.room === activeRoom);
    });
  }

  // ---- connection lifecycle ----

  function connectSocket() {
    socket = io({ transports: ["websocket", "polling"] });

    socket.on("connect", () => {
      connDot.classList.add("live");
      connLabel.textContent = "connected";
      sessionIdEl.textContent = socket.id.slice(0, 8);
      socket.emit("join", { username: me, room });
    });

    socket.on("disconnect", () => {
      connDot.classList.remove("live");
      connLabel.textContent = "disconnected — retrying…";
    });

    socket.on("join_error", (data) => {
      // If this happens before the chat screen is shown, it's the initial
      // join attempt; surface it on the join form instead of the chat log.
      if (chatScreen.hidden) {
        joinError.textContent = data.message;
        joinError.hidden = false;
        joinBtn.disabled = false;
      } else {
        joinError.hidden = false;
      }
    });

    socket.on("history", (data) => {
      if (data.room !== room) return;
      renderHistory(data.messages);
    });

    socket.on("message", (msg) => {
      if (msg.room !== room) return;
      renderMessage(msg);
      scrollToBottom();
    });

    socket.on("roster", (data) => {
      if (data.room !== room) return;
      renderRoster(data.users);
    });

    socket.on("typing", (data) => {
      if (data.room !== room) return;
      renderTyping(data.users);
    });
  }

  // ---- join flow ----

  function attemptJoin() {
    const name = usernameInput.value.trim();
    if (!name) {
      joinError.textContent = "Enter a display name to continue.";
      joinError.hidden = false;
      return;
    }
    joinError.hidden = true;
    joinBtn.disabled = true;

    me = name;
    room = roomSelect.value;

    meNameEl.textContent = me;
    currentRoomEl.textContent = room;
    messageInput.placeholder = `Message #${room}`;
    setActiveRoomItem(room);

    joinScreen.hidden = true;
    chatScreen.hidden = false;
    joinBtn.disabled = false;

    connectSocket();
    messageInput.focus();
  }

  joinBtn.addEventListener("click", attemptJoin);
  usernameInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") attemptJoin();
  });

  // ---- room switching ----

  roomList.addEventListener("click", (e) => {
    const li = e.target.closest(".room-item");
    if (!li || !socket) return;
    const newRoom = li.dataset.room;
    if (newRoom === room) return;

    room = newRoom;
    currentRoomEl.textContent = room;
    messageInput.placeholder = `Message #${room}`;
    setActiveRoomItem(room);
    typingStrip.hidden = true;

    socket.emit("switch_room", { room });
  });

  // ---- composer ----

  composer.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = messageInput.value.trim();
    if (!text || !socket) return;
    socket.emit("send_message", { body: text });
    socket.emit("typing", { is_typing: false });
    messageInput.value = "";
  });

  messageInput.addEventListener("input", () => {
    if (!socket) return;
    socket.emit("typing", { is_typing: true });
    clearTimeout(typingTimeout);
    typingTimeout = setTimeout(() => {
      socket.emit("typing", { is_typing: false });
    }, 2500);
  });
})();
