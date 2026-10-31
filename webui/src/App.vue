<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useTheme } from 'vuetify'

import { useBridge } from './composables/useBridge'

const bridge = useBridge()
const theme = useTheme()

const loading = ref(true)
const saving = ref(false)
const msg = ref('')
const msgType = ref<'success' | 'error'>('success')

interface Options {
  hosts: Array<{ id: string; name?: string }>
  images: Array<{ id: string; name?: string; image_name?: string }>
  models: Array<{ id: string; model?: string }>
}

const options = reactive<Options>({ hosts: [], images: [], models: [] })

const form = reactive({
  default_repo_url: '',
  default_branch: 'main',
  default_cli_name: 'opencode',
  default_host_id: '',
  default_image_id: '',
  default_model_id: '',
  skill_ids: '',
  task_timeout_seconds: 3600,
  task_poll_interval: 15,
  send_md_on_end: true,
  session_path: '',
})

function displayName(item: Record<string, unknown>): string {
  return (
    String(item.name || item.model || item.image_name || item.id || '')
  )
}

function syncTheme() {
  const isDark = document.documentElement.dataset.theme === 'dark'
  theme.global.name.value = isDark ? 'dark' : 'light'
}

async function load() {
  try {
    const [opts, settings] = (await Promise.all([
      bridge.apiGet('options'),
      bridge.apiGet('settings'),
    ])) as [Options, Record<string, unknown>]

    options.hosts = opts.hosts || []
    options.images = opts.images || []
    options.models = opts.models || []

    Object.assign(form, settings)
    form.task_timeout_seconds = Number(settings.task_timeout_seconds) || 3600
    form.task_poll_interval = Number(settings.task_poll_interval) || 15
  } catch (e) {
    msg.value = '加载配置失败：' + (e as Error).message
    msgType.value = 'error'
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  msg.value = ''
  try {
    await bridge.apiPost('settings/save', { ...form })
    msg.value = '✅ 已保存'
    msgType.value = 'success'
  } catch (e) {
    msg.value = '保存失败：' + (e as Error).message
    msgType.value = 'error'
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  syncTheme()
  new MutationObserver(syncTheme).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  })
  await bridge.init()
  await load()
})
</script>

<template>
  <v-container fluid class="pa-4">
    <v-row justify="center">
      <v-col cols="12" md="10" lg="8">
        <h1 class="text-h6 mb-1">MonkeyCode 高级设置</h1>
        <p class="text-body-2 text-medium-emphasis mb-4">
          配置默认任务档位、轮询参数、日志与会话行为。
        </p>

        <v-alert v-if="msg" :type="msgType" class="mb-4" density="compact">
          {{ msg }}
        </v-alert>

        <v-card v-if="!loading" class="mb-4">
          <v-card-title>任务默认值</v-card-title>
          <v-card-text>
            <v-text-field
              v-model="form.default_repo_url"
              label="默认 GitHub 仓库 URL"
              hint="留空：不绑定仓库也能创建任务"
              persistent-hint
              density="comfortable"
            />
            <v-text-field
              v-model="form.default_branch"
              label="默认分支"
              density="comfortable"
            />
            <v-select
              v-model="form.default_cli_name"
              label="默认 agent CLI"
              :items="['opencode', 'codex', 'claude']"
              density="comfortable"
            />
            <v-select
              v-model="form.default_host_id"
              label="默认宿主 ID"
              :items="options.hosts"
              item-title="name"
              item-value="id"
              hint="留空用平台默认"
              persistent-hint
              clearable
              density="comfortable"
            />
            <v-select
              v-model="form.default_image_id"
              label="默认镜像 ID"
              :items="options.images"
              :item-title="(i: Record<string, unknown>) => displayName(i)"
              item-value="id"
              hint="留空自动取第一个"
              persistent-hint
              clearable
              density="comfortable"
            />
            <v-select
              v-model="form.default_model_id"
              label="默认模型 ID"
              :items="options.models"
              :item-title="(i: Record<string, unknown>) => displayName(i)"
              item-value="id"
              hint="留空自动取第一个"
              persistent-hint
              clearable
              density="comfortable"
            />
            <v-text-field
              v-model="form.skill_ids"
              label="默认技能列表"
              hint="逗号分隔，如 feature-design,project-wiki"
              persistent-hint
              density="comfortable"
            />
          </v-card-text>
        </v-card>

        <v-card v-if="!loading" class="mb-4">
          <v-card-title>任务轮询与日志</v-card-title>
          <v-card-text>
            <v-text-field
              v-model.number="form.task_timeout_seconds"
              label="轮询超时（秒）"
              type="number"
              min="60"
              max="10800"
              density="comfortable"
            />
            <v-text-field
              v-model.number="form.task_poll_interval"
              label="轮询间隔（秒）"
              type="number"
              min="5"
              max="120"
              density="comfortable"
            />
            <v-switch
              v-model="form.send_md_on_end"
              label="任务完成时发送完整日志 md 文件"
              color="primary"
              hide-details
            />
          </v-card-text>
        </v-card>

        <v-card v-if="!loading" class="mb-4">
          <v-card-title>会话</v-card-title>
          <v-card-text>
            <v-text-field
              v-model="form.session_path"
              label="登录会话持久化文件路径"
              hint="留空：插件数据目录"
              persistent-hint
              density="comfortable"
            />
          </v-card-text>
        </v-card>

        <div class="d-flex align-center ga-3">
          <v-btn
            color="primary"
            :loading="saving"
            :disabled="loading"
            @click="save"
          >
            保存设置
          </v-btn>
        </div>
      </v-col>
    </v-row>
  </v-container>
</template>

<style>
html,
body {
  background: transparent !important;
}
</style>