<script setup>
import { computed, ref } from 'vue'
const props = defineProps({ account: Object, request: Function, claim: Function, busy: Boolean })
const emit = defineEmits(['updated'])
const open = ref(false)
const loading = ref(false)
const error = ref('')
const claimNotice = ref(null)
const claiming = ref(false)
const pending = r => String(r.status) === '1' || ['已完成', '待领取', '可领取'].includes((r.status_text || '').trim())
const pendingCount = computed(() => (props.account.rewards || []).filter(pending).length)
const color = r => pending(r) ? 'warning' : String(r.status) === '3' || r.status_text === '已发放' ? 'success' : 'grey'
const when = computed(() => props.account.reward_updated ? new Date(props.account.reward_updated * 1000).toLocaleString('zh-CN', {hour12:false}) : '尚未同步')
async function refresh() {
  if (loading.value || props.busy || claiming.value) return
  loading.value = true; error.value = ''
  try { emit('updated', (await props.request('rewards/refresh', {id:props.account.id})).data) }
  catch (e) { error.value = e?.response ? '奖励查询失败，请检查连接；更新插件后请先保存一次插件设置' : e.message }
  finally { loading.value = false }
}
async function claimAll() {
  if (claiming.value || props.busy || loading.value) return
  claiming.value = true; claimNotice.value = null
  try { claimNotice.value = await props.claim(props.account) }
  catch (e) { claimNotice.value = {type:'error', text:e?.response ? '领奖请求失败，请稍后重试' : e.message} }
  finally { claiming.value = false }
}
function show() { open.value = true; claimNotice.value = null; refresh() }
</script>

<template>
  <VBtn size="small" variant="text" color="primary" @click="show">奖励详情</VBtn>
  <VDialog v-model="open" max-width="620">
    <VCard class="bp-reward-dialog"><VCardTitle>签到奖励 · {{ account.name }}</VCardTitle><VCardText>
      <div class="bp-reward-header"><span>更新：{{ when }}</span><VBtn size="small" variant="text" color="primary" :loading="loading" :disabled="busy || claiming" @click="refresh">刷新奖励</VBtn></div>
      <p class="bp-reward-hint">奖励状态以 bp 返回为准。查看和刷新不会签到或领奖。</p>
      <p v-if="pendingCount && !account.reward_error" class="bp-reward-hint">已完成未领取 {{ pendingCount }} 项</p>
      <VAlert v-if="claimNotice" :type="claimNotice.type" variant="tonal" density="compact" class="mt-3">{{ claimNotice.text }}</VAlert>
      <VAlert v-if="error || account.reward_error" type="warning" variant="tonal" density="compact" class="mt-3">{{ error || account.reward_error }}{{ account.reward_updated ? '，下方保留上次查询结果。' : '' }}</VAlert>
      <div v-for="(r, i) in account.rewards || []" :key="i" class="bp-reward-item">
        <div class="bp-reward-header"><strong>{{ r.name }}</strong><VChip size="small" :color="color(r)" variant="tonal">{{ r.status_text || (r.status ? `状态未说明（${r.status}）` : '状态未说明') }}</VChip></div>
        <p>{{ r.description }}</p><p class="bp-reward-hint">进度 {{ r.progress ?? '—' }} / {{ r.target ?? '—' }}</p>
      </div>
      <p v-if="account.reward_updated && !account.rewards?.length" class="bp-reward-hint mt-4">本次查询未返回奖励任务。</p>
    </VCardText><VCardActions><VBtn @click="open = false">关闭</VBtn><VSpacer/><VBtn color="primary" variant="flat" :loading="claiming" :disabled="busy || loading || !account.has_token || account.auth_status === 'expired'" @click="claimAll">领取全部奖励</VBtn></VCardActions></VCard>
  </VDialog>
</template>

<style scoped>
.bp-reward-dialog{padding:12px;border-radius:16px}.bp-reward-header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.bp-reward-header>span,.bp-reward-hint{font-size:12px;opacity:.65}.bp-reward-item{padding-top:16px;margin-top:16px;border-top:1px solid rgba(var(--v-theme-on-surface),.12)}.bp-reward-item p{margin-top:6px;font-size:13px}.bp-reward-item strong{overflow-wrap:anywhere}
</style>
