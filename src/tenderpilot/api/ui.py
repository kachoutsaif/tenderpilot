"""Interface web minimale, servie par l'API sur « / ».

Un seul fichier HTML dans une chaîne Python : pas de dépendance, pas de compilation, et le
fichier est forcément inclus dans le paquet installé (un .html à part demanderait de le
déclarer dans pyproject.toml).

Sécurité : la réponse du LLM et les extraits d'avis sont du texte venu de l'extérieur. Ils
sont insérés avec textContent (jamais innerHTML) : un avis contenant du HTML ou du script
s'affiche comme du texte, sans s'exécuter. Les liens ne sont acceptés qu'en http(s).
"""

UI_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TenderPilot</title>
<style>
  :root {
    --bg: #f6f7f9; --panel: #ffffff; --text: #1b1f24; --muted: #5b6573;
    --line: #e2e6eb; --accent: #1f5fbf; --accent-soft: #e8f0fc; --warn: #8a5a00;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #111418; --panel: #1a1f25; --text: #e6e9ee; --muted: #9aa4b2;
      --line: #2a313a; --accent: #7aa7f0; --accent-soft: #1d2a3d; --warn: #e0b45c;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  main { max-width: 820px; margin: 0 auto; padding: 32px 16px 64px; }
  header h1 { margin: 0; font-size: 1.6rem; letter-spacing: -0.01em; }
  header p { margin: 6px 0 24px; color: var(--muted); }
  form { display: flex; gap: 8px; flex-wrap: wrap; }
  input[type=text] {
    flex: 1 1 320px; padding: 12px 14px; font: inherit; color: var(--text);
    background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  }
  input[type=text]:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
  button {
    padding: 12px 18px; font: inherit; font-weight: 600; border: 0; border-radius: 10px;
    background: var(--accent); color: #fff; cursor: pointer;
  }
  button:disabled { opacity: 0.6; cursor: progress; }
  .examples { margin: 12px 0 0; display: flex; gap: 8px; flex-wrap: wrap; }
  .examples button {
    background: var(--accent-soft); color: var(--accent); font-weight: 500;
    padding: 6px 12px; font-size: 0.9rem;
  }
  section.card {
    margin-top: 24px; background: var(--panel); border: 1px solid var(--line);
    border-radius: 12px; padding: 20px;
  }
  .label {
    font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted);
  }
  #answer { margin: 8px 0 0; }
  .ref { color: var(--accent); font-weight: 600; font-size: 0.8em; vertical-align: super; }
  #answer p { margin: 0 0 10px; }
  #answer ul, #answer ol { margin: 0 0 10px; padding-left: 22px; }
  .table-wrap { overflow-x: auto; margin: 4px 0 12px; }
  #answer table { border-collapse: collapse; width: 100%; font-size: 0.92rem; }
  #answer th, #answer td {
    border: 1px solid var(--line); padding: 6px 8px; text-align: left; vertical-align: top;
  }
  #answer th { background: var(--accent-soft); }
  ol#sources { padding-left: 20px; margin: 8px 0 0; }
  ol#sources li { margin-bottom: 14px; }
  ol#sources a { color: var(--accent); text-decoration: none; font-weight: 600; }
  ol#sources a:hover { text-decoration: underline; }
  .meta { color: var(--muted); font-size: 0.85rem; }
  blockquote {
    margin: 6px 0 0; padding: 8px 12px; border-left: 3px solid var(--line);
    color: var(--muted); font-size: 0.92rem;
  }
  .warn { color: var(--warn); font-size: 0.9rem; margin-top: 10px; }
  footer { margin-top: 32px; color: var(--muted); font-size: 0.85rem; }
  footer a { color: var(--muted); }
  [hidden] { display: none !important; }
</style>
</head>
<body>
<main>
  <header>
    <h1>TenderPilot</h1>
    <p>Posez une question sur les appels d'offres publics indexés (BOAMP).
       Chaque affirmation de la réponse renvoie à l'avis qui la justifie.</p>
  </header>

  <form id="ask">
    <input type="text" id="question" name="question" autocomplete="off" required
           placeholder="Ex. : Quels marchés de nettoyage sont ouverts ?">
    <button type="submit" id="go">Demander</button>
  </form>
  <div class="examples" id="examples">
    <button type="button">Quels marchés de nettoyage sont ouverts ?</button>
    <button type="button">Quels marchés concernent la voirie ?</button>
    <button type="button">Qui cherche un assureur ?</button>
  </div>

  <section class="card" id="result" hidden>
    <div class="label">Réponse</div>
    <div id="answer"></div>
    <p class="warn" id="invalid" hidden></p>
  </section>

  <section class="card" id="sources-card" hidden>
    <div class="label">Sources citées</div>
    <ol id="sources"></ol>
  </section>

  <footer>
    <span id="status">…</span> ·
    <a href="/docs">API</a> ·
    <a href="https://github.com/kachoutsaif/tenderpilot">Code source</a>
  </footer>
