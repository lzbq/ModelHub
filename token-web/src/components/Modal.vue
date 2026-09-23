<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import Icon from './Icon.vue'
withDefaults(defineProps<{ title: string; wide?: boolean; locked?: boolean }>(), { locked: false })
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLElement>()
let previous: HTMLElement | null = null
function keydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
  if (e.key !== 'Tab' || !dialog.value) return
  const elements = [...dialog.value.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]')]
  const first = elements[0], last = elements.at(-1)
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus() }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus() }
}
onMounted(() => { previous = document.activeElement as HTMLElement; dialog.value?.focus(); document.body.style.overflow = 'hidden'; document.addEventListener('keydown', keydown) })
onBeforeUnmount(() => { document.body.style.overflow = ''; document.removeEventListener('keydown', keydown); previous?.focus() })
</script>
<template><Teleport to="body"><div class="modal-backdrop" @click.self="!locked && $emit('close')"><section ref="dialog" class="modal" :class="{ 'modal-wide': wide }" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1"><header class="modal-header"><h2>{{ title }}</h2><button :disabled="locked" class="icon-button" aria-label="关闭弹窗" @click="$emit('close')"><Icon name="close" /></button></header><div class="modal-body"><slot /></div></section></div></Teleport></template>
