<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import StationPicker from './StationPicker.vue'
import ChargingBoard from './ChargingBoard.vue'
import RewardDetails from './RewardDetails.vue'
const props = defineProps({ api: { type: [Object, Function], required: true }, pluginId: { type: String, default: 'BpPulseSignin' }, mode: { type: String, default: 'dashboard' }, showSwitch: { type: Boolean, default: true } })
const emit = defineEmits(['close', 'switch', 'save'])
const accounts = ref([])
const station = ref(null)
const charging = ref(null)
const settings = ref({ enabled: false, cron: '0 8 * * *', notify: true })
const loaded = ref(false)
const loading = ref(false)
const saving = ref(false)
const notice = ref(null)
const cronError = ref('')
const busy = ref({})
const editor = ref(null)
const editing = ref(false)
const editorError = ref('')
const removeTarget = ref(null)
const loginTarget = ref(null)
const code = ref('')
const loginError = ref('')
const loginHint = ref('')
const now = ref(Date.now())
const timer = setInterval(() => { now.value = Date.now() }, 1000)
onUnmounted(() => clearInterval(timer))
const isSettings = computed(() => props.mode === 'settings')
const loggedIn = computed(() => accounts.value.filter(a => a.auth_status === 'valid').length)
const expired = computed(() => accounts.value.filter(a => ['expired', 'missing'].includes(a.auth_status)).length)
const enabledCount = computed(() => accounts.value.filter(a => a.enabled).length)
const couponCount = computed(() => {
  if (!settings.value.station || !accounts.value.some(a => a.coupon_updated)) return '—'
  return accounts.value.reduce((total, a) => total + (a.coupons || []).filter(c => c.scope === 'match' && c.validity === 'valid').length, 0)
})
const currentLogin = computed(() => accounts.value.find(a => a.id === loginTarget.value?.id))
const waitSeconds = computed(() => Math.max(0, Math.ceil(((currentLogin.value?.retryAt || 0) - now.value) / 1000)))
const phoneValid = v => /^1[3-9]\d{9}$/.test(v || '')
const codeValid = computed(() => /^\d{4,8}$/.test(code.value))
const authMeta = a => ({valid: ['已登录', 'success'], unknown: ['待验证', 'info'], expired: ['已过期', 'error'], missing: ['未登录', 'warning']}[a.auth_status] || ['待验证', 'info'])
const resultColor = a => ({success:'success', error:'error', expired:'warning', warning:'warning', processed:'info'}[a.status] || 'secondary')
function absorb(data, replaceSettings = false) {
  if (!data) return
  now.value = Date.now()
  accounts.value = (data.accounts || []).map(a => ({ ...a, retryAt: now.value + (a.sms_wait || 0) * 1000 }))
  station.value = data.station || null
  cronError.value = data.cron_error || ''
  if (!loaded.value || replaceSettings) settings.value = { ...data.settings }
  loaded.value = true
}
async function request(path, payload) {
  const url = `plugin/${props.pluginId || 'BpPulseSignin'}/${path}`
  const response = payload === undefined ? await props.api.get(url) : await props.api.post(url, payload)
  // MP 注入客户端通常直接返回 payload；兼容未解包的 Axios 响应。
  const body = typeof response?.success === 'boolean' ? response : response?.data
  if (!body || typeof body.success !== 'boolean') throw new Error('无法读取插件响应，请刷新重试')
  if (!body.success) throw new Error(body.message || '操作失败')
  return body
}
function errorText(error) { return error?.response ? '请求失败，请检查连接和管理员登录状态' : (error?.message || '操作失败，请稍后重试') }
async function refresh() {
  loading.value = true
  try { absorb((await request('status')).data); await charging.value?.refresh() } catch (e) { notice.value = { type:'error', text:errorText(e) } }
  finally { loading.value = false }
}
async function saveSettings() {
  if (saving.value) return
  saving.value = true
  try {
    const config = { ...settings.value, cron: settings.value.cron.trim() }
    await request('settings/validate', config)
    emit('save', config)
  } catch (e) { notice.value = {type:'error', text:errorText(e)} }
  finally { saving.value = false }
}
function openEditor(a) {
  editorError.value = ''
  editor.value = a ? {id:a.id, revision:a.revision, name:a.name, phone:a.phone, enabled:a.enabled, auto_claim:a.auto_claim ?? true, cookie:'', clear_token:false}
    : {name:'', phone:'', enabled:true, auto_claim:true, cookie:'', clear_token:false}
}
async function saveAccount() {
  if (editing.value) return
  if (!editor.value?.name?.trim() || !phoneValid(editor.value.phone)) { editorError.value = '请填写账号名称和有效的 11 位手机号'; return }
  editing.value = true
  try {
    const response = await request('account', editor.value)
    absorb(response.data); editor.value = null
    notice.value = {type:'success', text:response.message}
  } catch (e) { editorError.value = errorText(e) }
  finally { editing.value = false }
}
async function deleteAccount() {
  const account = removeTarget.value
  busy.value[account.id] = true
  try {
    const response = await request('delete', {id:account.id, revision:account.revision})
    absorb(response.data); removeTarget.value = null
    notice.value = {type:'success', text:response.message}
  } catch (e) { notice.value = {type:'error', text:errorText(e)}; removeTarget.value = null; await refresh() }
  finally { busy.value[account.id] = false }
}
async function checkIn(a) {
  busy.value[a.id] = true
  try {
    const response = await request('check-in', {id:a.id})
    absorb(response.data)
    const updated = accounts.value.find(item => item.id === a.id)
    notice.value = {type: ['error','expired','warning'].includes(updated?.status) ? 'warning' : 'success', text:`${a.name}：${response.message}`}
    if (updated?.auth_status === 'valid') await charging.value?.refreshAccount(updated)
  } catch (e) { notice.value = {type:'error', text:errorText(e)} }
  finally { busy.value[a.id] = false }
}
async function claimPrizes(a) {
  if (busy.value[a.id]) return
  busy.value[a.id] = true
  try {
    const response = await request('claim-prizes', {id:a.id})
    absorb(response.data)
    const updated = accounts.value.find(item => item.id === a.id)
    const resultNotice = {type:['error','expired'].includes(updated?.claim_status) ? 'warning' : 'success', text:`${a.name}：${response.message}`}
    notice.value = resultNotice
    if (updated?.auth_status === 'valid') await charging.value?.refreshAccount(updated)
    return resultNotice
  } catch (e) { notice.value = {type:'error', text:errorText(e)}; return notice.value }
  finally { busy.value[a.id] = false }
}
async function startLogin(a) {
  loginTarget.value = {id:a.id, name:a.name, phone:a.phone}
  code.value = ''; loginError.value = ''; loginHint.value = ''
  if (a.retryAt > Date.now()) {
    loginHint.value = a.code_pending ? '验证码已发送，请输入收到的验证码' : '发送请求正在冷却，请稍后重试'
    return
  }
  await sendCode()
}
async function sendCode() {
  const id = loginTarget.value.id
  busy.value[id] = true; loginError.value = ''; loginHint.value = ''
  try {
    const response = await request('send-code', {id})
    absorb(response.data); loginHint.value = response.message
  } catch (e) { loginError.value = errorText(e); await refresh() }
  finally { busy.value[id] = false }
}
async function verify() {
  if (!loginTarget.value || !codeValid.value || busy.value[loginTarget.value.id]) return
  const id = loginTarget.value.id
  busy.value[id] = true; loginError.value = ''
  try {
    const response = await request('login', {id, code:code.value})
    absorb(response.data); code.value = ''; loginTarget.value = null
    notice.value = {type:'success', text:response.message}
    const account = accounts.value.find(a => a.id === id)
    if (account) await charging.value?.refreshAccount(account)
  } catch (e) { loginError.value = errorText(e) }
  finally { busy.value[id] = false }
}
function closeLogin() { code.value = ''; loginTarget.value = null; loginError.value = '' }
function formatDate(value) { return value ? new Date(value).toLocaleString('zh-CN', {hour12:false}) : '尚未执行' }
onMounted(refresh)
</script>

