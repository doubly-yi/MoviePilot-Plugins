<script setup>
import Manager from './Manager.vue'
defineProps({ api: { type: [Object, Function], required: true }, pluginId: { type: String, default: 'BpPulseSignin' }, show_switch: { type: Boolean, default: true } })
const emit = defineEmits(['close', 'switch'])
</script>
<template><Manager mode="dashboard" :api="api" :plugin-id="pluginId" :show-switch="show_switch" @close="emit('close')" @switch="emit('switch')" /></template>
