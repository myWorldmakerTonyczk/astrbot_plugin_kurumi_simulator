import {noticeFields,readNotices} from "./notification-form.js";
const make=(tag,text,cls)=>{const el=document.createElement(tag);if(text)el.textContent=text;if(cls)el.className=cls;return el;};
const check=(name,text,value)=>{const label=make("label",null,"check"),input=make("input");input.type="checkbox";input.name=name;input.checked=value;label.append(input,document.createTextNode(text));return label;};

export class UserManager {
  constructor(post,rotate,remove){this.post=post;this.rotate=rotate;this.remove=remove;this.signature="";this.drafts=new Map();}
  render(users=[], mainUserId="", multiplayer=true) {
    const target=document.getElementById("managed-users"),signature=JSON.stringify([users, mainUserId, multiplayer]);
    if((target.contains(document.activeElement)&&document.activeElement.matches("input,textarea,select"))||signature===this.signature)return;
    this.signature=signature;
    const old=new Map([...target.querySelectorAll("details[data-user]")].map(el=>[el.dataset.user,el.open]));
    target.replaceChildren();
    for(const saved of users) {
      const user = {...saved, ...this.drafts.get(saved.id)?.values()};

      const policy={allow_custom_interval:false,max_instances:0,interval:3600,allow_panel_notice:true,allow_tool_notice:true,...user.policy};
      const row=make("details",null,"managed-user");row.dataset.user=user.id;row.open=old.has(user.id)?old.get(user.id):!multiplayer;
      const summary=make("summary");summary.append(make("strong",user.name),make("span",user.id === mainUserId ? "主用户" : "其他用户","caption"),make("span",`${user.instances?.length||0} 个实例`,"caption"));row.append(summary);
      const identity=make("div",null,"user-identity"),refresh=make("button","刷新ID");refresh.type="button";refresh.onclick=()=>this.rotate(user);
      const remove=make("button","删除用户","danger-button");remove.type="button";remove.onclick=()=>this.remove(user);
      if (multiplayer) identity.append(make("code",user.public_id||"尚未生成ID"),refresh); identity.append(remove);row.append(identity);
      const aliases=make("details",null,"user-bindings");aliases.append(make("summary",`绑定方式与所属实例（${user.bindings?.length||0} 个QQ / UMO绑定）`));
      for(const alias of user.bindings||[]) {
        const line=make("p");line.append(make("span",alias.type==="qq"?"QQ号：":"会话UMO："),make("code",alias.value));aliases.append(line);
      }
      if(!user.bindings?.length)aliases.append(make("p","仅通过管理员发放的随机ID识别。","caption"));
      for(const instance of user.instances||[]) {
        const line=make("p",instance.name);
        if(instance.reference_umo)line.append(make("br"),make("code",instance.reference_umo));
        aliases.append(line);
      }
      row.append(aliases);
      const form=make("form"),nameLabel=make("label","用户昵称"),name=make("input");name.name="nickname";name.value=user.nickname ?? user.name;name.required=true;name.maxLength=40;nameLabel.append(name);form.append(nameLabel);
      const permissions=make("details");permissions.append(make("summary","用户与实例权限"));
      const maxLabel=make("label","实例数量上限（0表示不限）"),max=make("input");
      max.type="number";max.min="0";max.max="1000";max.step="1";max.required=true;max.value=policy.max_instances;
      maxLabel.append(max);permissions.append(maxLabel);
      permissions.append(check("allow_custom_interval","允许在实例面板自行修改看盘间隔",policy.allow_custom_interval));
      const intervalLabel=make("label","管理员设置的看盘间隔"),line=make("div",null,"interval-row"),interval=make("input"),unit=make("select");
      interval.type="number";interval.name="interval";interval.min="600";interval.step="any";interval.required=true;
      const initialUnit=policy.interval%3600===0?3600:policy.interval%60===0?60:1;interval.value=policy.interval/initialUnit;
      for(const [value,text] of [[1,"秒"],[60,"分钟"],[3600,"小时"]]){const option=make("option",text);option.value=value;unit.append(option);}unit.value=initialUnit;interval.min=String(600/initialUnit);unit.onchange=()=>{interval.min=String(600/Number(unit.value));};line.append(interval,unit);intervalLabel.append(line);permissions.append(intervalLabel);
      permissions.append(make("p","默认1小时，最少10分钟。两处共用同一用户间隔，修改任一处都会同步该用户全部实例；未授权时只能由管理员修改。","caption"));
      permissions.append(check("allow_panel_notice","允许在实例面板修改主动汇报",policy.allow_panel_notice),check("allow_tool_notice","允许AI通过工具修改主动汇报",policy.allow_tool_notice));form.append(permissions);
      const notices=make("details");notices.append(make("summary","管理员设置的主动汇报与免打扰"));
      const fields=make("div");noticeFields(fields,user.notifications);notices.append(fields,make("p","这里变更通知默认值会同步该用户全部实例；仅改名或权限会保留实例已有的通知设置。","caption"));form.append(notices);
      const values = () => ({
        nickname:name.value,
        policy:{max_instances:Number(max.value),allow_custom_interval:form.elements.allow_custom_interval.checked,interval:Math.round(Number(interval.value)*Number(unit.value)),
          allow_panel_notice:form.elements.allow_panel_notice.checked,allow_tool_notice:form.elements.allow_tool_notice.checked},
        notifications:readNotices(fields),
      });
      const keepDraft = () => this.drafts.set(user.id, {form, values});
      form.addEventListener("input", keepDraft);
      form.addEventListener("change", keepDraft);
      form.onsubmit = event => event.preventDefault();
      row.append(form);target.append(row);
    }
    if(!users.length)target.append(make("p","还没有用户。新建交易实例时绑定私聊 UMO 即可。","caption"));
  }
  async save() {
    for (const {form} of this.drafts.values()) {
      if (!form.checkValidity()) throw Error("请检查用户昵称、看盘间隔和通知时间。");
    }
    for (const [id, draft] of this.drafts) {
      await this.post("command", {action:"update_user",user_id:id,...draft.values()});
      this.drafts.delete(id);
    }
    this.signature = "";
  }

}
