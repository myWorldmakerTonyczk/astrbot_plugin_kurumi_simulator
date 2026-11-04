export class ModelSettings {
  constructor(post,reload){
    this.dirty=false;
    this.form=document.getElementById("llm-settings");
    this.form.addEventListener("input",()=>{this.dirty=true;this.fields();});
    this.form.onsubmit=async(event)=>{
      event.preventDefault();const form=this.form,status=document.getElementById("llm-settings-status");
      try {
        const body={debug_prompt:form.elements.debug_prompt.checked,mode:form.elements.mode.value,provider_id:form.elements.provider_id.value,
          api_base:form.elements.api_base.value,model:form.elements.model.value,api_key:form.elements.api_key.value,timeout:Number(form.elements.timeout.value)};
        if(form.elements.headers.value.trim())body.headers=JSON.parse(form.elements.headers.value);
        await post("llm-settings",body);this.dirty=false;form.elements.api_key.value="";form.elements.headers.value="";document.activeElement?.blur();await reload();status.textContent="模型调用设置已保存，供后台看盘与日记使用。";
      }catch(error){status.textContent=error.message||"保存失败";}
    };
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
