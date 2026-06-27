const readKey = "feedz_read_links";
const darkKey = "feedz_dark_mode";

// Read links and theme choice live in localStorage, so the static page can
// remember them without a server.
function getReadLinks() {
  try {
    const links = JSON.parse(localStorage.getItem(readKey) || "[]");
    return Array.isArray(links) ? links : [];
  } catch {
    return [];
  }
}

function saveReadLinks(links) {
  localStorage.setItem(readKey, JSON.stringify([...new Set(links)]));
}

function allItems() {
  return [...document.querySelectorAll(".item")];
}

function applyReadState() {
  const readLinks = getReadLinks();

  allItems().forEach((item) => {
    item.classList.toggle("read", readLinks.includes(item.dataset.link));
  });
}

function applyDarkMode() {
  const isDark = localStorage.getItem(darkKey) === "1";
  const button = document.getElementById("darkMode");

  document.body.classList.toggle("dark", isDark);
  if (button) {
    button.textContent = isDark ? "☀️" : "🌙";
  }
}

function setupReadTracking() {
  // Clicking an article marks every copy of that URL as read.
  document.querySelectorAll(".item a").forEach((link) => {
    link.addEventListener("click", () => {
      const readLinks = getReadLinks();
      readLinks.push(link.href);
      saveReadLinks(readLinks);
      applyReadState();
    });
  });

  const markReadButton = document.getElementById("markRead");
  if (markReadButton) {
    markReadButton.addEventListener("click", () => {
      const links = allItems().map((item) => item.dataset.link);
      saveReadLinks(links);
      applyReadState();
    });
  }

  const clearReadButton = document.getElementById("clearRead");
  if (clearReadButton) {
    clearReadButton.addEventListener("click", () => {
      localStorage.removeItem(readKey);
      applyReadState();
    });
  }
}

function setupSearch() {
  const searchInput = document.getElementById("search");
  if (!searchInput) {
    return;
  }

  searchInput.addEventListener("input", (event) => {
    const query = event.target.value.toLowerCase();

    // Search against the text we rendered into data attributes in the template.
    allItems().forEach((item) => {
      const haystack = [
        item.dataset.title,
        item.dataset.source,
        item.dataset.category,
      ].join(" ");

      item.classList.toggle("hidden", !haystack.includes(query));
    });
  });
}

function setupDarkModeToggle() {
  const darkModeButton = document.getElementById("darkMode");
  if (!darkModeButton) {
    return;
  }

  darkModeButton.addEventListener("click", () => {
    const isDark = !document.body.classList.contains("dark");
    localStorage.setItem(darkKey, isDark ? "1" : "0");
    applyDarkMode();
  });
}

function setupRandomArticle() {
  const randomButton = document.getElementById("randomLink");
  if (!randomButton) {
    return;
  }

  randomButton.addEventListener("click", () => {
    const links = [...document.querySelectorAll(".item:not(.hidden) a")];
    const pick = links[Math.floor(Math.random() * links.length)];

    if (pick) {
      window.open(pick.href, "_blank", "noopener,noreferrer");
    }
  });
}

function start() {
  applyDarkMode();
  setupReadTracking();
  setupSearch();
  setupDarkModeToggle();
  setupRandomArticle();
  applyReadState();
}

start();
