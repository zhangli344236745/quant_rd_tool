import { ref } from "vue";

export const jobDrawerVisible = ref(false);

export function openJobDrawer() {
  jobDrawerVisible.value = true;
}