<template>
  <div class="bp-manager">
    <div class="bp-header">
      <h2>{{ isSettings ? 'bp PULSE 签到 - 插件配置' : 'bp PULSE 签到' }}</h2>
      <div class="bp-header-actions"><VBtn v-if="!isSettings" variant="text" size="small" :loading="loading" @click="refresh">刷新</VBtn><VBtn icon="mdi-close" variant="text" size="small" class="bp-close" aria-label="关闭" title="关闭" @click="emit('close')" /></div>
    </div>
    <VAlert v-if="notice" :type="notice.type" variant="tonal" closable class="mb-4" @click:close="notice = null">{{ notice.text }}</VAlert>
    <VProgressLinear v-if="loading" indeterminate color="primary" class="mb-4" />

    <template v-if="!isSettings">
      <div class="bp-summary">
        <div><span>账号总数</span><strong>{{ accounts.length }}</strong></div>
        <div><span>登录正常</span><strong class="bp-success">{{ loggedIn }}</strong></div>
        <div><span>待登录</span><strong :class="{'bp-attention':expired}">{{ expired }}</strong></div>
        <div><span>定时账号</span><strong>{{ enabledCount }}</strong></div>
        <div :title="settings.station ? '按最近同步结果统计本站适用且在有效期内的券，使用限制见下方详情' : '请先设置常用站点'"><span>可用优惠券</span><strong class="bp-success">{{ couponCount }}</strong></div>
      </div>
      <div class="bp-section-title mb-3"><h3>签到状态</h3><VChip size="small" color="primary" variant="tonal">{{ settings.enabled ? '定时已开启' : '定时未开启' }}</VChip></div>
      <div v-if="!accounts.length && loaded" class="bp-empty"><h3>还没有账号</h3><p>前往设置添加账号，完成登录后即可签到。</p><VBtn v-if="showSwitch" color="primary" variant="tonal" @click="emit('switch')">前往设置</VBtn></div>
      <VTable v-else density="comfortable" class="bp-status-table">
        <thead><tr><th>账号</th><th>登录状态</th><th>最近签到</th><th>签到结果</th><th class="text-right">操作</th></tr></thead>
        <tbody><tr v-for="a in accounts" :key="a.id">
          <td><strong>{{ a.name }}</strong><p class="bp-phone">{{ a.phone.slice(0,3) }}****{{ a.phone.slice(-4) }}</p><p v-if="!a.enabled" class="bp-hint">仅手动签到</p><p v-if="a.auto_claim === false" class="bp-hint">自动领奖已关闭</p></td>
          <td><VChip :color="authMeta(a)[1]" size="small" variant="tonal">{{ authMeta(a)[0] }}</VChip></td>
          <td class="bp-date">{{ formatDate(a.last_run) }}</td>
          <td><span :class="`bp-state-${a.status || 'idle'}`">{{ a.message || '尚未签到' }}</span><p v-if="a.claim_message" class="bp-hint" :class="`bp-state-${a.claim_status}`" :title="formatDate(a.last_claim)">手动领奖：{{ a.claim_message }}</p></td>
          <td><div class="bp-row-actions"><VBtn size="small" variant="tonal" color="primary" :loading="busy[a.id]" :disabled="!a.has_token || a.auth_status === 'expired'" @click="checkIn(a)">签到</VBtn><RewardDetails :account="a" :request="request" :claim="claimPrizes" :busy="!!busy[a.id]" @updated="absorb" /><VBtn size="small" variant="text" color="primary" :disabled="busy[a.id]" @click="startLogin(a)">登录</VBtn></div></td>
        </tr></tbody>
      </VTable>
      <ChargingBoard v-if="loaded && accounts.length" ref="charging" :accounts="accounts" :selected="settings.station" :station="station" :request="request" @updated="absorb" @notice="notice = $event" @settings="emit('switch')" />
      <div v-if="showSwitch" class="bp-board-footer"><VBtn color="primary" variant="flat" rounded="pill" @click="emit('switch')"><svg class="bp-gear" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="m19.4 13 .1-1-.1-1 2-1.5-2-3.5-2.3 1a8 8 0 0 0-1.7-1L15 3h-4l-.4 3a8 8 0 0 0-1.7 1l-2.3-1-2 3.5 2 1.5-.1 1 .1 1-2 1.5 2 3.5 2.3-1a8 8 0 0 0 1.7 1l.4 3h4l.4-3a8 8 0 0 0 1.7-1l2.3 1 2-3.5zM13 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7"/></svg>设置</VBtn></div>
    </template>

    <template v-else>
      <div class="bp-config-options">
        <VSwitch v-model="settings.enabled" color="primary" label="启用定时签到" hide-details />
        <VSwitch v-model="settings.notify" color="primary" label="发送签到结果通知" hide-details />
      </div>
      <VTextField v-model="settings.cron" label="执行周期（Cron）" placeholder="0 8 * * *" hint="五段表达式，按 MP 时区执行；示例：每天 08:00" persistent-hint density="comfortable" variant="outlined" :error-messages="cronError" class="mb-6" />
      <VAlert type="info" variant="tonal" density="compact" class="mb-6">登录失效时会发送通知。重新登录请在看板点击对应账号的“登录”。</VAlert>
      <StationPicker v-if="loaded" v-model="settings.station" :request="request" />
      <div class="bp-section-title mb-3"><div><h3>账号管理</h3><p class="bp-hint">账号修改即时保存；执行设置通过下方“保存”生效。</p></div><VBtn color="primary" variant="tonal" :disabled="!loaded" @click="openEditor(null)">添加账号</VBtn></div>
      <div v-if="!accounts.length && loaded" class="bp-empty"><h3>添加第一个账号</h3><p>填写手机号后，前往看板使用短信验证码登录。</p></div>
      <div class="bp-accounts">
        <VCard v-for="a in accounts" :key="a.id" variant="outlined" class="bp-account">
          <VCardText>
            <div class="bp-section-title"><div><h3>{{ a.name }}</h3><p class="bp-phone">{{ a.phone.slice(0,3) }}****{{ a.phone.slice(-4) }}</p></div><VChip :color="authMeta(a)[1]" size="small" variant="tonal">{{ authMeta(a)[0] }}</VChip></div>
            <div class="bp-account-actions"><span class="bp-hint">{{ a.enabled ? '参与定时签到' : '仅手动签到' }} · {{ a.auto_claim === false ? '手动领奖' : '自动领奖' }}</span><VSpacer/><VBtn variant="text" size="small" :disabled="busy[a.id]" @click="openEditor(a)">编辑</VBtn><VBtn variant="text" color="error" size="small" :disabled="busy[a.id]" @click="removeTarget = a">删除</VBtn></div>
          </VCardText>
        </VCard>
      </div>
      <div class="bp-config-footer"><VBtn variant="tonal" color="info" :disabled="saving" @click="emit('switch')">查看数据</VBtn><VBtn color="primary" variant="flat" :loading="saving" :disabled="!loaded" @click="saveSettings">保存</VBtn></div>
    </template>
    <VDialog :model-value="!!editor" max-width="520" persistent>
      <VCard v-if="editor" class="bp-dialog"><VCardTitle>{{ editor.id ? '编辑账号' : '添加账号' }}</VCardTitle><VCardText>
        <VAlert v-if="editorError" type="error" variant="tonal" class="mb-4">{{ editorError }}</VAlert>
        <VTextField v-model="editor.name" label="账号名称" placeholder="例如：我的账号" maxlength="40" variant="outlined" class="mb-2" />
        <VTextField v-model="editor.phone" label="手机号" type="tel" autocomplete="off" maxlength="11" variant="outlined" class="mb-2" />
        <VTextField v-model="editor.cookie" label="Token（可选）" type="password" autocomplete="new-password" variant="outlined" :hint="editor.id ? '留空保留已有登录信息；更换手机号会清除旧登录信息' : '可以留空，保存后点击登录'" persistent-hint />
        <VCheckbox v-if="editor.id" v-model="editor.clear_token" label="清除已保存的登录信息" color="warning" hide-details />
        <VSwitch v-model="editor.enabled" color="primary" label="参与定时签到" hide-details />
        <VSwitch v-model="editor.auto_claim" color="primary" label="签到后自动领取奖励" hide-details />
        <p class="bp-hint">关闭后，手动和定时签到均不主动领奖；可在“奖励详情”中点击“领取全部奖励”。</p>
      </VCardText><VCardActions><VSpacer/><VBtn :disabled="editing" @click="editor = null">取消</VBtn><VBtn color="primary" variant="flat" :loading="editing" @click="saveAccount">保存账号</VBtn></VCardActions></VCard>
    </VDialog>
    <VDialog :model-value="!!loginTarget" max-width="480" persistent>
      <VCard v-if="loginTarget" class="bp-dialog"><VCardTitle>短信登录 · {{ loginTarget.name }}</VCardTitle><VCardText>
        <p class="mb-4">验证码发送至 {{ loginTarget.phone.slice(0,3) }}****{{ loginTarget.phone.slice(-4) }}</p>
        <VAlert v-if="loginError" type="error" variant="tonal" class="mb-4">{{ loginError }}</VAlert>
        <VAlert v-else-if="loginHint" type="info" variant="tonal" class="mb-4">{{ loginHint }}</VAlert>
        <VProgressLinear v-if="busy[loginTarget.id]" indeterminate color="primary" class="mb-4" />
        <VTextField v-model="code" label="短信验证码" inputmode="numeric" autocomplete="one-time-code" maxlength="8" variant="outlined" :disabled="busy[loginTarget.id]" @keyup.enter="verify" />
        <VBtn variant="text" size="small" :disabled="busy[loginTarget.id] || waitSeconds > 0" @click="sendCode">{{ waitSeconds > 0 ? `${waitSeconds} 秒后可重新发送` : '重新发送验证码' }}</VBtn>
      </VCardText><VCardActions><VBtn :disabled="busy[loginTarget.id]" @click="closeLogin">取消</VBtn><VSpacer/><VBtn color="primary" variant="flat" :loading="busy[loginTarget.id]" :disabled="!codeValid" @click="verify">验证并登录</VBtn></VCardActions></VCard>
    </VDialog>
    <VDialog :model-value="!!removeTarget" max-width="420" persistent><VCard v-if="removeTarget" class="bp-dialog"><VCardTitle>删除账号</VCardTitle><VCardText>确定删除“{{ removeTarget.name }}”？该账号的登录信息和签到记录将一并移除。</VCardText><VCardActions><VSpacer/><VBtn :disabled="busy[removeTarget.id]" @click="removeTarget = null">取消</VBtn><VBtn color="error" :loading="busy[removeTarget.id]" @click="deleteAccount">确认删除</VBtn></VCardActions></VCard></VDialog>
  </div>
