<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useTheme } from 'vuetify'

import { useBridge } from './composables/useBridge'

const bridge = useBridge()
const theme = useTheme()
const tab = ref<'dashboard' | 'settings'>('dashboard')

const loading = ref(true)
const saving = ref(false)
const msg = ref('')
const msgType = ref<'success' | 'error'>('success')

// ---------- 概览数据 ----------
interface TaskItem {
  id: string
  status: string
  content?: string
  title?: string
  created_at?: number
  model?: Record<string, unknown>
}

const dash = reactive({
  user: {} as Record<string, unknown>,
  wallet: {} as Record<string, unknown>,
  subscription: {} as Record<string, unknown>,
  runningTasks: [] as TaskItem[],
  recentTasks: [] as TaskItem[],
})

const lowBalanceThreshold = ref(10000)
const detailLoading = ref(false)
const detailDialog = ref(false)
const detailTask = ref<Record<string, unknown> | null>(null)
const detailRounds = ref<Array<Record<string, unknown>>>([])

// ---------- 设置表单 ----------
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
  notify_on_task_end: true,
  task_summary_length: 200,
  md_log_max_rounds: 10,
  reply_read_timeout: 60,
  max_concurrent_tasks: 0,
  desensitize_enabled: true,
  auto_switch_model: false,
  fallback_model_ids: '',
  low_balance_threshold: 100,
})

function displayName(item: Record<string, unknown>): string {
  return String(item.name || item.model || item.image_name || item.id || '')
}

function syncTheme() {
  const isDark = document.documentElement.dataset.theme === 'dark'
  theme.global.name.value = isDark ? 'dark' : 'light'
}

function fmtDate(ts?: number): string {
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

function statusColor(status: string): string {
  if (status === 'processing' || status === 'running' || status === 'pending') return 'primary'
  if (status === 'completed' || status === 'success') return 'success'
  if (status === 'error' || status === 'failed') return 'error'
  return 'grey'
}

function statusText(status: string): string {
  const map: Record<string, string> = {
    pending: '排队中',
    processing: '执行中',
    running: '执行中',
    completed: '已完成',
    success: '已完成',
    error: '失败',
    failed: '失败',
    terminated: '已停止',
    stopped: '已停止',
  }
  return map[status] || status
}

function walletBalance(): number {
  // 平台原始值 1000 = 1 点
  return Number(dash.wallet.balance || 0) / 1000
}

function dailyToken(): { used: number; limit: number; percent: number } {
  const limit = Number(dash.wallet.daily_token_limit || 0)
  const balance = Number(dash.wallet.daily_token_balance || 0)
  const used = Math.max(limit - balance, 0)
  const percent = limit > 0 ? Math.round((used / limit) * 100) : 0
  return { used, limit, percent }
}

function lowBalanceAlert(): boolean {
  return walletBalance() < lowBalanceThreshold.value
}

// ---------- 数据加载 ----------
async function loadSettings() {
  const settings = (await bridge.apiGet('settings')) as Record<string, unknown>
  Object.assign(form, settings)
  form.task_timeout_seconds = Number(settings.task_timeout_seconds) || 3600
  form.task_poll_interval = Number(settings.task_poll_interval) || 15
  form.task_summary_length = Number(settings.task_summary_length) || 200
  form.md_log_max_rounds = Number(settings.md_log_max_rounds) || 10
  form.reply_read_timeout = Number(settings.reply_read_timeout) || 60
  form.max_concurrent_tasks = Number(settings.max_concurrent_tasks) || 0
  form.low_balance_threshold = Number(settings.low_balance_threshold) || 100
  lowBalanceThreshold.value = form.low_balance_threshold
}

async function loadOptions() {
  const opts = (await bridge.apiGet('options')) as Options
  options.hosts = opts.hosts || []
  options.images = opts.images || []
  options.models = opts.models || []
}

async function loadDashboard() {
  const data = (await bridge.apiGet('dashboard')) as typeof dash
  Object.assign(dash, data)
}

async function loadAll() {
  try {
    await Promise.all([loadSettings(), loadOptions(), loadDashboard()])
  } catch (e) {
    msg.value = '加载失败：' + (e as Error).message
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
    lowBalanceThreshold.value = form.low_balance_threshold
    msg.value = '✅ 已保存'
    msgType.value = 'success'
  } catch (e) {
    msg.value = '保存失败：' + (e as Error).message
    msgType.value = 'error'
  } finally {
    saving.value = false
  }
}

async function openTaskDetail(task: TaskItem) {
  detailDialog.value = true
  detailLoading.value = true
  detailTask.value = task
  detailRounds.value = []
  try {
    const data = (await bridge.apiGet('task/' + task.id)) as {
      task: Record<string, unknown>
      rounds: { chunks?: Array<Record<string, unknown>> }
    }
    detailTask.value = data.task || task
    detailRounds.value = data.rounds?.chunks || []
  } catch (e) {
    msg.value = '加载任务详情失败：' + (e as Error).message
    msgType.value = 'error'
  } finally {
    detailLoading.value = false
  }
}

function roundText(c: Record<string, unknown>): string {
  const d = c.data
  if (typeof d !== 'string') return JSON.stringify(d)
  if (d.length % 4 === 0) {
    try {
      const decoded = decodeURIComponent(
        atob(d.replace(/-/g, '+').replace(/_/g, '/')),
      )
      return decoded.slice(0, 300)
    } catch {
      return d.slice(0, 300)
    }
  }
  return d.slice(0, 300)
}

function roundLabel(c: Record<string, unknown>): string {
  return String(c.event || c.kind || 'agent')
}

onMounted(async () => {
  syncTheme()
  new MutationObserver(syncTheme).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  })
  await bridge.init()
  await loadAll()
})
</script>

