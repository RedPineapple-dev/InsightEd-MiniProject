import { useCallback, useRef, useState } from 'react'
import { Upload, FileText, Video as VideoIcon, X } from 'lucide-react'
import { motion } from 'framer-motion'

import { cn, bytesToHuman } from '../../lib/utils'

export function DropZone({ accept = 'video/*', kind = 'video', file, onFile, onClear, hint }) {
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef(null)

  const onDrop = useCallback(
    (e) => {
      e.preventDefault()
      setDragOver(false)
      const f = e.dataTransfer.files?.[0]
      if (f) onFile?.(f)
    },
    [onFile]
  )

  const Icon = kind === 'video' ? VideoIcon : FileText
  const heading = kind === 'video' ? 'Upload lecture video' : 'Upload slides / PDF'
  const sub = hint || (kind === 'video' ? 'MP4, MOV, MKV up to 2 GB' : 'PDF, PPTX up to 100 MB')

  if (file) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="card p-4 flex items-center gap-3"
      >
        <div className="h-10 w-10 rounded-lg bg-brand-500/10 text-brand-600 dark:text-brand-300 flex items-center justify-center shrink-0">
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-medium truncate text-ink-1">{file.name}</div>
          <div className="text-xs text-ink-3">{bytesToHuman(file.size)}</div>
        </div>
        <button
          onClick={onClear}
          className="p-1.5 rounded-lg text-ink-3 hover:text-red-500 hover:bg-red-500/10"
          aria-label="Remove"
        >
          <X className="h-4 w-4" />
        </button>
      </motion.div>
    )
  }

  return (
    <label
      htmlFor={`upload-${kind}`}
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
      className={cn(
        'card p-6 flex flex-col items-center justify-center text-center cursor-pointer',
        'border-dashed transition-all duration-200',
        dragOver
          ? 'border-brand-500 bg-brand-500/5 ring-2 ring-brand-500/30'
          : 'hover:border-border-strong hover:bg-surface-2/50'
      )}
    >
      <input
        ref={inputRef}
        id={`upload-${kind}`}
        type="file"
        accept={accept}
        className="sr-only"
        onChange={(e) => e.target.files?.[0] && onFile?.(e.target.files[0])}
      />
      <div className="h-12 w-12 rounded-2xl bg-brand-500/10 text-brand-600 dark:text-brand-300 flex items-center justify-center mb-3">
        <Upload className="h-5 w-5" />
      </div>
      <div className="font-display font-semibold text-ink-1">{heading}</div>
      <div className="text-sm text-ink-3 mt-1">{sub}</div>
      <div className="text-xs text-ink-3 mt-3">
        Drag and drop or <span className="text-brand-600 dark:text-brand-300 font-medium">browse</span>
      </div>
    </label>
  )
}
