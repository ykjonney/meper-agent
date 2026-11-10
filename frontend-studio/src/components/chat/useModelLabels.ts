import { useQuery } from '@tanstack/react-query';
import { modelApi, modelKeys } from '../../services/model-api';

/** 模型列表 → id→名称映射（供聊天顶栏/输入框显示人类可读模型名）。
 *  多处调用共享同一 queryKey，react-query 自动去重缓存。 */
export function useModelLabels() {
  const { data: modelsData } = useQuery({
    queryKey: modelKeys.list({ page_size: 100 }),
    queryFn: () => modelApi.list({ page_size: 100 }),
    staleTime: 60_000,
  });
  const modelNameById = new Map(
    (modelsData?.items ?? []).map((m) => [m.id, m.name]),
  );
  const modelLabel = (id?: string) => (id ? (modelNameById.get(id) ?? id) : '未配置');
  return { modelsData, modelLabel };
}
