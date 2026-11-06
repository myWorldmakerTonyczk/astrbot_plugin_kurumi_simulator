// Render the common plan and diary markup as text nodes only.
export function renderNotebookText(container, text) {
  if (container.dataset.rendered === text) return;
  container.dataset.rendered = text;
  container.replaceChildren();
  let section = container, list;
  for (const line of text.split(/\r?\n/)) {
    const heading = line.match(/^【([^】]+)】\s*(.*)$/) || line.match(/^#{1,4}\s+(.+)$/);
    if (heading) {
      section = document.createElement("section");
      const title = document.createElement("h4");
      title.textContent = heading[1];
      section.append(title);
      container.append(section);
      list = null;
      if (!heading[2]) continue;
    }
    const body = (heading?.[2] || line).trim();
    if (!body) {
      list = null;
      continue;
    }
    const bullet = body.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      if (!list) {
        list = document.createElement("ul");
        section.append(list);
      }
    } else list = null;
    const item = document.createElement(bullet ? "li" : "p");
    for (const part of (bullet?.[1] || body).split(/(\*\*[^*]+\*\*)/g)) {
      if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
        const strong = document.createElement("strong");
        strong.textContent = part.slice(2, -2);
        item.append(strong);
      } else item.append(part);
    }
    (list || section).append(item);
  }
}
