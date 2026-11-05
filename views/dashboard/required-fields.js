// Required cues reflect empty values, including dynamically rendered settings.
const markers = new WeakMap();
export function refreshRequired() {
  for (const field of document.querySelectorAll('[data-page="setup"] input, [data-page="setup"] select, [data-page="setup"] textarea, #create select, #binding input, #binding select, #instance-notifications input')) {
    const label = field.closest("label");
    if (!label) continue;
    let mark = markers.get(field);
    if (!mark && field.required) {
      mark = document.createElement("span");
      mark.className = "required-indicator";
      mark.textContent = "（必填）";
      label.insertBefore(mark, label.firstElementChild);
      markers.set(field, mark);
    }
    if (mark) {
      const empty = field.type === "checkbox" ? !field.checked : !String(field.value ?? "").trim();
      const hide = !field.required || field.disabled || !empty || !!field.closest("[hidden]");
      if (mark.hidden !== hide) mark.hidden = hide;
    }
  }
}
document.addEventListener("input", refreshRequired);
document.addEventListener("change", refreshRequired);
let scheduled = false;
new MutationObserver(() => {
  if (scheduled) return;
  scheduled = true;
  queueMicrotask(() => { scheduled = false; refreshRequired(); });
}).observe(document.body, {subtree:true,childList:true,attributes:true,attributeFilter:["required","disabled","hidden"]});
refreshRequired();
