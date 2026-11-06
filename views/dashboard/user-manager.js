import { noticeFields } from "./notification-form.js";

const roles = [["main", "主用户"], ["others", "其他用户"]];
const policyFields = {
  max_instances: "每位用户的实例数量上限（0 表示不限）",
  allow_custom_interval: "允许在实例面板修改看盘间隔",
  interval: "默认看盘间隔（分钟）",
  allow_panel_notice: "允许在实例面板修改主动汇报",
  allow_tool_notice: "允许 AI 通过工具修改主动汇报",
};
const policyDefaults = {max_instances:0, allow_custom_interval:false, interval:3600, allow_panel_notice:true, allow_tool_notice:true};

function make(tag, text, cls) {
  const el = document.createElement(tag);
  if (text) el.textContent = text;
  if (cls) el.className = cls;
  return el;
}

export class UserManager {
  constructor(post, remove) {
    this.post = post;
    this.remove = remove;
    this.signature = "";
    this.drafts = new Map();
  }

  renderRoles(mode, users) {
    const matrix = document.getElementById("workspace-role-settings");
    matrix.dataset.single = String(!mode.multiplayer);
    const profiles = mode.role_settings || Object.fromEntries(roles.map(([role]) => {
      const user = users.find(u => (u.id === mode.main_user_id) === (role === "main"));
      return [role, {policy:user?.policy, notifications:user?.notifications}];
    }));
    const signature = JSON.stringify(profiles);
    if (this.roleDirty || this.roleSignature === signature) return;
    this.roleSignature = signature;
    matrix.replaceChildren();
    matrix.append(make("h4", "用户权限与通知"));
    matrix.append(make("p", "每列适用于对应角色的用户。通知默认值变更会同步到已有实例。", "caption"));
    const grid = make("div", null, "role-settings-grid");
    grid.append(make("span", "设置项"));
    for (const [role, title] of roles) {
      const label = make("strong", title);
      label.dataset.role = role;
      grid.append(label);
    }
    const controls = {};
    const noticeInputs = {};
    for (const [role] of roles) {
      controls[role] = {};
      const wrapper = make("div");
      noticeFields(wrapper, profiles[role].notifications);
      noticeInputs[role] = [...wrapper.querySelectorAll("input")];
    }
    const addRow = (label, build) => {
      grid.append(make("span", label, "role-field-label"));
      for (const [role, title] of roles) {
        const cell = make("div", null, "role-setting-cell");
        cell.dataset.role = role;
        const input = build(role);
        input.setAttribute("aria-label", title + " " + label);
        input.setAttribute("form", "workspace-mode-settings");
        cell.append(input);
        grid.append(cell);
      }
    };
    for (const [key, label] of Object.entries(policyFields)) {
      addRow(label, role => {
        const input = make("input");
        const value = profiles[role].policy?.[key] ?? policyDefaults[key];
        if (typeof value === "boolean") {
          input.type = "checkbox";
          input.checked = value;
        } else {
          input.type = "number";
          input.min = key === "interval" ? 10 : 0;
          input.max = key === "interval" ? 1440 : 1000;
          input.step = key === "interval" ? "any" : "1";
          input.required = true;
          input.value = key === "interval" ? value / 60 : value;
        }
        controls[role][key] = input;
        return input;
      });
    }
    noticeInputs.main.forEach((input, index) => {
      const label = input.parentElement.textContent;
      const rowLabel = label || input.parentElement.innerText;
      addRow(rowLabel, role => noticeInputs[role][index]);
    });
    matrix.append(grid);
    this.roleValues = () => Object.fromEntries(roles.map(([role]) => {
      const policy = Object.fromEntries(Object.entries(controls[role]).map(([key, input]) =>
        [key, input.type === "checkbox" ? input.checked : key === "interval" ? Math.round(Number(input.value) * 60) : Number(input.value)]));
      const notices = Object.fromEntries(noticeInputs[role].map(input => [input.name, input.type === "checkbox" ? input.checked : input.value]));
      return [role, {policy, notifications:notices}];
    }));
    matrix.oninput = () => { this.roleDirty = true; };
  }

  render(users, mainUserId, multiplayer) {
    const target = document.getElementById("managed-users");
    const signature = JSON.stringify([users, mainUserId, multiplayer]);
    if (signature === this.signature) return;
    this.signature = signature;
    const old = new Map([...target.querySelectorAll("details[data-user]")].map(el => [el.dataset.user, el.open]));
    target.replaceChildren();
    for (const [role, title] of roles) {
      if (role === "others" && !multiplayer) continue;
      const group = make("section", null, "managed-user-group");
      group.append(make("h4", title));
      const members = users.filter(user => (user.id === mainUserId) === (role === "main"));
      if (!members.length) group.append(make("p", "暂无用户。可在新建交易实例时绑定私聊 UMO。", "caption"));
      for (const user of members) {
        const row = make("details", null, "managed-user");
        row.dataset.user = user.id;
        row.open = old.get(user.id) ?? !multiplayer;
        const summary = make("summary");
        summary.append(make("strong", user.name), make("span", (user.instances?.length || 0) + " 个实例", "caption"));
        row.append(summary);
        const bindings = (user.bindings || []).filter(alias => alias.type === "umo");
        row.append(make("p", bindings.length ? bindings.map(alias => alias.value).join("、") : "尚无私聊 UMO，请补充绑定。", "caption"));
        const form = make("form");
        const nickname = make("input");
        nickname.name = "nickname";
        nickname.required = true;
        nickname.maxLength = 40;
        nickname.value = this.drafts.get(user.id)?.nickname ?? user.name;
        const nameLabel = make("label", "用户昵称");
        nameLabel.append(nickname);
        const umoLabel = make("label", "添加私聊 UMO（每行一个）");
        const umos = make("textarea");
        umos.rows = 2;
        umos.placeholder = "default:FriendMessage:123456789";
        umos.value = this.drafts.get(user.id)?.umos ?? "";
        umoLabel.append(umos);
        form.append(nameLabel, umoLabel);
        form.oninput = () => this.drafts.set(user.id, {user, nickname:nickname.value, umos:umos.value});
        form.onsubmit = event => event.preventDefault();
        const remove = make("button", "删除用户", "danger-button");
        remove.type = "button";
        remove.onclick = () => this.remove(user);
        row.append(form, remove);
        group.append(row);
      }
      target.append(group);
    }
  }

  async save() {
    for (const [id, {user, nickname, umos}] of this.drafts) {
      const values = umos.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
      if (values.length) {
        await this.post("command", {action:"update_user_umo", user_id:id, umos:values});
      }
      if (nickname !== user.name) {
        await this.post("command", {action:"update_user", user_id:id, nickname, policy:user.policy, notifications:user.notifications});
      }
      this.drafts.delete(id);
    }
    this.signature = "";
  }
}
