/**
 * HumanNodeConfig 组件测试 — 验证固定审批行为的渲染与字段联动。
 *
 * 注意:组件已重构为系统固定三个审批行为(approve/reject/comment),
 * 不再有自定义 options,故不再测试添加/删除选项。
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi, beforeAll } from 'vitest'
import { render, fireEvent } from '@testing-library/react'
import HumanNodeConfig from './HumanNodeConfig'

// VariableSelector 需要 currentNodeId + allNodes（HumanNodeConfig 透传给它）
const defaultProps = {
  currentNodeId: 'node_test',
  allNodes: [] as never[],
}

// antd components require ResizeObserver
beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
})

describe('HumanNodeConfig', () => {
  it('renders without crashing', () => {
    const { container } = render(
      <HumanNodeConfig {...defaultProps} config={{}} onChange={vi.fn()} />,
    )
    expect(container.querySelector('.space-y-3')).toBeTruthy()
  })

  it('renders the three fixed approval behaviors (approve/reject/comment)', () => {
    const { container } = render(
      <HumanNodeConfig {...defaultProps} config={{}} onChange={vi.fn()} />,
    )
    // 三个 Tag(通过/驳回/意见),文案在 Tag 文本节点中
    const tags = container.querySelectorAll('.ant-tag')
    expect(tags.length).toBe(3)
    const tagTexts = Array.from(tags).map((t) => t.textContent)
    expect(tagTexts).toContain('通过')
    expect(tagTexts).toContain('驳回')
    expect(tagTexts).toContain('意见')
  })

  it('editing title calls onChange with new title', () => {
    const onChange = vi.fn()
    const { container } = render(
      <HumanNodeConfig {...defaultProps} config={{ title: '旧标题' }} onChange={onChange} />,
    )
    // 标题是第一个 Input(<input>),TextArea 是 <textarea>
    const titleInput = container.querySelector('input:not([type="number"])') as HTMLInputElement
    expect(titleInput.value).toBe('旧标题')

    fireEvent.change(titleInput, { target: { value: '新标题' } })
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange.mock.calls[0][0].title).toBe('新标题')
  })

  it('editing description calls onChange with new description', () => {
    const onChange = vi.fn()
    const { container } = render(
      <HumanNodeConfig {...defaultProps} config={{ description: '旧描述' }} onChange={onChange} />,
    )
    const textarea = container.querySelector('textarea') as HTMLTextAreaElement
    expect(textarea.value).toBe('旧描述')

    fireEvent.change(textarea, { target: { value: '新描述' } })
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange.mock.calls[0][0].description).toBe('新描述')
  })

  it('editing timeout_minutes calls onChange with parsed number', () => {
    const onChange = vi.fn()
    const { container } = render(
      <HumanNodeConfig {...defaultProps} config={{ timeout_minutes: 30 }} onChange={onChange} />,
    )
    const numberInput = container.querySelector('input[type="number"]') as HTMLInputElement
    expect(numberInput.value).toBe('30')

    fireEvent.change(numberInput, { target: { value: '90' } })
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange.mock.calls[0][0].timeout_minutes).toBe(90)
  })

  it('timeout_minutes falls back to 60 when input is empty/invalid', () => {
    const onChange = vi.fn()
    const { container } = render(
      <HumanNodeConfig {...defaultProps} config={{ timeout_minutes: 30 }} onChange={onChange} />,
    )
    const numberInput = container.querySelector('input[type="number"]') as HTMLInputElement
    fireEvent.change(numberInput, { target: { value: '' } })
    expect(onChange.mock.calls[0][0].timeout_minutes).toBe(60)
  })

  it('uses default values when config is empty', () => {
    const { container } = render(
      <HumanNodeConfig {...defaultProps} config={{}} onChange={vi.fn()} />,
    )
    const numberInput = container.querySelector('input[type="number"]') as HTMLInputElement
    expect(numberInput.value).toBe('60') // 默认超时 60 分钟
  })

  it('handles null-ish config gracefully without crashing', () => {
    expect(() =>
      render(
        <HumanNodeConfig
          {...defaultProps}
          config={{ options: 'corrupted' } as Record<string, unknown>}
          onChange={vi.fn()}
        />,
      ),
    ).not.toThrow()
  })
})
