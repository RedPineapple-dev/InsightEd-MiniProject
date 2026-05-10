import { forwardRef } from 'react'

import { cn } from '../../lib/utils'

export const Input = forwardRef(function Input(
  { className, label, hint, error, leftIcon, rightAddon, id, ...rest },
  ref
) {
  const inputId = id || `f-${rest.name || Math.random().toString(36).slice(2, 8)}`
  return (
    <div className="space-y-1.5">
      {label ? (
        <label htmlFor={inputId} className="block text-sm font-medium text-ink-2">
          {label}
        </label>
      ) : null}
      <div className="relative">
        {leftIcon ? (
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3 [&>svg]:h-4 [&>svg]:w-4">
            {leftIcon}
          </span>
        ) : null}
        <input
          id={inputId}
          ref={ref}
          className={cn(
            'input-base',
            leftIcon && 'pl-10',
            rightAddon && 'pr-10',
            error && 'border-red-500 focus:ring-red-500/40 focus:border-red-500',
            className
          )}
          {...rest}
        />
        {rightAddon ? (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-3">{rightAddon}</span>
        ) : null}
      </div>
      {error ? (
        <p className="text-xs text-red-500">{error}</p>
      ) : hint ? (
        <p className="text-xs text-ink-3">{hint}</p>
      ) : null}
    </div>
  )
})
