// ─── theme ───
const Theme = {
  init() {
    const saved = localStorage.getItem("theme") || "dark";
    document.documentElement.setAttribute("data-theme", saved);
    this.updateToggle(saved);
    document.querySelectorAll("[data-theme-toggle]").forEach(el =>
      el.addEventListener("click", () => this.toggle())
    );
  },
  toggle() {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("theme", next);
    this.updateToggle(next);
  },
  updateToggle(theme) {
    document.querySelectorAll("[data-theme-toggle]").forEach(el => {
      el.innerHTML = theme === "dark"
        ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>'
        : '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>';
    });
  }
};

// ─── toast ───
const Toast = {
  container: null,
  init() {
    this.container = document.querySelector(".toast-container");
    if (!this.container) {
      this.container = document.createElement("div");
      this.container.className = "toast-container";
      document.body.appendChild(this.container);
    }
  },
  show(message, { action, onAction, duration = 3000 } = {}) {
    if (!this.container) this.init();
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.innerHTML = `<span>${message}</span>`;
    if (action) {
      const btn = document.createElement("button");
      btn.className = "toast-action";
      btn.textContent = action;
      btn.addEventListener("click", () => {
        onAction?.();
        this.dismiss(toast);
      });
      toast.appendChild(btn);
    }
    this.container.appendChild(toast);
    setTimeout(() => this.dismiss(toast), duration);
  },
  dismiss(toast) {
    if (!toast.isConnected) return;
    toast.classList.add("is-leaving");
    toast.addEventListener("animationend", () => toast.remove(), { once: true });
  }
};

// ─── favorites store ───
const Favorites = {
  KEY: "aim:favorites:v2",
  all() {
    try {
      return JSON.parse(localStorage.getItem(this.KEY)) || [];
    } catch {
      return [];
    }
  },
  has(id) {
    return this.all().some(f => f.id === id);
  },
  add(painting) {
    const list = this.all();
    if (list.some(f => f.id === painting.id)) return list;
    list.unshift({
      id: painting.id,
      title: painting.title,
      artist: painting.artist,
      dated: painting.dated,
      image_url: painting.image_url,
      interpretation: painting.interpretation || "",
      saved_at: Date.now(),
    });
    localStorage.setItem(this.KEY, JSON.stringify(list));
    return list;
  },
  remove(id) {
    const list = this.all().filter(f => f.id !== id);
    localStorage.setItem(this.KEY, JSON.stringify(list));
    return list;
  },
  get(id) {
    return this.all().find(f => f.id === id);
  }
};

// ─── modal ───
const Modal = {
  el: null,
  imgEl: null,
  init() {
    this.el = document.querySelector("[data-modal]");
    if (!this.el) return;
    this.imgEl = this.el.querySelector(".modal-image");
    this.el.addEventListener("click", () => this.close());
    document.addEventListener("keydown", e => {
      if (e.key === "Escape" && this.el.classList.contains("is-open")) this.close();
    });
  },
  open(src, alt = "") {
    if (!this.el) return;
    this.imgEl.src = src;
    this.imgEl.alt = alt;
    this.el.classList.add("is-open");
    document.body.style.overflow = "hidden";
  },
  close() {
    if (!this.el) return;
    this.el.classList.remove("is-open");
    document.body.style.overflow = "";
  }
};

// ─── museum (artwork view) ───
const LISTEN_ICONS = {
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><polygon points="6 4 20 12 6 20"/></svg>',
  pause: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>',
  spinner: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M12 3a9 9 0 1 1-9 9"/></svg>',
};

