import { writable, derived, get } from 'svelte/store';
import { apiGet } from './api.js';

// ---- 顶部导航当前选中项（跨组件共享，供子页面主动切换标签）----
const urlTab = new URLSearchParams(window.location.search).get('tab');
export const activeMenu = writable(urlTab || localStorage.getItem('activeMenu') || 'network');
activeMenu.subscribe((v) => {
    if (v) localStorage.setItem('activeMenu', v);
});
export function switchTab(id) {
    activeMenu.set(id);
}

// ---- 全局“当前设备”上下文（顶部下拉选择，四个业务页面共享联动）----
export const devices = writable([]);
export const selectedDeviceId = writable(localStorage.getItem('selectedDeviceId') || null);
selectedDeviceId.subscribe((v) => {
    if (v !== null && v !== undefined) localStorage.setItem('selectedDeviceId', v);
});

// 根据 id 匹配当前设备；找不到则回退到列表第一个，空列表为 null
export const selectedDevice = derived([devices, selectedDeviceId], ([$devices, $id]) => {
    if (!$devices.length) return null;
    return $devices.find((d) => String(d.id) === String($id)) || $devices[0];
});

// 拉取设备列表并写入共享 store；自动纠正选中项（无选中/选中已失效 → 选第一个）
export async function loadDevices() {
    try {
        const list = await apiGet('/devices');
        setDevices(list);
    } catch (e) {
        console.error(e);
    }
}

// 供 Devices.svelte 在本地拉取后同步复用，避免二次请求
export function setDevices(list) {
    devices.set(list || []);
    const cur = get(selectedDeviceId);
    const stillValid = (list || []).some((d) => String(d.id) === String(cur));
    if ((!cur || !stillValid) && list && list.length) {
        selectedDeviceId.set(String(list[0].id));
    }
}

export function selectDevice(id) {
    selectedDeviceId.set(String(id));
}

// ---- 全局 Toast 通知 ----
export const toast = writable({ show: false, message: '', type: 'info' });
let toastTimer;
export function showToast(message, type = 'info') {
    toast.set({ show: true, message, type });
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        toast.update((t) => ({ ...t, show: false }));
    }, 3500);
}

// ---- 级联布控任务列表（“一键部署”写入，“任务运维列表”读取）----
export const tasksList = writable([
    {
        id: 'TSK-832',
        name: '吊装区-双级级联跌倒过滤安全任务',
        device: 'diaozhuang-2',
        interval: 3,
        agentType: '跌倒test',
        status: 'active',
        todayAlerts: 14,
        yoloTarget: 'human',
        yoloHumanThresh: 0.31,
        yoloVehicleThresh: 0.32,
        yoloNonMotorThresh: 0.37,
        intrusionDuration: 3,
        alarmInterval: 10,
        cropUp: 0.5,
        cropDown: 0.3,
        cropLeft: 0.4,
        cropRight: 0.6,
        maxTarget: 1.0,
        minTarget: 0.0,
        prompt:
            '你是工业安全监控AI，专职排查画面中是否有人【异常跌倒或长时间卧地】。优先判定：若人站立、行走、保持身体轴心直立于地面，直接输出 "no" 。'
    }
]);

// ---- 跨标签的“对话请求”桥：任务微调 / 套用模板时跳转到 AI 布控页并注入指令 ----
// { seq, type: 'loadConfig' | 'useTemplate', payload }
export const chatRequest = writable(null);
let seq = 0;
export function requestChat(type, payload) {
    seq += 1;
    chatRequest.set({ seq, type, payload });
}
