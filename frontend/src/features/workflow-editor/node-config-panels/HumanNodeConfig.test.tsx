/**
 * HumanNodeConfig 组件测试 — 验证固定三个审批行为展示。
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi, beforeAll } from 'vitest'
import { render } from '@testing-library/react'
import HumanNodeConfig from './HumanNodeConfig'

// antd components require ResizeObserver
beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})

const baseConfig = {
  title: '审批测试',
  description: '描述',
  timeout_minutes: 60,
  timeout_action: 'fail',
}

describe('HumanNodeConfig — 固定三个审批行为', () => {
  it('renders without crashing', () => {
    const { container } = render(
      <HumanNodeConfig config={baseConfig} onChange={vi.fn()} />,
    )
    expect(container.querySelector('.space-y-3')).toBeTruthy()
  })

  it('固定展示三个审批行为：通过 / 驳回 / 意见', () => {
    const { container } = render(
      <HumanNodeConfig config={baseConfig} onChange={vi.fn()} />,
    )
    const text = container.textContent ?? ''
    expect(text).toContain('通过')
    expect(text).toContain('驳回')
    expect(text).toContain('意见')
  })

  it('展示 variables key 说明文案', () => {
    const { container } = render(
      <HumanNodeConfig config={baseConfig} onChange={vi.fn()} />,
    )
    const text = container.textContent ?? ''
    expect(text).toContain('variables')
    expect(text).toContain('human_decision_')
  })

  it('不出现"添加选项"按钮', () => {
    const { container } = render(
      <HumanNodeConfig config={baseConfig} onChange={vi.fn()} />,
    )
    expect(container.querySelector('.ant-btn-link')).toBeNull()
    expect(container.textContent).not.toContain('添加选项')
  })

  it('不出现"暂无选项"占位文案', () => {
    const { container } = render(
      <HumanNodeConfig config={baseConfig} onChange={vi.fn()} />,
    )
    expect(container.textContent).not.toContain('暂无选项')
  })

  it('编辑 title 会触发 onChange', () => {
    const onChange = vi.fn()
    const { container } = render(
      <HumanNodeConfig config={baseConfig} onChange={onChange} />,
    )

    const titleInput = container.querySelector('input') as HTMLInputElement
    expect(titleInput).toBeTruthy()
    titleInput.focus()
    // simulate change using native event
    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      'value',
    )?.set
    nativeInputValueSetter?.call(titleInput, '新标题')
    titleInput.dispatchEvent(new Event('input', { bubbles: true }))

    expect(onChange).toHaveBeenCalled()
    const newConfig = onChange.mock.calls[0][0]
    expect(newConfig.title).toBe('新标题')
  })

  it('description 字段可编辑（TextArea）', () => {
    const onChange = vi.fn()
    const { container } = render(
      <HumanNodeConfig config={baseConfig} onChange={onChange} />,
    )
    const textarea = container.querySelector('textarea') as HTMLTextAreaElement
    expect(textarea).toBeTruthy()
    expect(textarea.value).toBe('描述')
  })
})
