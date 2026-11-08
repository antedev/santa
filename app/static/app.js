// Julklappsspelet – Clean Frontend Logic

let appState = null;
let selectedLoginUserId = null;
let currentSession = null; // { user, assignment, password }
let adminViewOpen = false;

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

// --- State Loading & Rendering ---

async function loadState() {
  try {
    appState = await apiRequest("/api/state");
    document.getElementById("eventTitle").textContent = `🎄 ${appState.event_title}`;
    document.getElementById("budgetInfo").textContent = appState.budget_info;

    renderLayoutVisibility();
    renderLoginScreen();
    renderUserDashboard();
    renderKidsCorner();
    renderChainVerification();
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
    // Only show clean login screen!
    loginScreen.classList.remove("hidden");
    mainNav.classList.add("hidden");
    appContent.classList.add("hidden");
  } else if (!currentSession && adminViewOpen) {
    // Discreet admin mode opened from footer while logged out
    loginScreen.classList.add("hidden");
    mainNav.classList.remove("hidden");
    appContent.classList.remove("hidden");
    userBar.classList.add("hidden");
    adminTabBtn.classList.remove("hidden");
    switchTab("tab-admin");
  } else {
    // Logged in user
    loginScreen.classList.add("hidden");
    mainNav.classList.remove("hidden");
    appContent.classList.remove("hidden");
    userBar.classList.remove("hidden");
    adminTabBtn.classList.toggle("hidden", !adminViewOpen);
  }
}

// --- Login Screen (Simple Name Picker) ---

function createNameTile(p) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = `user-tile ${selectedLoginUserId === p.id ? "selected" : ""}`;
  btn.textContent = p.name;
  btn.addEventListener("click", () => {
    selectedLoginUserId = p.id;
    renderLoginScreen();
    const loginForm = document.getElementById("loginForm");
    loginForm.classList.remove("hidden");
    document.getElementById("passwordPromptLabel").textContent = p.has_account
      ? `Ange din PIN-kod / lösenord, ${p.name}:`
      : `Välj en egen PIN-kod / lösenord, ${p.name} (första inloggningen):`;
    document.getElementById("loginPassword").focus();
  });
  return btn;
}

function renderLoginScreen() {
  const adultsGrid = document.getElementById("loginUserGrid");
  const kidsGrid = document.getElementById("loginKidsGrid");
  const kidsDivider = document.getElementById("kidsLoginDivider");

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

  const adultSection = document.getElementById("adultLotterySection");
  const kidSection = document.getElementById("kidWelcomeSection");

  if (user.is_kid) {
    adultSection.classList.add("hidden");
    kidSection.classList.remove("hidden");
    return;
  }

  adultSection.classList.remove("hidden");
  kidSection.classList.add("hidden");

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

// --- Tab 2: Barnen (Louise, Josefin & Elise) ---

function renderKidsCorner() {
  const container = document.getElementById("kidsListContainer");
  container.innerHTML = "";

  const kids = appState.participants.filter((p) => p.is_kid);
  kids.forEach((kid) => {
    const pledges = appState.kid_gifts.filter((g) => g.recipient_user_id === kid.id);
    const card = document.createElement("div");
    card.className = "kid-card";

    let pledgesHtml = "";
    if (pledges.length === 0) {
      pledgesHtml = `<p class="muted" style="margin-top:0.55rem;">Ingen paxad klapp ännu.</p>`;
    } else {
      const items = pledges
        .map((g) => {
          const canDelete =
            currentSession && currentSession.user.owner_tag === g.owner_tag;
          const notePart = g.gift_note ? ` – <em>"${escapeHtml(g.gift_note)}"</em>` : "";
          const delBtn = canDelete
            ? `<button type="button" class="btn btn-danger" onclick="deleteKidGift(${g.id})">Ta bort</button>`
            : "";
          return `<li class="kid-pledge-item">
            <span>🎁 Från <strong>${escapeHtml(g.giver_label)}</strong>${notePart}</span>
            ${delBtn}
          </li>`;
        })
        .join("");
      pledgesHtml = `<ul class="kid-pledge-list">${items}</ul>`;
    }

    card.innerHTML = `
      <h3>👶 ${escapeHtml(kid.name)}</h3>
      <p class="muted" style="margin:0.2rem 0;"><strong>Önskelista:</strong> ${
        kid.wishlist ? escapeHtml(kid.wishlist) : "Ingen önskelista inlagd än."
      }</p>
      ${pledgesHtml}
    `;
    container.appendChild(card);
  });

  // Extra gifts to adults (e.g. if a kid signed up to give a gift to an adult)
  const adultExtraGifts = appState.kid_gifts.filter((g) => {
    const rec = appState.participants.find((p) => p.id === g.recipient_user_id);
    return rec && !rec.is_kid;
  });

  if (adultExtraGifts.length > 0) {
    const extraCard = document.createElement("div");
    extraCard.className = "kid-card";
    const items = adultExtraGifts
      .map((g) => {
        const canDelete =
          currentSession && currentSession.user.owner_tag === g.owner_tag;
        const notePart = g.gift_note ? ` – <em>"${escapeHtml(g.gift_note)}"</em>` : "";
        const delBtn = canDelete
          ? `<button type="button" class="btn btn-danger" onclick="deleteKidGift(${g.id})">Ta bort</button>`
          : "";
        return `<li class="kid-pledge-item">
          <span>🎄 Till <strong>${escapeHtml(g.recipient_name)}</strong> från <strong>${escapeHtml(g.giver_label)}</strong>${notePart}</span>
          ${delBtn}
        </li>`;
      })
      .join("");
    extraCard.innerHTML = `
      <h3>🌟 Extra klappar</h3>
      <ul class="kid-pledge-list">${items}</ul>
    `;
    container.appendChild(extraCard);
  }

  if (currentSession) {
    const select = document.getElementById("kidGiftRecipient");
    const prevVal = select.value;
    select.innerHTML = "";
    const sorted = [...appState.participants].sort((a, b) => Number(b.is_kid) - Number(a.is_kid));
    sorted.forEach((p) => {
      if (p.id === currentSession.user.id) return;
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = `${p.name} (${p.is_kid ? "Barn" : "Vuxen"})`;
      select.appendChild(opt);
    });
    if (prevVal) select.value = prevVal;
  }
}

window.deleteKidGift = async function (giftId) {
  if (!currentSession) return;
  try {
    const q = new URLSearchParams({
      user_id: currentSession.user.id,
      password: currentSession.password,
    });
    await apiRequest(`/api/user/kid-gift/${giftId}?${q.toString()}`, "DELETE");
    showToast("Paxningen togs bort.");
    await loadState();
  } catch (err) {
    showToast(err.message, true);
  }
};

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
    card.innerHTML = `
      <strong>🎭 ${escapeHtml(item.alias_name)}</strong>
      <span class="tag">${item.has_drawn ? "✅ Dragit lott" : "⏳ Väntar"}</span>
    `;
    statusGrid.appendChild(card);
  });
}

