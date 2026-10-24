import React from 'react'

/**
 * Date input that opens the calendar picker when clicking anywhere on it
 * (browser default: only the trailing calendar icon opens it).
 */
export default function DateInput({ value, onChange, placeholder, style }) {
  const open = (e) => {
    const el = e.currentTarget
    try {
      if (el.showPicker && document.activeElement === el) el.showPicker()
      else if (el.showPicker) { el.focus(); el.showPicker() }
    } catch {
      /* showPicker unsupported (Safari/older): fallback to native behavior */
    }
  }
  return (
    <input
      type="date"
      value={value}
      placeholder={placeholder}
      style={style}
      onChange={onChange}
      onClick={open}
      onMouseDown={(e) => e.currentTarget.focus()}
    />
  )
}
