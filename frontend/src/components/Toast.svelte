<script>
    import { toast } from '../lib/controlStore.js';

    $: t = $toast;
    $: iconClass =
        t.type === 'success'
            ? 'bg-emerald-500 text-white'
            : t.type === 'warning'
            ? 'bg-amber-500 text-slate-900'
            : 'bg-indigo-500 text-white';
    $: iconName =
        t.type === 'success'
            ? 'fa-circle-check'
            : t.type === 'warning'
            ? 'fa-triangle-exclamation'
            : 'fa-bell';
</script>

<div
    class="fixed bottom-6 right-6 bg-slate-950 text-slate-100 px-5 py-3 rounded-xl shadow-2xl flex items-center space-x-3 z-50 transform transition-all duration-300 border border-slate-800 text-xs font-semibold
    {t.show ? 'translate-y-0 opacity-100' : 'translate-y-10 opacity-0 pointer-events-none'}"
>
    <span class="{iconClass} p-1 rounded-lg text-xs"><i class="fa-solid {iconName}"></i></span>
    <span>{t.message}</span>
</div>