const Museum = {
  current: null,
  prefetched: null,
  abortStream: null,
  audio: null,
  audioObjectUrl: null,
  audioBusy: false,
  els: {},

  init() {
    if (!document.querySelector("[data-museum]")) return;

    this.els = {
      root: document.querySelector("[data-museum]"),
      imgWrap: document.querySelector("[data-image-wrap]"),
      img: document.querySelector("[data-image]"),
      title: document.querySelector("[data-title]"),
      byline: document.querySelector("[data-byline]"),
      tags: document.querySelector("[data-tags]"),
      interp: document.querySelector("[data-interpretation]"),
      favBtn: document.querySelector("[data-fav-btn]"),
      nextBtn: document.querySelector("[data-next-btn]"),
      shareBtn: document.querySelector("[data-share-btn]"),
      sourceBtn: document.querySelector("[data-source-btn]"),
      listenBtn: document.querySelector("[data-listen-btn]"),
      listenIcon: document.querySelector("[data-listen-icon]"),
      listenLabel: document.querySelector("[data-listen-label]"),
      error: document.querySelector("[data-error]"),
    };

    this.els.img.addEventListener("click", () => {
      if (this.current) Modal.open(this.current.image_url, this.current.title);
    });

    this.els.favBtn?.addEventListener("click", () => this.toggleFavorite());
    this.els.nextBtn?.addEventListener("click", () => this.loadNext());
    this.els.shareBtn?.addEventListener("click", () => this.share());
    this.els.listenBtn?.addEventListener("click", () => this.toggleAudio());
    document.addEventListener("keydown", e => {
      if (e.target.matches("input, textarea")) return;
      if (e.key === "n" || e.key === "ArrowRight") this.loadNext();
      if (e.key === "f") this.toggleFavorite();
    });

    const initialId = window.__INITIAL_ID__;
    if (initialId) {
      this.loadById(initialId);
    } else {
      this.loadRandom();
    }
  },

  async loadRandom() {
    if (this.prefetched) {
      const next = this.prefetched;
      this.prefetched = null;
      await this.render(next);
      this.streamInterpretation(next.id);
      this.prefetchNext();
      return;
    }
    await this.fetchAndRender("/api/painting/random");
  },

  async loadById(id) {
    await this.fetchAndRender(`/api/painting/${encodeURIComponent(id)}`);
  },

  async loadNext() {
    history.replaceState(null, "", "/app");
    await this.loadRandom();
  },

  async fetchAndRender(url) {
    this.showError(null);
    this.setChanging(true);
    this.showSkeleton();
    try {
      const res = await fetch(url);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || "Could not load artwork.");
      }
      const painting = await res.json();
      await this.render(painting);
      this.streamInterpretation(painting.id);
      this.prefetchNext();
    } catch (e) {
      this.setChanging(false);
      this.showError(e.message);
    }
  },

  async render(painting) {
    this.current = painting;
    this.abortPreviousStream();
    this.resetAudio();
    this.setListenState("waiting");

    this.els.title.textContent = painting.title;
    const byline = [painting.artist, painting.dated].filter(Boolean).join(" · ");
    this.els.byline.textContent = byline;

    this.els.tags.innerHTML = "";
    [painting.medium, painting.classification, painting.culture, painting.century]
      .filter(Boolean)
      .slice(0, 4)
      .forEach(t => {
        const span = document.createElement("span");
        span.className = "tag";
        span.textContent = t;
        this.els.tags.appendChild(span);
      });

    if (painting.source_url) {
      this.els.sourceBtn.href = painting.source_url;
      this.els.sourceBtn.style.display = "";
    } else {
      this.els.sourceBtn.style.display = "none";
    }

    this.els.imgWrap.classList.add("is-loading");
    this.els.img.classList.remove("is-loaded");
    await this.loadImage(painting.image_url);
    this.els.img.src = painting.image_url;
    this.els.img.alt = painting.title;
    this.els.imgWrap.classList.remove("is-loading");
    this.els.img.classList.add("is-loaded");

    this.updateFavoriteButton();
    this.setChanging(false);
  },

  loadImage(src) {
    return new Promise(resolve => {
      const img = new Image();
      img.onload = () => resolve();
      img.onerror = () => resolve();
      img.src = src;
    });
  },

  showSkeleton() {
    this.els.interp.innerHTML = `
      <span class="skeleton"></span>
      <span class="skeleton"></span>
      <span class="skeleton"></span>
      <span class="skeleton"></span>
      <span class="skeleton"></span>
    `;
  },

  setChanging(changing) {
    this.els.root.classList.toggle("is-changing", changing);
  },

  abortPreviousStream() {
    if (this.abortStream) {
      this.abortStream.abort();
      this.abortStream = null;
    }
  },

  async streamInterpretation(id) {
    this.abortPreviousStream();
    const controller = new AbortController();
    this.abortStream = controller;

    this.els.interp.innerHTML = '<span class="cursor"></span>';
    const cursor = this.els.interp.querySelector(".cursor");
    let buffer = "";
    let textNode = document.createTextNode("");
    this.els.interp.insertBefore(textNode, cursor);

    try {
      const res = await fetch(`/api/painting/${encodeURIComponent(id)}/interpretation`, {
        signal: controller.signal,
      });
      if (!res.ok || !res.body) throw new Error("Stream failed");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let chunk = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        chunk += decoder.decode(value, { stream: true });
        const events = chunk.split("\n\n");
        chunk = events.pop() || "";
        for (const evt of events) {
          const parsed = this.parseSse(evt);
          if (!parsed) continue;
          if (parsed.event === "token" && parsed.data?.text) {
            buffer += parsed.data.text;
            textNode.nodeValue = buffer;
          } else if (parsed.event === "done") {
            buffer = parsed.data?.text || buffer;
            textNode.nodeValue = buffer;
            cursor?.remove();
            if (this.current && this.current.id === id) {
              this.current.interpretation = buffer;
              if (Favorites.has(id)) {
                Favorites.add({ ...this.current });
              }
              if (buffer) this.setListenState("idle");
            }
          } else if (parsed.event === "error") {
            cursor?.remove();
            this.showError("The interpretation couldn't be generated. Try a different artwork.");
          }
        }
      }
    } catch (e) {
      if (e.name !== "AbortError") {
        cursor?.remove();
        this.showError("Connection lost while writing the interpretation.");
      }
    }
  },

  parseSse(block) {
    const lines = block.split("\n");
    let event = "message";
    let data = "";
    for (const line of lines) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (!data) return null;
    try {
      return { event, data: JSON.parse(data) };
    } catch {
      return { event, data: null };
    }
  },

  async prefetchNext() {
    if (this.prefetched) return;
    try {
      const res = await fetch("/api/painting/random");
      if (res.ok) {
        const p = await res.json();
        const img = new Image();
        img.src = p.image_url;
        this.prefetched = p;
      }
    } catch { /* ignore */ }
  },

  setListenState(state) {
    const btn = this.els.listenBtn;
    if (!btn) return;
    btn.classList.remove("is-loading", "is-playing");
    btn.disabled = false;

    switch (state) {
      case "waiting":
        btn.disabled = true;
        this.els.listenIcon.innerHTML = LISTEN_ICONS.play;
        this.els.listenLabel.textContent = "Listen";
        break;
      case "loading":
        btn.classList.add("is-loading");
        btn.disabled = true;
        this.els.listenIcon.innerHTML = LISTEN_ICONS.spinner;
        this.els.listenLabel.textContent = "Loading…";
        break;
      case "playing":
        btn.classList.add("is-playing");
        this.els.listenIcon.innerHTML = LISTEN_ICONS.pause;
        this.els.listenLabel.textContent = "Pause";
        break;
      case "paused":
        this.els.listenIcon.innerHTML = LISTEN_ICONS.play;
        this.els.listenLabel.textContent = "Resume";
        break;
      case "idle":
      default:
        this.els.listenIcon.innerHTML = LISTEN_ICONS.play;
        this.els.listenLabel.textContent = "Listen";
        break;
    }
  },

  resetAudio() {
    if (this.audio) {
      this.audio.pause();
      this.audio.src = "";
      this.audio = null;
    }
    if (this.audioObjectUrl) {
      URL.revokeObjectURL(this.audioObjectUrl);
      this.audioObjectUrl = null;
    }
    this.audioBusy = false;
  },

  async toggleAudio() {
    if (this.audioBusy) return;

    if (this.audio) {
      if (this.audio.paused) {
        this.audio.play().catch(() => Toast.show("Audio playback failed."));
      } else {
        this.audio.pause();
      }
      return;
    }

    if (!this.current?.interpretation) {
      Toast.show("Still writing the interpretation…");
      return;
    }

    this.audioBusy = true;
    this.setListenState("loading");

    try {
      const res = await fetch(`/api/painting/${encodeURIComponent(this.current.id)}/audio`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || "Audio generation failed.");
      }
      const blob = await res.blob();
      this.audioObjectUrl = URL.createObjectURL(blob);
      const audio = new Audio(this.audioObjectUrl);
      this.audio = audio;
      audio.addEventListener("play", () => this.setListenState("playing"));
      audio.addEventListener("pause", () => {
        if (!audio.ended) this.setListenState("paused");
      });
      audio.addEventListener("ended", () => {
        audio.currentTime = 0;
        this.setListenState("idle");
      });
      audio.addEventListener("error", () => {
        Toast.show("Audio playback failed.");
        this.resetAudio();
        this.setListenState("idle");
      });
      await audio.play();
    } catch (e) {
      Toast.show(e.message || "Couldn't play audio.");
      this.resetAudio();
      this.setListenState(this.current?.interpretation ? "idle" : "waiting");
    } finally {
      this.audioBusy = false;
    }
  },

  updateFavoriteButton() {
    if (!this.els.favBtn || !this.current) return;
    const isFav = Favorites.has(this.current.id);
    this.els.favBtn.classList.toggle("is-favorited", isFav);
    this.els.favBtn.querySelector(".action-label").textContent = isFav ? "Saved" : "Save";
    this.els.favBtn.setAttribute("aria-pressed", String(isFav));
  },

  toggleFavorite() {
    if (!this.current) return;
    const id = this.current.id;
    if (Favorites.has(id)) {
      Favorites.remove(id);
      Toast.show("Removed from favorites.");
    } else {
      Favorites.add({ ...this.current });
      Toast.show("Saved to favorites.");
    }
    this.updateFavoriteButton();
  },

  async share() {
    if (!this.current) return;
    const url = `${window.location.origin}/app?id=${encodeURIComponent(this.current.id)}`;
    try {
      if (navigator.share && /Mobi|Android/i.test(navigator.userAgent)) {
        await navigator.share({ title: this.current.title, url });
      } else {
        await navigator.clipboard.writeText(url);
        Toast.show("Link copied to clipboard.");
      }
    } catch { /* ignore */ }
  },

  showError(msg) {
    if (!this.els.error) return;
    if (!msg) {
      this.els.error.style.display = "none";
      this.els.error.innerHTML = "";
      return;
    }
    this.els.error.style.display = "";
    this.els.error.innerHTML = `<span>${msg}</span><button type="button">Try another</button>`;
    this.els.error.querySelector("button").addEventListener("click", () => this.loadRandom());
  }
};

