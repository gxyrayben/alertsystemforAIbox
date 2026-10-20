<script>
    // 单个参数控件：按元数据决定渲染成开关 / 下拉 / 多行文本 / 数字 / 文本。
    // 逻辑、复核、输出三类元件的参数表单共用本组件，避免三份重复 markup 漂移。
    import { fieldMeta } from '../../lib/orchestrationSchema.js';

    export let name;              // 参数键
    export let value;             // 当前值
    export let onPatch;           // (patch: object) => void

    const INPUT_CLS = 'w-full bg-slate-950 border border-slate-800 text-slate-200 rounded-lg p-2 mt-1 text-xs';
    const AREA_CLS = 'w-full bg-slate-950 border border-slate-800 text-slate-200 rounded-lg p-2 mt-1 text-[11px] leading-relaxed';

    $: meta = fieldMeta(name);
    $: isBool = typeof value === 'boolean';
    $: isNumber = meta.type === 'number';
</script>

<div>
    <label class="text-[11px] text-slate-400 leading-snug" for={`param-${name}`}>{meta.label}</label>

    {#if isBool}
        <div class="flex items-center justify-between mt-1 py-1.5 px-2.5 rounded-lg bg-slate-900/60 border border-slate-800">
            <span class="text-[10px] text-slate-400">{value ? '已开启' : '已关闭'}</span>
            <input id={`param-${name}`} type="checkbox" checked={value}
                   on:change={(e) => onPatch({ [name]: e.target.checked })}
                   class="w-4 h-4 accent-indigo-500 rounded cursor-pointer" />
        </div>
    {:else if meta.type === 'select'}
        <select id={`param-${name}`} value={value}
                on:change={(e) => onPatch({ [name]: e.target.value })}
                class={INPUT_CLS}>
            {#each meta.options || [] as opt}<option value={opt}>{opt}</option>{/each}
        </select>
    {:else if meta.type === 'textarea'}
        <textarea id={`param-${name}`} rows="3" value={value}
                  on:input={(e) => onPatch({ [name]: e.target.value })}
                  class={AREA_CLS}></textarea>
    {:else if isNumber}
        <input id={`param-${name}`} type="number" step="any" value={value}
               on:input={(e) => onPatch({ [name]: e.target.value === '' ? '' : Number(e.target.value) })}
               class={INPUT_CLS} />
    {:else}
        <input id={`param-${name}`} type="text" value={value}
               on:input={(e) => onPatch({ [name]: e.target.value })}
               class="{INPUT_CLS} {name === 'output_id' ? 'font-mono' : ''}" />
    {/if}
</div>
