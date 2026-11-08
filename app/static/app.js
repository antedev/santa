// Julklappsspelet – Frontend Logic

let appState = null;
let selectedLoginUserId = null;
let currentInviteToken = null; // From URL ?u=...
let currentInviteInfo = null;  // { id, name, is_kid, has_account, invite_token }
let resetPinMode = false;
let currentSession = null;     // { user, assignment, password }
let adminViewOpen = false;
let adminInvitesCache = [];

// --- Utilities ---

function showToast(msg, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.toggle("error", isError);
  el.classList.remove("hidden");
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => {
    el.classList.add("hidden");
  }, 3800);
}

async function apiRequest(url, method = "GET", body = null) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body !== null) {
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || "Ett oväntat fel uppstod.");
  }
  return data;
}

function getAdminPassword() {
  return document.getElementById("adminPasswordInput").value || "";
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function buildPersonalLink(token) {
  return `${window.location.origin}/?u=${encodeURIComponent(token)}`;
}

// --- Snowflakes ---

function initSnowflakes() {
  const container = document.getElementById("snowContainer");
  const glyphs = ["❄", "❅", "❆", "✦"];
  for (let i = 0; i < 20; i++) {
    const span = document.createElement("span");
    span.className = "snowflake";
    span.textContent = glyphs[i % glyphs.length];
    span.style.left = `${Math.random() * 100}%`;
    span.style.fontSize = `${0.7 + Math.random() * 0.85}rem`;
    span.style.animationDuration = `${9 + Math.random() * 12}s`;
    span.style.animationDelay = `${Math.random() * 8}s`;
    container.appendChild(span);
  }
}

// --- Tabs ---

function switchTab(tabId) {
  const buttons = document.querySelectorAll(".tab-btn");
  const panels = document.querySelectorAll(".tab-panel");
  buttons.forEach((b) => b.classList.toggle("active", b.dataset.tab === tabId));
  panels.forEach((p) => p.classList.toggle("active", p.id === tabId));
}

function initTabs() {
  const buttons = document.querySelectorAll(".tab-btn");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      if (!currentSession && btn.dataset.tab !== "tab-admin") {
        adminViewOpen = false;
        renderLayoutVisibility();
        return;
      }
      switchTab(btn.dataset.tab);
    });
  });
}

// --- URL Invite Token Inspection ---

async function checkInviteUrlToken() {
  const params = new URLSearchParams(window.location.search);
  const token = params.get("u");
  if (!token) return;
  try {
    const info = await apiRequest(`/api/invite/${encodeURIComponent(token)}`);
    currentInviteToken = token;
    currentInviteInfo = info;
    selectedLoginUserId = info.id;
  } catch (err) {
    showToast(err.message, true);
  }
}

// --- State Loading & Rendering ---

async function loadState() {
  try {
    appState = await apiRequest("/api/state");
    document.getElementById("eventTitle").textContent = `🎄 ${appState.event_title}`;
    document.getElementById("budgetInfo").textContent = appState.budget_info;

    renderLayoutVisibility();
    renderLoginScreen();
    renderUserDashboard();
    renderKidsWishlists();
    renderChainVerification();
    if (adminViewOpen) {
      await loadAdminInvites();
    }
    renderAdminPanel();
  } catch (err) {
    showToast(err.message, true);
  }
}

function renderLayoutVisibility() {
  const loginScreen = document.getElementById("loginScreen");
  const mainNav = document.getElementById("mainNav");
  const appContent = document.getElementById("appContent");
  const userBar = document.getElementById("userBar");
  const adminTabBtn = document.getElementById("adminTabBtn");

  if (!currentSession && !adminViewOpen) {
    loginScreen.classList.remove("hidden");
    mainNav.classList.add("hidden");
    appContent.classList.add("hidden");
  } else if (!currentSession && adminViewOpen) {
    loginScreen.classList.add("hidden");
    mainNav.classList.remove("hidden");
    appContent.classList.remove("hidden");
    userBar.classList.add("hidden");
    adminTabBtn.classList.remove("hidden");
    switchTab("tab-admin");
  } else {
    loginScreen.classList.add("hidden");
    mainNav.classList.remove("hidden");
    appContent.classList.remove("hidden");
    userBar.classList.remove("hidden");
    adminTabBtn.classList.toggle("hidden", !adminViewOpen);
  }
}

