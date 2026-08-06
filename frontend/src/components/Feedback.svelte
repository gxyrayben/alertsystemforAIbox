<script>
    import { showToast, selectedDevice } from '../lib/controlStore.js';

    const CAM = 'https://placehold.co/800x500/1e293b/94a3b8?text=EdgeNode-01+Snapshot';
    const CROP = 'https://images.unsplash.com/photo-1581092160607-ee22621dd758?auto=format&fit=crop&w=150&q=80';

    let selectedAlert = 'alert-1';
    let showYoloCard = false;
    let showAgentCard = false;
    let alert1Status = 'pending'; // pending | yolo-optimized | agent-optimized
    let humanThresh = 0.31;

    function selectAlert(id) {
        selectedAlert = id;
    }

    function submitFeedback(type) {
        showYoloCard = false;
        showAgentCard = false;
        if (type === 'yolo-false') {
            showYoloCard = true;
            showToast('已归纳为前置小模型触发误报。建议微调人体检测阈值，减少无效抠图深度动作。', 'info');
        } else if (type === 'agent-false') {
            showAgentCard = true;
            showToast('已归纳为 Agent 识别语义冲突误报。AI 建议修改对应的 VLM Prompt，追加反向限制。', 'info');
        } else {
            showToast('已确认真实高危警报！该现场小图已归档入模型真实数据集。', 'success');
        }
    }

    function deployYolo() {
        showYoloCard = false;
        humanThresh = 0.45;
        alert1Status = 'yolo-optimized';
        showToast('🎉 前置小模型参数修改成功！人体检测阈值提升至 0.45，大幅剔除边缘噪光闪烁！', 'success');
    }
    function deployAgent() {
        showAgentCard = false;
        alert1Status = 'agent-optimized';
        showToast('🎉 后置 VLM Agent 提示词一键合并更新。成功增加反向排除规则，杜绝工人检修误判！', 'success');
    }
</script>

