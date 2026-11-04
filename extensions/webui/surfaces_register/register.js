import { store } from "/plugins/code_intelligence/webui/store.js";
export default function register(surfaces) {
  surfaces.registerSurface({ id: "code-intelligence", title: "Code Intelligence", icon: "code_blocks", order: 55,
    modalPath: "/plugins/code_intelligence/webui/main.html", open: () => store.mount(), close: () => store.cleanup() });
}
