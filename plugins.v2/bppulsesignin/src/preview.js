import {createApp, defineAsyncComponent, h, ref} from 'vue'
import {createVuetify} from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import 'vuetify/styles'
const Page = defineAsyncComponent(() => import('bppulse/Page'))
const Config = defineAsyncComponent(() => import('bppulse/Config'))
const page = ref('dashboard')
async function call(url, data) {
  const response = await fetch('/api/v1/'+url, {method:data === undefined ? 'GET':'POST',headers:{'Content-Type':'application/json','X-Test-Admin':'yes'},body:data===undefined?undefined:JSON.stringify(data)})
  if (!response.ok) throw new Error('测试接口连接失败')
  return response.json()
}
const api = {get:url=>call(url), post:(url,data)=>call(url,data)}
async function hostSave(config) {
  const response = await fetch('/api/v1/plugin/BpPulseSignin', {method:'PUT',headers:{'Content-Type':'application/json','X-Test-Admin':'yes'},body:JSON.stringify(config)})
  const body = await response.json()
  if (body.success) page.value = 'dashboard'
  else throw new Error('模拟宿主保存失败')
}
const vuetify = createVuetify({components,directives,theme:{defaultTheme:'light',themes:{light:{colors:{primary:'#8b5cf6',success:'#007c52',background:'#f6f8f7'}}}}})
createApp({render:()=>h(components.VApp,{},()=>h(components.VMain,{},()=>[
  h('div',{style:'padding:12px 24px;background:#e5f0ea;color:#24543e;font:13px system-ui'},'本地交互测试 · 使用模拟账号和 bp 服务 · 测试验证码 123456'),
  h('div',{style:'max-width:1100px;margin:24px auto;background:white;border-radius:18px'},[h(page.value === 'dashboard' ? Page : Config,{api,pluginId:'BpPulseSignin',onSave:hostSave,onSwitch:()=>{page.value=page.value==='dashboard'?'settings':'dashboard'}})]),
]))}).use(vuetify).mount('#app')
