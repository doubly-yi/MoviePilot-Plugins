<script setup>
import { computed, onMounted, ref } from 'vue'
const props = defineProps({ accounts: Array, selected: Object, station: Object, request: Function })
const emit = defineEmits(['updated', 'notice', 'settings'])
const refreshing = ref(false)
const all = ref(false)
const busy = ref({})
const when = value => value ? new Date(value * 1000).toLocaleString('zh-CN', {hour12:false}) : '尚未同步'
const date = value => value ? new Date(value * 1000).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai', hour12:false, year:'numeric',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '有效期未知'
const money = value => value == null ? '未知' : Number(value).toLocaleString('zh-CN', {maximumFractionDigits:2})
const couponTitle = c => c.type === '3' && c.rate != null ? `${money(c.rate)} 折 · 最多减 ${money(c.amount)} 元` : c.amount != null ? `减 ${money(c.amount)} 元` : c.kind || c.name
const inDate = c => c.validity === 'valid'
const matched = a => (a.coupons || []).filter(c => c.scope === 'match' && inDate(c))
const visible = a => all.value || !props.selected ? a.coupons || [] : (a.coupons || []).filter(c => c.scope === 'match' && !['used','expired'].includes(c.validity))
const count = computed(() => props.accounts.reduce((n,a) => n + matched(a).length, 0))
const limited = c => c.extra_limits || (c.usage_start && c.usage_start !== '00:00:00') || (c.usage_end && c.usage_end !== '23:59:59')
const validity = c => ({unknown:'有效期待确认', expired:'已过期', future:'尚未生效', used:'已使用或状态待确认'}[c.validity])
const guns = computed(() => [
  {name:'超充', available:props.station?.super_available, total:props.station?.super_total},
  {name:'快充', available:props.station?.fast_available, total:props.station?.fast_total},
  {name:'慢充', available:props.station?.slow_available, total:props.station?.slow_total}
].filter(g => g.total > 0))
async function refreshAccount(a, publish = true) {
  if (busy.value[a.id]) return
  busy.value[a.id] = true
  try {
    const response = await props.request('coupons/refresh', {id:a.id})
    if (publish) emit('updated', response.data)
  } catch (e) { emit('notice', {type:'error', text:`${a.name}：${e?.response ? '查询失败，请检查连接' : e.message}`}) }
  finally { busy.value[a.id] = false }
}
async function refresh() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    const pending = props.accounts.filter(a => a.has_token && a.auth_status !== 'expired').slice()
    const worker = async () => { while (pending.length) await refreshAccount(pending.shift(), false) }
    const station = async () => {
      if (!props.selected) return
      try { await props.request('station/refresh', {}) }
      catch (e) { emit('notice', {type:'error',text:e?.response ? '站点刷新失败' : e.message}) }
    }
    // 先查站点，避免与账号查询争用同一登录凭据的操作锁。
    await station()
    await Promise.all([worker(), worker()])
    emit('updated', (await props.request('status')).data)
  } catch (e) { emit('notice', {type:'error',text:e?.response ? '刷新失败，请检查连接' : e.message}) }
  finally { refreshing.value = false }
}
defineExpose({refresh, refreshAccount})
onMounted(refresh)
</script>