// --- Login Screen ---

function createNameTile(p) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = `user-tile ${selectedLoginUserId === p.id ? "selected" : ""}`;
  btn.textContent = p.name;
  btn.addEventListener("click", () => {
    selectedLoginUserId = p.id;
    renderLoginScreen();
    updateLoginFormPrompt(p);
  });
  return btn;
}

function updateLoginFormPrompt(p) {
  const loginForm = document.getElementById("loginForm");
  const needInviteNotice = document.getElementById("needInviteNotice");
  const resetPinToggleBtn = document.getElementById("resetPinToggleBtn");
  const loginSubmitBtn = document.getElementById("loginSubmitBtn");
  const hasMatchingToken = currentInviteInfo && currentInviteInfo.id === p.id;

  if (!p.has_account && !hasMatchingToken) {
    loginForm.classList.add("hidden");
    needInviteNotice.classList.remove("hidden");
    return;
  }

  needInviteNotice.classList.add("hidden");
  loginForm.classList.remove("hidden");

  // Show "Glömt PIN? Välj ny" if user is on their personal link and already has a PIN
  if (p.has_account && hasMatchingToken) {
    resetPinToggleBtn.classList.remove("hidden");
    resetPinToggleBtn.textContent = resetPinMode ? "Avbryt" : "Glömt PIN? Välj ny";
  } else {
    resetPinMode = false;
    resetPinToggleBtn.classList.add("hidden");
  }

  if (!p.has_account || resetPinMode) {
    document.getElementById("passwordPromptLabel").textContent = `Välj ny PIN-kod:`;
    loginSubmitBtn.textContent = "Spara & logga in 🎄";
  } else {
    document.getElementById("passwordPromptLabel").textContent = `Ange din PIN-kod:`;
    loginSubmitBtn.textContent = "Logga in 🎄";
  }
  document.getElementById("loginPassword").focus();
}

function renderLoginScreen() {
  const inviteBanner = document.getElementById("inviteBanner");
  const namePickerArea = document.getElementById("namePickerArea");
  const adultsGrid = document.getElementById("loginUserGrid");
  const kidsGrid = document.getElementById("loginKidsGrid");
  const kidsDivider = document.getElementById("kidsLoginDivider");

  if (currentInviteInfo) {
    const freshUser = appState.participants.find((u) => u.id === currentInviteInfo.id);
    if (freshUser) {
      currentInviteInfo.has_account = freshUser.has_account;
      selectedLoginUserId = freshUser.id;
      inviteBanner.classList.remove("hidden");
      namePickerArea.classList.add("hidden");
      document.getElementById("inviteUserName").textContent = freshUser.name;
      document.getElementById("inviteSubtext").textContent =
        !freshUser.has_account || resetPinMode
          ? "Välj en PIN-kod för att logga in."
          : "Ange din PIN-kod för att logga in.";
      updateLoginFormPrompt(freshUser);
      return;
    }
  }

  inviteBanner.classList.add("hidden");
  namePickerArea.classList.remove("hidden");

  adultsGrid.innerHTML = "";
  kidsGrid.innerHTML = "";

  const adults = appState.participants.filter((p) => !p.is_kid);
  const kids = appState.participants.filter((p) => p.is_kid);

  adults.forEach((p) => adultsGrid.appendChild(createNameTile(p)));

  if (kids.length > 0) {
    kidsDivider.classList.remove("hidden");
    kidsGrid.classList.remove("hidden");
    kids.forEach((p) => kidsGrid.appendChild(createNameTile(p)));
  } else {
    kidsDivider.classList.add("hidden");
    kidsGrid.classList.add("hidden");
  }

  if (selectedLoginUserId) {
    const sel = appState.participants.find((p) => p.id === selectedLoginUserId);
    if (sel) updateLoginFormPrompt(sel);
  }
}

