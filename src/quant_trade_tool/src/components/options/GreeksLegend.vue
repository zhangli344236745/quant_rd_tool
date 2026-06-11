<script setup lang="ts">
import GreekLabel from "./GreekLabel.vue";
</script>

<template>
  <div class="greeks-legend muted small">
    <GreekLabel greek="delta" layout="inline" show-hint />
    <span class="sep">·</span>
    <GreekLabel greek="gamma" layout="inline" show-hint />
    <span class="sep">·</span>
    <GreekLabel greek="theta" layout="inline" show-hint />
    <span class="sep">·</span>
    <GreekLabel greek="vega" layout="inline" show-hint />
  </div>
</template>

<style scoped>
.greeks-legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.sep {
  opacity: 0.45;
}
</style>