<template>
  <section class="bp-charging">
    <div class="bp-charge-heading"><h3>常用站点与优惠券</h3><VBtn size="small" variant="tonal" color="primary" :loading="refreshing" @click="refresh">刷新站点与优惠券</VBtn></div>
    <div v-if="selected" class="bp-station-card">
      <div><strong class="bp-station-name">{{ selected.name }}</strong><p class="bp-muted">{{ selected.address }}</p></div>
      <div class="bp-guns"><span v-for="g in guns" :key="g.name">{{ g.name }}空闲 <strong>{{ g.available ?? '—' }}</strong>/{{ g.total }}</span><span v-if="!guns.length">空闲 <strong>{{ station?.available ?? '—' }}</strong>/{{ station?.total ?? '—' }}</span><span v-if="station?.max_power" class="bp-muted">最高 {{ station.max_power }} kW</span></div>
      <p class="bp-muted">站点更新：{{ when(station?.updated) }}</p>
      <VAlert v-if="station?.error" type="warning" variant="tonal" density="compact" class="mt-3">{{ station.error }}{{ station.updated ? '，当前显示上次查询结果。' : '' }}</VAlert>
    </div>
    <div v-else class="bp-station-empty"><span>设置常用站点后，即可比较各账号的本站适用券。</span><VBtn color="primary" size="small" variant="text" @click="emit('settings')">选择站点</VBtn></div>
    <div class="bp-charge-heading bp-coupon-heading"><div><strong>{{ selected && !all ? `本站适用券 ${count} 张` : '全部未使用券' }}</strong><p class="bp-muted">按最近同步结果汇总，优先显示即将过期的券；使用门槛及限制仍需满足，优惠以结算为准。</p></div><VSwitch v-if="selected" v-model="all" label="全部未使用券" color="primary" density="compact" hide-details inset /></div>
    <div class="bp-coupon-accounts">
      <div v-for="a in accounts" :key="a.id" class="bp-coupon-account">
        <div class="bp-charge-heading"><h4>{{ a.name }}</h4><VChip size="small" :color="a.coupon_error || !a.coupon_updated ? 'warning' : matched(a).length ? 'success' : 'secondary'" variant="tonal">{{ a.coupon_error ? '刷新失败' : !a.has_token || a.auth_status === 'expired' ? '待登录' : !a.coupon_updated ? '待同步' : selected ? `${matched(a).length} 张本站适用` : `${(a.coupons || []).length} 张券` }}</VChip></div>
        <p class="bp-muted">优惠券更新：{{ when(a.coupon_updated) }}</p>
        <VAlert v-if="a.coupon_error" type="warning" variant="tonal" density="compact" class="mt-3">{{ a.coupon_error }}{{ a.coupon_updated ? '，下方为上次查询结果。' : '' }}</VAlert>
        <p v-if="!a.has_token || a.auth_status === 'expired'" class="bp-coupon-empty">请在下方账号列表手动登录后刷新。</p>
        <VProgressLinear v-if="busy[a.id]" indeterminate color="primary" class="mt-3"/>
        <div v-for="c in visible(a)" :key="c.id" class="bp-coupon">
          <div class="bp-charge-heading"><strong class="bp-coupon-value">{{ couponTitle(c) }}</strong><VChip v-if="c.expiring" color="warning" size="x-small">3 天内到期</VChip></div>
          <p>{{ c.kind }}<span v-if="c.minimum"> · 订单满 {{ money(c.minimum) }} 元</span></p>
          <p class="bp-muted">{{ c.name }}</p>
          <p class="bp-muted">有效期：{{ date(c.start) }} — {{ date(c.end) }}（北京时间）</p>
          <div class="bp-coupon-tags"><VChip v-if="selected" size="x-small" :color="c.scope === 'match' ? 'success' : 'secondary'">{{ {match:'本站适用',other:'其他站点',unknown:'站点范围待确认'}[c.scope] }}</VChip><VChip v-if="validity(c)" size="x-small" color="warning">{{ validity(c) }}</VChip><VChip v-if="limited(c)" size="x-small" color="warning">有额外使用限制</VChip></div>
          <details v-if="c.agreement || c.usage_start || c.extra_limits"><summary>使用规则</summary><p v-if="c.usage_start">每日 {{ c.usage_start }} — {{ c.usage_end || '未知' }}</p><p v-if="c.extra_limits">存在会员或星期限制，请在 bp 中确认具体要求。</p><p>{{ c.agreement || '暂无补充规则' }}</p></details>
        </div>
        <p v-if="a.coupon_updated && !visible(a).length && !busy[a.id]" class="bp-coupon-empty">{{ a.coupon_error ? '上次结果中没有匹配的券' : selected && !all ? '暂无本站适用券' : '暂无未使用优惠券' }}</p>
        <p v-if="selected && !all && (a.coupons || []).some(c => c.scope === 'unknown')" class="bp-muted">部分券的站点范围待确认，请切换“全部未使用券”查看。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.bp-charging{margin-top:28px;margin-bottom:28px}.bp-charge-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.bp-charge-heading h3{font-size:15px}.bp-station-card{margin-top:12px;padding:18px;border:1px solid rgba(var(--v-theme-primary),.25);border-radius:12px;background:rgba(var(--v-theme-primary),.025)}.bp-station-name{font-size:16px}.bp-muted{font-size:12px;opacity:.65;margin-top:5px}.bp-guns{display:flex;gap:20px;flex-wrap:wrap;align-items:center;margin:14px 0 8px}.bp-guns strong{font-size:24px;color:rgb(var(--v-theme-primary))}.bp-station-empty{padding:16px;border:1px dashed rgba(var(--v-theme-on-surface),.2);border-radius:10px;margin-top:12px;display:flex;align-items:center;justify-content:space-between;gap:12px}.bp-coupon-heading{margin:20px 0 12px;flex-wrap:wrap}.bp-coupon-accounts{display:grid;align-items:start;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.bp-coupon-account{border:1px solid rgba(var(--v-theme-on-surface),.12);border-radius:12px;padding:16px;min-width:0}.bp-coupon-account h4{font-size:15px}.bp-coupon{border-top:1px dashed rgba(var(--v-theme-on-surface),.15);margin-top:16px;padding-top:16px}.bp-coupon-value{color:rgb(var(--v-theme-primary));font-size:17px}.bp-coupon p{font-size:12px;margin-top:6px}.bp-coupon-tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}.bp-coupon-empty{padding:20px 0;font-size:13px;opacity:.65}.bp-coupon details{font-size:12px;margin-top:12px}.bp-coupon details p{white-space:pre-wrap;overflow-wrap:anywhere;opacity:.75}.bp-coupon summary{cursor:pointer;opacity:.7}
@media(max-width:600px){.bp-coupon-accounts{grid-template-columns:1fr}.bp-charge-heading{flex-wrap:wrap}.bp-station-empty{align-items:flex-start;flex-direction:column}.bp-guns{gap:12px}}
</style>