// ─── favorites page ───
const FavoritesPage = {
  pendingRemoval: null,

  init() {
    if (!document.querySelector("[data-favorites]")) return;
    this.render();
  },

  render() {
    const container = document.querySelector("[data-favorites]");
    const list = Favorites.all();

    if (list.length === 0) {
      container.innerHTML = `
        <div class="empty">
          <div class="empty-icon">⌘</div>
          <p>You haven't saved any artworks yet.</p>
          <p style="margin-top: 1.5rem;"><a class="cta" href="/app">Visit the museum</a></p>
        </div>
      `;
      return;
    }

    container.innerHTML = `<div class="favorites-grid"></div>`;
    const grid = container.querySelector(".favorites-grid");
    list.forEach(fav => grid.appendChild(this.card(fav)));
  },

  card(fav) {
    const card = document.createElement("article");
    card.className = "fav-card";
    card.innerHTML = `
      <div class="fav-image">
        <img src="${fav.image_url}" alt="${this.escape(fav.title)}" loading="lazy">
      </div>
      <div class="fav-meta">
        <h3 class="fav-title">${this.escape(fav.title)}</h3>
        <p class="fav-artist">${this.escape(fav.artist)}</p>
      </div>
      <button class="fav-remove" type="button" aria-label="Remove">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 6 6 18M6 6l12 12"/></svg>
      </button>
    `;

    card.addEventListener("click", e => {
      if (e.target.closest(".fav-remove")) return;
      window.location.href = `/app?id=${encodeURIComponent(fav.id)}`;
    });

    card.querySelector(".fav-remove").addEventListener("click", e => {
      e.stopPropagation();
      this.removeWithUndo(fav, card);
    });

    return card;
  },

  removeWithUndo(fav, card) {
    Favorites.remove(fav.id);
    card.style.transition = "opacity 200ms, transform 200ms";
    card.style.opacity = "0";
    card.style.transform = "scale(0.96)";
    setTimeout(() => {
      card.remove();
      if (Favorites.all().length === 0) this.render();
    }, 200);

    Toast.show(`Removed "${fav.title}".`, {
      action: "Undo",
      onAction: () => {
        Favorites.add(fav);
        this.render();
      },
      duration: 5000,
    });
  },

  escape(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));
  }
};

// ─── boot ───
document.addEventListener("DOMContentLoaded", () => {
  Theme.init();
  Toast.init();
  Modal.init();
  Museum.init();
  FavoritesPage.init();
});