<template>
  <v-container fluid class="pa-4">
    <v-row justify="center">
      <v-col cols="12" md="10" lg="8">
        <h1 class="text-h6 mb-1">MonkeyCode 后台</h1>
        <p class="text-body-2 text-medium-emphasis mb-4">
          账户详情、额度概览与运行中会话。
        </p>

        <v-alert v-if="msg" :type="msgType" class="mb-4" density="compact">
          {{ msg }}
        </v-alert>

        <v-tabs v-model="tab" color="primary" class="mb-4">
          <v-tab value="dashboard">概览</v-tab>
          <v-tab value="settings">设置</v-tab>
        </v-tabs>

        <v-window v-model="tab">
          <!-- ============ 概览 ============ -->
          <v-window-item value="dashboard">
            <v-row v-if="!loading">
              <v-col cols="12" md="6">
                <v-card class="mb-4">
                  <v-card-title>账户详情</v-card-title>
                  <v-card-text>
                    <v-list density="compact">
                      <v-list-item>
                        <template #prepend><v-icon>mdi-account</v-icon></template>
                        <v-list-item-title>{{
                          String(dash.user?.email || dash.user?.username || '-')
                        }}</v-list-item-title>
                        <v-list-item-subtitle>邮箱 / 用户名</v-list-item-subtitle>
                      </v-list-item>
                      <v-list-item>
                        <template #prepend><v-icon>mdi-star</v-icon></template>
                        <v-list-item-title>{{
                          String(dash.subscription?.plan || 'free')
                        }}</v-list-item-title>
                        <v-list-item-subtitle>订阅计划</v-list-item-subtitle>
                      </v-list-item>
                      <v-list-item>
                        <template #prepend><v-icon>mdi-badge-account</v-icon></template>
                        <v-list-item-title>{{
                          String(dash.user?.id || '-')
                        }}</v-list-item-title>
                        <v-list-item-subtitle>用户 ID</v-list-item-subtitle>
                      </v-list-item>
                    </v-list>
                  </v-card-text>
                </v-card>
              </v-col>

              <v-col cols="12" md="6">
                <v-card class="mb-4">
                  <v-card-title>额度</v-card-title>
                  <v-card-text>
                    <v-alert
                      v-if="lowBalanceAlert()"
                      type="warning"
                      density="compact"
                      class="mb-3"
                    >
                      ⚠️ 余额低于告警阈值（{{ lowBalanceThreshold }}）
                    </v-alert>
                    <div class="text-body-1 mb-1">
                      积分余额：
                      <strong :class="{ 'text-error': lowBalanceAlert() }">{{
                        walletBalance()
                      }}</strong>
                    </div>
                    <div class="text-body-2 mb-1">
                      每日 Token 剩余：{{ dailyToken().limit - dailyToken().used }} /
                      {{ dailyToken().limit }}
                    </div>
                    <v-progress-linear
                      :model-value="dailyToken().percent"
                      :color="dailyToken().percent > 80 ? 'error' : 'primary'"
                      height="8"
                      rounded
                    />
                    <div class="text-caption text-medium-emphasis mt-1">
                      已用 {{ dailyToken().used }}（{{ dailyToken().percent }}%）
                    </div>
                  </v-card-text>
                </v-card>
              </v-col>

              <v-col cols="12">
                <v-card>
                  <v-card-title>当前在运行的会话</v-card-title>
                  <v-card-text>
                    <v-list v-if="dash.runningTasks.length" density="compact">
                      <v-list-item
                        v-for="t in dash.runningTasks"
                        :key="t.id"
                        @click="openTaskDetail(t)"
                        class="mb-1"
                      >
                        <template #prepend>
                          <v-chip
                            size="small"
                            :color="statusColor(t.status)"
                            text-color="white"
                          >
                            {{ statusText(t.status) }}
                          </v-chip>
                        </template>
                        <v-list-item-title>{{
                          String(t.content || t.title || t.id).slice(0, 60)
                        }}</v-list-item-title>
                        <v-list-item-subtitle>
                          {{ t.id }} · {{ fmtDate(t.created_at) }}
                        </v-list-item-subtitle>
                        <template #append>
                          <v-icon size="small">mdi-chevron-right</v-icon>
                        </template>
                      </v-list-item>
                    </v-list>
                    <div v-else class="text-body-2 text-medium-emphasis">
                      当前没有运行中的会话。
                    </div>
                  </v-card-text>
                </v-card>
              </v-col>

              <v-col cols="12" class="mt-4">
                <v-card>
                  <v-card-title>最近任务</v-card-title>
                  <v-card-text>
                    <v-list v-if="dash.recentTasks.length" density="compact">
                      <v-list-item
                        v-for="t in dash.recentTasks"
                        :key="t.id"
                        @click="openTaskDetail(t)"
                      >
                        <template #prepend>
                          <v-chip
                            size="small"
                            :color="statusColor(t.status)"
                            text-color="white"
                          >
                            {{ statusText(t.status) }}
                          </v-chip>
                        </template>
                        <v-list-item-title>{{
                          String(t.content || t.title || t.id).slice(0, 60)
                        }}</v-list-item-title>
                        <v-list-item-subtitle>{{ t.id }}</v-list-item-subtitle>
                      </v-list-item>
                    </v-list>
                    <div v-else class="text-body-2 text-medium-emphasis">
                      暂无任务记录。
                    </div>
                  </v-card-text>
                </v-card>
              </v-col>
            </v-row>
          </v-window-item>

          <!-- ============ 设置 ============ -->
          <v-window-item value="settings">
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
                  clearable
                  density="comfortable"
                />
                <v-select
                  v-model="form.default_image_id"
                  label="默认镜像 ID"
                  :items="options.images"
                  :item-title="(i: Record<string, unknown>) => displayName(i)"
                  item-value="id"
                  clearable
                  density="comfortable"
                />
                <v-select
                  v-model="form.default_model_id"
                  label="默认模型 ID"
                  :items="options.models"
                  :item-title="(i: Record<string, unknown>) => displayName(i)"
                  item-value="id"
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
                <v-switch
                  v-model="form.notify_on_task_end"
                  label="任务完成时发送短通知"
                  color="primary"
                  hide-details
                />
                <v-text-field
                  v-model.number="form.task_summary_length"
                  label="通知中摘要截断长度"
                  type="number"
                  min="50"
                  max="1000"
                  density="comfortable"
                />
                <v-text-field
                  v-model.number="form.md_log_max_rounds"
                  label="任务日志导出的最大轮次数"
                  type="number"
                  min="3"
                  max="50"
                  density="comfortable"
                />
                <v-text-field
                  v-model.number="form.reply_read_timeout"
                  label="/mc 回复 等待 agent 响应的超时（秒）"
                  type="number"
                  min="10"
                  max="300"
                  density="comfortable"
                />
                <v-text-field
                  v-model.number="form.max_concurrent_tasks"
                  label="最大并发任务数（0 不限制）"
                  type="number"
                  min="0"
                  max="20"
                  density="comfortable"
                />
              </v-card-text>
            </v-card>

            <v-card v-if="!loading" class="mb-4">
              <v-card-title>自动切换与告警</v-card-title>
              <v-card-text>
                <v-switch
                  v-model="form.auto_switch_model"
                  label="任务失败时自动切换备用模型并重启"
                  color="primary"
                  hide-details
                />
                <v-text-field
                  v-model="form.fallback_model_ids"
                  label="备用模型 ID（逗号分隔）"
                  hint="用 /mc 环境 查询模型 ID"
                  persistent-hint
                  density="comfortable"
                />
                <v-text-field
                  v-model.number="form.low_balance_threshold"
                  label="余额低额告警阈值（点，1000 原始值=1 点）"
                  type="number"
                  min="0"
                  max="1000000"
                  density="comfortable"
                />
              </v-card-text>
            </v-card>

            <v-card v-if="!loading" class="mb-4">
              <v-card-title>会话与安全</v-card-title>
              <v-card-text>
                <v-text-field
                  v-model="form.session_path"
                  label="登录会话持久化文件路径"
                  hint="留空：插件数据目录"
                  persistent-hint
                  density="comfortable"
                />
                <v-switch
                  v-model="form.desensitize_enabled"
                  label="敏感信息自动脱敏（PAT/API Key 等）"
                  color="primary"
                  hide-details
                />
              </v-card-text>
            </v-card>

            <div class="d-flex align-center ga-3">
              <v-btn color="primary" :loading="saving" @click="save">
                保存设置
              </v-btn>
            </div>
          </v-window-item>
        </v-window>

        <!-- 会话详情 Dialog -->
        <v-dialog v-model="detailDialog" max-width="720">
          <v-card>
            <v-card-title>
              <span class="text-h6">会话详情</span>
            </v-card-title>
            <v-card-text v-if="detailLoading">加载中...</v-card-text>
            <v-card-text v-else>
              <div class="text-body-2 mb-2">
                <strong>任务 ID：</strong>{{ detailTask?.id }}
              </div>
              <div class="text-body-2 mb-2">
                <strong>状态：</strong>
                <v-chip
                  size="small"
                  :color="statusColor(String(detailTask?.status || ''))"
                  text-color="white"
                >
                  {{ statusText(String(detailTask?.status || '')) }}
                </v-chip>
              </div>
              <div v-if="detailTask?.content" class="text-body-2 mb-3">
                <strong>内容：</strong>{{ String(detailTask.content).slice(0, 200) }}
              </div>
              <v-divider class="mb-3" />
              <div class="text-subtitle-2 mb-2">执行轮次</div>
              <div
                v-for="(c, i) in detailRounds"
                :key="i"
                class="text-body-2 mb-2"
                style="white-space: pre-wrap"
              >
                <strong>[{{ roundLabel(c) }}]</strong> {{ roundText(c) }}
              </div>
              <div v-if="!detailRounds.length" class="text-body-2 text-medium-emphasis">
                暂无轮次记录。
              </div>
            </v-card-text>
            <v-card-actions>
              <v-spacer />
              <v-btn variant="text" @click="detailDialog = false">关闭</v-btn>
            </v-card-actions>
          </v-card>
        </v-dialog>
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