<div class="max-w-6xl mx-auto space-y-6">
    <div>
        <h2 class="text-lg font-bold text-white">双级数据闭环：告警回放与两维度标注舱</h2>
        <p class="text-xs text-slate-400 mt-1">在此对级联系统漏报或误报进行标注。您可以选择优化前置小模型的检测阈值（减少不必要的小图送检），或优化大模型的语义提示词 Prompt 过滤（减少最终误报）。</p>
        <span class="inline-flex items-center gap-1.5 mt-2 text-[11px] bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 px-2.5 py-1 rounded-lg">
            <i class="fa-solid fa-video text-[10px]"></i> 当前设备：<strong>{$selectedDevice?.name || '未选择'}</strong>
        </span>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        <!-- 左：告警列表 -->
        <div class="lg:col-span-4 bg-slate-950 p-4 rounded-2xl border border-slate-800 space-y-3">
            <p class="text-[10px] font-bold text-slate-500 uppercase tracking-wider">🚨 级联触发的高疑告警快照</p>

            <div
                on:click={() => selectAlert('alert-1')}
                class="p-3 rounded-xl border cursor-pointer transition-all flex items-center space-x-3 {selectedAlert === 'alert-1' ? 'border-indigo-500/30 bg-indigo-500/5 hover:border-indigo-500/50' : 'border-slate-800 bg-slate-950/40 hover:border-indigo-500/30'} {alert1Status !== 'pending' ? 'opacity-50' : ''}"
            >
                <div class="relative w-16 h-16 rounded-lg overflow-hidden border border-slate-800 shrink-0 bg-slate-900">
                    <img src={CAM} alt="" class="w-full h-full object-cover" />
                    <div class="absolute inset-0 bg-rose-500/10"></div>
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center justify-between">
                        {#if alert1Status === 'pending'}
                            <span class="text-[9px] bg-rose-500/20 text-rose-400 font-bold px-1.5 py-0.5 rounded border border-rose-500/30">待审核告警</span>
                        {:else if alert1Status === 'yolo-optimized'}
                            <span class="text-[9px] bg-amber-500/20 text-amber-400 font-bold px-1.5 py-0.5 rounded border border-amber-500/30">前置小模型参数已优化</span>
                        {:else}
                            <span class="text-[9px] bg-indigo-500/20 text-indigo-400 font-bold px-1.5 py-0.5 rounded border border-indigo-500/30">后置 Agent 规则已重构</span>
                        {/if}
                        <span class="text-[9px] text-slate-500 font-semibold">16:30:12</span>
                    </div>
                    <h4 class="text-xs font-bold text-slate-200 mt-1 truncate">吊装区 - 触发高空姿态预警</h4>
                    <p class="text-[10px] text-slate-400 mt-0.5 truncate">小模型触发 ➔ 扩图裁切 ➔ Agent分析跌倒异常</p>
                </div>
            </div>

            <div class="p-3 rounded-xl border border-slate-800 bg-slate-950/40 opacity-60 flex items-center space-x-3">
                <div class="w-16 h-16 rounded-lg overflow-hidden border border-slate-800 shrink-0 bg-slate-900"><img src={CAM} alt="" class="w-full h-full object-cover opacity-60" /></div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center justify-between"><span class="text-[9px] bg-slate-800 text-slate-400 font-bold px-1.5 py-0.5 rounded">小模型误报过滤</span><span class="text-[9px] text-slate-500">14:15:30</span></div>
                    <h4 class="text-xs font-semibold text-slate-500 mt-1 truncate">小图裁切目标: 车辆</h4>
                    <p class="text-[10px] text-slate-600 mt-0.5 truncate">已标注：微调小模型阈值 0.32 -&gt; 0.40 过滤背景闪烁</p>
                </div>
            </div>
        </div>

        <!-- 右：诊断与飞轮 -->
        <div class="lg:col-span-8 space-y-6">
            <div class="bg-slate-950 p-5 rounded-2xl border border-slate-800 space-y-4">
                <div class="flex justify-between items-center pb-3 border-b border-slate-800">
                    <div><span class="text-[10px] bg-slate-900 text-slate-400 px-2 py-1 rounded font-medium border border-slate-800">事件流水号: ID-20260720</span><h3 class="font-bold text-white mt-1 text-xs">检测设备源：{$selectedDevice?.name || '当前设备'} (小模型+跌倒智能体级联)</h3></div>
                    <div class="text-right"><p class="text-[10px] text-slate-500">双模型捕获时间</p><p class="text-xs font-semibold text-indigo-400 font-mono">2026-07-20 16:30:12</p></div>
                </div>

                <div class="grid grid-cols-3 gap-4">
                    <div class="col-span-2 relative rounded-xl overflow-hidden bg-slate-900 aspect-[16/10] border border-slate-800">
                        <img src={CAM} alt="" class="w-full h-full object-cover" />
                        <div class="absolute top-[20%] left-[55%] w-[18%] h-[35%] border-2 border-emerald-500 bg-emerald-500/10 rounded animate-pulse"></div>
                        <div class="absolute top-[16%] left-[55%] bg-emerald-600 text-white text-[8px] font-bold px-1.5 py-0.5 rounded shadow">前置小模型捕获区 (上扩0.5/下0.3)</div>
                    </div>
                    <div class="col-span-1 flex flex-col justify-between bg-slate-900 p-3 rounded-xl border border-slate-800">
                        <div class="text-center"><p class="text-[9px] text-slate-500 font-bold mb-1 uppercase">大模型Agent送检小图</p><div class="border-2 border-indigo-500/40 p-1.5 rounded-lg bg-slate-950 inline-block"><img src={CROP} alt="" class="h-24 object-cover rounded" /></div></div>
                        <div class="bg-indigo-950/40 text-[9px] text-slate-400 p-2 rounded text-center border border-indigo-500/10">Agent判别结果：<br><strong class="text-rose-400">异常躺卧 (置信度89%)</strong></div>
                    </div>
                </div>

                <div class="bg-slate-900/60 p-4 rounded-xl border border-slate-800 space-y-3">
                    <p class="text-xs font-bold text-slate-300">💡 智能闭环标注策略选择：</p>
                    <div class="grid grid-cols-3 gap-3">
                        <button on:click={() => submitFeedback('valid')} class="bg-slate-950 hover:bg-slate-800 text-slate-300 border border-slate-800 hover:border-emerald-500/50 py-2.5 rounded-xl text-[11px] font-bold transition-all flex flex-col items-center justify-center p-2 text-center"><i class="fa-solid fa-circle-check text-emerald-400 text-base mb-1"></i><span>真实危险告警</span><span class="text-[8px] text-slate-500 font-normal mt-0.5">确认异常, 保留归档</span></button>
                        <button on:click={() => submitFeedback('yolo-false')} class="bg-slate-950 hover:bg-slate-800 text-slate-300 border border-slate-800 hover:border-amber-500/50 py-2.5 rounded-xl text-[11px] font-bold transition-all flex flex-col items-center justify-center p-2 text-center"><i class="fa-solid fa-sliders text-amber-400 text-base mb-1"></i><span>前置小模型误报</span><span class="text-[8px] text-slate-500 font-normal mt-0.5">端侧误触发，微调小模型阈值</span></button>
                        <button on:click={() => submitFeedback('agent-false')} class="bg-slate-950 hover:bg-slate-800 text-slate-300 border border-slate-800 hover:border-indigo-500/50 py-2.5 rounded-xl text-[11px] font-bold transition-all flex flex-col items-center justify-center p-2 text-center"><i class="fa-solid fa-wand-magic-sparkles text-indigo-400 text-base mb-1"></i><span>大模型Agent误报</span><span class="text-[8px] text-slate-500 font-normal mt-0.5">大图漏判，微调提示词限制</span></button>
                    </div>
                </div>
            </div>

            {#if showYoloCard}
                <div class="bg-slate-950 p-5 rounded-2xl border border-amber-500/30 shadow-lg space-y-4">
                    <div class="flex items-center space-x-2 text-amber-400"><i class="fa-solid fa-sliders text-lg"></i><h3 class="font-bold text-white text-xs">前置小模型 - 动态阈值优化建议</h3></div>
                    <p class="text-[11px] text-slate-300 leading-relaxed bg-slate-900 p-3 rounded-lg border border-slate-800">💡 <strong>小模型飞轮动作:</strong> 检测到该告警属于外部阴影或静电闪烁引起。AI 建议微调小模型的<b>【人体检测阈值】</b>由当前的 <b>{humanThresh} ➔ 0.45</b>，过滤后续此类低置信度噪点触发，可减少 65% 的后续无效裁切开销。</p>
                    <div class="flex justify-end pt-2"><button on:click={deployYolo} class="bg-amber-600 hover:bg-amber-700 text-slate-950 px-4 py-2 rounded-xl text-[11px] font-bold shadow-md transition-all">一键下发修改，提高小模型过滤门槛</button></div>
                </div>
            {/if}

            {#if showAgentCard}
                <div class="bg-slate-950 p-5 rounded-2xl border border-indigo-500/30 shadow-lg space-y-4">
                    <div class="flex items-center space-x-2 text-indigo-400"><i class="fa-solid fa-wand-magic-sparkles text-lg"></i><h3 class="font-bold text-white text-xs">后置 Agent - 视觉 Prompt 语义约束修正建议</h3></div>
                    <p class="text-[11px] text-slate-300 leading-relaxed bg-slate-900 p-3 rounded-lg border border-slate-800">💡 <strong>Agent 飞轮动作:</strong> 标记为“卧地正常维护”误报。建议在大模型 Prompt 中追加反向剔除规则：<b>排除躺下或蹲下检修吊具、以及坐地正常操作等正常检修场景。</b></p>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-[10px] font-mono">
                        <div class="bg-slate-900 border border-slate-800 rounded p-3 relative"><span class="absolute top-2 right-2 text-[8px] bg-slate-800 text-slate-500 px-1 py-0.5 rounded font-bold uppercase">原始 Prompt</span><p class="text-slate-500 line-through mt-4 leading-relaxed">...检测画面中是否有人异常倒地。一旦发现人员轴线与地面平行，立即报警...</p></div>
                        <div class="bg-indigo-950/40 border border-indigo-500/20 rounded p-3 relative"><span class="absolute top-2 right-2 text-[8px] bg-indigo-500 text-white px-1 py-0.5 rounded font-bold uppercase">优化后 Prompt</span><p class="text-indigo-300 mt-4 leading-relaxed">...检测画面中是否有人异常倒地。<strong>【重要剔除例外】若是正常手持工具蹲下、趴下正常检修钢轨或设备的工人，严禁报警。</strong></p></div>
                    </div>
                    <div class="flex justify-end pt-2"><button on:click={deployAgent} class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-xl text-[11px] font-bold shadow-md transition-all flex items-center"><i class="fa-solid fa-arrows-spin mr-1.5 animate-spin"></i> 部署优化 Prompt 至后置智能体</button></div>
                </div>
            {/if}
        </div>
    </div>
</div>