// --- Logged-In User Dashboard ---

function renderUserDashboard() {
  if (!currentSession) return;

  const { user, assignment } = currentSession;
  document.getElementById("loggedInName").textContent = user.name;

  const wlInput = document.getElementById("myWishlistInput");
  if (document.activeElement !== wlInput) {
    wlInput.value = user.wishlist || "";
  }

  const drawNotReadyBox = document.getElementById("drawNotReadyBox");
  const lotteryMachineBox = document.getElementById("lotteryMachineBox");
  const matchRevealedBox = document.getElementById("matchRevealedBox");

  if (!appState.draw_generated || !assignment) {
    drawNotReadyBox.classList.remove("hidden");
    lotteryMachineBox.classList.add("hidden");
    matchRevealedBox.classList.add("hidden");
    return;
  }

  drawNotReadyBox.classList.add("hidden");

  // Customize copy slightly for kids vs adults
  if (user.is_kid) {
    document.getElementById("lotteryHeading").textContent = "Vill du vara med och ge en bonusklapp?";
    document.getElementById("lotterySubtext").textContent =
      "Om du också vill vara med i det hemliga julklappsspelet kan du dra en egen lott här!";
    document.getElementById("revealOverline").textContent = "Din hemliga bonusklapp går till:";
  } else {
    document.getElementById("lotteryHeading").textContent = "Dra din julklappslott!";
    document.getElementById("lotterySubtext").textContent =
      "Tryck på knappen för att dra vem du ska köpa julklapp till i år.";
    document.getElementById("revealOverline").textContent = "Du ska köpa en julklapp till:";
  }

  if (!user.has_drawn_lot) {
    lotteryMachineBox.classList.remove("hidden");
    matchRevealedBox.classList.add("hidden");
    document.getElementById("slotText").textContent = "🎁 Redo att dra lott 🎁";
  } else {
    lotteryMachineBox.classList.add("hidden");
    matchRevealedBox.classList.remove("hidden");
    populateMatchReveal(assignment);
  }
}

function populateMatchReveal(assignment) {
  document.getElementById("myAliasText").textContent = assignment.my_alias;
  document.getElementById("targetPersonName").textContent = assignment.target_name;
  document.getElementById("targetWishlistOwner").textContent = assignment.target_name;

  const latestTarget = appState.participants.find((p) => p.id === assignment.target_id);
  const wishlistText = latestTarget ? latestTarget.wishlist : assignment.target_wishlist;
  document.getElementById("targetWishlistText").textContent =
    wishlistText && wishlistText.trim()
      ? wishlistText
      : "Har inte skrivit någon önskelista ännu.";
}

async function runLotteryWheelAnimation(finalName) {
  const slotWindow = document.getElementById("slotWindow");
  const slotText = document.getElementById("slotText");
  const spinBtn = document.getElementById("spinLotteryBtn");

  spinBtn.disabled = true;
  slotWindow.classList.add("spinning");

  const adultNames = appState.participants
    .filter((p) => !p.is_kid)
    .map((p) => p.name);
  const pool = adultNames.length > 0 ? adultNames : [finalName];
  const totalSteps = 22;
  for (let i = 0; i < totalSteps; i++) {
    const candidate = pool[i % pool.length];
    slotText.textContent = `🎰 ${candidate}...`;
    const delay = 60 + Math.floor((i / totalSteps) ** 2 * 180);
    await new Promise((r) => setTimeout(r, delay));
  }

  slotWindow.classList.remove("spinning");
  slotText.textContent = `🎉 ${finalName}! 🎉`;
  await new Promise((r) => setTimeout(r, 700));
  spinBtn.disabled = false;
}

// --- Tab 2: Barnens önskelistor (Louise, Josefin & Elise) ---

