// Shared provider type definitions

export interface SetupStep {
  text: string;
  url?: string;
}

export interface ProviderDef {
  value: string;
  label: string;
  dot: string;
  color: string;
  oauth: boolean;
  defaultModel?: string;
  needsBaseUrl?: boolean;
  apiKeyLabel?: string;
  apiKeyPlaceholder?: string;
  hint?: string;
  setup_steps?: SetupStep[];
}

export const PROVIDERS: ProviderDef[] = [
  // ── OAuth (no API key needed) ──────────────────────────────────
  {
    value: "claude",  label: "Claude",      dot: "bg-orange-400", color: "text-orange-400",
    oauth: true, defaultModel: "claude-3-5-sonnet-latest",
    hint: "Authenticates via the Claude CLI — opens a browser tab. No API key needed.",
  },
  {
    value: "gemini",  label: "Gemini",      dot: "bg-blue-400",   color: "text-blue-400",
    oauth: true, defaultModel: "gemini-1.5-pro-latest",
    hint: "Authenticates via the Gemini CLI — opens a browser tab, then paste the code back.",
  },
  {
    value: "codex",   label: "Codex",       dot: "bg-emerald-400", color: "text-emerald-400",
    oauth: true, defaultModel: "gpt-4o",
    hint: "Authenticates via device code flow — opens a browser tab, enter the code shown here.",
  },
  // ── API Key providers ──────────────────────────────────────────
  {
    value: "gemini-api", label: "Google Gemini (API Key)", dot: "bg-blue-400", color: "text-blue-400",
    oauth: false, defaultModel: "gemini-2.0-flash",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "AIza...",
    hint: "Free API key from aistudio.google.com/apikey — no subscription needed.",
    setup_steps: [
      { text: "Go to aistudio.google.com/apikey", url: "https://aistudio.google.com/apikey" },
      { text: "Sign in with your Google account" },
      { text: "Click Create API key" },
      { text: "Select or create a project, then copy the key" },
    ],
  },
  {
    value: "openai",  label: "OpenAI",      dot: "bg-green-400",  color: "text-green-400",
    oauth: false, defaultModel: "gpt-4o",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "sk-...",
    setup_steps: [
      { text: "Login at platform.openai.com", url: "https://platform.openai.com" },
      { text: "Click your profile avatar → API keys" },
      { text: "Click Create new secret key" },
      { text: "Copy the key (shown once) and paste it here" },
    ],
  },
  {
    value: "deepseek",label: "DeepSeek",    dot: "bg-indigo-400", color: "text-indigo-400",
    oauth: false, defaultModel: "deepseek-chat",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "sk-...",
    hint: "OpenAI-compatible. Get key at platform.deepseek.com",
    setup_steps: [
      { text: "Login at platform.deepseek.com", url: "https://platform.deepseek.com" },
      { text: "Click API Keys in the left sidebar" },
      { text: "Click Create API Key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "groq",    label: "Groq",        dot: "bg-yellow-400", color: "text-yellow-400",
    oauth: false, defaultModel: "llama-3.3-70b-versatile",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "gsk_...",
    hint: "Ultra-fast inference. Get key at console.groq.com",
    setup_steps: [
      { text: "Login at console.groq.com", url: "https://console.groq.com" },
      { text: "Click API Keys in the left sidebar" },
      { text: "Click Create API Key" },
      { text: "Copy the key (starts with gsk_) and paste it here" },
    ],
  },
  {
    value: "openrouter", label: "OpenRouter", dot: "bg-violet-400", color: "text-violet-400",
    oauth: false, defaultModel: "openai/gpt-4o",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "sk-or-...",
    hint: "Routes to 200+ models. Model name format: provider/model",
    setup_steps: [
      { text: "Login at openrouter.ai", url: "https://openrouter.ai" },
      { text: "Click your avatar (top right) → Keys" },
      { text: "Click Create Key" },
      { text: "Copy the key (starts with sk-or-) and paste it here" },
    ],
  },
  {
    value: "xai",     label: "xAI / Grok",  dot: "bg-neutral-300", color: "text-neutral-300",
    oauth: false, defaultModel: "grok-3-latest",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "xai-...",
    setup_steps: [
      { text: "Login at console.x.ai", url: "https://console.x.ai" },
      { text: "Click API Keys in the left sidebar" },
      { text: "Click Create API Key" },
      { text: "Copy the key (starts with xai-) and paste it here" },
    ],
  },
  {
    value: "mistral", label: "Mistral",     dot: "bg-orange-300", color: "text-orange-300",
    oauth: false, defaultModel: "mistral-large-latest",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Get key at console.mistral.ai",
    setup_steps: [
      { text: "Login at console.mistral.ai", url: "https://console.mistral.ai" },
      { text: "Click API Keys in the left sidebar" },
      { text: "Click Create new key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "perplexity", label: "Perplexity", dot: "bg-teal-400", color: "text-teal-400",
    oauth: false, defaultModel: "llama-3.1-sonar-large-128k-online",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "pplx-...",
    hint: "Online models with web search built in",
    setup_steps: [
      { text: "Login at perplexity.ai", url: "https://www.perplexity.ai" },
      { text: "Go to Settings → API" },
      { text: "Click Generate under API Key" },
      { text: "Copy the key (starts with pplx-) and paste it here" },
    ],
  },
  {
    value: "together", label: "Together AI", dot: "bg-sky-400", color: "text-sky-400",
    oauth: false, defaultModel: "meta-llama/Llama-3-70b-chat-hf",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Open-source models at scale. Get key at api.together.xyz",
    setup_steps: [
      { text: "Login at api.together.xyz", url: "https://api.together.xyz" },
      { text: "Go to Settings → API Keys" },
      { text: "Click Create API Key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "cerebras", label: "Cerebras",   dot: "bg-cyan-400",  color: "text-cyan-400",
    oauth: false, defaultModel: "llama3.1-70b",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "csk-...",
    hint: "Fastest inference hardware. Get key at cloud.cerebras.ai",
    setup_steps: [
      { text: "Login at cloud.cerebras.ai", url: "https://cloud.cerebras.ai" },
      { text: "Click API Keys in the left sidebar" },
      { text: "Click Create new API key" },
      { text: "Copy the key (starts with csk-) and paste it here" },
    ],
  },
  {
    value: "fireworks", label: "Fireworks", dot: "bg-red-400",   color: "text-red-400",
    oauth: false, defaultModel: "accounts/fireworks/models/llama-v3p1-70b-instruct",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "fw_...",
    hint: "Fast open-source inference. Get key at fireworks.ai",
    setup_steps: [
      { text: "Login at fireworks.ai", url: "https://fireworks.ai" },
      { text: "Click your avatar → API Keys" },
      { text: "Click Create API key" },
      { text: "Copy the key (starts with fw_) and paste it here" },
    ],
  },
  {
    value: "azure",   label: "Azure OpenAI", dot: "bg-blue-500", color: "text-blue-500",
    oauth: false, defaultModel: "gpt-4o",
    needsBaseUrl: true,
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Requires your Azure resource endpoint URL",
    setup_steps: [
      { text: "Login at portal.azure.com", url: "https://portal.azure.com" },
      { text: "Search Azure OpenAI and create a new resource" },
      { text: "Open the resource → Keys and Endpoint" },
      { text: "Copy Key 1 and the Endpoint URL, paste both here" },
    ],
  },
  // ── OpenCode gateways ─────────────────────────────────────────
  {
    value: "opencode-zen", label: "OpenCode Zen", dot: "bg-fuchsia-400", color: "text-fuchsia-400",
    oauth: false, defaultModel: "claude-sonnet-4-6",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "sk-oc-...",
    hint: "OpenCode curated premium models gateway. Get key at opencode.ai/auth",
    setup_steps: [
      { text: "Login at opencode.ai", url: "https://opencode.ai" },
      { text: "Go to your account dashboard" },
      { text: "Copy your API key (starts with sk-oc-)" },
    ],
  },
  {
    value: "opencode-go",  label: "OpenCode Go",  dot: "bg-fuchsia-300", color: "text-fuchsia-300",
    oauth: false, defaultModel: "claude-haiku-4-5-20251001",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "sk-oc-...",
    hint: "OpenCode budget subscription. Same key as Zen — opencode.ai/auth",
    setup_steps: [
      { text: "Login at opencode.ai", url: "https://opencode.ai" },
      { text: "Go to your account dashboard" },
      { text: "Copy your API key (starts with sk-oc-) — same key works for Zen and Go" },
    ],
  },
  // ── More providers ─────────────────────────────────────────────
  {
    value: "cohere",    label: "Cohere",      dot: "bg-coral-400",    color: "text-orange-300",
    oauth: false, defaultModel: "command-r-plus",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Cohere Command models. Get key at dashboard.cohere.com",
    setup_steps: [
      { text: "Login at dashboard.cohere.com", url: "https://dashboard.cohere.com" },
      { text: "Click API Keys in the left sidebar" },
      { text: "Click New Trial Key or New Production Key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "deepinfra", label: "DeepInfra",   dot: "bg-slate-400",   color: "text-slate-400",
    oauth: false, defaultModel: "meta-llama/Meta-Llama-3.1-70B-Instruct",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Cheap open-source inference. Get key at deepinfra.com",
    setup_steps: [
      { text: "Login at deepinfra.com", url: "https://deepinfra.com" },
      { text: "Click your avatar → Account" },
      { text: "Go to API Keys → Create new key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "moonshot",  label: "Moonshot (Kimi)", dot: "bg-sky-300",  color: "text-sky-300",
    oauth: false, defaultModel: "moonshot-v1-8k",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "sk-...",
    hint: "Kimi long-context models. Get key at platform.moonshot.cn",
    setup_steps: [
      { text: "Login at platform.moonshot.cn", url: "https://platform.moonshot.cn" },
      { text: "Click API Keys in the left sidebar" },
      { text: "Click Create API Key" },
      { text: "Copy the key (starts with sk-) and paste it here" },
    ],
  },
  {
    value: "minimax",   label: "MiniMax",     dot: "bg-lime-400",    color: "text-lime-400",
    oauth: false, defaultModel: "abab6.5s-chat",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "MiniMax ABAB models. Get key at api.minimax.chat",
    setup_steps: [
      { text: "Login at platform.minimaxi.com", url: "https://platform.minimaxi.com" },
      { text: "Go to Account → API Key" },
      { text: "Click Create API Key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "nvidia",    label: "NVIDIA NIM",  dot: "bg-green-500",   color: "text-green-500",
    oauth: false, defaultModel: "meta/llama-3.1-70b-instruct",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "nvapi-...",
    hint: "NVIDIA NIM inference endpoints. Get key at build.nvidia.com",
    setup_steps: [
      { text: "Login at build.nvidia.com", url: "https://build.nvidia.com" },
      { text: "Click any model then click Get API Key" },
      { text: "Click Generate Key" },
      { text: "Copy the key (starts with nvapi-) and paste it here" },
    ],
  },
  {
    value: "nebius",    label: "Nebius AI",   dot: "bg-blue-300",    color: "text-blue-300",
    oauth: false, defaultModel: "meta-llama/Meta-Llama-3.1-70B-Instruct",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Nebius AI Studio. Get key at studio.nebius.ai",
    setup_steps: [
      { text: "Login at studio.nebius.ai", url: "https://studio.nebius.ai" },
      { text: "Click API Keys in the left sidebar" },
      { text: "Click Create API Key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "huggingface", label: "HuggingFace", dot: "bg-yellow-500", color: "text-yellow-500",
    oauth: false, defaultModel: "meta-llama/Llama-3.1-70B-Instruct",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "hf_...",
    hint: "HuggingFace Inference API. Get key at huggingface.co/settings/tokens",
    setup_steps: [
      { text: "Login at huggingface.co", url: "https://huggingface.co" },
      { text: "Click your avatar → Settings" },
      { text: "Click Access Tokens in the left menu" },
      { text: "Click New token → copy it (starts with hf_)" },
    ],
  },
  // ── More OpenAI-compatible providers ───────────────────────────
  {
    value: "sambanova", label: "SambaNova", dot: "bg-orange-400", color: "text-orange-400",
    oauth: false, defaultModel: "Meta-Llama-3.3-70B-Instruct",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Very fast inference. Get key at cloud.sambanova.ai",
    setup_steps: [
      { text: "Login at cloud.sambanova.ai", url: "https://cloud.sambanova.ai" },
      { text: "Open API Keys → generate a key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "hyperbolic", label: "Hyperbolic", dot: "bg-indigo-300", color: "text-indigo-300",
    oauth: false, defaultModel: "meta-llama/Llama-3.3-70B-Instruct",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Affordable open-source inference. Get key at app.hyperbolic.xyz",
    setup_steps: [
      { text: "Login at app.hyperbolic.xyz", url: "https://app.hyperbolic.xyz" },
      { text: "Settings → API Keys → create a key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "novita", label: "Novita AI", dot: "bg-emerald-300", color: "text-emerald-300",
    oauth: false, defaultModel: "deepseek/deepseek-v3-0324",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "200+ open-source models. Get key at novita.ai",
    setup_steps: [
      { text: "Login at novita.ai", url: "https://novita.ai" },
      { text: "Open Key Management → create a key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "zhipu", label: "Z.ai (GLM / Zhipu)", dot: "bg-blue-400", color: "text-blue-400",
    oauth: false, defaultModel: "glm-4.6",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "GLM-4.6 etc. Get key at z.ai",
    setup_steps: [
      { text: "Login at z.ai (or open.bigmodel.cn for China)", url: "https://z.ai" },
      { text: "Open the API Keys page → create a key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "siliconflow", label: "SiliconFlow", dot: "bg-cyan-300", color: "text-cyan-300",
    oauth: false, defaultModel: "deepseek-ai/DeepSeek-V3",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Many open-source models. Get key at siliconflow.com",
    setup_steps: [
      { text: "Login at siliconflow.com (.cn for China)", url: "https://siliconflow.com" },
      { text: "Open the API Keys page → create a key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "vercel-gateway", label: "Vercel AI Gateway", dot: "bg-neutral-200", color: "text-neutral-200",
    oauth: false, defaultModel: "openai/gpt-4o",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Routes to 100s of models. Model format: creator/model",
    setup_steps: [
      { text: "Open Vercel dashboard → AI Gateway", url: "https://vercel.com/ai-gateway" },
      { text: "Create an API key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "github-models", label: "GitHub Models", dot: "bg-slate-300", color: "text-slate-300",
    oauth: false, defaultModel: "openai/gpt-4o",
    apiKeyLabel: "GitHub PAT", apiKeyPlaceholder: "github_pat_...",
    hint: "Auth with a GitHub PAT (Models permission). Free tier available.",
    setup_steps: [
      { text: "GitHub → Settings → Developer settings → PATs", url: "https://github.com/settings/tokens" },
      { text: "Create a fine-grained token with the Models permission" },
      { text: "Copy the token and paste it here" },
    ],
  },
  {
    value: "chutes", label: "Chutes", dot: "bg-fuchsia-300", color: "text-fuchsia-300",
    oauth: false, defaultModel: "deepseek-ai/DeepSeek-V3-0324",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "cpk_...",
    hint: "Decentralized inference. Get key at chutes.ai",
    setup_steps: [
      { text: "Login at chutes.ai", url: "https://chutes.ai" },
      { text: "Create an API key (starts with cpk_)" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "writer", label: "Writer (Palmyra)", dot: "bg-rose-300", color: "text-rose-300",
    oauth: false, defaultModel: "palmyra-x5",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Palmyra enterprise LLMs. Get key at dev.writer.com",
    setup_steps: [
      { text: "Login at dev.writer.com", url: "https://dev.writer.com" },
      { text: "Open API keys → create a key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "ai21", label: "AI21 (Jamba)", dot: "bg-amber-300", color: "text-amber-300",
    oauth: false, defaultModel: "jamba-large",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Jamba long-context models. Get key at studio.ai21.com",
    setup_steps: [
      { text: "Login at studio.ai21.com", url: "https://studio.ai21.com" },
      { text: "Open API Keys → create a key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "upstage", label: "Upstage (Solar)", dot: "bg-violet-300", color: "text-violet-300",
    oauth: false, defaultModel: "solar-pro2",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Solar LLMs. Get key at console.upstage.ai",
    setup_steps: [
      { text: "Login at console.upstage.ai", url: "https://console.upstage.ai" },
      { text: "Open API Keys → create a key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "venice", label: "Venice AI", dot: "bg-red-300", color: "text-red-300",
    oauth: false, defaultModel: "llama-3.3-70b",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Privacy-focused inference. Get key at venice.ai",
    setup_steps: [
      { text: "Login at venice.ai", url: "https://venice.ai/settings/api" },
      { text: "Settings → API → create a key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "baseten", label: "Baseten", dot: "bg-lime-300", color: "text-lime-300",
    oauth: false, defaultModel: "deepseek-ai/DeepSeek-V3-0324",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Managed model APIs. Get key at app.baseten.co",
    setup_steps: [
      { text: "Login at app.baseten.co", url: "https://app.baseten.co" },
      { text: "Open API keys → create a key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "featherless", label: "Featherless AI", dot: "bg-teal-300", color: "text-teal-300",
    oauth: false, defaultModel: "Qwen/Qwen2.5-72B-Instruct",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "30,000+ open-source models. Get key at featherless.ai",
    setup_steps: [
      { text: "Login at featherless.ai", url: "https://featherless.ai" },
      { text: "Open the API keys page → create a key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "kluster", label: "kluster.ai", dot: "bg-sky-300", color: "text-sky-300",
    oauth: false, defaultModel: "deepseek-ai/DeepSeek-V3",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Real-time + batch inference. Get key at platform.kluster.ai",
    setup_steps: [
      { text: "Login at platform.kluster.ai", url: "https://platform.kluster.ai" },
      { text: "Open API Keys → create a key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "lambda", label: "Lambda Inference", dot: "bg-purple-300", color: "text-purple-300",
    oauth: false, defaultModel: "deepseek-v3-0324",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Open-weight models. Get key at cloud.lambda.ai",
    setup_steps: [
      { text: "Login at cloud.lambda.ai", url: "https://cloud.lambda.ai" },
      { text: "Open the API keys page → create a key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "parasail", label: "Parasail", dot: "bg-green-300", color: "text-green-300",
    oauth: false, defaultModel: "deepseek-ai/DeepSeek-V3-0324",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Serverless open-source inference. Get key at saas.parasail.io",
    setup_steps: [
      { text: "Login at saas.parasail.io", url: "https://saas.parasail.io" },
      { text: "Open API keys → create a key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "friendli", label: "FriendliAI", dot: "bg-blue-300", color: "text-blue-300",
    oauth: false, defaultModel: "deepseek-ai/DeepSeek-R1",
    apiKeyLabel: "Friendli Token", apiKeyPlaceholder: "flp_...",
    hint: "Fast serverless endpoints. Get a token at friendli.ai",
    setup_steps: [
      { text: "Login at friendli.ai", url: "https://friendli.ai" },
      { text: "Personal settings → Tokens → create a token" },
      { text: "Copy the token and paste it here" },
    ],
  },
  {
    value: "inference-net", label: "Inference.net", dot: "bg-zinc-300", color: "text-zinc-300",
    oauth: false, defaultModel: "deepseek-ai/deepseek-v3-0324",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Serverless open-source inference. Get key at inference.net",
    setup_steps: [
      { text: "Login at inference.net", url: "https://inference.net" },
      { text: "Open the API keys page → create a key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  {
    value: "gmi", label: "GMI Cloud", dot: "bg-yellow-300", color: "text-yellow-300",
    oauth: false, defaultModel: "deepseek-ai/DeepSeek-V3.1",
    apiKeyLabel: "API Key", apiKeyPlaceholder: "...",
    hint: "Many open-source models. Get key at console.gmicloud.ai",
    setup_steps: [
      { text: "Login at console.gmicloud.ai", url: "https://console.gmicloud.ai" },
      { text: "Open the API keys page → create a key" },
      { text: "Copy the key and paste it here" },
    ],
  },
  // ── Local / custom ─────────────────────────────────────────────
  {
    value: "lmstudio", label: "LM Studio",   dot: "bg-pink-400",    color: "text-pink-400",
    oauth: false, needsBaseUrl: true, defaultModel: "local-model",
    hint: "Local LM Studio server. Default: http://localhost:1234/v1",
  },
  {
    value: "ollama",  label: "Ollama",      dot: "bg-purple-400", color: "text-purple-400",
    oauth: false, needsBaseUrl: true, defaultModel: "llama3",
    hint: "Local models via Ollama. No auth needed.",
  },
  {
    value: "custom",  label: "Custom",      dot: "bg-muted-foreground", color: "text-muted-foreground",
    oauth: false, needsBaseUrl: true,
    apiKeyLabel: "Bearer Token / API Key", apiKeyPlaceholder: "...",
    hint: "Any OpenAI-compatible endpoint",
  },
];

export const OAUTH_PROVIDERS = PROVIDERS.filter((p) => p.oauth);
export const APIKEY_PROVIDERS = PROVIDERS.filter((p) => !p.oauth);

export function providerDef(type: string): ProviderDef {
  return PROVIDERS.find((p) => p.value === type) ?? PROVIDERS[PROVIDERS.length - 1];
}

export interface ProviderItem {
  id: string;
  name: string;
  provider_type: string;
  is_active: boolean;
  auth_type: string;
  auth_path?: string;
  model_name?: string | null;
  base_url?: string | null;
  cooldown_seconds?: number;
  available_models?: string[];
  last_error?: string | null;
  last_error_at?: string | null;
  last_used_at?: string | null;
}
