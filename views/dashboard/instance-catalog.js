/* Presentation model only. It does not establish identity or grant access. */
export function instanceGroups(games, users = []) {
  const people = new Map(
    users.map((u) => [
      String(u.id),
      {
        id: String(u.id),
        name: u.name || String(u.id),
        publicId: u.public_id,
        instances: [],
      },
    ]),
  );
  for (const game of games) {
    const id = game.owner_id ? String(game.owner_id) : "unassigned";
    if (!people.has(id))
      people.set(id, {
        id,
        name: id === "unassigned" ? "未分配用户" : game.owner_name || id,
        instances: [],
      });
    people.get(id).instances.push({
      id: game.id,
      name: game.name,
      ownerId: id,
      status: game.status,
    });
  }
  if (!people.size)
    people.set("unassigned", {
      id: "unassigned",
      name: "未分配用户",
      instances: [],
    });
  return [...people.values()];
}

export function renderInstanceDirectory(
  container,
  groups,
  selectedId,
  onSelect,
  onDelete = () => {},
) {
  const make = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  };
  const prior = [...container.querySelectorAll("details[data-owner-id]")];
  const seen = new Set(prior.map((n) => n.dataset.ownerId));
  const open = new Set(
    prior.filter((n) => n.open).map((n) => n.dataset.ownerId),
  );
  container.replaceChildren();
  for (const group of groups) {
    const section = make("details", undefined, "user-instance-group");
    section.dataset.ownerId = group.id;
    section.open = seen.has(group.id) ? open.has(group.id) : groups.length <= 3;
    const heading = make("summary"),
      avatar = make("span", Array.from(group.name)[0], "user-avatar"),
      copy = make("span", undefined, "user-group-name");
    copy.append(
      make("strong", group.name),
      make("small", `${group.instances.length} 个交易实例`),
    );
    if (group.publicId)
      copy.append(make("code", group.publicId, "user-public-id"));
    heading.append(
      avatar,
      copy,
      make("span", "展开 / 收起", "group-toggle-label"),
    );
    section.append(heading);
    const list = make("div", undefined, "instance-card-grid");
    if (!group.instances.length)
      list.append(make("p", "这位用户还没有交易实例。", "caption"));
    for (const instance of group.instances) {
      const button = make("button", undefined, "instance-entry instance-card");
      button.type = "button";
      button.dataset.instanceId = instance.id;
      button.setAttribute("aria-label", `打开 ${instance.name}`);
      const head = make("span", undefined, "instance-card-head");
      head.append(
        make("strong", instance.name),
        make(
          "small",
          { running: "运行中", paused: "已暂停", ended: "已结束" }[
            instance.status
          ] || "待开始",
          "instance-status",
        ),
      );
      button.append(
        head,
        make("span", "交易工作台 · 交易日志 · 计划与经验", "caption"),
        make("span", "打开实例", "instance-open"),
      );
      button.onclick = () => onSelect(instance);
      const tile = make("article", undefined, "instance-tile"),
        footer = make("div", undefined, "instance-card-footer"),
        remove = make("button", "删除", "delete-instance danger-text");
      remove.type = "button";
      remove.dataset.instanceId = instance.id;
      remove.setAttribute("aria-label", `删除 ${instance.name}`);
      remove.onclick = () => onDelete(instance);
      footer.append(remove);
      tile.append(button, footer);
      list.append(tile);
    }
    section.append(list);
    container.append(section);
  }
}