function renderKidsWishlists() {
  const container = document.getElementById("kidsListContainer");
  container.innerHTML = "";

  const kids = appState.participants.filter((p) => p.is_kid);
  kids.forEach((kid) => {
    const card = document.createElement("div");
    card.className = "kid-card";
    card.innerHTML = `
      <h3>👶 ${escapeHtml(kid.name)}</h3>
      <p class="wishlist-content" style="margin:0.35rem 0 0;">${
        kid.wishlist && kid.wishlist.trim()
          ? escapeHtml(kid.wishlist)
          : '<span class="muted">Har inte skrivit någon önskelista ännu.</span>'
      }</p>
    `;
    container.appendChild(card);
  });
}

// --- Tab 3: Kedjan ---

function renderChainVerification() {
  const chainBox = document.getElementById("chainVisualization");
  const statusGrid = document.getElementById("aliasStatusGrid");

  chainBox.innerHTML = "";
  statusGrid.innerHTML = "";

  if (!appState.draw_generated || appState.alias_cycle.length === 0) {
    chainBox.innerHTML = `<span class="muted">Ingen kedja genererad än.</span>`;
    return;
  }

  appState.alias_cycle.forEach((alias) => {
    const node = document.createElement("span");
    node.className = "chain-node";
    node.textContent = `🎭 ${alias}`;
    chainBox.appendChild(node);

    const arrow = document.createElement("span");
    arrow.className = "chain-arrow";
    arrow.textContent = "➔";
    chainBox.appendChild(arrow);
  });

  const firstNode = document.createElement("span");
  firstNode.className = "chain-node loop-back";
  firstNode.textContent = `🎭 ${appState.alias_cycle[0]}`;
  chainBox.appendChild(firstNode);

  appState.alias_board.forEach((item) => {
    const card = document.createElement("div");
    card.className = `alias-card ${item.has_drawn ? "drawn" : ""}`;
    const bonusBadge = item.is_kid_bonus ? " (Bonuslott)" : "";
    card.innerHTML = `
      <strong>🎭 ${escapeHtml(item.alias_name)}${bonusBadge}</strong>
      <span class="tag">${item.has_drawn ? "✅ Dragit lott" : "⏳ Väntar"}</span>
    `;
    statusGrid.appendChild(card);
  });
}

// --- Tab 4: Admin Panel & Personal Links ---

async function loadAdminInvites() {
  try {
    const res = await apiRequest("/api/admin/invites", "POST", {
      admin_password: getAdminPassword(),
    });
    adminInvitesCache = res.invites || [];
  } catch (_) {
    adminInvitesCache = [];
  }
}

