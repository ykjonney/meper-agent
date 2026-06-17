/**
 * HumanNodeConfig 组件测试 — 验证添加/删除选项不崩溃。
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
  options: ['approve', 'reject'],
  timeout_minutes: 60,
  timeout_action: 'fail',
}

describe('HumanNodeConfig', () => {
  it('renders without crashing', () => {
    const { container } = render(
      <HumanNodeConfig config={baseConfig} onChange={vi.fn()} />,
    )
    expect(container.querySelector('.space-y-3')).toBeTruthy()
  })

  it('add option calls onChange with new empty option', () => {
    const onChange = vi.fn()
    const { container } = render(
      <HumanNodeConfig config={baseConfig} onChange={onChange} />,
    )

    // The add button is the ant-btn-link with + icon
    const addBtn = container.querySelector('.ant-btn-link') as HTMLButtonElement
    expect(addBtn).toBeTruthy()
    addBtn.click()

    expect(onChange).toHaveBeenCalledTimes(1)
    const newConfig = onChange.mock.calls[0][0]
    expect(newConfig.options).toEqual(['approve', 'reject', ''])
  })

  it('remove option calls onChange without the removed item', () => {
    const onChange = vi.fn()
    const { container } = render(
      <HumanNodeConfig config={baseConfig} onChange={onChange} />,
    )

    // Delete buttons have ant-btn-dangerous class
    const deleteBtns = container.querySelectorAll('.ant-btn-dangerous')
    expect(deleteBtns.length).toBe(2)

    ;(deleteBtns[0] as HTMLButtonElement).click()

    expect(onChange).toHaveBeenCalledTimes(1)
    const newConfig = onChange.mock.calls[0][0]
    expect(newConfig.options).toEqual(['reject'])
  })

  it('add option then re-render does not crash', () => {
    const onChange = vi.fn()
    const { container, rerender } = render(
      <HumanNodeConfig config={baseConfig} onChange={onChange} />,
    )

    // Click add
    const addBtn = container.querySelector('.ant-btn-link') as HTMLButtonElement
    addBtn.click()
    const newConfig = onChange.mock.calls[0][0]

    // Simulate parent re-render with new config (this is what happens in real app)
    rerender(<HumanNodeConfig config={newConfig} onChange={onChange} />)

    // Should now have 3 option inputs (antd Input renders as span.ant-input > input)
    const optionInputs = container.querySelectorAll('input.font-mono, .font-mono input, input[placeholder*="选项"]')
    expect(optionInputs.length).toBe(3)
  })

  it('remove option then re-render does not crash', () => {
    const onChange = vi.fn()
    const { container, rerender } = render(
      <HumanNodeConfig config={baseConfig} onChange={onChange} />,
    )

    // Click delete on first option
    const deleteBtns = container.querySelectorAll('.ant-btn-dangerous')
    ;(deleteBtns[1] as HTMLButtonElement).click()
    const newConfig = onChange.mock.calls[0][0]

    // Simulate parent re-render with new config
    rerender(<HumanNodeConfig config={newConfig} onChange={onChange} />)

    // Should now have 1 option input
    const optionInputs = container.querySelectorAll('input.font-mono, .font-mono input, input[placeholder*="选项"]')
    expect(optionInputs.length).toBe(1)
  })

  it('handles empty options array', () => {
    const onChange = vi.fn()
    const { container } = render(
      <HumanNodeConfig config={{ ...baseConfig, options: [] }} onChange={onChange} />,
    )

    const addBtn = container.querySelector('.ant-btn-link') as HTMLButtonElement
    addBtn.click()

    const newConfig = onChange.mock.calls[0][0]
    expect(newConfig.options).toEqual([''])
  })

  it('handles non-array options gracefully', () => {
    const onChange = vi.fn()
    const { container } = render(
      <HumanNodeConfig
        config={{ options: 'corrupted' } as Record<string, unknown>}
        onChange={onChange}
      />,
    )

    const addBtn = container.querySelector('.ant-btn-link') as HTMLButtonElement
    addBtn.click()

    const newConfig = onChange.mock.calls[0][0]
    expect(Array.isArray(newConfig.options)).toBe(true)
  })
})
