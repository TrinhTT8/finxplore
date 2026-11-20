import { MAX_COMPARE } from "../lib/config";

// TODO (Phase 3, FR-9): pick up to 4 companies + one metric, show chart and takeaway.
export default function ComparePage() {
  return (
    <section>
      <h1>Compare companies</h1>
      <p>Compare up to {MAX_COMPARE} companies side by side. Coming in Phase 3.</p>
    </section>
  );
}
