import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { modelApi } from '../services/model-api'

/**
 * useActiveModels — AI 功能（工具生成/测试）共用的「活跃模型列表 + 默认选中」。
 *
 * 单一缓存键（一次拉取多组件共享），默认选中第一个 active 模型。
 */
export function useActiveModels() {
  const { data } = useQuery({
    queryKey: ['models', 'tool-ai'],
    queryFn: () => modelApi.list({ page: 1, page_size: 100 }),
  })
  const activeModels = useMemo(
    () => (data?.items ?? []).filter((m) => m.status === 'active'),
    [data],
  )
  const [modelId, setModelId] = useState('')
  useEffect(() => {
    if (!modelId && activeModels.length) setModelId(activeModels[0].id)
  }, [activeModels, modelId])
  return { activeModels, modelId, setModelId }
}
