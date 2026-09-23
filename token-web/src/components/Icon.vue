<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 20 })
const paths: Record<string, string> = {
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  dashboard: 'M3 3h7v11H3z M14 3h7v7h-7z M3 18h7v3H3z M14 14h7v7h-7z',
  box: 'm12 3 9 5-9 5-9-5 9-5z M3 8v9l9 5 9-5V8 M12 13v9 M7 5.8l9 5',
  key: 'M14 3a7 7 0 0 0-6.6 9.3L2 18v4h4v-3h3v-3l2-2A7 7 0 1 0 14 3z M16 7h.01',
  chat: 'M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-3 3V11.5A8.5 8.5 0 0 1 9.5 3h3a8.5 8.5 0 0 1 8.5 8.5z M7 10h8 M7 14h5',
  sparkle: 'm12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3z',
  book: 'M4 3h13a3 3 0 0 1 3 3v15H5a3 3 0 0 1-3-3V5a2 2 0 0 1 2-2z M2 17h18 M7 7h8 M7 11h5',
  arrow: 'M5 12h14 M13 6l6 6-6 6',
  search: 'M21 21l-6-6 M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0',
  close: 'm6 6 12 12 M6 18 18 6',
  plus: 'M12 5v14 M5 12h14',
  refresh: 'M20 7v5h-5 M4 17v-5h5 M19 12a7 7 0 0 0-12-5L4 10 M5 12a7 7 0 0 0 12 5l3-3',
  send: 'm22 2-7 20-4-9-9-4L22 2z M22 2 11 13',
  check: 'm5 12 4 4L19 6',
  user: 'M20 21v-2a6 6 0 0 0-6-6h-4a6 6 0 0 0-6 6v2 M16 6a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
  copy: 'M9 8h11v13H9z M15 8V3H3v13h6',
  bolt: 'm13 2-9 12h7l-1 8 10-13h-7l1-7z',
  chevron: 'm9 5 7 7-7 7',
  info: 'M12 11v6 M12 7h.01 M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
}
</script>
<template><svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="paths[name] || paths.grid" /></svg></template>
