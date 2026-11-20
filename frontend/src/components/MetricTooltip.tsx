import { useId } from "react";
import { GLOSSARY, type MetricKey } from "../lib/glossary";

/** Plain-English label with an accessible hover/focus tooltip (FR-7). */
export default function MetricTooltip({ metric }: { metric: MetricKey }) {
  const entry = GLOSSARY[metric];
  const id = useId();
  return (
    <span className="metric-tooltip">
      <button type="button" className="metric-label" aria-describedby={id}>
        {entry.label}
      </button>
      <span role="tooltip" id={id} className="tooltip-body">
        <strong>{entry.definition}</strong>
        <br />
        <em>Example:</em> {entry.example}
      </span>
    </span>
  );
}
