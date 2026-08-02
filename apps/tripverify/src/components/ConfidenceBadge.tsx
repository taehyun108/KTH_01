import type { Confidence } from "@/core/types/confidence";
import { CONFIDENCE_EMOJI, CONFIDENCE_LABEL } from "@/lib/format";

const STYLE: Record<Confidence, string> = {
  high: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  medium: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  low: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
};

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${STYLE[confidence]}`}
      title={`신뢰도: ${CONFIDENCE_LABEL[confidence]}`}
    >
      {CONFIDENCE_EMOJI[confidence]} {CONFIDENCE_LABEL[confidence]}
    </span>
  );
}
