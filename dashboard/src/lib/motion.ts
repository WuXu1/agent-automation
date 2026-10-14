import type { Transition } from 'motion/react'

// From DESIGN.md: strong ease-out for UI, the iOS drawer curve for drawers. No invented curves.
export const easeOut = [0.23, 1, 0.32, 1] as const
export const easeDrawer = [0.32, 0.72, 0, 1] as const

export const fade: Transition = { duration: 0.18, ease: easeOut }
export const drawer: Transition = { duration: 0.32, ease: easeDrawer }
export const spring: Transition = { type: 'spring', duration: 0.5, bounce: 0.15 }
