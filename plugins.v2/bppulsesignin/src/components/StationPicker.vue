<script setup>
import { ref } from 'vue'
const props = defineProps({ modelValue: Object, request: Function })
const emit = defineEmits(['update:modelValue'])
const open = ref(false)
const keyword = ref('')
const searched = ref('')
const items = ref([])
const total = ref(0)
const page = ref(1)
const busy = ref(false)
const error = ref('')
async function search(next = 1) {
  if (busy.value) return
  const query = next === 1 ? keyword.value.trim() : searched.value
  if (query.length < 2) { error.value = '请输入至少 2 个字符'; return }
  busy.value = true; error.value = ''
  try {
    const response = await props.request('stations/search', {keyword:query, page:next})
    items.value = response.data.items
    total.value = response.data.total; page.value = next; searched.value = query
  } catch (e) { items.value = []; error.value = e?.response ? '搜索失败，请检查连接' : e.message }
  finally { busy.value = false }
}
function select(item) {
  emit('update:modelValue', {id:item.id, name:item.name, address:item.address})
  open.value = false
}
</script>

<template>
  <div class="bp-picker">
    <div class="bp-picker-heading"><h3>常用充电站</h3><VBtn color="primary" variant="tonal" @click="open = true">{{ modelValue ? '更换站点' : '选择站点' }}</VBtn></div>
    <div v-if="modelValue" class="bp-selected"><div><strong>{{ modelValue.name }}</strong><p>{{ modelValue.address }}</p></div><VBtn variant="text" size="small" @click="emit('update:modelValue', null)">清除</VBtn></div>
    <p v-else class="bp-picker-hint">选择常去的站点，在看板查看空闲枪数及各账号适用的优惠券。</p>
    <p class="bp-picker-hint">所有账号共用；选择后点击下方“保存”生效。</p>
    <VDialog v-model="open" max-width="620">
      <VCard class="bp-search-dialog"><VCardTitle>选择常用充电站</VCardTitle><VCardText>
        <p class="bp-picker-hint mb-4">使用已登录账号查询，输入站名关键词即可。</p>
        <div class="bp-search-input"><VTextField v-model="keyword" label="站点关键词" placeholder="输入站点名称" maxlength="50" variant="outlined" density="comfortable" hide-details :disabled="busy" @keyup.enter="search()"/><VBtn color="primary" :loading="busy" @click="search()">搜索</VBtn></div>
        <VAlert v-if="error" type="error" variant="tonal" class="mt-4">{{ error }}</VAlert>
        <p v-else-if="searched" class="bp-picker-hint mt-4">“{{ searched }}” · 共 {{ total }} 个结果</p>
        <div class="bp-search-results"><button v-for="item in items" :key="item.id" type="button" :disabled="busy" @click="select(item)"><strong>{{ item.name }}</strong><span>{{ item.address || '暂无地址' }}</span></button></div>
        <p v-if="searched && !items.length && !error && !busy" class="bp-picker-hint">没有找到站点，请尝试更短的关键词。</p>
        <div v-if="total > 10" class="bp-search-pages"><VBtn variant="text" :disabled="busy || page === 1" @click="search(page - 1)">上一页</VBtn><span>第 {{ page }} 页</span><VBtn variant="text" :disabled="busy || page * 10 >= total" @click="search(page + 1)">下一页</VBtn></div>
      </VCardText><VCardActions><VSpacer/><VBtn @click="open = false">取消</VBtn></VCardActions></VCard>
    </VDialog>
  </div>
</template>

<style scoped>
.bp-picker{margin-bottom:28px}.bp-picker-heading,.bp-selected,.bp-search-input,.bp-search-pages{display:flex;align-items:center;justify-content:space-between;gap:12px}.bp-picker h3{font-size:15px}.bp-picker-hint,.bp-selected p{font-size:12px;opacity:.65;margin-top:6px}.bp-selected{border:1px solid rgba(var(--v-theme-on-surface),.12);padding:16px;border-radius:10px;margin-top:12px}.bp-search-dialog{padding:12px;border-radius:16px}.bp-search-input .v-input{min-width:0}.bp-search-results{display:grid;gap:8px;margin-top:16px}.bp-search-results button{text-align:left;padding:14px;border:1px solid rgba(var(--v-theme-on-surface),.12);border-radius:8px;color:inherit}.bp-search-results button:hover{background:rgba(var(--v-theme-primary),.06)}.bp-search-results span{display:block;font-size:12px;opacity:.65;margin-top:5px}.bp-search-pages{justify-content:center;margin-top:12px}
</style>