</template>

<style scoped>
.bp-manager{padding:20px;max-width:1200px;margin:0 auto;color:rgb(var(--v-theme-on-surface));font-size:14px}
.bp-header,.bp-section-title,.bp-account-actions{display:flex;align-items:center;justify-content:space-between;gap:12px}
.bp-header{margin-bottom:28px}.bp-header-actions{display:flex;align-items:center;gap:4px}.bp-close{color:rgba(var(--v-theme-on-surface),.6)}.bp-manager h2{font-size:18px;font-weight:600}.bp-manager h3{font-size:15px;font-weight:600}.bp-hint,.bp-phone{font-size:12px;opacity:.65;margin:4px 0 0}
.bp-summary{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-bottom:24px}.bp-summary>div{background:rgba(var(--v-theme-on-surface),.025);border-left:2px solid rgba(var(--v-theme-primary),.35);padding:12px 16px;border-radius:10px;display:flex;flex-direction:column;gap:4px}.bp-summary span{opacity:.65;font-size:12px}.bp-summary strong{font-size:24px;font-weight:600}.bp-success,.bp-state-success{color:rgb(var(--v-theme-success))}.bp-attention,.bp-state-expired,.bp-state-warning{color:rgb(var(--v-theme-warning))}.bp-state-error{color:rgb(var(--v-theme-error))}
.bp-status-table{border:1px solid rgba(var(--v-theme-on-surface),.12);border-radius:10px}.bp-status-table th{white-space:nowrap}.bp-status-table td{padding-top:12px!important;padding-bottom:12px!important}.bp-status-table td:first-child{min-width:140px}.bp-status-table td:nth-child(4){min-width:170px;font-size:12px}.bp-date{min-width:140px;font-size:12px;opacity:.7}.bp-row-actions{display:flex;justify-content:flex-end;gap:4px}.bp-board-footer{display:flex;justify-content:flex-end;margin-top:24px;position:sticky;bottom:16px}.bp-gear{width:20px;height:20px;margin-right:8px}
.bp-config-options{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-bottom:24px}.bp-accounts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.bp-account{border-color:rgba(var(--v-theme-on-surface),.12);border-radius:12px}.bp-account-actions{gap:6px;margin-top:16px}.bp-empty{text-align:center;border:1px dashed rgba(var(--v-theme-on-surface),.2);border-radius:12px;padding:36px 16px}.bp-empty p{opacity:.6;margin:8px 0 20px}.bp-dialog{padding:12px;border-radius:16px}.bp-phone{font-variant-numeric:tabular-nums}.bp-config-footer{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-top:24px;padding:0;background:transparent}
@media(max-width:600px){.bp-manager{padding:16px}.bp-manager h2{font-size:16px}.bp-header{gap:4px}.bp-summary{grid-template-columns:repeat(2,1fr)}.bp-summary>div{padding:10px 12px}.bp-summary>div:last-child{grid-column:1/-1}.bp-config-options{grid-template-columns:1fr;gap:0}.bp-accounts{grid-template-columns:1fr}}
</style>
