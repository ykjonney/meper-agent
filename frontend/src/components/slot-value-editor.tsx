/**
 * SlotValueEditor — Direct editor for Agent prompt_slots.
 *
 * Renders a TextArea for each fixed slot (role/task/constraints/context/output_format).
 * No template selection — slots are stored directly on the Agent document.
 */
import { FIXED_SLOTS } from '../constants/prompt-slots'

interface Props {
  slotValues: Record<string, string>
  onChange: (slotValues: Record<string, string>) => void
}

export default function SlotValueEditor({ slotValues, onChange }: Props) {
  const handleSlotChange = (slotName: string, value: string) => {
    onChange({ ...slotValues, [slotName]: value })
  }

  return (
    <div className="flex flex-col gap-3">
      {FIXED_SLOTS.map((slot) => {
        const value = slotValues[slot.name] ?? ''
        const isFilled = value.trim().length > 0

        return (
          <div key={slot.name} className="border border-gray-100 rounded-lg p-3">
            {/* Slot header */}
            <div className="flex items-center gap-2 mb-2">
              <span className="text-sm font-medium text-[#0F172A]">
                {slot.label}
              </span>
              {slot.required && (
                <span className="text-[10px] text-[#EF4444]">必填</span>
              )}
              {isFilled && (
                <span className="text-[10px] text-[#10B981]">已填写</span>
              )}
            </div>

            <textarea
              placeholder={slot.placeholder}
              value={value}
              onChange={(e) => handleSlotChange(slot.name, e.target.value)}
              rows={3}
              className="w-full text-sm border border-gray-200 rounded-md px-3 py-2
                         focus:outline-none focus:ring-1 focus:ring-blue-400 focus:border-blue-400
                         placeholder:text-[#CBD5E1] resize-y min-h-[60px]"
            />
          </div>
        )
      })}
    </div>
  )
}