function renderAdminPanel() {
  const lockedBanner = document.getElementById("liveLockedBanner");
  const editableArea = document.getElementById("adminEditableArea");
  const goLiveBtn = document.getElementById("goLiveBtn");

  if (appState.is_live) {
    lockedBanner.classList.remove("hidden");
    editableArea.classList.add("hidden");
    goLiveBtn.classList.add("hidden");
  } else {
    lockedBanner.classList.add("hidden");
    editableArea.classList.remove("hidden");
    goLiveBtn.classList.remove("hidden");
  }

  // Personal Invite Links
  const invitesEl = document.getElementById("adminInvitesList");
  invitesEl.innerHTML = "";
  if (adminInvitesCache.length === 0) {
    invitesEl.innerHTML = `<span class="muted">Ange rätt admin-lösenord och klicka "Ladda" för att se de personliga länkarna.</span>`;
  } else {
    adminInvitesCache.forEach((inv) => {
      const url = buildPersonalLink(inv.invite_token);
      const statusBadge = inv.has_account
        ? `<span class="tag" style="background:rgba(69,184,119,0.2);color:#7ef0ae;">🔒 PIN vald</span>`
        : `<span class="tag">⏳ Ej öppnad än</span>`;
      const row = document.createElement("div");
      row.className = "admin-item-row";
      row.style.gridTemplateColumns = "1fr auto 1.8fr auto";
      row.innerHTML = `
        <strong>${escapeHtml(inv.name)} ${inv.is_kid ? "👶" : "🎅"}</strong>
        ${statusBadge}
        <input type="text" readonly value="${escapeHtml(url)}" onclick="this.select()" />
        <button type="button" class="btn btn-outline btn-sm" onclick="copySingleLink('${escapeHtml(inv.name)}', '${escapeHtml(inv.invite_token)}')">
          📋 Kopiera
        </button>
      `;
      invitesEl.appendChild(row);
    });
  }

  const listEl = document.getElementById("adminParticipantsList");
  listEl.innerHTML = "";
  appState.participants.forEach((p) => {
    const row = document.createElement("div");
    row.className = "admin-item-row";
    row.innerHTML = `
      <input type="text" value="${escapeHtml(p.name)}" id="editName_${p.id}" />
      <select id="editRole_${p.id}">
        <option value="adult" ${!p.is_kid ? "selected" : ""}>🎅 Vuxen</option>
        <option value="kid" ${p.is_kid ? "selected" : ""}>👶 Barn</option>
      </select>
      <input type="text" value="${escapeHtml(p.wishlist)}" id="editWish_${p.id}" placeholder="Önskelista..." />
      <div class="button-group">
        <button type="button" class="btn btn-outline btn-sm" onclick="saveParticipant(${p.id})">Spara</button>
        <button type="button" class="btn btn-danger" onclick="removeParticipant(${p.id})">✕</button>
      </div>
    `;
    listEl.appendChild(row);
  });

  const exclList = document.getElementById("adminExclusionsList");
  exclList.innerHTML = "";
  appState.exclusions.forEach((ex) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.innerHTML = `
      <span>${escapeHtml(ex.user_a_name)} ↔ ${escapeHtml(ex.user_b_name)}</span>
      <button type="button" class="btn btn-danger" onclick="removeExclusion(${ex.id})">✕</button>
    `;
    exclList.appendChild(chip);
  });

  const adults = appState.participants.filter((p) => !p.is_kid);
  const selA = document.getElementById("exclUserA");
  const selB = document.getElementById("exclUserB");
  selA.innerHTML = "";
  selB.innerHTML = "";
  adults.forEach((a, idx) => {
    const optA = document.createElement("option");
    optA.value = a.id;
    optA.textContent = a.name;
    if (idx === 0) optA.selected = true;
    selA.appendChild(optA);

    const optB = document.createElement("option");
    optB.value = a.id;
    optB.textContent = a.name;
    if (idx === 1) optB.selected = true;
    selB.appendChild(optB);
  });

  const devBox = document.getElementById("devInspectorBox");
  const devTableContainer = document.getElementById("devCycleTableContainer");
  if (appState.dev_mode_enabled && appState.dev_debug_cycle && appState.dev_debug_cycle.length > 0) {
    devBox.classList.remove("hidden");
    const rowsHtml = appState.dev_debug_cycle
      .map(
        (step) => `
        <tr>
          <td><strong>${escapeHtml(step.giver_name)}</strong> (${escapeHtml(step.giver_alias)})${step.is_kid_bonus ? " 👶 Bonus" : ""}</td>
          <td>➔</td>
          <td><strong>${escapeHtml(step.target_name)}</strong></td>
        </tr>
      `
      )
      .join("");
    devTableContainer.innerHTML = `
      <table class="dev-table">
        <tbody>${rowsHtml}</tbody>
      </table>
    `;
  } else {
    devBox.classList.add("hidden");
    devTableContainer.innerHTML = "";
  }
}

window.copySingleLink = async function (name, token) {
  const url = buildPersonalLink(token);
  await navigator.clipboard.writeText(url);
  showToast(`Kopierade länk för ${name}! 📋`);
};

window.saveParticipant = async function (userId) {
  try {
    const name = document.getElementById(`editName_${userId}`).value;
    const is_kid = document.getElementById(`editRole_${userId}`).value === "kid";
    const wishlist = document.getElementById(`editWish_${userId}`).value;
    await apiRequest(`/api/admin/participants/${userId}`, "PUT", {
      admin_password: getAdminPassword(),
      name,
      is_kid,
      wishlist,
    });
    showToast("Deltagaren sparades!");
    await loadState();
  } catch (err) {
    showToast(err.message, true);
  }
};

