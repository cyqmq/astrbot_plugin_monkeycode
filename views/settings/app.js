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
  { key: "summary_prompt", type: "text" },
  { key: "session_path", type: "text" },
  { key: "auto_checkin_hour", type: "int" },
];

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
    const data = await bridge.apiGet("settings");
    fill(data);
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