</main>
<script>
  const $ = (id) => document.getElementById(id);

  function safeUrl(url) {
    try {
      const u = new URL(url);
      return (u.protocol === "https:" || u.protocol === "http:") ? u.href : null;
    } catch { return null; }
  }

  // Réponse : le LLM écrit du Markdown (paragraphes, listes, tableaux, **gras**, renvois [n]).
  // Rendu minimal et SÛR : chaque élément est créé avec createElement et rempli avec du
  // texte, jamais comme du HTML. Un avis contenant du HTML s'affiche, il ne s'exécute pas.
  function inline(parent, text) {
    for (const part of text.split(/(\\*\\*[^*]+\\*\\*|\\[\\d+\\])/)) {
      if (!part) continue;
      if (/^\\*\\*[^*]+\\*\\*$/.test(part)) {
        const b = document.createElement("strong");
        b.textContent = part.slice(2, -2);
        parent.appendChild(b);
      } else if (/^\\[\\d+\\]$/.test(part)) {
        const sup = document.createElement("span");
        sup.className = "ref";
        sup.textContent = part;
        parent.appendChild(sup);
      } else {
        parent.appendChild(document.createTextNode(part));
      }
    }
  }

  function cells(line) {
    return line.trim().replace(/^\\|/, "").replace(/\\|$/, "").split("|").map((c) => c.trim());
  }

  function renderAnswer(text) {
    const box = $("answer");
    box.textContent = "";
    const lines = text.replace(/\\r/g, "").split("\\n");
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      if (line.trim().startsWith("|")) {                        // tableau
        const rows = [];
        while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(lines[i++]);
        const table = document.createElement("table");
        rows.forEach((row, n) => {
          if (/^\\s*\\|?\\s*:?-{2,}/.test(row)) return;            // ligne |---|---|
          const tr = document.createElement("tr");
          for (const c of cells(row)) {
            const td = document.createElement(n === 0 ? "th" : "td");
            inline(td, c);
            tr.appendChild(td);
          }
          table.appendChild(tr);
        });
        const wrap = document.createElement("div");
        wrap.className = "table-wrap";
        wrap.appendChild(table);
        box.appendChild(wrap);
        continue;
      }
      const bullet = /^\\s*([-*•]|\\d+[.)])\\s+/;
      if (bullet.test(line)) {                                   // liste
        const ordered = /^\\s*\\d/.test(line);
        const list = document.createElement(ordered ? "ol" : "ul");
        while (i < lines.length && bullet.test(lines[i])) {
          const li = document.createElement("li");
          inline(li, lines[i++].replace(bullet, ""));
          list.appendChild(li);
        }
        box.appendChild(list);
        continue;
      }
      const p = document.createElement("p");                     // paragraphe
      const para = [];
      while (i < lines.length && lines[i].trim() && !lines[i].trim().startsWith("|")
             && !bullet.test(lines[i])) para.push(lines[i++].replace(/^#+\\s*/, ""));
      inline(p, para.join(" "));
      box.appendChild(p);
    }
  }

  function renderSources(citations) {
    const list = $("sources");
    list.textContent = "";
    for (const c of citations) {
      const li = document.createElement("li");
      li.value = c.number;
      const url = safeUrl(c.url || "");
      const title = document.createElement(url ? "a" : "strong");
      title.textContent = c.title || c.notice_id;
      if (url) { title.href = url; title.target = "_blank"; title.rel = "noopener"; }
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = "Avis " + c.notice_id;
      const quote = document.createElement("blockquote");
      quote.textContent = (c.excerpt || "").replace(/^\\[[^\\]]*\\]\\s*/, "") + " …";
      li.append(title, meta, quote);
      list.appendChild(li);
    }
    $("sources-card").hidden = citations.length === 0;
  }

  async function ask(question) {
    $("go").disabled = true;
    $("go").textContent = "Recherche…";
    $("result").hidden = false;
    $("answer").textContent = "Lecture des avis et rédaction de la réponse…";
    $("invalid").hidden = true;
    $("sources-card").hidden = true;
    try {
      const resp = await fetch("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, k: 5 }),
      });
      if (!resp.ok) throw new Error("Erreur " + resp.status);
      const data = await resp.json();
      renderAnswer(data.answer || "");
      renderSources(data.citations || []);
      if ((data.invalid_citations || []).length) {
        $("invalid").textContent = "Citations ignorées car elles ne renvoient à aucune source : "
          + data.invalid_citations.join(", ");
        $("invalid").hidden = false;
      }
    } catch (err) {
      $("answer").textContent = "La question n'a pas pu aboutir (" + err.message + "). Réessayez.";
    } finally {
      $("go").disabled = false;
      $("go").textContent = "Demander";
    }
  }

  $("ask").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("question").value.trim();
    if (q) ask(q);
  });
  for (const b of $("examples").querySelectorAll("button")) {
    b.addEventListener("click", () => { $("question").value = b.textContent; ask(b.textContent); });
  }

  fetch("/health").then((r) => {
    $("status").textContent = r.ok ? "API en ligne" : "API indisponible";
  }).catch(() => { $("status").textContent = "API injoignable"; });
</script>
</body>
</html>
"""