window.removeParticipant = async function (userId) {
  try {
    const q = new URLSearchParams({ admin_password: getAdminPassword() });
    await apiRequest(`/api/admin/participants/${userId}?${q.toString()}`, "DELETE");
    showToast("Deltagaren togs bort.");
    await loadState();
  } catch (err) {
    showToast(err.message, true);
  }
};

window.removeExclusion = async function (exclId) {
  try {
    const q = new URLSearchParams({ admin_password: getAdminPassword() });
    await apiRequest(`/api/admin/exclusions/${exclId}?${q.toString()}`, "DELETE");
    showToast("Undantaget togs bort.");
    await loadState();
  } catch (err) {
    showToast(err.message, true);
  }
};

// --- Event Listeners ---

document.addEventListener("DOMContentLoaded", async () => {
  initSnowflakes();
  initTabs();
  await checkInviteUrlToken();
  await loadState();

  // Switch back from personal link view to all users list if desired
  document.getElementById("showAllUsersBtn").addEventListener("click", () => {
    currentInviteInfo = null;
    currentInviteToken = null;
    selectedLoginUserId = null;
    resetPinMode = false;
    window.history.replaceState({}, "", "/");
    document.getElementById("loginForm").classList.add("hidden");
    document.getElementById("needInviteNotice").classList.add("hidden");
    renderLoginScreen();
  });

  // Toggle Reset PIN mode when on personal link
  document.getElementById("resetPinToggleBtn").addEventListener("click", () => {
    resetPinMode = !resetPinMode;
    renderLoginScreen();
  });

  // Login Form
  document.getElementById("loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!selectedLoginUserId) return;
    const password = document.getElementById("loginPassword").value;
    try {
      const res = await apiRequest("/api/auth/login", "POST", {
        user_id: selectedLoginUserId,
        password,
        invite_token: currentInviteToken,
        reset_pin: resetPinMode,
      });
      currentSession = {
        user: res.user,
        assignment: res.assignment,
        password,
      };
      resetPinMode = false;
      adminViewOpen = false;
      document.getElementById("loginPassword").value = "";
      switchTab("tab-my-santa");
      await loadState();
    } catch (err) {
      showToast(err.message, true);
    }
  });

  // Logout
  document.getElementById("logoutBtn").addEventListener("click", () => {
    currentSession = null;
    if (!currentInviteInfo) {
      selectedLoginUserId = null;
    }
    adminViewOpen = false;
    document.getElementById("loginForm").classList.add("hidden");
    loadState();
  });

  // Discreet Admin Button in Footer
  document.getElementById("openAdminFooterBtn").addEventListener("click", async () => {
    adminViewOpen = !adminViewOpen;
    if (adminViewOpen) {
      await loadAdminInvites();
      renderAdminPanel();
    }
    renderLayoutVisibility();
    if (adminViewOpen) {
      switchTab("tab-admin");
    } else if (currentSession) {
      switchTab("tab-my-santa");
    }
  });

  document.getElementById("unlockAdminBtn").addEventListener("click", async () => {
    await loadAdminInvites();
    renderAdminPanel();
    showToast("Admin-länkar uppdaterade!");
  });

  document.getElementById("copyAllLinksBtn").addEventListener("click", async () => {
    if (adminInvitesCache.length === 0) {
      await loadAdminInvites();
    }
    if (adminInvitesCache.length === 0) {
      showToast("Kunde inte hämta länkar – kontrollera admin-lösenordet.", true);
      return;
    }
    const lines = adminInvitesCache.map(
      (inv) => `${inv.name}: ${buildPersonalLink(inv.invite_token)}`
    );
    await navigator.clipboard.writeText(lines.join("\n"));
    showToast("Alla personliga länkar kopierades! 📋");
  });

  // Spin Lottery Wheel (Both Adults and Kids!)
  document.getElementById("spinLotteryBtn").addEventListener("click", async () => {
    if (!currentSession) return;
    try {
      const res = await apiRequest("/api/user/draw-lot", "POST", {
        user_id: currentSession.user.id,
        password: currentSession.password,
        invite_token: currentInviteToken,
      });
      await runLotteryWheelAnimation(res.assignment.target_name);
      currentSession.user = res.user;
      currentSession.assignment = res.assignment;
      await loadState();
    } catch (err) {
      showToast(err.message, true);
    }
  });

  // Save Wishlist
  document.getElementById("wishlistForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!currentSession) return;
    const wishlist = document.getElementById("myWishlistInput").value;
    try {
      const res = await apiRequest("/api/user/wishlist", "POST", {
        user_id: currentSession.user.id,
        password: currentSession.password,
        wishlist,
      });
      currentSession.user.wishlist = res.wishlist;
      await loadState();
      showToast("Önskelistan är sparad! ✨");
    } catch (err) {
      showToast(err.message, true);
    }
  });

  // Admin Add Participant
  document.getElementById("adminAddParticipantForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("newPartName").value;
    const is_kid = document.getElementById("newPartRole").value === "kid";
    const wishlist = document.getElementById("newPartWishlist").value;
    try {
      await apiRequest("/api/admin/participants", "POST", {
        admin_password: getAdminPassword(),
        name,
        is_kid,
        wishlist,
      });
      document.getElementById("newPartName").value = "";
      document.getElementById("newPartWishlist").value = "";
      await loadState();
      showToast(`${name} lades till!`);
    } catch (err) {
      showToast(err.message, true);
    }
  });

  // Admin Add Exclusion
  document.getElementById("adminAddExclusionForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const user_a_id = Number(document.getElementById("exclUserA").value);
    const user_b_id = Number(document.getElementById("exclUserB").value);
    try {
      await apiRequest("/api/admin/exclusions", "POST", {
        admin_password: getAdminPassword(),
        user_a_id,
        user_b_id,
      });
      await loadState();
      showToast("Undantaget lades till!");
    } catch (err) {
      showToast(err.message, true);
    }
  });

  // Admin Generate Draw
  document.getElementById("generateDrawBtn").addEventListener("click", async () => {
    const seed = document.getElementById("drawSeedInput").value.trim() || null;
    try {
      await apiRequest("/api/admin/generate-draw", "POST", {
        admin_password: getAdminPassword(),
        seed,
      });
      currentSession = null;
      await loadState();
      showToast("Ny lottningskedja genererad! 🎲");
    } catch (err) {
      showToast(err.message, true);
    }
  });

  // Save to seed.json
  document.getElementById("saveSeedBtn").addEventListener("click", async () => {
    try {
      await apiRequest("/api/admin/save-seed", "POST", {
        admin_password: getAdminPassword(),
      });
      showToast("Sparat till seed.json! 💾");
    } catch (err) {
      showToast(err.message, true);
    }
  });

  // Reset from seed.json
  document.getElementById("resetSeedBtn").addEventListener("click", async () => {
    if (!confirm("Vill du återställa allt från seed.json och slumpa en ny kedja?")) {
      return;
    }
    try {
      await apiRequest("/api/admin/reset-from-seed", "POST", {
        admin_password: getAdminPassword(),
      });
      currentSession = null;
      selectedLoginUserId = null;
      await loadState();
      showToast("Återställt från seed.json! 🔄");
    } catch (err) {
      showToast(err.message, true);
    }
  });

  // Lock & Go Live
  document.getElementById("goLiveBtn").addEventListener("click", async () => {
    if (!confirm("Låsa lottningen och radera all admin-insyn?")) {
      return;
    }
    try {
      await apiRequest("/api/admin/go-live", "POST", {
        admin_password: getAdminPassword(),
      });
      await loadState();
      showToast("Nu är sidan LIVE och admin-insynen är raderad! 🔒");
    } catch (err) {
      showToast(err.message, true);
    }
  });
});
