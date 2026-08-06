<script>
    import { onMount } from 'svelte';
    import { apiGet, apiPost } from '../lib/api.js';

    let config = {
        provider: 'Google (Gemini API)',
        model_name: 'gemini-2.5-flash-preview-09-2025',
        base_url: 'https://generativelanguage.googleapis.com',
        api_key: ''
    };

    const providerDefaults = {
        'Google (Gemini API)': { model_name: 'gemini-2.5-flash-preview-09-2025', base_url: 'https://generativelanguage.googleapis.com' },
        'OpenAI': { model_name: 'gpt-4o', base_url: 'https://api.openai.com/v1' },
        'Anthropic': { model_name: 'claude-3-5-sonnet-20240620', base_url: 'https://api.anthropic.com' },
        'Azure OpenAI': { model_name: 'gpt-4o', base_url: 'https://your-resource-name.openai.azure.com' },
        'Local (Ollama/vLLM)': { model_name: 'llama3.1', base_url: 'http://localhost:11434/v1' },
        'Kimi (Moonshot)': { model_name: 'moonshot-v1-8k', base_url: 'https://api.moonshot.cn/v1' },
        '阶跃星辰 (StepFun)': { model_name: 'step-1-8k', base_url: 'https://api.stepfun.com/v1' },
        '智谱 (Zhipu)': { model_name: 'glm-4', base_url: 'https://open.bigmodel.cn/api/paas/v4' },
        'DeepSeek': { model_name: 'deepseek-chat', base_url: 'https://api.deepseek.com' },
        'MiniMax': { model_name: 'abab6.5s-chat', base_url: 'https://api.minimax.chat/v1' }
    };

    function handleProviderChange() {
        const defaults = providerDefaults[config.provider];
        if (defaults) {
            config.model_name = defaults.model_name;
            config.base_url = defaults.base_url;
        }
    }

    let showApiKey = false;
    let isSaving = false;
    let isFetchingModels = false;
    let availableModels = [];
    let useCustomModel = false;

    onMount(async () => {
        await fetchConfig();
    });

    async function fetchAvailableModels() {
        isFetchingModels = true;
        try {
            const data = await apiPost('/llm/models', config);
            availableModels = data.models || [];
            if (availableModels.length > 0) {
                useCustomModel = false;
                // 如果当前模型不在列表中，默认选中第一个
                if (!availableModels.includes(config.model_name)) {
                    config.model_name = availableModels[0];
                }
                alert(`成功获取 ${availableModels.length} 个模型！请在下拉列表中进行选择。`);
            } else {
                alert('未获取到模型列表，可能是 API 接口暂不支持或配置有误。');
            }
        } catch (e) {
            console.error(e);
            alert(e.status ? `获取失败: ${e.detail || '未知错误'}` : '获取失败，请检查网络或后端连接。');
        } finally {
            isFetchingModels = false;
        }
    }

    async function fetchConfig() {
        try {
            config = await apiGet('/llm/config');
        } catch (e) { console.error(e); }
    }

    async function saveConfig() {
        isSaving = true;
        try {
            await apiPost('/llm/config', config);
            alert('模型配置已保存并应用！');
        } catch (e) {
            console.error(e);
            alert(e.status ? `保存失败: ${e.detail || '未知错误'}` : '保存失败，请检查后端连接。');
        } finally {
            isSaving = false;
        }
    }
</script>

