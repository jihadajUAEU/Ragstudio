import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";

import { rs } from "../../lib/design-tokens";
import { cn } from "../../lib/utils";

const buttonVariants = cva(
  `inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 ${rs.focus.ring} focus-visible:ring-offset-2 ${rs.focus.offset} disabled:pointer-events-none disabled:opacity-50`,
  {
    variants: {
      variant: {
        default: `${rs.bg.accent} ${rs.text.white} ${rs.hover.accentDeep}`,
        secondary: `border ${rs.border.strong} ${rs.bg.paper} ${rs.text.ink} ${rs.hover.field}`,
        ghost: `${rs.text.body} ${rs.hover.accentSoft}`,
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-8 px-3 text-xs",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : "button";

  return (
    <Comp
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}