// --- Tab 4: Admin Panel ---

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
          <td><strong>${escapeHtml(step.giver_name)}</strong> (${escapeHtml(step.giver_alias)})</td>
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

document.addEventListener("DOMContentLoaded", () => {
  initSnowflakes();
  initTabs();
  loadState();

  // Login Form
  document.getElementById("loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!selectedLoginUserId) return;
    const password = document.getElementById("loginPassword").value;
    try {
      const res = await apiRequest("/api/auth/login", "POST", {
        user_id: selectedLoginUserId,
        password,
      });
      currentSession = {
        user: res.user,
        assignment: res.assignment,
        password,
      };
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
    selectedLoginUserId = null;
    adminViewOpen = false;
    document.getElementById("loginForm").classList.add("hidden");
    loadState();
  });

  // Discreet Admin Button in Footer
  document.getElementById("openAdminFooterBtn").addEventListener("click", () => {
    adminViewOpen = !adminViewOpen;
    renderLayoutVisibility();
    if (adminViewOpen) {
      switchTab("tab-admin");
    } else if (currentSession) {
      switchTab("tab-my-santa");
    }
  });

  // Spin Lottery Wheel
  document.getElementById("spinLotteryBtn").addEventListener("click", async () => {
    if (!currentSession) return;
    try {
      const res = await apiRequest("/api/user/draw-lot", "POST", {
        user_id: currentSession.user.id,
        password: currentSession.password,
      });
      await runLotteryWheelAnimation(res.assignment.target_name);
      currentSession.user = res.user;
      currentSession.assignment = res.assignment;
      await loadState();
    } catch (err) {
      showToast(err.message, true);
    }
  });

  // Replay Spin Animation
  document.getElementById("replaySpinBtn").addEventListener("click", async () => {
    if (!currentSession || !currentSession.assignment) return;
    document.getElementById("matchRevealedBox").classList.add("hidden");
    document.getElementById("lotteryMachineBox").classList.remove("hidden");
    await runLotteryWheelAnimation(currentSession.assignment.target_name);
    document.getElementById("lotteryMachineBox").classList.add("hidden");
    document.getElementById("matchRevealedBox").classList.remove("hidden");
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

  // Add Kid Gift Pledge
  document.getElementById("kidGiftForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!currentSession) return;
    const recipient_user_id = Number(document.getElementById("kidGiftRecipient").value);
    const giver_mode = document.getElementById("kidGiftMode").value;
    const gift_note = document.getElementById("kidGiftNote").value;
    try {
      await apiRequest("/api/user/kid-gift", "POST", {
        user_id: currentSession.user.id,
        password: currentSession.password,
        recipient_user_id,
        giver_mode,
        gift_note,
      });
      document.getElementById("kidGiftNote").value = "";
      await loadState();
      showToast("Sparat! 🎁");
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
