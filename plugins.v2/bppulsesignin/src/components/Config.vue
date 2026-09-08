<script setup>
import Manager from './Manager.vue'
defineProps({ api: { type: [Object, Function], required: true }, pluginId: { type: String, default: 'BpPulseSignin' }, initialConfig: { type: Object, default: () => ({}) } })
const emit = defineEmits(['close', 'switch', 'save'])
</script>
<template><Manager mode="settings" :api="api" :plugin-id="pluginId" @close="emit('close')" @switch="emit('switch')" @save="emit('save', $event)" /></template>
