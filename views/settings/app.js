// MonkeyCode 高级设置视图
const bridge = window.AstrBotPluginView;

const FIELDS = [
  { key: "default_repo_url", type: "text" },
  { key: "default_branch", type: "text" },
  { key: "default_cli_name", type: "text" },
  { key: "default_host_id", type: "text" },
  { key: "default_image_id", type: "text" },
  { key: "default_model_id", type: "text" },
  { key: "skill_ids", type: "text" },
  { key: "task_timeout_seconds", type: "int" },
  { key: "task_poll_interval", type: "int" },
  { key: "send_md_on_end", type: "bool" },
  { key: "session_path", type: "text" },
];

// 动态下拉字段：key -> options 数据源键
const SELECT_FIELDS = {
  default_host_id: "hosts",
  default_image_id: "images",
  default_model_id: "models",
};

function fillSelect(el, items, value) {
  el.innerHTML = "";
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = "留空（自动）";
  el.appendChild(empty);
  for (const item of items || []) {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.name || item.id || item.model || item.image_name || item.id;
    el.appendChild(opt);
  }
  if (value) el.value = value;
}

function readValue(el, type) {
  if (type === "bool") return el.checked;
  if (type === "int") {
    const v = parseInt(el.value, 10);
    return Number.isNaN(v) ? "" : v;
  }
  return el.value;
}

function setValue(el, type, value) {
  if (type === "bool") {
    el.checked = Boolean(value);
  } else if (type === "int") {
    el.value = value ?? "";
  } else {
    el.value = value ?? "";
  }
}

function collect() {
  const payload = {};
  for (const f of FIELDS) {
    const el = document.getElementById(f.key);
    if (el) payload[f.key] = readValue(el, f.type);
  }
  return payload;
}

function fill(data) {
  for (const f of FIELDS) {
    const el = document.getElementById(f.key);
    if (el) setValue(el, f.type, data[f.key]);
  }
}

function setStatus(text, ok = true) {
  const el = document.getElementById("status");
  el.textContent = text;
  el.className = "status " + (ok ? "ok" : "err");
  setTimeout(() => {
    el.textContent = "";
    el.className = "status";
  }, 4000);
}

async function main() {
  await bridge.ready();

  try {
    // 先拉取动态下拉选项（需要登录态）
    const options = await bridge.apiGet("options");
    for (const [key, source] of Object.entries(SELECT_FIELDS)) {
      const el = document.getElementById(key);
      if (el) fillSelect(el, options[source], "");
    }
    // 再加载当前配置并选中已保存的值
    const settings = await bridge.apiGet("settings");
    for (const [key, source] of Object.entries(SELECT_FIELDS)) {
      const el = document.getElementById(key);
      if (el) fillSelect(el, options[source], settings[key]);
    }
    fill(settings);
  } catch (e) {
    setStatus("加载配置失败：" + e.message, false);
  }

  document.getElementById("save").addEventListener("click", async () => {
    const payload = collect();
    try {
      await bridge.apiPost("settings/save", payload);
      setStatus("✅ 已保存", true);
    } catch (e) {
      setStatus("保存失败：" + e.message, false);
    }
  });
}

main();