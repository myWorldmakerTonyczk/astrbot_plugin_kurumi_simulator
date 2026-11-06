export class ModelSettings {
  constructor(post) {
    this.post = post;
    this.dirty = false;
    this.form = document.getElementById("llm-settings");
    this.form.addEventListener("input", () => { this.dirty = true; this.fields(); });
  }

  values() {
    const fields = this.form.elements;
    const body = {
      debug_prompt: fields.debug_prompt.checked, mode: fields.mode.value,
      provider_id: fields.provider_id.value, api_base: fields.api_base.value,
      model: fields.model.value, api_key: fields.api_key.value, timeout: Number(fields.timeout.value),
    };
    if (fields.headers.value.trim()) {
      try { body.headers = JSON.parse(fields.headers.value); }
      catch { throw Error("模型接口的自定义请求头须为有效 JSON。"); }
    }
    return body;
  }

  async save(values) {
    await this.post("llm-settings", values);
    this.dirty = false;
    this.form.elements.api_key.value = "";
    this.form.elements.headers.value = "";
  }
  fields(){const custom=this.form.elements.mode.value==="custom";
    this.form.elements.provider_id.required=!custom;
    this.form.elements.provider_id.disabled=custom;
    for(const name of ["api_base","model","api_key","headers","timeout"])this.form.elements[name].disabled=!custom;
    this.form.elements.api_base.required=custom;
    this.form.elements.model.required=custom;for(const el of this.form.querySelectorAll("[data-llm-mode]"))el.hidden=(el.dataset.llmMode==="custom")!==custom;}
  render(config,providers=[]){
    if(!config||this.dirty||this.form.contains(document.activeElement))return;
    const form=this.form;
    form.elements.debug_prompt.checked=config.debug_prompt===true;
    for(const key of ["mode","api_base","model","timeout"])form.elements[key].value=config[key]??(key==="timeout"?120:"");
    const select=form.elements.provider_id;select.replaceChildren();
    for(const item of [{id:"",name:"请选择平台模型"},...providers]){const option=document.createElement("option");option.value=item.id;option.textContent=item.name||item.id;select.append(option);}select.value=config.provider_id||"";
    form.elements.api_key.placeholder=config.key_configured?"已保存，留空保持原密钥":"填写API Key；无密钥的本地接口可留空";
    form.elements.headers.placeholder=config.headers_configured?"已有请求头（不回显）；留空保留，输入{}清空":"可选JSON，如 {\"X-Client\":\"kurumi\"}";
    this.fields();
  }
}
