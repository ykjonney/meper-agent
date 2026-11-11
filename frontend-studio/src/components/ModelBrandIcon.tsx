import { memo, type ComponentType } from 'react';
// 深层按需引（components/Mono=单色可染色 / components/Color=品牌彩版）：
// 厂商 index.mjs 经 Combine.mjs 静态依赖 @lobehub/ui（本项目不装），Mono/Color
// 零外部依赖，绕开整条引用链。
import ClaudeMono from '@lobehub/icons/es/Claude/components/Mono';
import ClaudeColor from '@lobehub/icons/es/Claude/components/Color';
import DeepSeekMono from '@lobehub/icons/es/DeepSeek/components/Mono';
import DeepSeekColor from '@lobehub/icons/es/DeepSeek/components/Color';
import DoubaoMono from '@lobehub/icons/es/Doubao/components/Mono';
import DoubaoColor from '@lobehub/icons/es/Doubao/components/Color';
import GeminiMono from '@lobehub/icons/es/Gemini/components/Mono';
import GeminiColor from '@lobehub/icons/es/Gemini/components/Color';
import GrokMono from '@lobehub/icons/es/Grok/components/Mono';
import HunyuanMono from '@lobehub/icons/es/Hunyuan/components/Mono';
import HunyuanColor from '@lobehub/icons/es/Hunyuan/components/Color';
import MetaMono from '@lobehub/icons/es/Meta/components/Mono';
import MetaColor from '@lobehub/icons/es/Meta/components/Color';
import MistralMono from '@lobehub/icons/es/Mistral/components/Mono';
import MistralColor from '@lobehub/icons/es/Mistral/components/Color';
import MoonshotMono from '@lobehub/icons/es/Moonshot/components/Mono';
import OpenAIMono from '@lobehub/icons/es/OpenAI/components/Mono';
import QwenMono from '@lobehub/icons/es/Qwen/components/Mono';
import QwenColor from '@lobehub/icons/es/Qwen/components/Color';
import WenxinMono from '@lobehub/icons/es/Wenxin/components/Mono';
import WenxinColor from '@lobehub/icons/es/Wenxin/components/Color';
import ZhipuMono from '@lobehub/icons/es/Zhipu/components/Mono';
import ZhipuColor from '@lobehub/icons/es/Zhipu/components/Color';

/** 单厂商的 Mono（可染色）/Color（品牌彩，可选——Grok/Moonshot/OpenAI 等纯
 *  单色品牌无 Color，brand 变体回退 Mono 原色）logo 组件对。 */
interface BrandPair {
  Mono: ComponentType<{ size?: number; color?: string }>;
  Color?: ComponentType<{ size?: number }>;
}

/** 厂商 key → 真实品牌 logo 组件对（@lobehub/icons 深层按需引）。 */
const BRANDS: Record<string, BrandPair> = {
  deepseek: { Mono: DeepSeekMono, Color: DeepSeekColor },
  zhipu: { Mono: ZhipuMono, Color: ZhipuColor },
  qwen: { Mono: QwenMono, Color: QwenColor },
  openai: { Mono: OpenAIMono },
  anthropic: { Mono: ClaudeMono, Color: ClaudeColor },
  moonshot: { Mono: MoonshotMono },
  gemini: { Mono: GeminiMono, Color: GeminiColor },
  doubao: { Mono: DoubaoMono, Color: DoubaoColor },
  hunyuan: { Mono: HunyuanMono, Color: HunyuanColor },
  grok: { Mono: GrokMono },
  mistral: { Mono: MistralMono, Color: MistralColor },
  meta: { Mono: MetaMono, Color: MetaColor },
  wenxin: { Mono: WenxinMono, Color: WenxinColor },
};

/** 厂商身份色（avatar 变体的底色，与 ModelsPage 旧 vendorStyle 同表）。 */
const BRAND_BG: Record<string, string> = {
  deepseek: '#4D6BFE',
  zhipu: '#2E5BFF',
  qwen: '#FF6A00',
  openai: '#0D0D0D',
  anthropic: '#D97757',
  moonshot: '#0B0B1E',
  gemini: '#3B82F6',
  doubao: '#325ABE',
  hunyuan: '#0052D9',
  grok: '#000000',
  mistral: '#FF7000',
  meta: '#0668E1',
  wenxin: '#4E6EF2',
};

/** 从名称 / model_id / provider_tag 推断厂商 key（正则宽松匹配，与
 *  ModelsPage 旧 vendorStyle 同一套词表）。'' = 未知厂商。 */
export function resolveModelBrand(...texts: (string | undefined | null)[]): string {
  const key = texts.filter(Boolean).join(' ').toLowerCase();
  if (!key) return '';
  if (/glm|zhipu|chatglm|智谱/.test(key)) return 'zhipu';
  if (/deepseek|深度求索/.test(key)) return 'deepseek';
  if (/qwen|tongyi|dashscope|通义|阿里云/.test(key)) return 'qwen';
  if (/claude|anthropic/.test(key)) return 'anthropic';
  if (/kimi|moonshot/.test(key)) return 'moonshot';
  if (/gemini|google/.test(key)) return 'gemini';
  if (/doubao|豆包/.test(key)) return 'doubao';
  if (/hunyuan|混元/.test(key)) return 'hunyuan';
  if (/grok|xai/.test(key)) return 'grok';
  if (/mistral|mixtral/.test(key)) return 'mistral';
  if (/llama|meta\b/.test(key)) return 'meta';
  if (/wenxin|ernie|文心/.test(key)) return 'wenxin';
  if (/gpt|openai|\bo[1345]\b/.test(key)) return 'openai';
  return '';
}

export interface ModelBrandIconProps {
  /** 模型的任意标识文本（name / model_id / provider_tag，多参数拼成匹配串） */
  name?: string;
  modelId?: string;
  providerTag?: string;
  /** 图标边长（px），默认 14 */
  size?: number;
  /** brand=品牌彩色裸 logo（浅底界面内嵌用）；avatar=品牌色圆角方底+白单色
   *  logo（徽章/卡片头用，等价旧 vendorStyle 的 badge-44）。 */
  variant?: 'brand' | 'avatar';
}

/** 模型厂商真实 logo（@lobehub/icons）：按名称推断厂商渲染品牌 logo；
 *  未知厂商回退灰底首字母；完全无文本返回 null。 */
function ModelBrandIconBase({ name, modelId, providerTag, size = 14, variant = 'brand' }: ModelBrandIconProps) {
  const brand = resolveModelBrand(name, modelId, providerTag);
  const pair = brand ? BRANDS[brand] : undefined;
  if (!pair) {
    const label = (name || modelId || '').trim().slice(0, 1).toUpperCase();
    if (!label) return null;
    return (
      <span
        className="inline-flex items-center justify-center rounded-[8px] text-white font-bold shrink-0 select-none"
        style={{ width: size + 6, height: size + 6, fontSize: size * 0.72, background: '#5A6472' }}
      >
        {label}
      </span>
    );
  }
  if (variant === 'avatar') {
    const box = size + 10;
    return (
      <span
        className="inline-flex items-center justify-center rounded-[8px] shrink-0 select-none"
        style={{ width: box, height: box, background: BRAND_BG[brand] ?? '#5A6472' }}
        aria-hidden
      >
        <pair.Mono size={size} color="#fff" />
      </span>
    );
  }
  return <pair.Color size={size} />;
}

export const ModelBrandIcon = memo(ModelBrandIconBase);
