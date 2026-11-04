const labels = {
  enabled: "主动向用户汇报外汇信息", analysis: "看盘完成后汇报", liquidation: "爆仓 / 模拟强平时通知",
  margin_call: "保证金不足时通知", deposit: "追加虚拟资金后通知", end: "本局结束时通知",
  use_window: "仅在指定时段发送看盘汇报", random_delay: "在时段内随机延迟发送",
};
const defaults = {enabled:true,analysis:false,liquidation:true,margin_call:true,deposit:true,end:true,
  use_window:false,random_delay:false,window_start:"09:00",window_end:"22:00",quiet_start:"00:00",quiet_end:"07:00",timezone:"Asia/Shanghai"};
const make = (tag, text) => { const el=document.createElement(tag); if(text)el.textContent=text; return el; };

export function noticeFields(container, values={}, disabled=false) {
  const current={...defaults,...values};
  container.replaceChildren();
  const grid=make("div");grid.className="notice-switches";
  for(const [key,text] of Object.entries(labels)) {
    const label=make("label");label.className="check";
    const input=make("input");input.type="checkbox";input.name=key;input.checked=current[key];input.disabled=disabled;
    label.append(input,document.createTextNode(text));grid.append(label);
  }
  container.append(grid);
  const times=make("div");times.className="form-grid notice-window";
  for(const [key,text] of [["window_start","看盘汇报时段开始"],["window_end","看盘汇报时段结束"],
      ["quiet_start","免打扰开始（所有主动消息）"],["quiet_end","免打扰结束"],["timezone","通知时区"]]) {
    const label=make("label",text),input=make("input");input.name=key;input.type=key==="timezone"?"text":"time";
    input.value=current[key];input.required=true;input.disabled=disabled;label.append(input);times.append(label);
  }
  container.append(times);
  const note=make("p","免打扰默认00:00～07:00，爆仓、保证金等紧急通知也会排队到黑名单结束。连续看盘的待发汇报会合并为最新一条，避免刷屏。消息仅发往已验证的主参考私聊，可先在目标私聊通过交易工具选择此实例。");
  note.className="caption";container.append(note);
}

export function readNotices(container) {
  return Object.fromEntries(Object.keys(defaults).map(key=>{const input=container.querySelector(`[name="${key}"]`);return [key,typeof defaults[key]==="boolean"?input.checked:input.value];}));
}

export class InstanceNotices {
  constructor(post, reload) {
    this.gid="";this.signature="";this.dirty=false;
    const form=document.getElementById("instance-notifications");
    form.addEventListener("input",()=>{this.dirty=true;});
    form.onsubmit=async(event)=>{
      event.preventDefault();
      try {
        await post("command",{action:"notifications",game:this.gid,settings:readNotices(document.getElementById("instance-notice-fields"))});
        this.dirty=false;document.activeElement?.blur();await reload();
        document.getElementById("instance-notice-status").textContent="主动汇报设置已保存。";
      } catch(error) {document.getElementById("instance-notice-status").textContent=error.message||"保存失败";}
    };
  }
  render(access,gid) {
    if(gid!==this.gid){this.gid=gid;this.signature="";this.dirty=false;}
    if(!access)return;
    const signature=JSON.stringify(access);
    const save=document.querySelector("#instance-notifications button");
    save.dataset.permissionDisabled=String(access.allow_panel_notice===false);
    save.disabled=access.allow_panel_notice===false;
    const permitted=access.allow_panel_notice!==false;
    for(const input of document.querySelectorAll("#instance-notice-fields input"))input.disabled=!permitted;
    if(!permitted)document.getElementById("instance-notice-status").textContent="管理员未开放实例面板修改，请到用户与权限设置。";
    if(this.dirty||signature===this.signature)return;
    this.signature=signature;
    const allowed=access.allow_panel_notice!==false;
    noticeFields(document.getElementById("instance-notice-fields"),access.notifications, !allowed);
    document.querySelector("#instance-notifications button").disabled=!allowed;
    document.getElementById("instance-notice-status").textContent=allowed?"此处仅修改当前实例。":"管理员未开放实例面板修改，请在设置的用户与权限中调整。";
  }
}
