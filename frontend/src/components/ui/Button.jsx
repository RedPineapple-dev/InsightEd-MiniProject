import { forwardRef } from 'react'
import { Loader2 } from 'lucide-react'

import { cn } from '../../lib/utils'

const VARIANTS = {
  primary: 'btn-primary',
  secondary: 'btn-secondary',
  ghost: 'btn-ghost',
  danger: 'btn-danger',
}

const SIZES = {
  sm: 'h-8 px-3 text-sm',
  md: 'h-10 px-4 text-sm',
  lg: 'h-12 px-6 text-base',
  icon: 'h-10 w-10 p-0',
}

const Button = forwardRef(function Button(
  { variant = 'primary', size = 'md', loading, className, children, disabled, leftIcon, rightIcon, ...rest },
  ref
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(VARIANTS[variant] || VARIANTS.primary, SIZES[size], className)}
      {...rest}
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : leftIcon ? (
        <span className="-ml-0.5 [&>svg]:h-4 [&>svg]:w-4">{leftIcon}</span>
      ) : null}
      {children}
      {!loading && rightIcon ? (
        <span className="-mr-0.5 [&>svg]:h-4 [&>svg]:w-4">{rightIcon}</span>
      ) : null}
    </button>
  )
})

export default Button