<div class="flex flex-col h-full items-center justify-start pt-8">
    <div class="w-full max-w-4xl bg-slate-950 rounded-2xl border border-slate-800 overflow-hidden">
        <!-- 头部标题区 -->
        <div class="px-8 py-6 border-b border-slate-800 flex items-center space-x-4">
            <div class="w-12 h-12 bg-indigo-500/10 rounded-xl flex items-center justify-center text-indigo-400">
                <i class="fa-solid fa-microchip text-2xl"></i>
            </div>
            <div>
                <h3 class="text-lg font-bold text-white">系统大语言模型 (LLM) 配置</h3>
                <p class="text-sm text-slate-400 mt-0.5">在此配置外部 AI 接口参数，为会话管理和预警智能分析提供底层大模型能力支持。</p>
            </div>
        </div>

        <!-- 表单配置区 -->
        <div class="p-10 space-y-8">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-x-12 gap-y-8">
                <!-- 模型厂家 -->
                <div class="flex flex-col space-y-2">
                    <label class="text-sm font-semibold text-slate-200" for="provider">模型厂家 (Provider)</label>
                    <div class="relative">
                        <select
                            id="provider"
                            bind:value={config.provider}
                            on:change={handleProviderChange}
                            class="w-full px-4 py-3 border border-slate-800 rounded-xl outline-none focus:border-indigo-500 bg-slate-900 text-slate-100 placeholder-slate-500 appearance-none cursor-pointer text-sm"
                        >
                            <optgroup label="国际主流大模型">
                                <option value="Google (Gemini API)">Google (Gemini API)</option>
                                <option value="OpenAI">OpenAI</option>
                                <option value="Anthropic">Anthropic</option>
                                <option value="Azure OpenAI">Azure OpenAI</option>
                            </optgroup>
                            <optgroup label="国内大模型">
                                <option value="Kimi (Moonshot)">Kimi (Moonshot)</option>
                                <option value="阶跃星辰 (StepFun)">阶跃星辰 (StepFun)</option>
                                <option value="智谱 (Zhipu)">智谱 (Zhipu)</option>
                                <option value="DeepSeek">DeepSeek</option>
                                <option value="MiniMax">MiniMax</option>
                            </optgroup>
                            <optgroup label="私有化部署">
                                <option value="Local (Ollama/vLLM)">Local (Ollama/vLLM)</option>
                            </optgroup>
                        </select>
                        <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-4 text-slate-500">
                            <svg class="fill-current h-4 w-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z"/></svg>
                        </div>
                    </div>
                </div>

                <!-- 模型类别 -->
                <div class="flex flex-col space-y-2">
                    <label class="text-sm font-semibold text-slate-200" for="model_name">模型类别 (Model Name)</label>
                    <div class="relative flex items-center">
                        {#if availableModels.length > 0 && !useCustomModel}
                            <select
                                id="model_name"
                                bind:value={config.model_name}
                                on:change={(e) => {
                                    if(e.target.value === '___custom___') {
                                        useCustomModel = true;
                                        config.model_name = '';
                                    }
                                }}
                                class="w-full pl-4 pr-12 py-3 border border-slate-800 rounded-xl outline-none focus:border-indigo-500 bg-slate-900 text-slate-100 placeholder-slate-500 text-sm font-mono appearance-none cursor-pointer"
                            >
                                {#each availableModels as m}
                                    <option value={m}>{m}</option>
                                {/each}
                                <optgroup label="自定义选项">
                                    <option value="___custom___">✏️ 手动输入 (Custom...)</option>
                                </optgroup>
                            </select>
                            <div class="pointer-events-none absolute inset-y-0 right-10 flex items-center px-2 text-slate-500">
                                <svg class="fill-current h-4 w-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z"/></svg>
                            </div>
                        {:else}
                            <input
                                id="model_name"
                                type="text"
                                bind:value={config.model_name}
                                placeholder="例如: gemini-pro"
                                class="w-full pl-4 pr-12 py-3 border border-slate-800 rounded-xl outline-none focus:border-indigo-500 bg-slate-900 text-slate-100 placeholder-slate-500 text-sm font-mono"
                            />
                        {/if}
                        <button
                            on:click={fetchAvailableModels}
                            disabled={isFetchingModels || !config.base_url}
                            class="absolute right-1.5 p-1.5 text-indigo-400 hover:bg-indigo-500/10 rounded-lg disabled:opacity-50 transition-colors flex items-center justify-center bg-slate-900 border border-slate-800"
                            title="尝试从当前接口地址拉取可用模型列表"
                        >
                            <i class="fa-solid {isFetchingModels ? 'fa-spinner animate-spin' : 'fa-network-wired'} text-sm"></i>
                        </button>
                    </div>
                </div>

                <!-- 接口地址 -->
                <div class="flex flex-col space-y-2">
                    <label class="text-sm font-semibold text-slate-200" for="base_url">接口地址 (Base URL)</label>
                    <input
                        id="base_url"
                        type="text"
                        bind:value={config.base_url}
                        placeholder="https://..."
                        class="w-full px-4 py-3 border border-slate-800 rounded-xl outline-none focus:border-indigo-500 bg-slate-900 text-slate-100 placeholder-slate-500 text-sm"
                    />
                </div>

                <!-- API 密钥 -->
                <div class="flex flex-col space-y-2">
                    <label class="text-sm font-semibold text-slate-200" for="api_key">API 密钥 (API Key)</label>
                    <div class="relative">
                        <div class="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-slate-500">
                            <i class="fa-solid fa-key text-sm"></i>
                        </div>
                        {#if showApiKey}
                            <input
                                id="api_key_text"
                                type="text"
                                bind:value={config.api_key}
                                placeholder="为空时将使用系统内置预览 Key（仅限 Gemini）"
                                class="w-full pl-11 pr-12 py-3 border border-slate-800 rounded-xl outline-none focus:border-indigo-500 bg-slate-900 text-slate-100 placeholder-slate-500 text-sm"
                            />
                        {:else}
                            <input
                                id="api_key_pwd"
                                type="password"
                                bind:value={config.api_key}
                                placeholder="为空时将使用系统内置预览 Key（仅限 Gemini）"
                                class="w-full pl-11 pr-12 py-3 border border-slate-800 rounded-xl outline-none focus:border-indigo-500 bg-slate-900 text-slate-100 placeholder-slate-500 text-sm"
                            />
                        {/if}
                        <button
                            on:click={() => showApiKey = !showApiKey}
                            class="absolute inset-y-0 right-0 pr-4 flex items-center text-slate-500 hover:text-slate-300"
                        >
                            <i class="fa-solid fa-eye text-base"></i>
                        </button>
                    </div>
                    <p class="text-[11px] text-slate-500">您的 API 密钥仅保存在浏览器本地，不会上传至任何第三方服务器。</p>
                </div>
            </div>

            <!-- 底部保存按钮 -->
            <div class="pt-6 border-t border-slate-800 flex justify-end">
                <button
                    on:click={saveConfig}
                    disabled={isSaving}
                    class="flex items-center px-6 py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl shadow-lg shadow-indigo-500/20 transition-all font-bold active:scale-95 disabled:opacity-50"
                >
                    <i class="fa-solid {isSaving ? 'fa-arrows-rotate animate-spin' : 'fa-gear'} text-base mr-2"></i>
                    {isSaving ? '正在应用配置...' : '保存配置并应用'}
                </button>
            </div>
        </div>
    </div>
</div>
